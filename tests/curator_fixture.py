"""Fixtures for the curator's tests: a paper laid out like work/<id>/ with real PDFs, and a seeded database.

build_work() takes the demo workspace of tests.demo_workspace (Step 2 results with every state a reaction
can be in) and adds what an import reads: a 1-page main PDF and a 2-page SI made with PyMuPDF (their real
sha256 in paper.json, under the reference-manager file names) and a step1/regions.json that agrees with
the views. The helpers after it change the Step 2 results the way a re-run of the pipeline would.

seed_db() fills a database directly (SQL plus store.insert_reaction), without the importer, so the store
can be tested on its own; make_db() is the importer's way: build_work() imported into a fresh file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf

from curator import db, importer, records, store
from pipeline.extract_view import block_view
from tests import demo_workspace
from tests.test_extract_records import demo_views

PAGE = (600.0, 800.0)
SI_PAGE = (595.0, 842.0)
MAIN_NAME = "Demo et al. - J. Made-up Chem. - 2026 - Every state a reaction can be in.pdf"
SI_NAME = "SI-" + MAIN_NAME
DOI = "10.5555/demo.2026.42"
LAYOUTS = {"1": "product_scope", "2": "reactant_table"}
REGION_BOX = [35, 10, 325, 675]
EXCLUDED_BOX = [340, 15, 580, 170]
CONTEXT = {"reaction_class": "A made-up coupling, to look at every state a reaction can record",
           "numbering_convention": "", "notes": ""}
# The demo's records: e001-2 failed (no record), the others were extracted.
ORIGIN_IDS = ("main:scheme2/1/e001-1", "main:scheme2/1/e001-3", "main:scheme2/1/e001-4",
              "main:scheme2/1/e001-5", "main:scheme2/1/e001-6")
FAILED_ID = "main:scheme2/1/e001-2"


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _boxes(node, out: list) -> list:
    """(bbox, label) of everything in a view that has a box."""
    if isinstance(node, dict):
        bbox = node.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox):
            out.append((bbox, str(node.get("label") or node.get("key") or node.get("eid") or "")))
        for value in node.values():
            _boxes(value, out)
    elif isinstance(node, list):
        for value in node:
            _boxes(value, out)
    return out


def main_pdf(boxes=()) -> bytes:
    """The main text: one 600 x 800 pt page with a framed label at every box, and a DOI on it."""
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE[0], height=PAGE[1])
    for bbox, label in boxes:
        page.draw_rect(pymupdf.Rect(bbox), color=(0.3, 0.4, 0.6), width=0.6)
        page.insert_text((bbox[0] + 2, bbox[1] + 9), label, fontsize=7)
    page.insert_text((40, 780), f"Every state a reaction can be in.  DOI: {DOI}", fontsize=9)
    doc.set_metadata({"title": "Every state a reaction can be in", "author": "Demo et al."})
    return doc.tobytes()


def si_pdf() -> bytes:
    doc = pymupdf.open()
    for n, text in ((1, "Supporting Information"), (2, "General Procedure E: 3fa was prepared following ...")):
        page = doc.new_page(width=SI_PAGE[0], height=SI_PAGE[1])
        page.insert_text((60, 80), text, fontsize=11)
        page.insert_text((60, 800), f"S{n}", fontsize=9)
    return doc.tobytes()


def build_work(root: Path, paper_id: str = "demo") -> Path:
    """work/<paper_id>/ ready for an import, with its PDFs under root/Data/<paper_id>/; returns root/work."""
    root = Path(root)
    work = root / "work"
    ws = demo_workspace.build(work, paper_id)

    # The fixtures' records all carry the reaction id of the first row; give each its own, as the
    # pipeline does, and give the blocks a layout.
    views = []
    for path in sorted((ws / "step2" / "blocks").glob("*/view.json")):
        view = _read(path)
        region_id, block_id = view["region"]["region_id"], view["block"]["block_id"]
        view["block"]["layout"] = LAYOUTS.get(block_id, "other")
        for e in view["entries"]:
            for rv in e["reactions"]:
                if rv["record"]:
                    rv["record"]["reaction_id"] = f"{region_id}/{block_id}/{rv['rid']}"
                    rv["record"]["source"]["reaction_id"] = rv["rid"]
        _write(path, view)
        views.append(view)
    _write(ws / "step2" / "reactions.json", {"paper_id": paper_id, "records": [
        rv["record"] for v in views for e in v["entries"] for rv in e["reactions"] if rv["record"]]})

    data = root / "Data" / paper_id
    data.mkdir(parents=True, exist_ok=True)
    main, si = data / MAIN_NAME, data / SI_NAME
    main.write_bytes(main_pdf(_boxes(views, []) + [(REGION_BOX, "Scheme 2"), (EXCLUDED_BOX, "Scheme 1")]))
    si.write_bytes(si_pdf())
    documents = {"main": {"pdf": str(main.resolve()), "sha256": db.sha_bytes(main.read_bytes())},
                 "si": {"pdf": str(si.resolve()), "sha256": db.sha_bytes(si.read_bytes())}}
    _write(ws / "si" / "manifest.json", {"pdf": str(si.resolve()), "page_count": 2, "dpi": 100, "metadata": {},
                                         "pages": [{"page": n, "size_pt": list(SI_PAGE),
                                                    "render": f"pages/p{n:03d}.png"} for n in (1, 2)]})

    paper = _read(ws / "paper.json")
    paper["source_dir"] = str(data.resolve())
    paper["documents"] = documents
    done = {"status": "done", "version": 1, "params": {}, "sources": documents,
            "started_at": "2026-01-01T00:00:00+00:00", "finished_at": "2026-01-01T00:01:00+00:00", "seconds": 60.0}
    steps = paper["steps"]

    def minutes(a, b):  # the steps ran one after the other
        return {"started_at": f"2026-01-01T00:0{a}:00+00:00", "finished_at": f"2026-01-01T00:0{b}:00+00:00"}
    steps["preprocess"] = {**done, **steps["preprocess"], "sources": documents, **minutes(0, 1)}
    steps["locate"] = {**done, "summary": {"regions": 2}, **minutes(1, 2)}
    steps["extract"] = {**done, **steps["extract"], "version": 6, "sources": documents, **minutes(2, 3),
                        "params": {"codex": {"model": "demo-model", "reasoning_effort": "medium"},
                                   "blocks": None, "kinds": None, "limit": None, "entries": True}}
    _write(ws / "paper.json", paper)

    region = views[0]["region"]
    blocks = [{**v["block"], "include": True, "page": v["block"]["page"] or 1} for v in views]
    regions = [
        {"region_id": "main:scheme1", "doc": "main", "label": "Scheme 1", "caption": "Scheme 1. Earlier work",
         "kind": "background", "presentation": "vector_graphic", "include": False,
         "exclude_reason": "Prior work, not an experiment of this paper.", "first_page": 1, "last_page": 1,
         "footnotes": None, "notes": "", "related": [], "boxes": [{"page": 1, "bbox": EXCLUDED_BOX}],
         "blocks": [{"block_id": "1", "title": None, "kind": "background", "layout": "other", "page": 1,
                     "bbox": EXCLUDED_BOX, "include": False, "scheme_id": None, "notes": ""}]},
        {**region, "kind": "substrate_scope", "presentation": "vector_graphic", "include": True,
         "exclude_reason": None, "first_page": 1, "last_page": 1, "related": [],
         "boxes": [{"page": 1, "bbox": REGION_BOX}], "blocks": blocks},
    ]
    _write(ws / "step1" / "regions.json", {"caption_check": [], "paper": CONTEXT, "regions": regions,
                                           "schemes": [], "si_sections": [], "docs_in_scope": ["main"]})
    return work


# ----------------------------------------------------------------------------- changing a built work dir

def paper_dir(work: Path, paper_id: str = "demo") -> Path:
    return Path(work) / paper_id


def load_records(work: Path, paper_id: str = "demo") -> list[dict]:
    return _read(paper_dir(work, paper_id) / "step2" / "reactions.json")["records"]


def _views(work, paper_id):
    for path in sorted((paper_dir(work, paper_id) / "step2" / "blocks").glob("*/view.json")):
        yield path, _read(path)


def modify_record(work: Path, origin_id: str, change, paper_id: str = "demo") -> dict:
    """change(record) edits the record `origin_id` in place, in reactions.json and in its view.json;
    returns the record as written."""
    path = paper_dir(work, paper_id) / "step2" / "reactions.json"
    data = _read(path)
    (rec,) = [r for r in data["records"] if r["reaction_id"] == origin_id]
    change(rec)
    _write(path, data)
    for vpath, view in _views(work, paper_id):
        for e in view["entries"]:
            for rv in e["reactions"]:
                if rv["record"] and rv["record"]["reaction_id"] == origin_id:
                    rv["record"] = rec
                    _write(vpath, view)
    return rec


def remove_record(work: Path, origin_id: str, paper_id: str = "demo") -> None:
    """The reaction disappears from the pipeline's results (reactions.json and its view)."""
    path = paper_dir(work, paper_id) / "step2" / "reactions.json"
    data = _read(path)
    data["records"] = [r for r in data["records"] if r["reaction_id"] != origin_id]
    _write(path, data)
    for vpath, view in _views(work, paper_id):
        for e in view["entries"]:
            e["reactions"] = [rv for rv in e["reactions"]
                              if not (rv["record"] and rv["record"]["reaction_id"] == origin_id)]
        _write(vpath, view)


