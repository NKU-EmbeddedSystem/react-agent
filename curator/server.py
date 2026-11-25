"""The curator's HTTP server (python -m curator serve): the JSON API, the PDFs, renders, exports, and the
front end in curator/web/.

Everything comes from the database; nothing under work/ or Data/ is read. Each request opens its own
SQLite connection (sqlite3 objects must not cross threads) and closes it when the answer is out.

There are no accounts. What keeps other web pages out of the API: the Host header must name this
server (a foreign domain made to resolve to 127.0.0.1, DNS rebinding, is refused), an Origin header
must be this server's own, and POST/PUT bodies must be declared JSON, which a cross-site form cannot
send and a cross-site script cannot without a preflight this server never answers. Bound to anything
but loopback, everyone who can reach the port can read and change the data.

  /                       web/index.html (a placeholder page until the front end is built)
  /web/<path>             files of curator/web/ (Last-Modified / 304, explicit MIME table: pdf.js needs
                          text/javascript for .mjs and application/wasm)
  /api/...                the routes registered below with @route

HEAD is GET without the body. Errors are JSON {"error": "<message>"}: 400 bad request or Host (also a
body with NaN, a number beyond any float, or nested too deep), 403 foreign Origin, 404, 405, 409
(+ "current"), 411, 413, 415 not JSON, 416 (+ Content-Range), 422 (+ "errors", "warnings"), 500, and
501 for a method the server does not know.
"""

from __future__ import annotations

import ipaddress
import json
import math
import os
import queue
import re
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import traceback
import urllib.parse
from datetime import datetime
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import db, export, pdfdocs, records, store
from .config import ACTIONS, DEFAULT_PORT, REVIEW_STATUSES, WEB_DIR, default_author

MAX_BODY = 10 * 1024 * 1024
MAX_DEPTH = 64                     # nesting of a request body
PDF_CHUNK = 1 << 20                # bytes per read of a PDF blob while streaming it
EXPORT_SPOOL = 32 * 1024 * 1024    # a batch export larger than this is spooled to a temp file
LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}
WILDCARD = {"0.0.0.0", "::", ""}   # bind addresses that listen on every interface

MIME = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json",
    ".wasm": "application/wasm", ".svg": "image/svg+xml", ".png": "image/png", ".gif": "image/gif",
    ".ico": "image/x-icon", ".bcmap": "application/octet-stream", ".pfb": "application/octet-stream",
    ".icc": "application/octet-stream", ".ttf": "font/ttf", ".woff2": "font/woff2",
}

