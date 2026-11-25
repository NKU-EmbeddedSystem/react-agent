"""Bringing the pipeline's results into the curator database (python -m curator import).

Per paper it reads work/<id>/paper.json, step1/regions.json, step2/reactions.json, step2/blocks/*/view.json
and the PDFs paper.json names, which must still hash to what the pipeline read. Nothing under work/ or
Data/ is read after this: the PDFs go into `blobs`, the blocks' context into `blocks`, the records
(without crop paths) into `reactions`.

Importing a paper again replaces what its previous import brought in, as a whole:

  nothing changed since the paper's last import   skipped (content_sha: reactions.json, regions.json,
                                                   the views and the PDFs are all the same); `force`
                                                   imports it again anyway
  otherwise                                        every current reaction of the paper (from the
                                                   pipeline or made by hand) becomes an old version:
                                                   in_latest 0, superseded_by this import, read-only and
                                                   hidden by default, its revisions kept; every record
                                                   of the new reactions.json is inserted anew (rev 1,
                                                   action import); a PDF that changed replaces the
                                                   stored document; blocks are brought up to date

What a person did to the old reactions (edits, reviews, reactions added by hand) is not carried over; it
stays readable in the old versions and their history, and the report counts it.
Guards: only papers whose extract step is done and still up to date (no earlier step ran again after it
started, and it read the very PDFs that are there now: steps.extract.sources); a PDF that no longer
hashes to paper.json refuses the paper. A record holding NaN or Infinity is left out. Each paper is one
transaction; a dry run runs everything inside one transaction that is rolled back (each paper a
savepoint in it).
"""

from __future__ import annotations

import html
import json
import math
import os
import re
import subprocess
import traceback
from contextlib import contextmanager
from pathlib import Path

from . import db, pdfdocs, records, store
from .config import ROOT
from .diff import diff

DOCS = ("main", "si")
COUNTS = ("inserted", "superseded", "superseded_touched", "superseded_created", "failed_not_imported", "blocks",
          "validation_errors", "validation_warnings")
# A DOI as printed: ASCII without spaces, quotes or angle brackets (so 。，” and the CJK text after them
# are not taken in when nothing separates them).
DOI_RE = re.compile(r"10\.\d{4,9}/[!#-;=?-~]+")
EDITION = re.compile(r"(\w+)\s+edition\b", re.IGNORECASE)  # Angewandte: "German Edition: DOI: …" comes first
ET_AL = re.compile(r"\bet\s+al\b|等")
EARLIER_STEPS = ("preprocess", "locate")  # what extract builds on (pipeline.steps.STEPS order)
STALE = "extract 的结果已过期（PDF 或第一步在 extract 之后又跑过），请重跑 extract"
SIZE_TOLERANCE = 0.5  # pt a page of the PDF may differ from the pipeline's manifest before it is reported
META_FIELDS = ("title", "authors", "journal", "year", "doi")  # what the import fills in (note is a person's)


class NotImported(Exception):
    """The paper is skipped or refused; `reason` says why, in words for the report."""

    def __init__(self, outcome: str, reason: str):
        super().__init__(reason)
        self.outcome, self.reason = outcome, reason


def _refuse(reason: str):
    raise NotImported("refused", reason)


# ----------------------------------------------------------------------------- bibliographic data

def _alnum(text: str) -> str:
    """Letters and digits only, casefolded (CJK letters are letters)."""
    return re.sub(r"[\W_]+", "", text.casefold())


def _clean(value) -> str | None:
    if not isinstance(value, str):
        return None
    return re.sub(r"\s+", " ", html.unescape(value)).strip() or None


def filename_meta(filename: str) -> dict:
    """Reference-manager file names, 'Authors - Journal - Year - Title.pdf' (by the curator's own PDF reader): {authors, journal, year, title}, or {} for any other name."""
    parts = [p.strip() for p in Path(filename).stem.split(" - ")]
    if len(parts) >= 4 and re.fullmatch(r"\d{4}", parts[2]):
        return {"authors": parts[0], "journal": parts[1], "year": int(parts[2]), "title": " - ".join(parts[3:])}
    return {}