def rename_ids(work: Path, old_prefix: str, new_prefix: str, paper_id: str = "demo") -> None:
    """Every reaction id that starts with old_prefix gets new_prefix instead (Step 1 renamed a region)."""
    path = paper_dir(work, paper_id) / "step2" / "reactions.json"
    data = _read(path)
    for r in data["records"]:
        if r["reaction_id"].startswith(old_prefix):
            r["reaction_id"] = new_prefix + r["reaction_id"][len(old_prefix):]
    _write(path, data)


def set_step(work: Path, step: str, paper_id: str = "demo", **fields) -> None:
    """Change paper.json steps.<step> (e.g. status="running")."""
    path = paper_dir(work, paper_id) / "paper.json"
    paper = _read(path)
    paper["steps"].setdefault(step, {}).update(fields)
    _write(path, paper)


def replace_pdf(work: Path, doc: str, pdf: bytes, paper_id: str = "demo", rerun: bool = True) -> None:
    """Another PDF for a document, and paper.json's `documents` as any `pipeline run` writes it. `rerun`:
    every step ran again on it (their `sources`); else the steps keep the PDF they read before."""
    path = paper_dir(work, paper_id) / "paper.json"
    paper = _read(path)
    Path(paper["documents"][doc]["pdf"]).write_bytes(pdf)
    paper["documents"][doc]["sha256"] = db.sha_bytes(pdf)
    if rerun:
        for step in paper["steps"].values():
            step["sources"] = paper["documents"]
    _write(path, paper)