PLACEHOLDER = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>curator</title></head>
<body style="font-family: sans-serif; max-width: 40em; margin: 3em auto; line-height: 1.6">
<h1>反应数据集管理</h1>
<p>前端还没有构建（没有 curator/web/index.html）。服务器和 API 已经可以用，例如
<a href="/api/info">/api/info</a>、<a href="/api/papers">/api/papers</a>、<a href="/api/reactions">/api/reactions</a>。</p>
</body></html>
"""


class HTTPError(Exception):
    """An answer the server decides on itself (the store's exceptions are mapped in Handler._error)."""

    def __init__(self, status: int, message: str, headers=()):
        super().__init__(message)
        self.status, self.message, self.headers = status, message, list(headers)


# ----------------------------------------------------------------------------- Host and Range headers

def host_name(header: str | None) -> str | None:
    """The name in a Host header ('name', 'name:port', '[v6]:port'), lowercased; None if malformed."""
    h = (header or "").strip().lower()
    if h.startswith("["):
        name, sep, rest = h[1:].partition("]")
        if not sep:
            return None
    else:
        name, sep, port = h.partition(":")
        rest = sep + port
    if not name or (rest and not re.fullmatch(r":\d{1,5}", rest)):
        return None
    return name


def host_check(allow=()):
    """A test of Host names: loopback names and addresses, plus the names in `allow` (the address the
    server is bound to). A wildcard bind (0.0.0.0, ::) lets in any IP address and this machine's name:
    DNS rebinding needs a domain name, so IP literals are safe."""
    names = LOOPBACK_NAMES | {str(a).strip().strip("[]").lower() for a in allow}
    wildcard = bool(names & WILDCARD)
    if wildcard:
        names.add(socket.gethostname().lower())

    def ok(name: str) -> bool:
        if name in names:
            return True
        try:
            ip = ipaddress.ip_address(name)
        except ValueError:
            return False
        return wildcard or ip.is_loopback

    return ok


def is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def byte_range(header: str | None, size: int):
    """(start, end) inclusive for a single 'bytes=' range; None to send the whole file (no Range, another
    unit, several ranges, or a range that is not valid: RFC 9110 lets a server ignore those).
    HTTPError 416 for a range that lies outside the file."""
    if not header:
        return None
    m = re.fullmatch(r"\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*", header, re.IGNORECASE)
    if not m or not (m.group(1) or m.group(2)):
        return None
    unsatisfiable = HTTPError(416, f"请求的字节范围不在文件之内（文件 {size} 字节）",
                              [("Content-Range", f"bytes */{size}")])

    def number(digits: str) -> int:  # past any file size, without int() of thousands of digits (ValueError)
        digits = digits.lstrip("0") or "0"
        return int(digits) if len(digits) <= 19 else 10 ** 19

    if not m.group(1):  # bytes=-n: the last n bytes
        n = number(m.group(2))
        if n == 0 or size == 0:
            raise unsatisfiable
        return max(0, size - n), size - 1
    start = number(m.group(1))
    if m.group(2) and number(m.group(2)) < start:  # 'bytes=9-3' is no range at all
        return None
    if start >= size:
        raise unsatisfiable
    return start, (min(number(m.group(2)), size - 1) if m.group(2) else size - 1)


def etag_matches(header: str | None, etag: str) -> bool:
    """Whether If-None-Match names `etag` (quoted), weakly compared."""
    if not header:
        return False
    tags = [t.strip() for t in header.split(",")]
    return "*" in tags or etag in (t[2:] if t.startswith("W/") else t for t in tags)


def _disposition(kind: str, filename: str) -> str:
    ascii_name = re.sub(r'[^\x20-\x7e]|["\\]', "_", filename)
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{urllib.parse.quote(filename, safe='')}"


def _query(qs: str) -> dict[str, str]:
    """A query string as the store takes it: a repeated key becomes one comma-separated value."""
    out: dict[str, str] = {}
    for k, v in urllib.parse.parse_qsl(qs, keep_blank_values=True):
        out[k] = f"{out[k]},{v}" if out.get(k) else v
    return out


def _reject_constant(name):
    raise ValueError(f"JSON 里不能有 {name}")


def _finite_float(text: str) -> float:
    """A JSON number as a float; 1e999 overflows to infinity, which no JSON column can hold."""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"JSON 里的数 {text[:30]} 超出范围")
    return value


def _too_deep(value, limit: int = MAX_DEPTH) -> bool:
    """Whether a parsed body nests deeper than `limit` (a record is about a dozen levels deep; the
    validator and the diff recurse, and Python's recursion has a limit)."""
    stack = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, (dict, list)):
            if depth > limit:
                return True
            stack.extend((v, depth + 1) for v in (node.values() if isinstance(node, dict) else node))
    return False


# ----------------------------------------------------------------------------- routes

ROUTES: list[tuple[str, re.Pattern, object]] = []


def route(method: str, pattern: str):
    def register(fn):
        ROUTES.append((method, re.compile(pattern), fn))
        return fn
    return register


class Request:
    """What a route gets: the handler (to write an answer itself), the connection, the path's groups,
    the query (dict of str) and the JSON body (dict, POST/PUT only)."""

    def __init__(self, handler, conn, groups, query, body):
        self.handler, self.conn, self.groups, self.query, self.body = handler, conn, groups, query, body

    def need(self, key):
        if self.body.get(key) is None:
            raise store.BadRequest(f"缺少 {key}")
        return self.body[key]

    def author(self):
        return self.body.get("author")

    def comment(self):
        value = self.body.get("comment")
        if value is not None and not isinstance(value, str):
            raise store.BadRequest("comment 应为字符串")
        return (value or "").strip() or None