def find_doi(text: str) -> str | None:
    """The paper's DOI on its first page: the first one that is not labelled as the German edition's,
    without the punctuation that follows it in a sentence (a closing bracket stays when the DOI opened
    it: 10.1016/0040-4039(95)00001-x)."""
    text = text or ""
    pairs = {")": "(", "]": "[", "}": "{"}
    for m in DOI_RE.finditer(text):
        labels = EDITION.findall(text, max(0, m.start() - 60), m.start())
        if labels and labels[-1].casefold() == "german":
            continue
        doi = m.group()
        while doi:
            last = doi[-1]
            if last in ".,;:'" or (last in pairs and doi.count(pairs[last]) < doi.count(last)):
                doi = doi[:-1]
            else:
                break
        if doi:
            return doi
    return None


def _authors(meta_author: str | None, fn_authors: str | None) -> str | None:
    """The PDF's author metadata, unless it is a single name where the file name says "et al." (or 等):
    many publishers put only the first author there."""
    if meta_author and fn_authors and ET_AL.search(fn_authors) and not re.search(r"[,;&、]|\sand\s", meta_author):
        return fn_authors
    return meta_author or fn_authors


def auto_meta(filename: str, metadata: dict, first_page_text: str) -> dict:
    """{title, authors, journal, year, doi} as far as the main PDF tells: journal and year from the file
    name, authors from the PDF's metadata (else, or where it names one of several, the file name), the
    title from the file name unless the PDF's own title extends it (file names are often cut short), the
    DOI from the first page."""
    meta = metadata if isinstance(metadata, dict) else {}
    fn = filename_meta(filename)
    meta_title = _clean(meta.get("title"))
    title = fn.get("title")
    if not title:
        title = meta_title or Path(filename).stem or None
    elif meta_title and (start := _alnum(title)[:25]) and _alnum(meta_title).startswith(start):
        title = meta_title
    return {"title": title, "authors": _authors(_clean(meta.get("author")), fn.get("authors")),
            "journal": fn.get("journal"), "year": fn.get("year"), "doi": find_doi(first_page_text)}


# ----------------------------------------------------------------------------- reading work/<id>/

def _paper_key(name: str):
    return (0, int(name), "") if name.isdigit() else (1, 0, name)


def paper_dirs(work_dir) -> dict[str, Path]:
    """{paper_id: dir} of the papers under a work dir (directories with a paper.json), in paper order."""
    work_dir = Path(work_dir)
    dirs = [p for p in work_dir.iterdir() if p.is_dir() and (p / "paper.json").is_file()]
    return {p.name: p for p in sorted(dirs, key=lambda p: _paper_key(p.name))}