def make_db(tmp) -> tuple:
    """build_work() under tmp, imported into a fresh database file tmp/db/curator.sqlite:
    (conn, db_path, work_dir). The caller closes conn."""
    work = build_work(Path(tmp))
    db_path = Path(tmp) / "db" / "curator.sqlite"
    conn = db.connect(db_path, create=True)
    importer.import_work(conn, work, log=lambda *a: None)
    return conn, db_path, work


# ----------------------------------------------------------------------------- a database without the importer

PAPER, PAPER2 = "demo", "12"
IDENTITY_PAGES = [[PAGE[0], PAGE[1], 0, [1, 0, 0, -1, 0, PAGE[1]]]]
_TINY_PDF: list[bytes] = []


def tiny_pdf() -> bytes:
    """A real one-page 600 x 800 PDF, made once."""
    if not _TINY_PDF:
        doc = pymupdf.open()
        doc.new_page(width=PAGE[0], height=PAGE[1]).insert_text((50, 50), "demo", fontsize=12)
        _TINY_PDF.append(doc.tobytes())
    return _TINY_PDF[0]


def demo_records() -> list[tuple[dict, dict]]:
    """(record, pipeline_info) of every extracted reaction of the demo's first block, normalized, each with
    its own reaction id."""
    out = []
    view = demo_views()[0]
    for e in view["entries"]:
        for rv in e["reactions"]:
            if rv["record"]:
                rec = records.normalize(rv["record"])
                rid = rv["reaction"]["rid"]
                rec["reaction_id"] = f"main:scheme2/1/{rid}"
                rec["source"]["reaction_id"] = rid
                out.append((rec, {"status": rv["status"], "flags": [], "errors": rv["errors"],
                                  "warnings": rv["warnings"], "seconds": rv["seconds"]}))
    return out


def second_record() -> dict:
    """The one reaction of the second paper: a table entry with a primed label and a note in Chinese."""
    rec, _ = demo_records()[1]
    rec["reaction_id"] = "main:table1/1/e001-1"
    rec["label"] = "3a′"
    rec["kind"] = "optimization"
    rec["notes"] = "产率由核磁测定"
    rec["source"].update(figure="Table 1", caption="Table 1. Optimization", region_id="main:table1",
                         block_id="1", entry_id="e001", reaction_id="e001-1")
    rec["steps"][0]["products"][0]["label"] = "3a′"
    return rec