def _counts(conn) -> dict:
    """What the database holds; current reactions by state (deleted ones counted only under `deleted`), and
    the old versions re-imports replaced (`not_latest`)."""
    cur = "deleted = 0 AND in_latest = 1"
    statuses = ", ".join(f"sum({cur} AND review_status = '{s}') AS {s}" for s in REVIEW_STATUSES)
    r = conn.execute(
        "SELECT (SELECT count(*) FROM papers) AS papers, (SELECT count(*) FROM documents) AS documents,"
        " (SELECT count(*) FROM blocks) AS blocks, (SELECT count(*) FROM imports) AS imports,"
        f" (SELECT max(import_id) FROM imports) AS last_import, sum({cur}) AS reactions,"
        f" sum(deleted = 1 AND in_latest = 1) AS deleted, sum({cur} AND pending_sha IS NOT NULL) AS pending,"
        f" sum({cur} AND {store.EDITED_SQL}) AS edited, sum(in_latest = 0) AS not_latest,"
        f" {statuses} FROM reactions").fetchone()
    counts = ("papers", "documents", "blocks", "imports", "reactions", "deleted", "pending", "edited", "not_latest")
    return {**{k: r[k] or 0 for k in counts}, "last_import": r["last_import"],
            "status": {s: r[s] or 0 for s in REVIEW_STATUSES}}


@route("GET", r"/api/info")
def _info(r):
    return {"default_author": default_author(), "review_statuses": list(REVIEW_STATUSES), "actions": list(ACTIONS),
            "known": records.KNOWN, "templates": records.TEMPLATES, "counts": _counts(r.conn),
            "instance_label": os.environ.get("CURATOR_INSTANCE_LABEL", "")}


@route("GET", r"/api/facets")
def _facets(r):
    return store.facets(r.conn, r.query)


@route("GET", r"/api/imports")
def _imports(r):
    return store.list_imports(r.conn)


@route("GET", r"/api/papers")
def _papers(r):
    return store.list_papers(r.conn)


@route("GET", r"/api/papers/([^/]+)")
def _paper(r):
    return store.get_paper(r.conn, r.groups[0])


@route("PUT", r"/api/papers/([^/]+)")
def _paper_update(r):
    # The fields under "fields", or (for convenience) at the top level of the body.
    fields = r.body.get("fields")
    if fields is None:
        fields = {k: r.body[k] for k in store.PAPER_FIELDS if k in r.body}
    return store.update_paper(r.conn, r.groups[0], base_rev=r.need("base_rev"), fields=fields, author=r.author(),
                              comment=r.comment())


@route("GET", r"/api/papers/([^/]+)/history")
def _paper_history(r):
    return store.paper_history(r.conn, r.groups[0])


@route("GET", r"/api/blocks/([^/]+)")
def _block(r):
    return store.get_block(r.conn, r.groups[0])


@route("GET", r"/api/reactions")
def _reactions(r):
    return store.list_reactions(r.conn, r.query)


@route("POST", r"/api/reactions")
def _create(r):
    return 201, store.create(r.conn, paper_id=r.need("paper_id"), block_pk=r.body.get("block_pk"),
                             entry_id=r.body.get("entry_id"), author=r.author(), comment=r.comment())


REACTION = r"/api/reactions/([^/]+)"


@route("GET", REACTION)
def _reaction(r):
    return store.get_reaction(r.conn, r.groups[0])


@route("PUT", REACTION)
def _update(r):
    return store.update(r.conn, r.groups[0], base_rev=r.need("base_rev"), data=r.need("data"), author=r.author(),
                        comment=r.comment())


@route("GET", REACTION + r"/neighbours")
def _neighbours(r):
    return store.neighbours(r.conn, r.groups[0], r.query)


@route("POST", REACTION + r"/review")
def _review(r):
    return store.review(r.conn, r.groups[0], base_rev=r.need("base_rev"), status=r.need("status"),
                        note=r.body.get("note"), author=r.author(), comment=r.comment())


@route("POST", REACTION + r"/revert")
def _revert(r):
    return store.revert(r.conn, r.groups[0], base_rev=r.need("base_rev"), to_rev=r.need("to_rev"),
                        author=r.author(), comment=r.comment())