def _read_json(path: Path, what: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _refuse(f"没有 {what}")
    except (OSError, ValueError) as e:
        _refuse(f"{what} 无法读取：{e}")


def _manifest(path: Path):
    """A document's manifest from Step 0, only used to compare page sizes: None if it cannot be read."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _pages(numbers: list[int]) -> str:
    shown = "、".join(map(str, numbers[:10]))
    return shown + (f" 等 {len(numbers)} 页" if len(numbers) > 10 else "")


def _geometry(name: str, info: dict, manifest) -> list[str]:
    """Where the PDF's pages disagree with the pipeline's manifest, and rotated pages (the pipeline's text
    tools and crops do not agree with PDF coordinates there)."""
    out = []
    manifest = manifest if isinstance(manifest, dict) else {}
    sizes = {p.get("page"): p.get("size_pt") for p in manifest.get("pages") or [] if isinstance(p, dict)}
    off = []
    for n, (w, h, *_) in enumerate(info["pages"], 1):
        s = sizes.get(n)
        if isinstance(s, list) and len(s) == 2 and all(isinstance(v, (int, float)) for v in s) \
                and (abs(w - s[0]) > SIZE_TOLERANCE or abs(h - s[1]) > SIZE_TOLERANCE):
            off.append(n)
    if off:
        out.append(f"文档 {name} 第 {_pages(off)} 页的尺寸和流水线 manifest 记的相差超过 {SIZE_TOLERANCE}pt")
    if manifest.get("page_count") not in (None, info["page_count"]):
        out.append(f"文档 {name} 有 {info['page_count']} 页，流水线 manifest 记的是 {manifest['page_count']} 页")
    rotated = [n for n, p in enumerate(info["pages"], 1) if p[2]]
    if rotated:
        out.append(f"文档 {name} 第 {_pages(rotated)} 页是旋转的：流水线在旋转页上的框可能和 PDF 坐标对不上")
    return out


def _partial(params: dict) -> str | None:
    """How an extract run was narrowed (--blocks, --kinds, --limit, --no-entries), or None."""
    bits = [f"{k}={v}" for k in ("blocks", "kinds", "limit") if (v := params.get(k)) not in (None, [], "")]
    if params.get("entries") is False:
        bits.append("没有逐条反应")
    return "，".join(bits) or None


def _strip_view(view: dict) -> dict:
    """view.json without the records and drafts of its reactions (those live in `reactions`) and without
    crop paths: they point into work/, and every picture is rendered from its box (records.normalize).
    A NaN or Infinity the pipeline wrote becomes null (no JSON can carry it)."""
    return _finite_or_null(records.normalize({**view, "entries": [
        {**e, "reactions": [{k: v for k, v in rv.items() if k not in ("record", "draft")}
                            for rv in e.get("reactions") or [] if isinstance(rv, dict)]}
        for e in view.get("entries") or [] if isinstance(e, dict)]}))


def _load(pdir: Path, pid: str, src: dict) -> dict:
    """Everything one paper's import reads from its work dir and its PDFs, checked; no database. Fills
    `src` as it goes, so that a paper that is skipped or refused still reports its steps."""
    warn = src["warnings"].append
    paper = _read_json(pdir / "paper.json", "paper.json")
    if not isinstance(paper, dict):
        _refuse("paper.json 不是对象")
    steps = paper.get("steps") if isinstance(paper.get("steps"), dict) else {}
    src["steps"] = {name: {k: v for k, v in s.items() if k != "sources"} for name, s in steps.items()
                    if isinstance(s, dict)}
    extract = steps.get("extract") if isinstance(steps.get("extract"), dict) else {}
    if extract.get("status") != "done":
        raise NotImported("skipped", f"extract 步骤没有完成（{extract.get('status') or '没有运行过'}）")
    if paper.get("paper_id") not in (None, pid):
        warn(f"paper.json 的 paper_id 是 {paper.get('paper_id')}，按目录名 {pid} 导入")
    if partial := _partial(extract.get("params") if isinstance(extract.get("params"), dict) else {}):
        warn(f"extract 是部分运行（{partial}）：结果里可能缺少反应")
    # The runner's own rule: an earlier step that ran again after extract started leaves its results stale
    # (Step 1 may have renamed the blocks they hang on, Step 0 read another PDF).
    started = extract.get("started_at")
    for name in EARLIER_STEPS:
        s = steps.get(name)
        if isinstance(s, dict) and (s.get("status") != "done"
                                    or (started and str(s.get("finished_at") or "") > str(started))):
            _refuse(f"{STALE}（{name} 在 extract 之后又运行过：{s.get('status')}，{s.get('finished_at') or '未完成'}）")
    read = extract.get("sources") if isinstance(extract.get("sources"), dict) else None
    if read is None:
        warn("paper.json 没有记下 extract 读的 PDF，无法确认结果和现在的 PDF 对得上")

    # The PDFs: the very files the pipeline read.
    src["docs"] = {}
    documents = paper.get("documents") if isinstance(paper.get("documents"), dict) else {}
    for name in sorted((set(read or {}) & set(DOCS)) - set(documents)):
        _refuse(f"{STALE}（extract 读过文档 {name}，paper.json 里已经没有了）")
    for name, d in documents.items():
        if name not in DOCS:
            warn(f"忽略文档 {name}（只导入 main 和 si）")
            continue
        if not isinstance(d, dict) or not isinstance(d.get("pdf"), str) or not d["pdf"]:
            _refuse(f"paper.json 里文档 {name} 没有 PDF 路径")
        path = Path(d["pdf"])
        if not path.is_absolute():
            path = Path(paper.get("source_dir") or pdir) / path
        if not path.is_file():
            _refuse(f"找不到文档 {name} 的 PDF：{path}")
        if not d.get("sha256"):
            _refuse(f"paper.json 没有记下文档 {name} 的 sha256，无法确认 PDF 就是流水线读的那个")
        data = path.read_bytes()
        sha = db.sha_bytes(data)
        if sha != d["sha256"]:
            _refuse(f"文档 {name} 的 PDF 不是流水线读的那个文件（sha256 {sha[:12]}…，paper.json 记的是"
                    f" {str(d['sha256'])[:12]}…）：{path}")
        if read is not None:
            used = read.get(name).get("sha256") if isinstance(read.get(name), dict) else None
            if used is None:
                _refuse(f"{STALE}（extract 没有读过文档 {name}）")
            if used != sha:
                _refuse(f"{STALE}（extract 读的文档 {name} 是 {str(used)[:12]}…，现在的 PDF 是 {sha[:12]}…）")
        try:
            info = pdfdocs.pdf_info(data)
        except ValueError as e:
            _refuse(f"文档 {name}：{e}")
        for w in _geometry(name, info, _manifest(pdir / name / "manifest.json")):
            warn(w)
        src["docs"][name] = {"filename": path.name, "bytes": data, "sha": sha, "info": info}
    if "main" not in src["docs"]:
        _refuse("paper.json 里没有正文 PDF（documents.main）")

    # An opt-in consolidated workspace has an explicit completion/hash gate. A failed rerun must
    # never silently import a previously published result left on disk.
    consolidation = pdir / "consolidation.json"
    if consolidation.exists():
        manifest = _read_json(consolidation, "consolidation.json")
        if not isinstance(manifest, dict) or manifest.get("status") != "done":
            _refuse("consolidate 尚未成功完成，拒绝导入旧产物")
        if manifest.get("reactions_sha") != db.sha_bytes((pdir / "step2/reactions.json").read_bytes()):
            _refuse("consolidate 产物哈希不匹配")
        for relative, expected in manifest.get("artifact_hashes", {}).items():
            path = (pdir / relative).resolve()
            if not path.is_relative_to(pdir.resolve()) or not path.is_file() or db.sha_bytes(path.read_bytes()) != expected:
                _refuse(f"consolidate 上下文哈希不匹配：{relative}")
        if manifest.get("partial"):
            warn("consolidate 是小样本试运行，仅包含部分核查结果")

    # Blocks: the included ones of regions.json, each with its view.json.
    regions = _read_json(pdir / "step1" / "regions.json", "step1/regions.json")
    content = {f"pdf/{name}": [d["sha"], d["filename"]] for name, d in src["docs"].items()}
    content["step1/regions.json"] = db.sha_bytes((pdir / "step1" / "regions.json").read_bytes())
    if not isinstance(regions, dict) or not isinstance(regions.get("regions"), list):
        _refuse("step1/regions.json 没有 regions 列表")
    src["context"] = _finite_or_null(regions.get("paper"))
    views = {}
    for path in sorted((pdir / "step2" / "blocks").glob("*/view.json")):
        view = _read_json(path, f"step2/blocks/{path.parent.name}/view.json")
        content[f"step2/blocks/{path.parent.name}/view.json"] = db.sha_bytes(path.read_bytes())
        if isinstance(view, dict) and isinstance(view.get("ref"), str):
            views[view["ref"]] = view
    src["blocks"] = []
    for region in regions["regions"]:
        for block in region.get("blocks") or []:
            if not (region.get("include") and block.get("include")):
                continue
            ref = f"{region.get('region_id')}/{block.get('block_id')}"
            view = views.pop(ref, None)
            if view is None:
                warn(f"block {ref} 没有 view.json，没有导入")
            else:
                src["blocks"].append((region, block, view))
    if views:
        warn(f"忽略不属于纳入 block 的 view.json：{', '.join(sorted(views))}")

    # What the views say about each reaction (by pipeline id), and which ones failed.
    src["info"], src["block_of"], src["failed"] = {}, {}, []
    empty = []
    for region, block, view in src["blocks"]:
        region_id, block_id = region["region_id"], block["block_id"]
        for e in view.get("entries") or []:
            if not e.get("reactions"):
                empty.append(f"{region_id}/{block_id}/{e.get('eid')}（{e.get('status')}）")
            for rv in e.get("reactions") or []:
                key = f"{region_id}/{block_id}/{rv.get('rid')}"
                src["info"][key] = {k: rv.get(k) for k in ("status", "flags", "errors", "warnings", "seconds")}
                # The block's own warnings live in its view (shown there once); a record keeps
                # only what its own reaction reported.
                src["info"][key]["warnings"] = list(dict.fromkeys(rv.get("warnings") or []))
                src["info"][key]["errors"] = list(dict.fromkeys(rv.get("errors") or []))
                src["block_of"][key] = (region_id, block_id)
                if not rv.get("record") and not (consolidation.exists() and rv.get("status") == "skipped"):
                    src["failed"].append(key)
    if empty:
        warn(f"{len(empty)} 个条目没有得到反应：{', '.join(empty[:10])}" + ("…" if len(empty) > 10 else ""))

    # The records.
    path = pdir / "step2" / "reactions.json"
    try:
        raw = path.read_bytes()
        doc = json.loads(raw)
    except FileNotFoundError:
        _refuse("没有 step2/reactions.json")
    except (OSError, ValueError) as e:
        _refuse(f"step2/reactions.json 无法读取：{e}")
    if not isinstance(doc, dict) or not isinstance(doc.get("records"), list):
        _refuse("step2/reactions.json 没有 records 列表")
    src["reactions_sha"] = content["step2/reactions.json"] = db.sha_bytes(raw)
    # Everything this import reads: the same again on the next import means the paper did not change.
    src["content_sha"] = db.sha_json(content)
    src["records"] = {}
    for i, rec in enumerate(doc["records"]):
        oid = rec.get("reaction_id") if isinstance(rec, dict) else None
        if not isinstance(oid, str) or not oid:
            warn(f"reactions.json 第 {i + 1} 条没有 reaction_id，没有导入")
        elif oid in src["records"]:
            warn(f"reactions.json 里 {oid} 出现了不止一次，只导入第一条")
        elif not _finite(rec):  # Python's json writes NaN and Infinity, which are no JSON: not storable
            warn(f"reactions.json 里 {oid} 含 NaN 或无穷大，没有导入")
        else:
            data = records.normalize(rec)
            src["records"][oid] = (data, db.sha_json(data))
    return src


def _finite(value) -> bool:
    """No NaN or Infinity anywhere in a JSON value."""
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(map(_finite, value.values()))
    if isinstance(value, list):
        return all(map(_finite, value))
    return True


def _finite_or_null(value):
    """A JSON value with NaN and Infinity as null."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _finite_or_null(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite_or_null(v) for v in value]
    return value


# ----------------------------------------------------------------------------- writing one paper

@contextmanager
def _transaction(conn):
    """One paper's writes: a transaction of its own, or a savepoint inside the dry run's."""
    if not conn.in_transaction:
        with db.write(conn):
            yield
        return
    conn.execute("SAVEPOINT import_paper")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK TO import_paper")
        conn.execute("RELEASE import_paper")
        raise
    conn.execute("RELEASE import_paper")


def _paper(conn, pid: str, src: dict, import_id: int, author: str) -> None:
    """Insert the paper, or bring its automatic bibliographic data up to date (never once a person edited
    it). `context` (regions.json paper{}) is the pipeline's and is always replaced."""
    main = src["docs"]["main"]
    meta = auto_meta(main["filename"], main["info"]["metadata"], main["info"]["first_page_text"])
    now = db.now_iso()
    p = conn.execute("SELECT * FROM papers WHERE paper_id = ?", (pid,)).fetchone()
    if p is None:
        conn.execute("INSERT INTO papers (paper_id, title, authors, journal, year, doi, note, meta_origin, context,"
                     " rev, created_at, updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, NULL, 'auto', ?, 1, ?, ?, ?)",
                     (pid, *(meta[k] for k in META_FIELDS), db.dumps(src["context"]), now, now, author))
        db.insert_revision(conn, entity="paper", entity_id=pid, rev=1, action="import", author=author,
                           snapshot={**meta, "note": None}, diff=[], import_id=import_id, created_at=now)
        return
    conn.execute("UPDATE papers SET context = ? WHERE paper_id = ?", (db.dumps(src["context"]), pid))
    if p["meta_origin"] != "auto":
        return
    old = {k: p[k] for k in store.PAPER_FIELDS}
    new = {**old, **meta}
    changes = diff(old, new)
    if changes:
        rev = p["rev"] + 1
        db.insert_revision(conn, entity="paper", entity_id=pid, rev=rev, action="reimport", author=author,
                           snapshot=new, diff=changes, import_id=import_id, base_rev=p["rev"], created_at=now)
        conn.execute(f"UPDATE papers SET {', '.join(f'{k} = ?' for k in META_FIELDS)}, rev = ?, updated_at = ?,"
                     " updated_by = ? WHERE paper_id = ?", [*(new[k] for k in META_FIELDS), rev, now, author, pid])


def _documents(conn, pid: str, src: dict, stored: dict, warn) -> None:
    """Store the paper's PDFs: a new document is added, one whose PDF changed is replaced (its old blob
    stays, the old versions of the paper's reactions were drawn on it)."""
    for name, d in src["docs"].items():
        old = stored.get(name)
        if old is not None and old["sha256"] == d["sha"]:
            if old["filename"] != d["filename"]:
                conn.execute("UPDATE documents SET filename = ? WHERE doc_id = ?", (d["filename"], old["doc_id"]))
            continue
        pdfdocs.store_pdf(conn, d["bytes"])
        info = d["info"]
        cols = (d["filename"], d["sha"], info["page_count"], db.dumps(info["pages"]), db.dumps(info["metadata"]))
        if old is None:
            conn.execute("INSERT INTO documents (paper_id, doc, filename, sha256, page_count, pages, pdf_meta)"
                         " VALUES (?, ?, ?, ?, ?, ?, ?)", (pid, name, *cols))
        else:
            warn(f"文档 {name} 的 PDF 换过（sha256 {old['sha256'][:12]}… → {d['sha'][:12]}…），用新的替换")
            conn.execute("UPDATE documents SET filename = ?, sha256 = ?, page_count = ?, pages = ?, pdf_meta = ?"
                         " WHERE doc_id = ?", (*cols, old["doc_id"]))
    for name in sorted(set(stored) - set(src["docs"])):
        warn(f"库里有文档 {name}，paper.json 里已经没有了；保留库里的")


def _blocks(conn, pid: str, src: dict, import_id: int) -> dict:
    """Upsert the blocks of this import (a block keeps its block_pk), mark the others not latest; returns
    {(region_id, block_id): block_pk} of every block of the paper."""
    seen = []
    for region, rblock, view in src["blocks"]:
        # regions.json is Step 1's word on the block; the view's copy fills what it leaves out
        block = {**(view.get("block") or {}), **{k: v for k, v in rblock.items() if v is not None}}
        vregion = view.get("region") or {}
        cols = {"slug": view.get("slug"), "doc": region.get("doc") or vregion.get("doc") or "main",
                "page": block.get("page") if isinstance(block.get("page"), int) else None,
                "figure": region.get("label") or vregion.get("label"), "layout": block.get("layout"),
                "kind": block.get("kind"), "title": block.get("title"),
                "region": db.dumps(_finite_or_null({**vregion, "boxes": region.get("boxes") or []})),
                "view": db.dumps(_strip_view(view)), "import_id": import_id, "in_latest": 1}
        key = (pid, region["region_id"], rblock["block_id"])
        row = conn.execute("SELECT block_pk FROM blocks WHERE paper_id = ? AND region_id = ? AND block_id = ?",
                           key).fetchone()
        if row is None:
            cols = {"paper_id": pid, "region_id": key[1], "block_id": key[2], **cols}
            seen.append(conn.execute(f"INSERT INTO blocks ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                     list(cols.values())).lastrowid)
        else:
            conn.execute(f"UPDATE blocks SET {', '.join(f'{k} = ?' for k in cols)} WHERE block_pk = ?",
                         [*cols.values(), row["block_pk"]])
            seen.append(row["block_pk"])
    conn.execute(f"UPDATE blocks SET in_latest = 0 WHERE paper_id = ? AND block_pk NOT IN ({', '.join('?' * len(seen))})",
                 [pid, *seen])
    return {(r["region_id"], r["block_id"]): r["block_pk"]
            for r in conn.execute("SELECT region_id, block_id, block_pk FROM blocks WHERE paper_id = ?", (pid,))}


def _unchanged(conn, pid: str, src: dict, stored: dict) -> int | None:
    """The import whose content this paper still has (nothing read differs from it), or None. Imports made
    before content_sha was recorded compare reactions.json and the PDFs."""
    last = conn.execute("SELECT import_id, content_sha, reactions_sha FROM import_papers WHERE paper_id = ?"
                        " AND outcome = 'imported' ORDER BY import_id DESC LIMIT 1", (pid,)).fetchone()
    if last is None:
        return None
    if last["content_sha"] is not None:
        return last["import_id"] if last["content_sha"] == src["content_sha"] else None
    same_pdfs = set(stored) == set(src["docs"]) and all(stored[n]["sha256"] == d["sha"] for n, d in src["docs"].items())
    return last["import_id"] if same_pdfs and last["reactions_sha"] == src["reactions_sha"] else None


def _write(conn, pid: str, src: dict, import_id: int, res: dict, author: str, force: bool) -> None:
    """One paper into the database (inside its transaction); NotImported rolls it back."""
    warn, counts = res["warnings"].append, res["counts"]
    stored = {r["doc"]: r for r in conn.execute("SELECT doc, doc_id, sha256, filename FROM documents"
                                                " WHERE paper_id = ?", (pid,))}
    same = None if force else _unchanged(conn, pid, src, stored)
    if same is not None:
        res["unchanged"] = True
        raise NotImported("skipped", f"和上次导入（批次 #{same}）的内容相同，没有变化；要重新覆盖请加 --force")

    _paper(conn, pid, src, import_id, author)
    _documents(conn, pid, src, stored, warn)
    block_pks = _blocks(conn, pid, src, import_id)
    counts["blocks"] = len(src["blocks"])

    # The paper is replaced as a whole: what the last import (and people since) made current becomes an
    # old version. Its rows and revisions stay; the triggers keep them read-only from now on.
    old = conn.execute("SELECT id, touched, origin_id FROM reactions WHERE paper_id = ? AND in_latest = 1",
                       (pid,)).fetchall()
    if old:
        conn.execute("UPDATE reactions SET in_latest = 0, superseded_by = ? WHERE paper_id = ? AND in_latest = 1",
                     (import_id, pid))
    counts["superseded"] = len(old)
    counts["superseded_touched"] = sum(1 for r in old if r["touched"])
    counts["superseded_created"] = sum(1 for r in old if r["origin_id"] is None)
    res["superseded_ids"] = [r["id"] for r in old]

    docs = store.docs_for(conn, pid)
    for oid, (data, sha) in src["records"].items():
        errors, warnings = records.validate(data, docs)
        counts["validation_errors"] += len(errors)
        counts["validation_warnings"] += len(warnings)
        if errors or warnings:
            res["validation"][oid] = {"errors": errors, "warnings": warnings}
        source = data.get("source") if isinstance(data.get("source"), dict) else {}
        block_pk = block_pks.get(src["block_of"].get(oid) or (source.get("region_id"), source.get("block_id")))
        store.insert_reaction(conn, paper_id=pid, block_pk=block_pk, origin_id=oid, data=data, action="import",
                              author=author, import_id=import_id, pipeline_sha=sha, pipeline_info=src["info"].get(oid))
        counts["inserted"] += 1
    counts["failed_not_imported"] = len(src["failed"])
    res["failed_ids"] = list(src["failed"])


def _paper_row(conn, import_id: int, pid: str, res: dict, src: dict) -> None:
    conn.execute("INSERT INTO import_papers (import_id, paper_id, outcome, reason, steps, reactions_sha, counts,"
                 " content_sha) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (import_id, pid, res["outcome"], res["reason"], db.dumps(src.get("steps")),
                  src.get("reactions_sha"), db.dumps(res["counts"]), src.get("content_sha")))


def _import_paper(conn, pid: str, pdir: Path | None, import_id: int, *, author: str, force: bool, log) -> dict:
    res = {"outcome": "imported", "reason": None, "unchanged": False, "counts": dict.fromkeys(COUNTS, 0),
           "failed_ids": [], "superseded_ids": [], "warnings": [], "validation": {}}
    src = {"warnings": res["warnings"]}
    try:
        if pdir is None:
            raise NotImported("skipped", "work 目录里没有这篇文献（没有 paper.json）")
        _load(pdir, pid, src)
        with _transaction(conn):
            _write(conn, pid, src, import_id, res, author, force)
            _paper_row(conn, import_id, pid, res, src)
        return res
    except NotImported as e:
        res.update(outcome=e.outcome, reason=e.reason)
    except Exception as e:  # one broken paper must not stop the others
        res.update(outcome="refused", reason=f"导入出错：{type(e).__name__}: {e}")
        log(traceback.format_exc().rstrip())
    res.update(counts=dict.fromkeys(COUNTS, 0), failed_ids=[], superseded_ids=[], validation={})
    with _transaction(conn):
        _paper_row(conn, import_id, pid, res, src)
    return res


# ----------------------------------------------------------------------------- the run

def _git(where: Path, *args) -> str | None:
    # GIT_OPTIONAL_LOCKS=0: `status` must not refresh (write) the index of a checkout someone is working in
    try:
        out = subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True, timeout=20,
                             env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def repo_state(work_dir: Path) -> tuple[str | None, int | None]:
    """(commit, dirty) of the repository the work dir lies in, else of the curator's own checkout: the
    pipeline code the results most likely came from. (None, None) without git."""
    for where in (work_dir, ROOT):
        top = _git(where, "rev-parse", "--show-toplevel")
        # ROOT's own checkout, not whatever repository happens to contain it: a demo or a vendored copy
        # must not inherit the commit of the project it was copied into.
        if where == ROOT and (top is None or Path(top).resolve() != Path(ROOT).resolve()):
            continue
        commit = _git(where, "rev-parse", "HEAD")
        if commit:
            status = _git(where, "status", "--porcelain")
            return commit, None if status is None else int(bool(status))
    return None, None


def _line(pid: str, res: dict) -> str:
    if res["outcome"] == "skipped":
        return f"文献 {pid}：跳过 — {res['reason']}"
    if res["outcome"] == "refused":
        return f"文献 {pid}：拒绝 — {res['reason']}"
    c = res["counts"]
    head = f"文献 {pid}：已导入 — 新增 {c['inserted']}"
    if c["superseded"]:
        people = "，".join(x for x in (f"{c['superseded_touched']} 条有人工修改或审核" if c["superseded_touched"] else "",
                                      f"{c['superseded_created']} 条是人工新建或复制的" if c["superseded_created"] else "") if x)
        head = (f"文献 {pid}：已覆盖导入 — 新增 {c['inserted']}，替换旧版本的反应 {c['superseded']}"
                + (f"（其中 {people}）" if people else ""))
    return (f"{head}，失败未导入 {c['failed_not_imported']}；block {c['blocks']}；"
            f"校验错误 {c['validation_errors']}，警告 {c['validation_warnings']}")


def import_work(conn, work_dir, *, papers=None, dry_run=False, author="import", force=False, log=print) -> dict:
    """Import the papers of a work dir (all, or the ids in `papers`); returns the report, which is also
    stored in `imports.report`. `dry_run`: everything is done and then rolled back. `force`: a paper whose
    content did not change since its last import replaces its reactions all the same."""
    work_dir = Path(work_dir).resolve()
    if not work_dir.is_dir():
        raise FileNotFoundError(f"没有 work 目录：{work_dir}")
    if not isinstance(author, str) or not author.strip():
        raise ValueError("请填写导入者（--author）")
    author = author.strip()
    dirs = paper_dirs(work_dir)
    ids = list(dirs) if papers is None else sorted({str(p) for p in papers}, key=_paper_key)
    commit, dirty = repo_state(work_dir)
    options = {"papers": None if papers is None else ids, "dry_run": bool(dry_run), "force": bool(force)}
    run = dict(work_dir=work_dir, ids=ids, dirs=dirs, author=author, force=bool(force),
               options=options, commit=commit, dirty=dirty, log=log)
    if dry_run:
        with db.write(conn, rollback=True):
            report = _run(conn, **run)
        report["import_id"] = None  # it was rolled back with everything else
        log(f"试运行：{_totals_line(report)}；没有写入任何数据")
        return report
    report = _run(conn, **run)
    if not conn.in_transaction:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    log(f"导入批次 #{report['import_id']}：{_totals_line(report)}")
    return report


def _totals_line(report: dict) -> str:
    t = report["totals"]
    same = f"（其中 {t['unchanged']} 篇没有变化）" if t["unchanged"] else ""
    return (f"{t['imported']} 篇导入，{t['skipped']} 篇跳过{same}，{t['refused']} 篇拒绝；新增 {t['inserted']}，"
            f"替换旧版本的反应 {t['superseded']}")


def _run(conn, *, work_dir, ids, dirs, author, force, options, commit, dirty, log) -> dict:
    with db.write(conn):
        import_id = conn.execute(
            "INSERT INTO imports (started_at, work_dir, repo_commit, repo_dirty, author, options)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (db.now_iso(), str(work_dir), commit, dirty, author, db.dumps(options))).lastrowid
    report = {"import_id": import_id, "dry_run": options["dry_run"], "papers": {}}
    for pid in ids:
        res = report["papers"][pid] = _import_paper(conn, pid, dirs.get(pid), import_id, author=author,
                                                    force=force, log=log)
        log(("[试运行] " if options["dry_run"] else "") + _line(pid, res))
        for w in res["warnings"]:
            log(f"    注意：{w}")
    totals = dict.fromkeys(("imported", "skipped", "refused", "unchanged"), 0) | dict.fromkeys(COUNTS, 0)
    for res in report["papers"].values():
        totals[res["outcome"]] += 1
        totals["unchanged"] += bool(res.get("unchanged"))
        for k, v in res["counts"].items():
            totals[k] += v
    report["totals"] = totals
    with db.write(conn):
        conn.execute("UPDATE imports SET finished_at = ?, report = ? WHERE import_id = ?",
                     (db.now_iso(), db.dumps(report), import_id))
    return report
