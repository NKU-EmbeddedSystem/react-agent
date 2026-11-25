"""The curator's HTTP server and command line, over the fixture paper imported into a database file whose
work dir and PDFs are deleted right after the import: everything must come from the database."""

import http.client
import io
import json
import shutil
import socket
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import pymupdf

from curator import db, pdfdocs, server, store
from curator.__main__ import check, main
from curator.config import WEB_DIR
from tests import curator_fixture as fx

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never through a proxy
E1, E3, E4, E5, E6 = fx.ORIGIN_IDS
_BUILT: dict = {}


def built() -> Path:
    """The fixture imported once per run into tmp/built/db/curator.sqlite, its work/ and Data/ removed."""
    if not _BUILT:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name) / "built"
        conn, db_path, _ = fx.make_db(root)
        conn.close()
        shutil.rmtree(root / "work")
        shutil.rmtree(root / "Data")
        _BUILT.update(tmp=tmp, root=root, db=db_path)
    return _BUILT["db"]


def tearDownModule():
    if _BUILT:
        _BUILT["tmp"].cleanup()


def start(handler):
    httpd = server._Server(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


class Served(unittest.TestCase):
    """A copy of the imported database per test, served on a free port."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db_path = self.tmp / "curator.sqlite"
        shutil.copy(built(), self.db_path)
        self.httpd = server.make_server(self.db_path, "127.0.0.1", 0)
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.servers = [self.httpd]

    def tearDown(self):
        for httpd in self.servers:
            httpd.shutdown()
            httpd.server_close()
            httpd.RequestHandlerClass.pool.close()
        self._tmp.cleanup()

    def request(self, method, path, body=None, headers=None, base=None):
        """(status, headers, bytes); a dict body is sent as JSON."""
        headers = dict(headers or {})
        data = body
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request((base or self.base) + path, data=data, headers=headers, method=method)
        try:
            with OPENER.open(req) as res:
                return res.status, res.headers, res.read()
        except urllib.error.HTTPError as err:
            with err:
                return err.code, err.headers, err.read()

    def get(self, path, headers=None):
        return self.request("GET", path, headers=headers)

    def api(self, method, path, body=None, headers=None):
        status, hdrs, raw = self.request(method, path, body, headers)
        self.assertEqual(hdrs["Content-Type"], "application/json; charset=utf-8", path)
        self.assertEqual(hdrs["Cache-Control"], "no-cache")
        return status, json.loads(raw)

    def raw(self, method, path, headers=(), body=b"", skip_host=False):
        """A request exactly as written (no Host, no Content-Type unless given): (status, body)."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            c.putrequest(method, path, skip_host=skip_host, skip_accept_encoding=True)
            for k, v in headers:
                c.putheader(k, v)
            c.endheaders(body or None)
            res = c.getresponse()
            return res.status, res.read()
        finally:
            c.close()

    def ids(self) -> dict:
        conn = db.connect(self.db_path)
        try:
            return {r["origin_id"]: r["id"] for r in conn.execute("SELECT id, origin_id FROM reactions")}
        finally:
            conn.close()

    def blob(self, doc_id=1) -> bytes:
        conn = db.connect(self.db_path)
        try:
            return conn.execute("SELECT b.data FROM documents d JOIN blobs b ON b.sha256 = d.sha256"
                                " WHERE d.doc_id = ?", (doc_id,)).fetchone()[0]
        finally:
            conn.close()


class Pool(Served):
    """Connections are kept and handed on, never opened and closed per request (that deadlocked inside
    SQLite under bursts of requests)."""

    def pool(self):
        return self.httpd.RequestHandlerClass.pool

    def settled(self, open_, idle):
        """The pool's (open, idle) once the last request's thread has given its connection back (the
        answer reaches the client a moment before that)."""
        pool = self.pool()
        for _ in range(200):
            if (pool._open, pool._idle.qsize()) == (open_, idle):
                break
            threading.Event().wait(0.01)
        return pool._open, pool._idle.qsize()

    def test_one_connection_serves_requests_one_after_another(self):
        for _ in range(5):
            self.assertEqual(self.api("GET", "/api/info")[0], 200)
        self.assertEqual(self.settled(1, 1), (1, 1))

    def test_an_unexpected_error_discards_the_connection(self):
        self.api("GET", "/api/info")
        with mock.patch.object(store, "list_reactions", side_effect=RuntimeError("boom")), \
                redirect_stderr(io.StringIO()):
            self.assertEqual(self.api("GET", "/api/reactions")[0], 500)
        self.assertEqual(self.settled(0, 0), (0, 0))
        # An expected refusal keeps it.
        self.assertEqual(self.api("GET", "/api/reactions/999999")[0], 404)
        self.assertEqual(self.settled(1, 1), (1, 1))

    def test_a_burst_with_clients_hanging_up_leaves_the_server_answering(self):
        rid = next(iter(self.ids().values()))
        paths = ["/api/reactions", f"/api/reactions/{rid}", f"/api/reactions/{rid}/history", "/api/facets",
                 "/api/docs/1/render?page=1&bbox=50,50,200,200&dpi=100", "/api/docs/1/pdf"]

        def hang_up(path):
            with socket.create_connection(("127.0.0.1", self.port), timeout=5) as c:
                c.sendall(f"GET {path} HTTP/1.0\r\nHost: 127.0.0.1:{self.port}\r\n\r\n".encode())
                c.recv(1)  # gone after the first byte of the answer

        def worker(n):
            for i in range(12):
                path = paths[(n + i) % len(paths)]
                if (n + i) % 3 == 0:
                    hang_up(path)
                else:
                    self.request("GET", path, headers={"Range": "bytes=0-99"} if path.endswith("pdf") else None)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(24)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertFalse(any(t.is_alive() for t in threads))
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/api/info")
        self.assertEqual(c.getresponse().status, 200)
        c.close()
        self.assertLessEqual(self.pool()._open, self.pool().size)


class OldVersions(Served):
    """Reactions a re-import of their paper replaced: hidden by default, read-only, copyable."""

    def test_api(self):
        rid = next(iter(self.ids().values()))
        conn = db.connect(self.db_path)
        try:
            with db.write(conn):
                conn.execute("UPDATE reactions SET in_latest = 0, superseded_by = 1 WHERE id = ?", (rid,))
        finally:
            conn.close()
        listed = lambda q="": [r["id"] for r in self.api("GET", f"/api/reactions{q}")[1]["rows"]]
        self.assertNotIn(rid, listed())
        self.assertEqual(listed("?latest=0"), [rid])
        self.assertIn(rid, listed("?latest=all"))
        status, body = self.api("GET", f"/api/reactions/{rid}")
        self.assertEqual((status, body["superseded_by"], body["superseded"]["import_id"]), (200, 1, 1))
        status, body = self.api("POST", f"/api/reactions/{rid}/review",
                                {"base_rev": 1, "status": "reviewed", "note": None, "author": "ann"})
        self.assertEqual(status, 400)
        self.assertIn("旧版本", body["error"])
        status, body = self.api("POST", f"/api/reactions/{rid}/copy", {"author": "ann"})
        self.assertEqual((status, body["in_latest"], body["superseded_by"]), (201, True, None))
        info = self.api("GET", "/api/info")[1]["counts"]
        self.assertEqual((info["reactions"], info["not_latest"]), (5, 1))  # 4 left + the copy; 1 old


class Static(Served):
    def test_front_page(self):
        status, headers, body = self.get("/")
        self.assertEqual((status, headers["Content-Type"]), (200, "text/html; charset=utf-8"))
        # A web dir without index.html gets the placeholder; with one, the file.
        web = self.tmp / "web"
        web.mkdir()
        httpd, base = start(server.make_handler(self.db_path, web_dir=web))
        self.servers.append(httpd)
        status, headers, body = self.request("GET", "/", base=base)
        self.assertEqual((status, headers["Content-Type"]), (200, "text/html; charset=utf-8"))
        self.assertIn("前端还没有构建", body.decode("utf-8"))
        (web / "index.html").write_text("<!doctype html><p>前端</p>", encoding="utf-8")
        status, headers, body = self.request("GET", "/", base=base)
        self.assertEqual((status, body.decode("utf-8")), (200, "<!doctype html><p>前端</p>"))
        self.assertIn("Last-Modified", headers)

    def test_vendored_module_and_304(self):
        status, headers, body = self.get("/web/vendor/pdfjs/build/pdf.min.mjs")
        self.assertEqual((status, headers["Content-Type"]), (200, "text/javascript; charset=utf-8"))
        self.assertEqual(body, (WEB_DIR / "vendor/pdfjs/build/pdf.min.mjs").read_bytes())
        status, _, body = self.get("/web/vendor/pdfjs/build/pdf.min.mjs",
                                   {"If-Modified-Since": headers["Last-Modified"]})
        self.assertEqual((status, body), (304, b""))

    def test_mime_table(self):
        web = self.tmp / "web"
        web.mkdir()
        expected = {"a.html": "text/html; charset=utf-8", "a.js": "text/javascript; charset=utf-8",
                    "a.mjs": "text/javascript; charset=utf-8", "a.css": "text/css; charset=utf-8",
                    "a.json": "application/json", "a.wasm": "application/wasm", "a.svg": "image/svg+xml",
                    "a.png": "image/png", "a.gif": "image/gif", "a.bcmap": "application/octet-stream",
                    "a.pfb": "application/octet-stream", "a.icc": "application/octet-stream", "a.ttf": "font/ttf",
                    "a.woff2": "font/woff2", "a.xyz": "application/octet-stream", "A.MJS": "text/javascript; charset=utf-8"}
        for name in expected:
            (web / name).write_bytes(b"x")
        httpd, base = start(server.make_handler(self.db_path, web_dir=web))
        self.servers.append(httpd)
        for name, ctype in expected.items():
            status, headers, _ = self.request("GET", f"/web/{name}", base=base)
            self.assertEqual((status, headers["Content-Type"]), (200, ctype), name)

    def test_nothing_outside_web(self):
        for path in ("/web/../server.py", "/web/%2e%2e/server.py", "/web/..%2fserver.py", "/web/..%2Fdb.py",
                     "/web/vendor/../../server.py", "/web/vendor/pdfjs/../../../curator/server.py",
                     "/web//etc/passwd", "/web/%2fetc%2fpasswd", "/web/a%00b", "/web/", "/web/vendor", "/nope",
                     "/api/nope", "/api/reactions/1/nope"):
            status, _, _ = self.get(path)
            self.assertEqual(status, 404, path)


class Security(Served):
    def test_host(self):
        self.assertEqual(self.get("/api/info", {"Host": "evil.example"})[0], 400)
        self.assertEqual(self.get("/api/info", {"Host": f"evil.example:{self.port}"})[0], 400)
        self.assertEqual(self.get("/web/vendor/pdfjs/VERSION", {"Host": "evil.example"})[0], 400)
        self.assertEqual(self.get("/api/info", {"Host": f"127.0.0.1:{self.port}x"})[0], 400)
        for host in (f"localhost:{self.port}", f"[::1]:{self.port}", "127.0.0.1", f"LOCALHOST:{self.port}"):
            self.assertEqual(self.get("/api/info", {"Host": host})[0], 200, host)
        status, body = self.raw("GET", "/api/info", skip_host=True)
        self.assertEqual(status, 400)
        self.assertIn("Host", json.loads(body)["error"])

    def test_host_names(self):
        self.assertEqual([server.host_name(h) for h in ("a:1", "A", "[::1]:80", "[::1]", "", None, "a:b", "[::1", ":80")],
                         ["a", "a", "::1", "::1", None, None, None, None, None])
        local = server.host_check()
        self.assertEqual([local(n) for n in ("localhost", "127.0.0.1", "127.0.0.2", "::1", "192.168.1.5", "evil.example")],
                         [True, True, True, True, False, False])
        named = server.host_check(["myhost"])
        self.assertEqual((named("myhost"), named("other")), (True, False))
        # bound to every interface: any IP address (no DNS rebinding with an IP literal), no foreign names
        anywhere = server.host_check(["0.0.0.0"])
        self.assertEqual([anywhere(n) for n in ("192.168.1.5", "10.0.0.2", "fe80::1", "evil.example")],
                         [True, True, True, False])

    def test_content_type(self):
        rid = self.ids()[E1]
        body = json.dumps({"base_rev": 1, "status": "reviewed", "note": None, "author": "ann"}).encode()
        for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"):
            status, _, _ = self.request("POST", f"/api/reactions/{rid}/review", body, {"Content-Type": ctype})
            self.assertEqual(status, 415, ctype)
        status, raw = self.raw("POST", f"/api/reactions/{rid}/review",
                               [("Content-Length", str(len(body)))], body)  # no Content-Type at all
        self.assertEqual(status, 415)
        self.assertIn("JSON", json.loads(raw)["error"])
        status, _, _ = self.request("PUT", f"/api/reactions/{rid}", body, {"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        status, data = self.api("POST", f"/api/reactions/{rid}/review", body,
                                {"Content-Type": "application/json; charset=utf-8"})
        self.assertEqual((status, data["review_status"]), (200, "reviewed"))

    def test_origin(self):
        rid = self.ids()[E1]
        review = {"base_rev": 1, "status": "problem", "note": None, "author": "ann"}
        self.assertEqual(self.get("/api/info", {"Origin": "http://evil.example"})[0], 403)
        status, data = self.api("POST", f"/api/reactions/{rid}/review", review, {"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        self.assertIn("evil.example", data["error"])
        self.assertEqual(self.api("POST", f"/api/reactions/{rid}/review", review, {"Origin": "null"})[0], 403)
        self.assertEqual(self.api("POST", f"/api/reactions/{rid}/review", review,
                                  {"Origin": f"http://localhost:{self.port}"})[0], 403)  # not the Host sent
        self.assertEqual(self.api("POST", f"/api/reactions/{rid}/review", review, {"Origin": self.base})[0], 200)

    def test_body(self):
        rid = self.ids()[E1]
        json_type = ("Content-Type", "application/json")
        status, raw = self.raw("POST", f"/api/reactions/{rid}/review",
                               [json_type, ("Content-Length", str(server.MAX_BODY + 1))])
        self.assertEqual(status, 413)
        self.assertIn("10 MB", json.loads(raw)["error"])
        self.assertEqual(self.raw("POST", f"/api/reactions/{rid}/review", [json_type])[0], 411)
        for body in (b"{", b"[1, 2]", b'{"base_rev": NaN}', b"\xff\xfe", b""):
            status, _, raw = self.request("POST", f"/api/reactions/{rid}/review", body,
                                          {"Content-Type": "application/json"})
            self.assertEqual(status, 400, body)
            self.assertIn("error", json.loads(raw))

    def test_numbers_no_json_can_hold(self):
        # 1e999 parses to infinity: a 400 like NaN, not a 500 from the json_valid CHECK, and /api/validate
        # does not pass what PUT then refuses.
        rid = self.ids()[E1]
        data = self.api("GET", f"/api/reactions/{rid}")[1]["data"]
        text = json.dumps({"base_rev": 1, "data": {**data, "results": [1.5]}, "author": "ann"}).replace("1.5", "1e999")
        for path in (f"/api/reactions/{rid}", "/api/validate"):
            status, _, raw = self.request("PUT" if path != "/api/validate" else "POST", path, text.encode(),
                                          {"Content-Type": "application/json"})
            self.assertEqual(status, 400, path)
            self.assertIn("超出范围", json.loads(raw)["error"])
        self.assertEqual(self.api("GET", f"/api/reactions/{rid}")[1]["rev"], 1)

    def test_body_nested_too_deep(self):
        for depth in (1000, 100_000):  # the validator's recursion; json.loads's own
            body = '{"paper_id": "demo", "data": {"notes": ' + "[" * depth + "]" * depth + "}}"
            status, _, raw = self.request("POST", "/api/validate", body.encode(), {"Content-Type": "application/json"})
            self.assertEqual(status, 400, depth)
            self.assertIn("嵌套太深", json.loads(raw)["error"])

    def test_ids_beyond_sqlite(self):
        # 20-digit ids raised OverflowError when bound: a 500 with a traceback.
        big = "9" * 20
        err = io.StringIO()
        with redirect_stderr(err):
            for path in (f"/api/reactions/{big}", f"/api/reactions/R{big}", f"/api/reactions/1/revisions/{big}",
                         f"/api/blocks/{big}", f"/api/docs/{big}/pdf", f"/api/docs/{big}/render?page=1",
                         f"/api/reactions?offset={big}", f"/api/reactions?block={big}", f"/api/reactions?ids={big}",
                         f"/api/facets?block={big}", f"/api/export/reactions/{big}.json",
                         f"/api/reactions/{big}/neighbours", f"/api/reactions/1/diff?from={big}"):
                status, data = self.api("GET", path)
                self.assertIn(status, (400, 404), path)
            for path, body in (("/api/reactions/1/revert", {"base_rev": 1, "to_rev": 10 ** 20, "author": "a"}),
                               ("/api/export", {"ids": [10 ** 20]}),
                               ("/api/reactions", {"paper_id": "demo", "block_pk": 10 ** 20, "author": "a"}),
                               ("/api/validate", {"id": 10 ** 20, "data": {}})):
                status, data = self.api("POST", path, body)
                self.assertIn(status, (400, 404), path)
        self.assertNotIn("Traceback", err.getvalue())

    def test_head(self):
        status, headers, body = self.request("HEAD", "/api/info")
        self.assertEqual((status, body, headers["Content-Type"]), (200, b"", "application/json; charset=utf-8"))
        self.assertEqual(int(headers["Content-Length"]), len(self.get("/api/info")[2]))
        size = len(self.blob(1))
        status, headers, body = self.request("HEAD", "/api/docs/1/pdf")
        self.assertEqual((status, body, headers["Content-Length"], headers["Accept-Ranges"]),
                         (200, b"", str(size), "bytes"))
        self.assertEqual(headers["ETag"], f'"{db.sha_bytes(self.blob(1))}"')
        status, headers, _ = self.request("HEAD", "/api/docs/1/pdf", headers={"Range": "bytes=0-9"})
        self.assertEqual((status, headers["Content-Range"]), (206, f"bytes 0-9/{size}"))
        self.assertEqual(self.raw("HEAD", "/api/info", [("Host", "evil.example")], skip_host=True)[0], 400)
        self.assertEqual(self.request("HEAD", "/api/nope")[0], 404)

    def test_unknown_method_answers_json(self):
        for method in ("DELETE", "OPTIONS", "PATCH"):
            status, headers, raw = self.request(method, "/api/reactions/1")
            self.assertEqual((status, headers["Content-Type"]), (501, "application/json; charset=utf-8"), method)
            self.assertEqual(json.loads(raw)["error"], f"不支持 {method} 请求")
            self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_listen_backlog(self):
        # One connection per request: a burst of them must not overflow the default backlog of 5.
        self.assertGreaterEqual(server._Server.request_queue_size, 128)
        self.assertGreaterEqual(self.httpd.request_queue_size, 128)

    def test_internal_error(self):
        err = io.StringIO()
        with mock.patch.object(store, "list_imports", side_effect=RuntimeError("boom")), redirect_stderr(err):
            status, data = self.api("GET", "/api/imports")
        self.assertEqual(status, 500)
        self.assertIn("RuntimeError: boom", data["error"])
        self.assertIn("Traceback", err.getvalue())
        self.assertEqual(self.api("GET", "/api/imports")[0], 200)

    def test_methods(self):
        self.assertEqual(self.api("PUT", "/api/info", {})[0], 405)
        self.assertEqual(self.api("POST", "/api/reactions/1/history", {})[0], 405)
        self.assertEqual(self.api("POST", "/api/nope", {})[0], 404)
        self.assertEqual(self.request("DELETE", "/api/reactions/1")[0], 501)


class Api(Served):
    def test_info(self):
        status, info = self.api("GET", "/api/info")
        self.assertEqual(status, 200)
        self.assertEqual(info["review_statuses"], ["unreviewed", "reviewed", "problem", "excluded"])
        self.assertIn("accept_import", info["actions"])
        self.assertIn("NMR", info["known"]["yield_type"])
        self.assertEqual(info["templates"]["condition"]["origin"], "curator")
        self.assertTrue(info["default_author"])
        c = info["counts"]
        self.assertEqual((c["papers"], c["documents"], c["blocks"], c["imports"], c["reactions"], c["deleted"]),
                         (1, 2, 2, 1, 5, 0))
        self.assertEqual(c["status"]["unreviewed"], 5)

    def test_queries(self):
        ids = self.ids()
        rid = ids[E1]
        status, page = self.api("GET", "/api/reactions")
        self.assertEqual((status, page["total"], len(page["rows"])), (200, 5, 5))
        self.assertEqual(self.api("GET", "/api/reactions?limit=2&offset=1&sort=id&order=desc")[1]["rows"][0]["id"],
                         sorted(ids.values())[-2])
        self.assertEqual(self.api("GET", "/api/reactions?flag=issues")[1]["total"], 1)
        self.assertEqual(self.api("GET", "/api/reactions?status=reviewed&status=problem")[1]["total"], 0)
        self.assertEqual(self.api("GET", "/api/reactions?q=" + "%E4%B8%8D%E5%AD%98%E5%9C%A8")[1]["total"], 0)
        self.assertEqual(self.api("GET", "/api/reactions?status=bogus")[0], 400)
        self.assertEqual(self.api("GET", "/api/reactions?sort=nope")[0], 400)
        facets = self.api("GET", "/api/facets?status=unreviewed")[1]
        self.assertEqual((facets["total"], facets["paper"][0]["value"]), (5, "demo"))
        imports = self.api("GET", "/api/imports")[1]
        self.assertEqual(imports[0]["papers"][0]["outcome"], "imported")
        self.assertEqual(self.api("GET", "/api/papers")[1][0]["paper_id"], "demo")
        paper = self.api("GET", "/api/papers/demo")[1]
        self.assertEqual((paper["doi"], sorted(paper["documents"])), (fx.DOI, ["main", "si"]))
        self.assertEqual(self.api("GET", "/api/papers/demo/history")[1][0]["action"], "import")
        r = self.api("GET", f"/api/reactions/{rid}")[1]
        block = self.api("GET", f"/api/blocks/{r['block_pk']}")[1]
        self.assertIn(rid, [x["id"] for x in block["reactions"]])
        self.assertEqual((r["origin_id"], r["rid"], r["rev"]), (E1, f"R{rid:06d}", 1))
        self.assertEqual(self.api("GET", f"/api/reactions/R{rid:06d}")[1]["id"], rid)
        nb = self.api("GET", f"/api/reactions/{rid}/neighbours?sort=id")[1]
        self.assertEqual(set(nb), {"prev", "next"})
        history = self.api("GET", f"/api/reactions/{rid}/history")[1]
        self.assertEqual([h["action"] for h in history], ["import"])
        self.assertEqual(self.api("GET", f"/api/reactions/{rid}/revisions/1")[1]["snapshot"]["data"], r["data"])
        self.assertEqual(self.api("GET", f"/api/reactions/{rid}/diff?from=1&to=current")[1], [])
        self.assertEqual(self.api("GET", f"/api/reactions/{rid}/diff?from=pipeline")[1], [])
        for path, code in ((f"/api/reactions/{rid}/diff", 400), (f"/api/reactions/{rid}/diff?from=x", 400),
                           (f"/api/reactions/{rid}/diff?from=1&to=pending", 404),
                           ("/api/reactions/999", 404), ("/api/reactions/x", 404), ("/api/reactions/999/history", 404),
                           (f"/api/reactions/{rid}/revisions/9", 404), ("/api/papers/nope", 404),
                           ("/api/papers/nope/history", 404), ("/api/blocks/999", 404), ("/api/blocks/x", 400)):
            status, data = self.api("GET", path)
            self.assertEqual(status, code, path)
            self.assertIsInstance(data["error"], str)

    def test_edit(self):
        rid = self.ids()[E1]
        data = self.api("GET", f"/api/reactions/{rid}")[1]["data"]
        data["label"] = "1a′"
        data["reaction_id"] = "somebody else's"
        status, r = self.api("PUT", f"/api/reactions/{rid}", {"base_rev": 1, "data": data, "author": "ann",
                                                               "comment": "标签"})
        self.assertEqual((status, r["rev"], r["label"], r["data"]["reaction_id"], r["edited"]), (200, 2, "1a′", E1, True))
        self.assertIsInstance(r["warnings"], list)
        # stale base: 409 with the current version
        status, err = self.api("PUT", f"/api/reactions/{rid}", {"base_rev": 1, "data": data, "author": "ann"})
        self.assertEqual((status, err["current"]["rev"], err["current"]["label"]), (409, 2, "1a′"))
        self.assertIn("error", err)
        # errors block: 422 with the paths
        data["steps"][0]["products"][0]["bbox"] = [500, 700, 900, 900]
        status, err = self.api("PUT", f"/api/reactions/{rid}", {"base_rev": 2, "data": data, "author": "ann"})
        self.assertEqual(status, 422)
        self.assertTrue(any("bbox" in e for e in err["errors"]))
        self.assertIsInstance(err["warnings"], list)
        for body in ({"data": data, "author": "ann"}, {"base_rev": 2, "author": "ann"},
                     {"base_rev": 2, "data": data, "author": ""}, {"base_rev": 2, "data": data, "author": "a",
                                                                   "comment": 5}):
            self.assertEqual(self.api("PUT", f"/api/reactions/{rid}", body)[0], 400, body)
        self.assertEqual(self.api("PUT", "/api/reactions/999", {"base_rev": 1, "data": data, "author": "a"})[0], 404)
        history = self.api("GET", f"/api/reactions/{rid}/history")[1]
        self.assertEqual([(h["action"], h["comment"]) for h in history], [("edit", "标签"), ("import", None)])
        self.assertEqual(history[0]["diff"][0]["path"], ["data", "label"])

    def test_review_revert_delete_copy_create(self):
        ids = self.ids()
        rid = ids[E3]
        r = self._ok("POST", f"/api/reactions/{rid}/review",
                     {"base_rev": 1, "status": "problem", "note": "看不清", "author": "ann"})
        self.assertEqual((r["review_status"], r["review_note"], r["touched"]), ("problem", "看不清", True))
        self.assertEqual(self.api("POST", f"/api/reactions/{rid}/review",
                                  {"base_rev": 2, "status": "bogus", "note": None, "author": "ann"})[0], 400)
        data = r["data"]
        data["notes"] = "changed"
        self._ok("PUT", f"/api/reactions/{rid}", {"base_rev": 2, "data": data, "author": "ann"})
        r = self._ok("POST", f"/api/reactions/{rid}/revert", {"base_rev": 3, "to_rev": 1, "author": "ann"})
        self.assertEqual((r["rev"], r["edited"], r["review_status"]), (4, False, "problem"))
        self.assertEqual(self.api("POST", f"/api/reactions/{rid}/revert",
                                  {"base_rev": 4, "to_rev": 99, "author": "ann"})[0], 404)
        r = self._ok("POST", f"/api/reactions/{rid}/delete", {"base_rev": 4, "author": "ann"})
        self.assertTrue(r["deleted"])
        self.assertNotIn(rid, [x["id"] for x in self.api("GET", "/api/reactions")[1]["rows"]])
        self.assertIn(rid, [x["id"] for x in self.api("GET", "/api/reactions?deleted=1")[1]["rows"]])
        r = self._ok("POST", f"/api/reactions/{rid}/restore", {"base_rev": 5, "author": "ann"})
        self.assertFalse(r["deleted"])
        self.assertEqual(self.api("POST", f"/api/reactions/{rid}/delete", {"base_rev": 1, "author": "ann"})[0], 409)

        c = self._ok("POST", f"/api/reactions/{rid}/copy", {"author": "ann"}, 201)
        self.assertEqual((c["copied_from"], c["origin_id"], c["data"]["reaction_id"]), (rid, None, None))
        block_pk = self.api("GET", f"/api/reactions/{rid}")[1]["block_pk"]
        n = self._ok("POST", "/api/reactions",
                     {"paper_id": "demo", "block_pk": block_pk, "entry_id": "e001", "author": "ann"}, 201)
        self.assertEqual((n["data"]["source"]["entry_id"], n["block_pk"], n["origin_id"]), ("e001", block_pk, None))
        for body, code in (({"block_pk": block_pk, "author": "ann"}, 400),
                           ({"paper_id": "nope", "author": "ann"}, 404),
                           ({"paper_id": "demo", "block_pk": 999, "author": "ann"}, 404),
                           ({"paper_id": "demo"}, 400)):
            self.assertEqual(self.api("POST", "/api/reactions", body)[0], code, body)
        self.assertEqual(self.api("GET", "/api/reactions")[1]["total"], 7)

    def _ok(self, method, path, body, code=200):
        status, data = self.api(method, path, body)
        self.assertEqual(status, code, (path, data))
        return data

    def test_pending(self):
        ids = self.ids()
        conn = db.connect(self.db_path)
        try:  # what a re-import does with a touched reaction whose pipeline version changed
            for origin in (E4, E5):
                row = conn.execute("SELECT * FROM reactions WHERE id = ?", (ids[origin],)).fetchone()
                state = store.state_of(row)
                newer = {**state["data"], "notes": "pipeline re-run"}
                store.apply_state(conn, ids[origin], {**state, "review_status": "reviewed"}, action="review",
                                  author="ann")
                store.apply_state(conn, ids[origin], {**state, "review_status": "reviewed"}, action="review",
                                  author="ann", extra={"pending_data": newer, "pending_sha": db.sha_json(newer),
                                                       "pending_import": 1})
        finally:
            conn.close()
        a, b = ids[E4], ids[E5]
        r = self.api("GET", f"/api/reactions/{a}")[1]
        self.assertEqual(r["pending"]["diff"][0]["path"], ["data", "notes"])
        self.assertEqual(self.api("GET", f"/api/reactions/{a}/diff?from=current&to=pending")[1][0]["new"],
                         "pipeline re-run")
        self.assertEqual(self.api("GET", "/api/reactions?pending=1")[1]["total"], 2)
        r = self._ok("POST", f"/api/reactions/{a}/pending/accept", {"base_rev": 2, "author": "ann"})
        self.assertEqual((r["pending"], r["data"]["notes"], r["edited"]), (None, "pipeline re-run", False))
        r = self._ok("POST", f"/api/reactions/{b}/pending/dismiss", {"base_rev": 2, "author": "ann"})
        self.assertEqual((r["pending"], r["rev"]), (None, 3))
        self.assertNotEqual(r["data"]["notes"], "pipeline re-run")
        self.assertEqual(self.api("POST", f"/api/reactions/{b}/pending/dismiss", {"base_rev": 3, "author": "ann"})[0],
                         400)
        self.assertEqual(self.api("POST", f"/api/reactions/{b}/pending/nope", {"base_rev": 3, "author": "ann"})[0], 404)

    def test_paper(self):
        p = self._ok("PUT", "/api/papers/demo", {"base_rev": 1, "fields": {"title": "新标题", "year": "2025"},
                                                 "author": "ann"})
        self.assertEqual((p["title"], p["year"], p["meta_origin"], p["rev"]), ("新标题", 2025, "edited", 2))
        p = self._ok("PUT", "/api/papers/demo", {"base_rev": 2, "note": "顶层字段也可以", "author": "ann"})
        self.assertEqual((p["note"], p["rev"]), ("顶层字段也可以", 3))
        status, err = self.api("PUT", "/api/papers/demo", {"base_rev": 1, "fields": {"doi": "x"}, "author": "ann"})
        self.assertEqual((status, err["current"]["rev"]), (409, 3))
        self.assertEqual(self.api("PUT", "/api/papers/demo", {"base_rev": 3, "fields": {"context": "x"},
                                                              "author": "ann"})[0], 400)
        self.assertEqual(self.api("PUT", "/api/papers/nope", {"base_rev": 1, "fields": {}, "author": "ann"})[0], 404)
        self.assertEqual([h["action"] for h in self.api("GET", "/api/papers/demo/history")[1]], ["meta", "meta", "import"])

    def test_validate(self):
        rid = self.ids()[E1]
        data = self.api("GET", f"/api/reactions/{rid}")[1]["data"]
        status, res = self.api("POST", "/api/validate", {"paper_id": "demo", "data": data})
        self.assertEqual((status, res["errors"]), (200, []))
        data["steps"][0]["products"][0]["bbox"] = [500, 700, 900, 900]
        res = self.api("POST", "/api/validate", {"paper_id": "demo", "data": data})[1]
        self.assertTrue(any("bbox" in e for e in res["errors"]))
        # the same problem in the base it started from only warns
        conn = db.connect(self.db_path)
        try:
            row = conn.execute("SELECT * FROM reactions WHERE id = ?", (rid,)).fetchone()
            store.apply_state(conn, rid, {**store.state_of(row), "data": data}, action="edit", author="ann")
        finally:
            conn.close()
        data["label"] = "x"
        res = self.api("POST", "/api/validate", {"id": rid, "data": data, "base_rev": 2})[1]
        self.assertEqual(res["errors"], [])
        self.assertTrue(any("原有问题" in w for w in res["warnings"]))
        res = self.api("POST", "/api/validate", {"id": rid, "data": data, "base_rev": 1})[1]
        self.assertTrue(res["errors"])
        self.assertTrue(self.api("POST", "/api/validate", {"paper_id": "demo", "data": [1]})[1]["errors"])
        for body, code in (({"data": data}, 400), ({"paper_id": "nope", "data": data}, 404),
                           ({"paper_id": "demo"}, 400), ({"id": 999, "data": data}, 404)):
            self.assertEqual(self.api("POST", "/api/validate", body)[0], code, body)


class Pdf(Served):
    def test_whole_file_and_etag(self):
        pdf = self.blob(1)
        status, headers, body = self.get("/api/docs/1/pdf")
        self.assertEqual((status, headers["Content-Type"], body), (200, "application/pdf", pdf))
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(headers["Content-Length"], str(len(pdf)))
        self.assertEqual(headers["ETag"], f'"{db.sha_bytes(pdf)}"')
        self.assertIn("inline", headers["Content-Disposition"])
        for tag in (headers["ETag"], f"W/{headers['ETag']}", f'"other", {headers["ETag"]}', "*"):
            status, h, body = self.get("/api/docs/1/pdf", {"If-None-Match": tag})
            self.assertEqual((status, body, h["ETag"]), (304, b"", headers["ETag"]), tag)
        self.assertEqual(self.get("/api/docs/1/pdf", {"If-None-Match": '"other"'})[0], 200)
        self.assertEqual(self.get("/api/docs/2/pdf")[2], self.blob(2))
        for doc in (99, "x"):
            self.assertEqual(self.api("GET", f"/api/docs/{doc}/pdf")[0], 404)

    def test_ranges(self):
        pdf = self.blob(1)
        size = len(pdf)
        for rng, (a, b) in (("bytes=0-99", (0, 99)), ("bytes=100-", (100, size - 1)), ("bytes=-50", (size - 50, size - 1)),
                            (f"bytes=10-{size + 1000}", (10, size - 1)), (f"bytes=-{size + 5}", (0, size - 1)),
                            (f"bytes={size - 1}-{size - 1}", (size - 1, size - 1)), ("BYTES = 5 - 9", (5, 9))):
            status, headers, body = self.get("/api/docs/1/pdf", {"Range": rng})
            self.assertEqual((status, headers["Content-Range"], body), (206, f"bytes {a}-{b}/{size}", pdf[a:b + 1]), rng)
            self.assertEqual(headers["Content-Length"], str(b - a + 1))
        for rng in (f"bytes={size}-", f"bytes={size + 10}-{size + 20}", "bytes=-0"):
            status, headers, body = self.get("/api/docs/1/pdf", {"Range": rng})
            self.assertEqual((status, headers["Content-Range"]), (416, f"bytes */{size}"), rng)
            self.assertIn("error", json.loads(body))
        # several ranges, another unit, a range that is not one: the whole file
        for rng in ("bytes=0-1,5-6", "items=0-5", "bytes=9-3", "bytes=-", "bytes=abc"):
            status, headers, body = self.get("/api/docs/1/pdf", {"Range": rng})
            self.assertEqual((status, body), (200, pdf), rng)
            self.assertNotIn("Content-Range", headers)
        # numbers with thousands of digits: past any file, not a ValueError from int()
        status, headers, _ = self.get("/api/docs/1/pdf", {"Range": f"bytes={'9' * 5000}-"})
        self.assertEqual((status, headers["Content-Range"]), (416, f"bytes */{size}"))
        status, _, body = self.get("/api/docs/1/pdf", {"Range": f"bytes=0-{'9' * 5000}"})
        self.assertEqual((status, body), (206, pdf))
        status, _, body = self.get("/api/docs/1/pdf", {"Range": f"bytes=-{'0' * 4990}{'9' * 3}"})
        self.assertEqual((status, body), (206, pdf[-999:]))
        etag = f'"{db.sha_bytes(pdf)}"'
        self.assertEqual(self.get("/api/docs/1/pdf", {"Range": "bytes=0-9", "If-Range": etag})[0], 206)
        status, _, body = self.get("/api/docs/1/pdf", {"Range": "bytes=0-9", "If-Range": '"old"'})
        self.assertEqual((status, body), (200, pdf))

    def test_streamed_in_chunks(self):
        pdf = self.blob(1)
        old = server.PDF_CHUNK
        server.PDF_CHUNK = 1000
        try:
            self.assertEqual(self.get("/api/docs/1/pdf")[2], pdf)
            self.assertEqual(self.get("/api/docs/1/pdf", {"Range": "bytes=999-2500"})[2], pdf[999:2501])
        finally:
            server.PDF_CHUNK = old

    def test_client_hangs_up(self):
        # pdf.js drops its first, whole-file request once it sees Accept-Ranges; the server goes on serving.
        old = server.PDF_CHUNK
        server.PDF_CHUNK = 16
        try:
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            c.request("GET", "/api/docs/1/pdf")
            res = c.getresponse()
            res.read(10)
            c.close()
        finally:
            server.PDF_CHUNK = old
        self.assertEqual(self.get("/api/docs/1/pdf")[2], self.blob(1))

    def test_render(self):
        status, headers, png = self.get("/api/docs/1/render?page=1&bbox=55,102,145,140&dpi=72")
        self.assertEqual((status, headers["Content-Type"]), (200, "image/png"))
        pix = pymupdf.Pixmap(png)
        self.assertAlmostEqual(pix.width, 90, delta=1)
        self.assertAlmostEqual(pix.height, 38, delta=1)
        etag = headers["ETag"]
        self.assertTrue(etag.startswith('"') and etag.endswith('"'))
        status, h, body = self.get("/api/docs/1/render?page=1&bbox=55,102,145,140&dpi=72", {"If-None-Match": etag})
        self.assertEqual((status, body, h["ETag"]), (304, b"", etag))
        # A revalidation after a restart (nothing cached) answers 304 without drawing the picture.
        pdfdocs.clear_caches()
        with mock.patch.object(pdfdocs, "render_png", side_effect=AssertionError("rendered")):
            status, _, body = self.get("/api/docs/1/render?page=1&bbox=55,102,145,140&dpi=72", {"If-None-Match": etag})
        self.assertEqual((status, body), (304, b""))
        other = self.get("/api/docs/1/render?page=1&bbox=55,102,145,141&dpi=72")[1]["ETag"]
        self.assertNotEqual(other, etag)
        status, _, png = self.get("/api/docs/2/render?page=2&dpi=36")  # a whole SI page
        pix = pymupdf.Pixmap(png)
        self.assertEqual((status, pix.width, pix.height), (200, round(fx.SI_PAGE[0] / 2), round(fx.SI_PAGE[1] / 2)))
        self.assertEqual(self.get("/api/docs/1/render?page=1&bbox=0,0,10,10&pad=5&dpi=72")[0], 200)
        for query in ("", "page=0", "page=2", "page=x", "page=1&bbox=1,2,3", "page=1&bbox=a,b,c,d",
                      "page=1&bbox=10,10,5,5", "page=1&bbox=700,700,800,800", "page=1&dpi=abc", "page=1&pad=-1",
                      "page=1.5"):
            status, data = self.api("GET", f"/api/docs/1/render?{query}")
            self.assertEqual(status, 400, query)
            self.assertIsInstance(data["error"], str)
        self.assertEqual(self.api("GET", "/api/docs/99/render?page=1")[0], 404)


class Export(Served):
    def test_single(self):
        rid = self.ids()[E1]
        status, headers, body = self.get(f"/api/export/reactions/R{rid:06d}.json")
        self.assertEqual((status, headers["Content-Type"]), (200, "application/json; charset=utf-8"))
        self.assertIn(f'attachment; filename="R{rid:06d}.json"', headers["Content-Disposition"])
        rec = json.loads(body)
        self.assertEqual((rec["id"], rec["provenance"]["origin_id"]), (f"R{rid:06d}", E1))
        self.assertEqual(rec["record"], self.api("GET", f"/api/reactions/{rid}")[1]["data"])
        self.assertEqual(self.get(f"/api/export/reactions/{rid}.json")[2], body)
        self.assertEqual(self.api("GET", "/api/export/reactions/999.json")[0], 404)

    def test_jsonl(self):
        ids = self.ids()
        status, headers, body = self.request("POST", "/api/export", {"format": "jsonl"})
        self.assertEqual((status, headers["Content-Type"], headers["X-Export-Count"]), (200, "application/x-ndjson", "5"))
        self.assertRegex(headers["Content-Disposition"], r'attachment; filename="reactions-\d{8}-\d{6}\.jsonl"')
        self.assertEqual(len(body.decode("utf-8").splitlines()), 5)
        self.assertEqual(headers["Content-Length"], str(len(body)))
        # excluded and deleted reactions stay out unless asked
        self.request("POST", f"/api/reactions/{ids[E3]}/review",
                     {"base_rev": 1, "status": "excluded", "note": None, "author": "ann"})
        self.request("POST", f"/api/reactions/{ids[E4]}/delete", {"base_rev": 1, "author": "ann"})
        def lines(body):
            return [json.loads(x)["id"] for x in body.decode("utf-8").splitlines()]
        self.assertEqual(len(lines(self.request("POST", "/api/export", {"format": "jsonl"})[2])), 3)
        self.assertEqual(len(lines(self.request("POST", "/api/export", {"format": "jsonl", "include_excluded": True,
                                                                        "include_deleted": True})[2])), 5)
        self.assertEqual(lines(self.request("POST", "/api/export", {"format": "jsonl", "ids": [ids[E1], ids[E3]]})[2]),
                         [f"R{ids[E1]:06d}"])
        self.assertEqual(lines(self.request("POST", "/api/export", {"filter": {"flag": "issues"}})[2]),
                         [f"R{ids[E6]:06d}"])
        for body in ({"format": "csv"}, {"filter": "x"}, {"ids": "1"}, {"ids": ["x"]}, {"filter": {"status": "nope"}}):
            self.assertEqual(self.api("POST", "/api/export", body)[0], 400, body)

    def test_zip(self):
        ids = self.ids()
        chosen = [ids[E1], ids[E3]]
        status, headers, body = self.request("POST", "/api/export", {"format": "zip", "ids": chosen, "images": True})
        self.assertEqual((status, headers["Content-Type"], headers["X-Export-Count"]), (200, "application/zip", "2"))
        self.assertRegex(headers["Content-Disposition"], r'filename="reactions-\d{8}-\d{6}\.zip"')
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            names = z.namelist()
            manifest = json.loads(z.read("manifest.json"))
            self.assertEqual((manifest["count"], manifest["ids"]), (2, [f"R{i:06d}" for i in sorted(chosen)]))
            for i in chosen:
                self.assertEqual(json.loads(z.read(f"reactions/R{i:06d}.json"))["id"], f"R{i:06d}")
                files = [x["file"] for x in manifest["images"][f"R{i:06d}"]]
                self.assertTrue(files)
                for f in files:
                    self.assertIn(f, names)
                    self.assertTrue(z.read(f).startswith(b"\x89PNG"))
            self.assertEqual(manifest["image_errors"], [])
        status, _, body = self.request("POST", "/api/export", {"format": "zip", "filter": {"paper": "demo"}})
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            self.assertFalse([n for n in z.namelist() if n.startswith("images/")])
            self.assertEqual(json.loads(z.read("manifest.json"))["filter"], {"paper": "demo"})


class NoWorkDir(Served):
    def test_everything_comes_from_the_database(self):
        root = _BUILT["root"]
        self.assertFalse((root / "work").exists())
        self.assertFalse((root / "Data").exists())
        rid = self.ids()[E1]
        r = self.api("GET", f"/api/reactions/{rid}")[1]
        thumb = r["thumb"]
        doc_id = r["documents"][thumb["doc"]]["doc_id"]
        bbox = ",".join(map(str, thumb["bbox"]))
        self.assertEqual(self.get(f"/api/docs/{doc_id}/render?page={thumb['page']}&bbox={bbox}")[0], 200)
        self.assertEqual(self.get(f"/api/docs/{doc_id}/pdf", {"Range": "bytes=0-4"})[2], b"%PDF-")
        block = self.api("GET", f"/api/blocks/{r['block_pk']}")[1]
        self.assertTrue(block["view"]["entries"])


class Cli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_main(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def test_import_export_check(self):
        work = fx.build_work(self.tmp)
        path = self.tmp / "db" / "curator.sqlite"
        code, out, _ = self.run_main("--db", path, "import", "--work", work, "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("试运行", out)
        self.assertFalse(path.exists())  # a dry run leaves no database behind
        code, out, _ = self.run_main("--db", path, "import", "--work", work, "--author", "tester")
        self.assertEqual(code, 0)
        self.assertIn("文献 demo：已导入", out)
        conn = db.connect(path)
        try:
            self.assertEqual(conn.execute("SELECT author FROM imports").fetchone()[0], "tester")
            self.assertEqual(conn.execute("SELECT count(*) FROM reactions").fetchone()[0], 5)
        finally:
            conn.close()
        code, out, _ = self.run_main("--db", path, "import", "--work", work, "--papers", "demo")
        self.assertEqual(code, 0)
        self.assertIn("没有变化", out)  # the same results again: nothing to replace
        code, out, _ = self.run_main("--db", path, "import", "--work", work, "--papers", "demo", "--force")
        self.assertEqual(code, 0)
        self.assertIn("替换旧版本的反应 5", out)

        jsonl = self.tmp / "out" / "all.jsonl"
        code, out, _ = self.run_main("--db", path, "export", "--out", jsonl)
        self.assertEqual(code, 0)
        self.assertIn("已导出 5 条反应", out)
        self.assertEqual(len(jsonl.read_text(encoding="utf-8").splitlines()), 5)
        self.assertFalse(list(jsonl.parent.glob("*.part")))
        code, _, _ = self.run_main("--db", path, "export", "--out", self.tmp / "two.zip", "--images", "--ids",
                                   "R000001,2", "--papers", "demo")
        self.assertEqual(code, 0)
        with zipfile.ZipFile(self.tmp / "two.zip") as z:
            manifest = json.loads(z.read("manifest.json"))
            self.assertEqual((manifest["ids"], manifest["filter"]), (["R000001", "R000002"], {"paper": "demo"}))
            self.assertTrue(any(n.startswith("images/R000001/") for n in z.namelist()))
        code, out, _ = self.run_main("--db", path, "export", "--out", self.tmp / "none.jsonl", "--status", "reviewed")
        self.assertEqual((code, (self.tmp / "none.jsonl").read_bytes()), (0, b""))
        code, _, err = self.run_main("--db", path, "export", "--out", self.tmp / "bad.jsonl", "--status", "bogus")
        self.assertEqual(code, 1)
        self.assertIn("审核状态", err)
        self.assertFalse((self.tmp / "bad.jsonl").exists())

        code, out, _ = self.run_main("--db", path, "check")
        self.assertEqual(code, 0)
        self.assertIn("检查了 10 条反应（其中 5 条是重新导入替换掉的旧版本）、1 篇文献、2 个 PDF：没有发现问题", out)

    def test_check_finds_tampering(self):
        path = self.tmp / "curator.sqlite"
        shutil.copy(built(), path)
        conn = db.connect(path)
        try:
            self.assertEqual(check(conn)[0], [])
        finally:
            conn.close()
        raw = sqlite3.connect(path)
        try:
            # What the triggers allow: a revision for a new rev, then the rev moved on without the data.
            snap = json.loads(raw.execute("SELECT snapshot FROM revisions WHERE entity = 'reaction' AND entity_id = '1'"
                                          ).fetchone()[0])
            snap["data"]["label"] = "forged"
            raw.execute("INSERT INTO revisions (entity, entity_id, rev, action, author, created_at, snapshot, diff)"
                        " VALUES ('reaction', '1', 2, 'edit', 'x', '2026-01-01', ?, '[]')", (json.dumps(snap),))
            raw.execute("UPDATE reactions SET rev = 2 WHERE id = 1")
            # What only a raw connection without the triggers can do.
            raw.execute("DROP TRIGGER reactions_need_revision")
            raw.execute("DROP TRIGGER papers_need_revision")
            raw.execute("UPDATE reactions SET data = json_set(data, '$.label', 'edited behind the log') WHERE id = 3")
            raw.execute("UPDATE reactions SET review_status = 'reviewed' WHERE id = 4")
            raw.execute("UPDATE reactions SET rev = 7 WHERE id = 5")
            raw.execute("UPDATE papers SET title = 'x' WHERE paper_id = 'demo'")
            raw.execute("UPDATE blobs SET data = CAST('%PDF-tampered' AS BLOB) WHERE rowid = 1")
            raw.commit()
        finally:
            raw.close()
        code, out, _ = self.run_main("--db", path, "check")
        self.assertEqual(code, 1)
        lines = out.splitlines()
        self.assertIn("R000001：数据和最新版本的快照不一致", lines)
        self.assertIn("R000003：data_sha 和数据不符", lines)
        self.assertIn("R000003：数据和最新版本的快照不一致", lines)
        self.assertIn("R000004：审核状态、备注或删除标记和最新版本的快照不一致", lines)
        self.assertIn("R000005：当前是第 7 版，最新的版本记录却是第 1 版", lines)
        self.assertIn("文献 demo：题录和最新版本的快照不一致", lines)
        self.assertTrue(any(line.startswith("PDF ") for line in lines))
        self.assertNotIn("R000002", out)
        self.assertRegex(lines[-1], r"发现 \d+ 个问题")

    def tampered(self, *sql) -> list[str]:
        """check's problems after raw SQL on a copy of the built database, its triggers dropped first."""
        path = self.tmp / f"t{len(list(self.tmp.iterdir()))}.sqlite"
        shutil.copy(built(), path)
        raw = sqlite3.connect(path)
        try:
            for (name,) in raw.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
                raw.execute(f"DROP TRIGGER {name}")
            raw.execute("PRAGMA foreign_keys = OFF")
            for stmt in sql:
                raw.execute(*stmt) if isinstance(stmt, tuple) else raw.execute(stmt)
            raw.commit()
        finally:
            raw.close()
        conn = db.connect(path)
        try:
            return check(conn)[0]
        finally:
            conn.close()

    def test_check_reads_the_whole_log(self):
        edit = {"op": "change", "path": ["data", "notes"], "old": "", "new": "x"}
        conn = db.connect(built())
        try:
            snap = db.loads(conn.execute("SELECT snapshot FROM revisions WHERE entity = 'reaction' AND entity_id = '3'"
                                         ).fetchone()[0])
        finally:
            conn.close()
        forged = json.dumps({**snap, "data": {"forged": True}})
        # An edited reaction whose first revision was rewritten (what INSERT OR REPLACE did before the
        # trigger refused it): the newest snapshot still agrees with the row, the chain does not.
        problems = self.tampered(
            ("INSERT INTO revisions (entity, entity_id, rev, action, author, created_at, snapshot, diff) VALUES"
             " ('reaction', '2', 2, 'edit', 'x', 'now', ?, ?)",
             (json.dumps({**snap, "data": {**snap["data"], "notes": "x"}}), json.dumps([edit]))),
            ("UPDATE revisions SET snapshot = ? WHERE entity = 'reaction' AND entity_id = '2' AND rev = 1",
             (forged,)),
            "UPDATE reactions SET rev = 2, data = (SELECT json_extract(snapshot, '$.data') FROM revisions"
            " WHERE entity = 'reaction' AND entity_id = '2' AND rev = 2) WHERE id = 2")
        self.assertIn("R000002：第 2 版记的改动和前后两版的快照对不上", problems)
        self.assertIn("R000002：有人改过（edit），touched 却是 0：重新导入会覆盖这些修改", problems)
        problems = self.tampered("UPDATE revisions SET action = 'edit' WHERE entity = 'reaction' AND entity_id = '4'")
        self.assertIn("R000004：第 1 版的操作是 edit，第一版只能是 import / create / copy", problems)
        problems = self.tampered("INSERT INTO revisions (entity, entity_id, rev, action, author, created_at, snapshot,"
                                 " diff) VALUES ('paper', 'demo', 2, 'meta', 'x', 'now', (SELECT snapshot FROM"
                                 " revisions WHERE entity = 'paper'), '[]')",
                                 "UPDATE papers SET rev = 2")
        self.assertIn("文献 demo：题录有人改过，meta_origin 却不是 edited：重新导入会覆盖这些修改", problems)
        # malformed JSON is reported, not a traceback
        problems = self.tampered("UPDATE reactions SET pending_data = '{broken', pending_sha = 'x' WHERE id = 1",
                                 "UPDATE revisions SET diff = '[' WHERE entity = 'reaction' AND entity_id = '5'")
        self.assertIn("R000001：待采用的数据不是有效的 JSON", problems)
        self.assertIn("R000005：第 1 版的快照或改动不是有效的 JSON", problems)
        problems = self.tampered("UPDATE reactions SET block_pk = 99999, last_import = 424242 WHERE id = 1")
        self.assertIn("外键：reactions 的第 1 行指向 blocks 里没有的行", problems)
        self.assertIn("外键：reactions 的第 1 行指向 imports 里没有的行", problems)

    def test_check_beside_a_writer(self):
        # A save committed while check runs is either all seen or not at all.
        path = self.tmp / "c.sqlite"
        shutil.copy(built(), path)
        conn, other = db.connect(path), db.connect(path)

        class Interleaved:  # the connection, with a save of another one just before the reactions are read
            def __getattr__(self, name):
                return getattr(conn, name)

            def execute(self, sql, *args):
                if sql.startswith("SELECT * FROM reactions"):
                    store.update_paper(other, "demo", base_rev=1, fields={"note": "hello"}, author="ann")
                    rid = other.execute("SELECT id FROM reactions ORDER BY id").fetchone()[0]
                    store.review(other, rid, base_rev=1, status="reviewed", note=None, author="ann")
                return conn.execute(sql, *args)
        try:
            self.assertEqual(check(Interleaved())[0], [])
            self.assertEqual(check(conn)[0], [])
            self.assertEqual(conn.execute("SELECT rev FROM papers").fetchone()[0], 2)
        finally:
            conn.close()
            other.close()

    def test_backup(self):
        path, copy = self.tmp / "c.sqlite", self.tmp / "backups" / "c-copy.sqlite"
        shutil.copy(built(), path)
        conn = db.connect(path)
        store.review(conn, 1, base_rev=1, status="reviewed", note="ok", author="ann")  # still in the -wal
        try:
            code, out, _ = self.run_main("--db", path, "backup", "--out", copy)
        finally:
            conn.close()
        self.assertEqual(code, 0)
        self.assertIn("已备份到", out)
        conn = db.connect(copy)
        try:
            self.assertEqual(check(conn)[0], [])
            self.assertEqual(conn.execute("SELECT review_status FROM reactions WHERE id = 1").fetchone()[0], "reviewed")
        finally:
            conn.close()
        code, _, err = self.run_main("--db", path, "backup", "--out", copy)
        self.assertEqual(code, 1)
        self.assertIn("已经存在", err)
        self.assertFalse(list(copy.parent.glob("*.part")))

    def test_export_status_excluded_warns(self):
        path = self.tmp / "c.sqlite"
        shutil.copy(built(), path)
        code, out, err = self.run_main("--db", path, "export", "--out", self.tmp / "x.jsonl", "--status", "excluded")
        self.assertEqual(code, 0)
        self.assertIn("--include-excluded", err)
        code, _, err = self.run_main("--db", path, "export", "--out", self.tmp / "y.jsonl", "--status", "excluded",
                                     "--include-excluded")
        self.assertEqual((code, err), (0, ""))

    def test_serve_that_cannot_start(self):
        path = self.tmp / "c.sqlite"
        shutil.copy(built(), path)
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            code, _, err = self.run_main("--db", path, "serve", "--port", taken.getsockname()[1])
        self.assertEqual(code, 1)
        self.assertIn("端口已被占用", err)
        self.assertNotIn("Traceback", err)
        bad = self.tmp / "bad.sqlite"
        bad.write_bytes(b"not a database, but long enough to have a header" * 100)
        code, _, err = self.run_main("--db", bad, "serve", "--port", 0)
        self.assertEqual(code, 1)
        self.assertIn("无法打开数据库", err)

    def test_import_refused_exits_1(self):
        work = fx.build_work(self.tmp)
        pdf = Path(json.loads((work / "demo" / "paper.json").read_text())["documents"]["main"]["pdf"])
        pdf.write_bytes(pdf.read_bytes() + b"\n% changed\n")
        code, out, _ = self.run_main("--db", self.tmp / "c.sqlite", "import", "--work", work)
        self.assertEqual(code, 1)
        self.assertIn("文献 demo：拒绝", out)

    def test_missing_database(self):
        path = self.tmp / "nothing.sqlite"
        for argv in (("export", "--out", self.tmp / "x.jsonl"), ("check",), ("serve", "--port", "0")):
            code, _, err = self.run_main("--db", path, *argv)
            self.assertEqual(code, 1, argv)
            self.assertIn("先运行 python -m curator import", err)
        self.assertFalse(path.exists())
        code, _, err = self.run_main("--db", path, "import", "--work", self.tmp / "no-work")
        self.assertEqual(code, 1)
        self.assertIn("没有 work 目录", err)

    def test_serve_banner(self):
        self.assertEqual([server.is_loopback(h) for h in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "192.168.1.5")],
                         [True, True, True, False, False])
        self.assertEqual(len(server.banner("127.0.0.1", 8791, "db")), 1)
        lines = server.banner("0.0.0.0", 8791, "db")
        self.assertEqual(lines[0], "curator: http://0.0.0.0:8791/  （数据库：db）")
        self.assertIn("没有任何认证", lines[1])
        with self.assertRaises(FileNotFoundError):
            server.make_server(self.tmp / "nothing.sqlite", "127.0.0.1", 0)


if __name__ == "__main__":
    unittest.main()