@route("POST", REACTION + r"/copy")
def _copy(r):
    return 201, store.copy(r.conn, r.groups[0], author=r.author(), comment=r.comment())


@route("POST", REACTION + r"/(delete|restore)")
def _delete(r):
    action = store.delete if r.groups[1] == "delete" else store.restore
    return action(r.conn, r.groups[0], base_rev=r.need("base_rev"), author=r.author(), comment=r.comment())


@route("POST", REACTION + r"/pending/(accept|dismiss)")
def _pending(r):
    action = store.accept_pending if r.groups[1] == "accept" else store.dismiss_pending
    return action(r.conn, r.groups[0], base_rev=r.need("base_rev"), author=r.author(), comment=r.comment())


@route("GET", REACTION + r"/history")
def _history(r):
    return store.history(r.conn, r.groups[0])


@route("GET", REACTION + r"/revisions/([^/]+)")
def _revision(r):
    return store.revision(r.conn, r.groups[0], r.groups[1])


@route("GET", REACTION + r"/diff")
def _diff(r):
    if not r.query.get("from"):
        raise store.BadRequest("缺少参数 from（版本号或 pipeline）")
    return store.diff_between(r.conn, r.groups[0], r.query["from"], r.query.get("to") or "current")


@route("POST", r"/api/validate")
def _validate(r):
    """The checks of a save, without saving. With `id`, the reaction's data at `base_rev` (default: now)
    is the base whose problems only warn, and reaction_id is the server's, as in store.update."""
    data, paper_id, base = r.need("data"), r.body.get("paper_id"), None
    if r.body.get("id") is not None:
        current = store.get_reaction(r.conn, r.body["id"])
        paper_id = current["paper_id"] if paper_id is None else paper_id
        base = current["data"] if r.body.get("base_rev") is None else \
            store.revision(r.conn, current["id"], r.body["base_rev"])["snapshot"]["data"]
        if isinstance(data, dict):
            data = {**data, "reaction_id": current["data"].get("reaction_id")
                    if isinstance(current["data"], dict) else None}
    if paper_id is None:
        raise store.BadRequest("缺少 paper_id")
    if r.conn.execute("SELECT 1 FROM papers WHERE paper_id = ?", (str(paper_id),)).fetchone() is None:
        raise store.NotFound(f"没有文献 {paper_id}")
    if isinstance(data, dict):
        data = records.normalize(data)
    errors, warnings = records.validate(data, store.docs_for(r.conn, str(paper_id)), base=base)
    return {"errors": errors, "warnings": warnings}


@route("GET", r"/api/docs/([^/]+)/pdf")
def _pdf(r):
    r.handler.send_pdf(r.conn, r.groups[0])


@route("GET", r"/api/docs/([^/]+)/render")
def _render(r):
    q = r.query
    if not q.get("page"):
        raise store.BadRequest("缺少参数 page")
    args = (r.conn, r.groups[0], q["page"], q["bbox"].split(",") if q.get("bbox") else None)
    options = {"dpi": q.get("dpi") or 150, "pad": q.get("pad") or 0}
    # Revalidated on every use (no-cache): the ETag is known without drawing, so a 304 costs no render.
    etag = f'"{pdfdocs.render_etag(*args, **options)}"'
    if etag_matches(r.handler.headers.get("If-None-Match"), etag):
        return r.handler.send(304, None, None, [("ETag", etag)])
    png, _ = pdfdocs.render_png(*args, **options)
    r.handler.send(200, png, "image/png", [("ETag", etag)])


@route("GET", r"/api/export/reactions/([^/]+)\.json")
def _export_one(r):
    rec = export.export_record(r.conn, r.groups[0])
    r.handler.send(200, json.dumps(rec, ensure_ascii=False, indent=2).encode("utf-8"),
                   "application/json; charset=utf-8", [("Content-Disposition", _disposition("attachment",
                                                                                           f"{rec['id']}.json"))])