def seed_db(conn) -> dict:
    """Two papers inserted directly: 'demo' (main document, one block, the demo's five reactions) and '12'
    (main document, one reaction without a block). Returns the ids:
    {paper, paper2, import_id, doc_id, doc_id2, block_pk, ids: {origin_id: id}, other: id}."""
    now = db.now_iso()
    pdf = tiny_pdf()
    sha = db.sha_bytes(pdf)
    view = block_view(demo_views()[0])
    for e in view["entries"]:
        for rv in e["reactions"]:
            rv.pop("record", None)
            rv.pop("draft", None)
    with db.write(conn):
        import_id = conn.execute(
            "INSERT INTO imports (started_at, finished_at, work_dir, repo_commit, repo_dirty, author, options, report)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (now, now, "/fixture/work", "0" * 40, 0, "import", db.dumps({"papers": None}), db.dumps({}))).lastrowid
        conn.execute("INSERT INTO blobs (sha256, size, data) VALUES (?, ?, ?)", (sha, len(pdf), pdf))
        doc_ids = {}
        for pid, title in ((PAPER, "Every state a reaction can be in"), (PAPER2, "A second paper")):
            meta = {"title": title, "authors": "Demo et al.", "journal": "J. Made-up Chem.", "year": 2026,
                    "doi": DOI if pid == PAPER else None, "note": None}
            conn.execute("INSERT INTO papers (paper_id, title, authors, journal, year, doi, note, context, rev,"
                         " created_at, updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                         (pid, *meta.values(), db.dumps(CONTEXT), now, now, "import"))
            db.insert_revision(conn, entity="paper", entity_id=pid, rev=1, action="import", author="import",
                               snapshot=meta, diff=[], import_id=import_id, created_at=now)
            doc_ids[pid] = conn.execute(
                "INSERT INTO documents (paper_id, doc, filename, sha256, page_count, pages, pdf_meta)"
                " VALUES (?, 'main', ?, ?, 1, ?, ?)",
                (pid, MAIN_NAME, sha, db.dumps(IDENTITY_PAGES), db.dumps({"title": title}))).lastrowid
            conn.execute("INSERT INTO import_papers (import_id, paper_id, outcome, reason, steps, counts)"
                         " VALUES (?, ?, 'imported', NULL, ?, ?)",
                         (import_id, pid, db.dumps({"extract": {"status": "done", "version": 6}}),
                          db.dumps({"inserted": 5 if pid == PAPER else 1})))
        region = {**view["region"], "boxes": [{"page": 1, "bbox": REGION_BOX}]}
        block_pk = conn.execute(
            "INSERT INTO blocks (paper_id, region_id, block_id, slug, doc, page, figure, layout, kind, title,"
            " region, view, import_id) VALUES (?, ?, ?, ?, 'main', 1, ?, ?, ?, ?, ?, ?, ?)",
            (PAPER, "main:scheme2", "1", view["slug"], "Scheme 2", "product_scope", "substrate_scope",
             "Scope of the coupling", db.dumps(region), db.dumps(view), import_id)).lastrowid
        ids = {}
        for rec, info in demo_records():
            if rec["reaction_id"].endswith("e001-3"):
                info["warnings"] = ["the scale is read from the SI"]
            ids[rec["reaction_id"]] = store.insert_reaction(
                conn, paper_id=PAPER, block_pk=block_pk, origin_id=rec["reaction_id"], data=rec, action="import",
                author="import", import_id=import_id, pipeline_sha=db.sha_json(rec), pipeline_info=info)
        rec = second_record()
        other = store.insert_reaction(conn, paper_id=PAPER2, block_pk=None, origin_id=rec["reaction_id"], data=rec,
                                      action="import", author="import", import_id=import_id,
                                      pipeline_sha=db.sha_json(rec),
                                      pipeline_info={"status": "ok", "flags": [], "errors": [], "warnings": [],
                                                     "seconds": 1})
    return {"paper": PAPER, "paper2": PAPER2, "import_id": import_id, "doc_id": doc_ids[PAPER],
            "doc_id2": doc_ids[PAPER2], "block_pk": block_pk, "ids": ids, "other": other}