@route("POST", r"/api/export")
def _export(r):
    b = r.body
    fmt = b.get("format") or "jsonl"
    if fmt not in ("jsonl", "zip"):
        raise store.BadRequest(f"不支持的导出格式：{fmt!r}（jsonl 或 zip）")
    flt, ids = b.get("filter"), b.get("ids")
    if flt is not None and not isinstance(flt, dict):
        raise store.BadRequest("filter 应为对象")
    if ids is not None and not isinstance(ids, list):
        raise store.BadRequest("ids 应为列表")
    with tempfile.SpooledTemporaryFile(EXPORT_SPOOL) as fp:
        with db.read(r.conn):  # the set and its records as of one moment, whatever is saved meanwhile
            chosen = export.select_ids(r.conn, flt, ids, include_excluded=bool(b.get("include_excluded")),
                                       include_deleted=bool(b.get("include_deleted")))
            if fmt == "zip":
                export.write_zip(r.conn, chosen, fp, images=bool(b.get("images")), filter=flt)
                ctype = "application/zip"
            else:
                export.write_jsonl(r.conn, chosen, fp)
                ctype = "application/x-ndjson"
        size = fp.tell()
        fp.seek(0)
        name = f"reactions-{datetime.now().strftime('%Y%m%d-%H%M%S')}.{fmt}"
        r.handler.head(200, ctype, size, [("Content-Disposition", _disposition("attachment", name)),
                                          ("X-Export-Count", str(len(chosen)))])
        shutil.copyfileobj(fp, r.handler.wfile, PDF_CHUNK)


# ----------------------------------------------------------------------------- the handler

class ConnectionPool:
    """The server's SQLite connections, kept open and handed from one request to the next.

    Opening and closing a connection per request deadlocked inside SQLite 3.51.1 under bursts of requests
    (sqlite3_open_v2 on two threads against sqlite3_close_v2 on a third, all waiting on SQLite's own
    mutexes; every API request hung until a restart). Here connections are opened lazily up to `size` and
    closed only when one is discarded or the server stops, and both happen under one lock, so an open never
    runs beside a close. A request that ends with a transaction still open, or with an error, gives its
    connection back closed rather than in an unknown state."""

    def __init__(self, path, size: int = 16, wait: float = 60.0):
        self.path, self.size, self.wait = Path(path), size, wait
        self._idle: queue.LifoQueue = queue.LifoQueue()
        self._lock = threading.Lock()
        self._open = 0

    def acquire(self) -> sqlite3.Connection:
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            if self._open < self.size:
                conn = db.connect(self.path, threads=True)
                self._open += 1
                return conn
        try:
            return self._idle.get(timeout=self.wait)
        except queue.Empty:
            raise HTTPError(503, "服务器忙，请稍后再试") from None

    def release(self, conn: sqlite3.Connection, clean: bool = True) -> None:
        if clean and not conn.in_transaction:
            self._idle.put(conn)
            return
        with self._lock:
            self._open -= 1
            try:
                conn.close()
            except sqlite3.Error:
                pass

    def close(self) -> None:
        with self._lock:
            while True:
                try:
                    conn = self._idle.get_nowait()
                except queue.Empty:
                    break
                self._open -= 1
                conn.close()


def make_handler(db_path, *, host_allow=None, web_dir=None, pool: ConnectionPool | None = None):
    """The request handler class for a database file. host_allow: Host names accepted besides loopback
    (serve passes the bound address); web_dir: where the front end is (default curator/web/); pool: the
    connections to use (one is made for the handler otherwise; it is at `Handler.pool`)."""
    db_path = Path(db_path)
    pool = pool or ConnectionPool(db_path)
    web = Path(web_dir or WEB_DIR).resolve()
    host_ok = host_check(host_allow or ())

    class Handler(BaseHTTPRequestHandler):
        server_version = "curator"

        def log_message(self, fmt, *args):  # keep the console quiet; failures are printed in _handle
            pass

        def do_GET(self):
            self._handle("GET")

        def do_HEAD(self):  # GET's answer without its body (RFC 9110: a server supports GET and HEAD)
            self._handle("HEAD")

        def do_POST(self):
            self._handle("POST")

        def do_PUT(self):
            self._handle("PUT")

        def send_error(self, code, message=None, explain=None):
            """What BaseHTTPRequestHandler answers itself (another method, a malformed request line,
            headers too large) as JSON in Chinese, like every other answer, instead of English HTML."""
            self._head = self.command == "HEAD"
            self._sent = False
            self.close_connection = True
            text = {501: f"不支持 {self.command} 请求", 414: "请求的地址太长", 431: "请求头太大",
                    505: "不支持这个 HTTP 版本"}.get(code, "请求的格式不对")
            try:
                self.send_json({"error": text}, code, [("Connection", "close")])
            except OSError:
                pass

        # ---- writing answers

        def head(self, status: int, ctype: str | None, length: int | None, headers=()):
            self.send_response(status)
            self._sent = True
            if ctype:
                self.send_header("Content-Type", ctype)
            if length is not None:
                self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()

        def send(self, status: int, body: bytes | None, ctype: str | None, headers=()):
            self.head(status, ctype, None if status == 304 else len(body or b""), headers)
            if body and not self._head:
                self.wfile.write(body)

        def send_json(self, data, status: int = 200, headers=()):
            self.send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                      "application/json; charset=utf-8", headers)

        def send_pdf(self, conn, doc_id):
            row = pdfdocs.doc_row(conn, doc_id)
            size, etag = row["size"], f'"{row["sha256"]}"'
            headers = [("Accept-Ranges", "bytes"), ("ETag", etag),
                       ("Content-Disposition", _disposition("inline", row["filename"]))]
            if etag_matches(self.headers.get("If-None-Match"), etag):
                return self.send(304, None, None, headers)
            if_range = self.headers.get("If-Range")
            rng = byte_range(self.headers.get("Range"), size) if if_range in (None, etag) else None
            start, end = rng or (0, size - 1)
            if rng:
                headers.append(("Content-Range", f"bytes {start}-{end}/{size}"))
            self.head(206 if rng else 200, "application/pdf", end - start + 1, headers)
            if self._head:
                return
            chunks = pdfdocs.read_range(conn, row["blob_rowid"], start, end, PDF_CHUNK)
            try:
                for data in chunks:
                    self.wfile.write(data)
            finally:
                chunks.close()  # a client that hangs up mid-file must not leave the blob open

        def _file(self, rel: str):
            try:
                target = (web / rel).resolve()
            except (OSError, ValueError):
                target = None
            if target is None or not target.is_relative_to(web) or not target.is_file():
                raise HTTPError(404, "没有这个文件")
            # Revalidated on every use; an unchanged file costs a 304, not a download.
            modified = formatdate(target.stat().st_mtime, usegmt=True)
            if self.headers.get("If-Modified-Since") == modified:
                return self.send(304, None, None, [("Last-Modified", modified)])
            self.send(200, target.read_bytes(), MIME.get(target.suffix.lower(), "application/octet-stream"),
                      [("Last-Modified", modified)])

        # ---- reading requests

        def _check(self, method: str):
            host = self.headers.get("Host")
            name = host_name(host)
            if name is None or not host_ok(name):
                raise HTTPError(400, f"不接受的 Host：{host!r}（只接受本机或服务器绑定的地址）")
            origin = self.headers.get("Origin")
            if origin is not None and origin.strip().lower() != f"http://{host.strip().lower()}":
                raise HTTPError(403, f"拒绝来自其他网站的请求（Origin：{origin}）")
            if method in ("POST", "PUT"):
                ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if ctype != "application/json":
                    raise HTTPError(415, "请求体必须是 JSON（Content-Type: application/json）")

        def _body(self) -> dict:
            length = self.headers.get("Content-Length")
            if length is None:
                raise HTTPError(411, "缺少 Content-Length")
            if not length.strip().isdigit():
                raise HTTPError(400, f"Content-Length 不对：{length!r}")
            if int(length) > MAX_BODY:
                self.close_connection = True  # the body is not read
                raise HTTPError(413, f"请求体超过 {MAX_BODY // (1024 * 1024)} MB")
            raw = self.rfile.read(int(length))
            try:
                body = json.loads(raw, parse_constant=_reject_constant, parse_float=_finite_float)
            except ValueError as e:  # also UnicodeDecodeError, NaN / Infinity and 1e999
                raise HTTPError(400, f"请求体不是有效的 JSON：{e}") from None
            except RecursionError:
                raise HTTPError(400, "请求体嵌套太深") from None
            if not isinstance(body, dict):
                raise HTTPError(400, "请求体应为 JSON 对象")
            if _too_deep(body):
                raise HTTPError(400, f"请求体嵌套太深（超过 {MAX_DEPTH} 层）")
            return body

        def _handle(self, method: str):
            self._sent = False
            self._head = method == "HEAD"
            method = "GET" if self._head else method
            conn, clean = None, False
            try:
                self._check(method)
                url = urllib.parse.urlsplit(self.path)
                path = urllib.parse.unquote(url.path)
                if method == "GET" and path == "/":
                    if not (web / "index.html").is_file():
                        return self.send(200, PLACEHOLDER.encode("utf-8"), MIME[".html"])
                    return self._file("index.html")
                if method == "GET" and path.startswith("/web/"):
                    return self._file(path[len("/web/"):])
                found = [(m_, fn, match) for m_, pattern, fn in ROUTES if (match := pattern.fullmatch(path))]
                hit = next(((fn, match.groups()) for m_, fn, match in found if m_ == method), None)
                if hit is None:
                    raise HTTPError(405, f"{path} 不支持 {method}") if found else HTTPError(404, "没有这个地址")
                body = self._body() if method in ("POST", "PUT") else None
                conn = pool.acquire()
                result = hit[0](Request(self, conn, hit[1], _query(url.query), body))
                if result is not None:
                    status, data = result if isinstance(result, tuple) else (200, result)
                    self.send_json(data, status)
                clean = True
            except (BrokenPipeError, ConnectionResetError):
                clean = True  # the client hung up (pdf.js drops its first request once it knows ranges work)
            except Exception as e:  # noqa: BLE001 - every failure becomes an answer
                # An expected refusal leaves the connection as it was; anything else may not have.
                clean = isinstance(e, (HTTPError, store.StoreError, LookupError, ValueError))
                self._error(e)
            finally:
                if conn is not None:
                    pool.release(conn, clean)

        def _error(self, e: Exception):
            if isinstance(e, HTTPError):
                status, extra, headers = e.status, {}, e.headers
            elif isinstance(e, store.Conflict):
                status, extra, headers = 409, {"current": e.current}, ()
            elif isinstance(e, store.Invalid):
                status, extra, headers = 422, {"errors": e.errors, "warnings": e.warnings}, ()
            elif isinstance(e, (store.NotFound, LookupError)):
                status, extra, headers = 404, {}, ()
            elif isinstance(e, (store.BadRequest, ValueError)):
                status, extra, headers = 400, {}, ()
            else:
                traceback.print_exc(file=sys.stderr)
                status, extra, headers = 500, {}, ()
                e = f"服务器内部错误：{type(e).__name__}: {e}"
            if self._sent:  # the answer has begun; all that is left is to hang up
                self.close_connection = True
                return
            try:
                self.send_json({"error": str(e), **extra}, status, headers)
            except (BrokenPipeError, ConnectionResetError):
                pass

    Handler.pool = pool
    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # Each request is a connection of its own (HTTP/1.0): a burst of them (parallel thumbnails, a script)
    # must not overflow socketserver's default backlog of 5, which resets the connections that do.
    request_queue_size = 128


class _Server6(_Server):
    address_family = socket.AF_INET6


def make_server(db_path, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """A server on host:port for an existing database (FileNotFoundError, SchemaError now rather than on
    the first request)."""
    db.connect(db_path).close()
    cls = _Server6 if ":" in host else _Server
    handler = make_handler(db_path, host_allow=[host])
    httpd = cls((host, port), handler)
    httpd.pool = handler.pool
    return httpd


def banner(host: str, port: int, db_path) -> list[str]:
    shown = f"[{host}]" if ":" in host else host
    lines = [f"curator: http://{shown}:{port}/  （数据库：{db_path}）"]
    if not is_loopback(host):
        lines.append(f"注意：服务器绑定在 {host}，没有任何认证：能连到这个端口的人都能查看和修改数据。")
    return lines


def serve(db_path, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
    httpd = make_server(db_path, host, port)
    for line in banner(host, httpd.server_address[1], db_path):
        print(line, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        httpd.pool.close()
