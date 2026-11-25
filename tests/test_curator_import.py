import json
import re
import tempfile
import unittest
from pathlib import Path

import pymupdf

from curator import db, importer, records, store
from curator.config import ROOT
from tests import curator_fixture as fx

E1, E3, E4, E5, E6 = fx.ORIGIN_IDS
TABLES = ("blobs", "papers", "documents", "imports", "import_papers", "blocks", "reactions", "revisions")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


class Work(unittest.TestCase):
    """A fresh work dir (build_work) and an empty database file; nothing imported yet."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.work = fx.build_work(self.tmp)
        self.paper_dir = self.work / "demo"
        self.conn = db.connect(self.tmp / "db" / "curator.sqlite", create=True)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def run_import(self, **kw) -> dict:
        self.lines = []
        return importer.import_work(self.conn, self.work, log=self.lines.append, **kw)

    def count(self, table: str) -> int:
        return self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def dump(self) -> dict:
        return {t: sorted(map(tuple, self.conn.execute(f"SELECT * FROM {t}")), key=repr) for t in TABLES}

    def revisions(self) -> list:
        return [tuple(r) for r in self.conn.execute("SELECT * FROM revisions ORDER BY rev_id")]

    def row(self, origin_id: str):
        return self.conn.execute("SELECT * FROM reactions WHERE origin_id = ? AND in_latest = 1",
                                 (origin_id,)).fetchone()

    def paper_json(self) -> dict:
        return _read(self.paper_dir / "paper.json")

    def main_pdf(self) -> Path:
        return Path(self.paper_json()["documents"]["main"]["pdf"])

    def refused_cleanly(self, report: dict, *needles: str) -> None:
        """The paper was refused for the given reason and nothing of it reached the database."""
        res = report["papers"]["demo"]
        self.assertEqual(res["outcome"], "refused")
        for needle in needles:
            self.assertIn(needle, res["reason"])
        self.assertEqual(res["counts"], dict.fromkeys(importer.COUNTS, 0))
        row = self.conn.execute("SELECT outcome, reason FROM import_papers WHERE import_id = ?",
                                (report["import_id"],)).fetchone()
        self.assertEqual(tuple(row), ("refused", res["reason"]))


class FirstImport(Work):
    def setUp(self):
        super().setUp()
        self.report = self.run_import()
        self.import_id = self.report["import_id"]

    def test_report(self):
        r = self.report
        self.assertEqual(set(r), {"import_id", "dry_run", "papers", "totals"})
        self.assertFalse(r["dry_run"])
        res = r["papers"]["demo"]
        self.assertEqual(set(res), {"outcome", "reason", "unchanged", "counts", "failed_ids", "superseded_ids",
                                    "warnings", "validation"})
        self.assertEqual((res["outcome"], res["reason"], res["unchanged"]), ("imported", None, False))
        self.assertEqual(res["counts"], {"inserted": 5, "superseded": 0, "superseded_touched": 0,
                                         "superseded_created": 0, "failed_not_imported": 1, "blocks": 2,
                                         "validation_errors": 0,
                                         "validation_warnings": sum(len(v["warnings"])
                                                                    for v in res["validation"].values())})
        self.assertEqual(res["failed_ids"], [fx.FAILED_ID])
        self.assertTrue(all(not v["errors"] for v in res["validation"].values()))
        self.assertEqual((r["totals"]["imported"], r["totals"]["inserted"]), (1, 5))

        i = self.conn.execute("SELECT * FROM imports").fetchone()
        self.assertEqual(i["import_id"], self.import_id)
        self.assertEqual(db.loads(i["report"]), r)
        self.assertIsNotNone(i["finished_at"])
        self.assertEqual(i["work_dir"], str(self.work.resolve()))
        self.assertEqual(i["author"], "import")
        self.assertEqual(db.loads(i["options"]), {"papers": None, "dry_run": False, "force": False})
        # The work dir is in /tmp: the commit is the curator's own checkout's (the tests run inside it).
        if (ROOT / ".git").exists():
            self.assertRegex(i["repo_commit"] or "", r"^[0-9a-f]{40}$")
            self.assertIn(i["repo_dirty"], (0, 1))
        else:
            self.assertIsNone(i["repo_commit"])

        p = self.conn.execute("SELECT * FROM import_papers").fetchone()
        self.assertEqual((p["paper_id"], p["outcome"], p["reason"]), ("demo", "imported", None))
        self.assertEqual(db.loads(p["counts"]), res["counts"])
        self.assertEqual(p["reactions_sha"], db.sha_bytes((self.paper_dir / "step2" / "reactions.json").read_bytes()))
        self.assertRegex(p["content_sha"] or "", r"^[0-9a-f]{64}$")
        steps = db.loads(p["steps"])
        self.assertEqual((steps["extract"]["status"], steps["extract"]["version"]), ("done", 6))
        self.assertEqual(steps["extract"]["params"]["codex"]["model"], "demo-model")
        self.assertNotIn("sources", steps["extract"])

        self.assertTrue(self.lines[0].startswith("文献 demo：已导入"), self.lines[0])
        self.assertIn("新增 5", self.lines[0])
        self.assertIn("失败未导入 1", self.lines[0])
        wal = self.tmp / "db" / "curator.sqlite-wal"
        self.assertTrue(not wal.exists() or wal.stat().st_size == 0)  # checkpointed

    def test_reactions(self):
        recs = {r["reaction_id"]: r for r in fx.load_records(self.work)}
        rows = {r["origin_id"]: r for r in self.conn.execute("SELECT * FROM reactions")}
        self.assertEqual(sorted(rows), sorted(fx.ORIGIN_IDS))
        self.assertNotIn(fx.FAILED_ID, rows)
        block_pk = self.conn.execute("SELECT block_pk FROM blocks WHERE region_id = 'main:scheme2' AND block_id = '1'"
                                     ).fetchone()[0]
        for oid, row in rows.items():
            data = records.normalize(recs[oid])
            self.assertEqual(db.loads(row["data"]), data)
            self.assertNotIn('"crop"', row["data"])
            self.assertEqual(row["data_sha"], db.sha_json(data))
            self.assertEqual(row["pipeline_sha"], row["data_sha"])
            self.assertEqual((row["rev"], row["touched"], row["in_latest"], row["deleted"]), (1, 0, 1, 0))
            self.assertEqual((row["first_import"], row["last_import"]), (self.import_id, self.import_id))
            self.assertEqual((row["block_pk"], row["layout"], row["figure"], row["doc"]),
                             (block_pk, "product_scope", "Scheme 2", "main"))
            self.assertTrue(row["sort_key"].startswith("demo|0|00001|main:scheme000002|"), row["sort_key"])
            rev = self.conn.execute("SELECT * FROM revisions WHERE entity = 'reaction' AND entity_id = ?",
                                    (str(row["id"]),)).fetchall()
            self.assertEqual([(r["rev"], r["action"], r["import_id"], r["author"]) for r in rev],
                             [(1, "import", self.import_id, "import")])
        self.assertEqual(db.loads(rows[E1]["pipeline_info"]),
                         {"status": "ok", "flags": ["inferred", "unresolved"], "errors": [], "warnings": [],
                          "seconds": 1})
        self.assertEqual(store.get_reaction(self.conn, rows[E1]["id"])["edited"], False)

    def test_documents(self):
        paper = self.paper_json()
        blobs = {r["sha256"]: r for r in self.conn.execute("SELECT * FROM blobs")}
        self.assertEqual(set(blobs), {d["sha256"] for d in paper["documents"].values()})
        for d in paper["documents"].values():
            data = Path(d["pdf"]).read_bytes()
            self.assertEqual((blobs[d["sha256"]]["data"], blobs[d["sha256"]]["size"]), (data, len(data)))
        docs = {r["doc"]: r for r in self.conn.execute("SELECT * FROM documents")}
        self.assertEqual((docs["main"]["filename"], docs["si"]["filename"]), (fx.MAIN_NAME, fx.SI_NAME))
        self.assertEqual((docs["main"]["page_count"], docs["si"]["page_count"]), (1, 2))
        self.assertEqual(db.loads(docs["main"]["pages"]), [[600.0, 800.0, 0, [1.0, 0.0, 0.0, -1.0, 0.0, 800.0]]])
        self.assertEqual([p[:3] for p in db.loads(docs["si"]["pages"])], [[*fx.SI_PAGE, 0]] * 2)
        self.assertEqual(db.loads(docs["main"]["pdf_meta"])["title"], "Every state a reaction can be in")

    def test_paper(self):
        p = self.conn.execute("SELECT * FROM papers").fetchone()
        meta = {"title": "Every state a reaction can be in", "authors": "Demo et al.", "journal": "J. Made-up Chem.",
                "year": 2026, "doi": fx.DOI, "note": None}
        self.assertEqual({k: p[k] for k in meta}, meta)
        self.assertEqual((p["paper_id"], p["meta_origin"], p["rev"], p["updated_by"]), ("demo", "auto", 1, "import"))
        self.assertEqual(db.loads(p["context"]), fx.CONTEXT)
        (rev,) = self.conn.execute("SELECT * FROM revisions WHERE entity = 'paper'").fetchall()
        self.assertEqual((rev["entity_id"], rev["rev"], rev["action"], rev["import_id"]),
                         ("demo", 1, "import", self.import_id))
        self.assertEqual(db.loads(rev["snapshot"]), meta)

    def test_blocks(self):
        blocks = {r["block_id"]: r for r in self.conn.execute("SELECT * FROM blocks")}
        self.assertEqual(set(blocks), {"1", "2"})  # main:scheme1 is excluded
        b = blocks["1"]
        self.assertEqual({k: b[k] for k in ("paper_id", "region_id", "slug", "doc", "page", "figure", "layout",
                                            "kind", "title", "import_id", "in_latest")},
                         {"paper_id": "demo", "region_id": "main:scheme2", "slug": "main-scheme2__1", "doc": "main",
                          "page": 1, "figure": "Scheme 2", "layout": "product_scope", "kind": "substrate_scope",
                          "title": "Scope of the coupling", "import_id": self.import_id, "in_latest": 1})
        self.assertEqual(blocks["2"]["layout"], "reactant_table")
        region = db.loads(b["region"])
        self.assertEqual(region["boxes"], [{"page": 1, "bbox": fx.REGION_BOX}])
        self.assertEqual(region["label"], "Scheme 2")
        view = db.loads(b["view"])
        original = _read(self.paper_dir / "step2" / "blocks" / "main-scheme2__1" / "view.json")
        self.assertEqual(view["ref"], "main:scheme2/1")
        self.assertEqual(len(view["entries"]), len(original["entries"]))
        reactions = [rv for e in view["entries"] for rv in e["reactions"]]
        self.assertEqual([rv["rid"] for rv in reactions], [rv["rid"] for e in original["entries"]
                                                           for rv in e["reactions"]])
        for rv in reactions:
            self.assertFalse({"record", "draft"} & set(rv))
            self.assertIn("status", rv)
        # Crop paths point into work/ and are not kept (pictures are rendered from the boxes).
        self.assertIn('"crop"', json.dumps(original))
        self.assertNotIn('"crop"', b["view"])
        self.assertEqual(view["template"], records.normalize(original["template"]))
        self.assertEqual(view["entries"][0]["bbox"], original["entries"][0]["bbox"])

    def test_second_import_changes_nothing(self):
        before = self.dump()
        report = self.run_import()
        res = report["papers"]["demo"]
        self.assertEqual((res["outcome"], res["unchanged"]), ("skipped", True))
        after = self.dump()
        self.assertEqual({t: after[t] for t in TABLES if not t.startswith("import")},
                         {t: before[t] for t in TABLES if not t.startswith("import")})
        self.assertEqual(self.count("import_papers"), 2)


class Refusals(Work):
    def test_pdf_not_what_the_pipeline_read(self):
        pdf = self.main_pdf()
        pdf.write_bytes(pdf.read_bytes() + b"\n% changed\n")
        report = self.run_import()
        self.refused_cleanly(report, "sha256", "main")
        for t in ("blobs", "papers", "documents", "blocks", "reactions", "revisions"):
            self.assertEqual(self.count(t), 0, t)
        self.assertTrue(self.lines[0].startswith("文献 demo：拒绝"))

    def test_pdf_missing(self):
        Path(self.paper_json()["documents"]["si"]["pdf"]).unlink()
        self.refused_cleanly(self.run_import(), "找不到", "si")
        self.assertEqual(self.count("reactions"), 0)

    def test_extract_not_done_is_skipped(self):
        fx.set_step(self.work, "extract", status="running")
        report = self.run_import()
        res = report["papers"]["demo"]
        self.assertEqual(res["outcome"], "skipped")
        self.assertIn("running", res["reason"])
        p = self.conn.execute("SELECT * FROM import_papers").fetchone()
        self.assertEqual((p["outcome"], p["reason"]), ("skipped", res["reason"]))
        self.assertEqual(db.loads(p["steps"])["extract"]["status"], "running")
        self.assertEqual((self.count("papers"), self.count("reactions")), (0, 0))
        self.assertTrue(self.lines[0].startswith("文献 demo：跳过"))

    def test_step_run_again_after_extract(self):
        # `pipeline run --steps preprocess locate` after extract: Step 1 may have renamed the blocks.
        fx.set_step(self.work, "locate", finished_at="2026-01-02T00:00:00+00:00")
        self.refused_cleanly(self.run_import(), "extract 的结果已过期", "locate")
        fx.set_step(self.work, "locate", finished_at="2026-01-01T00:02:00+00:00", status="failed")
        self.refused_cleanly(self.run_import(), "extract 的结果已过期", "failed")
        fx.set_step(self.work, "locate", status="done")
        fx.set_step(self.work, "preprocess", status="running", finished_at=None)
        self.refused_cleanly(self.run_import(), "preprocess")
        self.assertEqual((self.count("papers"), self.count("reactions")), (0, 0))
        fx.set_step(self.work, "preprocess", status="done", finished_at="2026-01-01T00:01:00+00:00")
        self.assertEqual(self.run_import()["papers"]["demo"]["outcome"], "imported")

    def test_extract_without_sources_warns(self):
        paper = self.paper_json()
        del paper["steps"]["extract"]["sources"]
        _write(self.paper_dir / "paper.json", paper)
        res = self.run_import()["papers"]["demo"]
        self.assertEqual(res["outcome"], "imported")
        self.assertTrue(any("没有记下 extract 读的 PDF" in w for w in res["warnings"]))

    def test_paper_filter(self):
        report = self.run_import(papers=["nope"])
        self.assertEqual(list(report["papers"]), ["nope"])
        self.assertEqual(report["papers"]["nope"]["outcome"], "skipped")
        self.assertEqual(self.count("papers"), 0)
        report = self.run_import(papers=["demo"])
        self.assertEqual(report["papers"]["demo"]["outcome"], "imported")
        self.assertEqual(db.loads(self.conn.execute("SELECT options FROM imports WHERE import_id = ?",
                                                    (report["import_id"],)).fetchone()[0])["papers"], ["demo"])

    def test_broken_file_refuses_only_that_paper(self):
        path = self.paper_dir / "step2" / "blocks" / "main-scheme2__1" / "view.json"
        view = _read(path)
        view["entries"] = ["not an entry"]
        _write(path, view)
        report = self.run_import()
        self.refused_cleanly(report, "导入出错")
        self.assertEqual((self.count("papers"), self.count("reactions")), (0, 0))

    def test_record_with_nan_is_left_out(self):
        # Python's json writes NaN; it is no JSON, and one such record must not refuse the paper.
        fx.modify_record(self.work, E6, lambda r: r["steps"][0]["products"][0].update(bbox=[float("nan"), 1, 2, 3]))
        res = self.run_import()["papers"]["demo"]
        self.assertEqual((res["outcome"], res["counts"]["inserted"]), ("imported", 4))
        self.assertTrue(any(E6 in w and "NaN" in w for w in res["warnings"]))
        self.assertIsNone(self.row(E6))

    def test_nan_in_a_view_becomes_null(self):
        path = self.paper_dir / "step2" / "blocks" / "main-scheme2__1" / "view.json"
        view = _read(path)
        view["entries"][0]["bbox"] = [float("inf"), 1, 2, 3]
        _write(path, view)
        self.assertEqual(self.run_import()["papers"]["demo"]["outcome"], "imported")
        stored = db.loads(self.conn.execute("SELECT view FROM blocks WHERE block_id = '1'").fetchone()[0])
        self.assertEqual(stored["entries"][0]["bbox"], [None, 1, 2, 3])

    def test_warnings(self):
        # A rotated SI page, a page whose size differs from Step 0's manifest, a narrowed extract run and a
        # reaction id twice in reactions.json: all imported, each reported.
        doc = pymupdf.open(stream=fx.si_pdf(), filetype="pdf")
        doc[1].set_rotation(90)
        fx.replace_pdf(self.work, "si", doc.tobytes())
        manifest = _read(self.paper_dir / "si" / "manifest.json")
        manifest["pages"][0]["size_pt"] = [612.0, 792.0]
        _write(self.paper_dir / "si" / "manifest.json", manifest)
        fx.set_step(self.work, "extract", params={**self.paper_json()["steps"]["extract"]["params"],
                                                  "blocks": ["main:scheme2/1"]})
        path = self.paper_dir / "step2" / "reactions.json"
        doc = _read(path)
        doc["records"].append({**doc["records"][0], "notes": "a second copy"})
        _write(path, doc)
        res = self.run_import()["papers"]["demo"]
        self.assertEqual((res["outcome"], res["counts"]["inserted"]), ("imported", 5))
        for needle in ("文档 si 第 2 页是旋转的", "文档 si 第 1、2 页的尺寸和流水线 manifest 记的相差",
                       "extract 是部分运行（blocks=", f"{E1} 出现了不止一次"):
            self.assertTrue(any(needle in w for w in res["warnings"]), needle)
        self.assertNotEqual(db.loads(self.row(E1)["data"])["notes"], "a second copy")  # the first one counts

    def test_dry_run_writes_nothing(self):
        report = self.run_import(dry_run=True)
        self.assertTrue(report["dry_run"])
        self.assertIsNone(report["import_id"])
        self.assertEqual(report["papers"]["demo"]["counts"]["inserted"], 5)
        for t in TABLES:
            self.assertEqual(self.count(t), 0, t)
        self.assertTrue(self.lines[0].startswith("[试运行] 文献 demo：已导入"))
        self.assertIn("没有写入", self.lines[-1])
        self.assertEqual(self.run_import()["import_id"], 1)  # the dry run left no trace, not even an id


class Reimport(Work):
    """make_db's state: the fixture imported once. Importing the paper again replaces its reactions."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.conn, self.db_path, self.work = fx.make_db(self.tmp)
        self.paper_dir = self.work / "demo"
        self.log = self.revisions()
        self.first = {r["origin_id"]: r["id"] for r in self.conn.execute("SELECT id, origin_id FROM reactions")}

    def written(self) -> list[dict]:
        """The revisions appended since the last call (the earlier ones unchanged)."""
        now = self.revisions()
        self.assertEqual(now[:len(self.log)], self.log)
        new, self.log = now[len(self.log):], now
        cols = [d[0] for d in self.conn.execute("SELECT * FROM revisions LIMIT 0").description]
        return [dict(zip(cols, r)) for r in new]

    def counts(self, report) -> dict:
        self.assertEqual(report["papers"]["demo"]["outcome"], "imported", report["papers"]["demo"]["reason"])
        return report["papers"]["demo"]["counts"]

    def current(self) -> dict:
        """{origin_id: row} of the paper's current reactions."""
        return {r["origin_id"]: r for r in self.conn.execute("SELECT * FROM reactions WHERE in_latest = 1")}

    def rerun(self, origin_id: str, notes: str) -> dict:
        """The pipeline now says something else about one reaction; its normalized data."""
        return records.normalize(fx.modify_record(self.work, origin_id, lambda r: r.update(notes=notes)))

    def replaced(self, report, n_old: int, n_new: int) -> None:
        """The paper's reactions were replaced: the old rows are old versions of this import, untouched
        otherwise (their revisions too); the new rows are rev 1 imports."""
        c = self.counts(report)
        self.assertEqual((c["superseded"], c["inserted"]), (n_old, n_new))
        old = self.conn.execute("SELECT * FROM reactions WHERE superseded_by = ?", (report["import_id"],)).fetchall()
        self.assertEqual(len(old), n_old)
        self.assertTrue(all(r["in_latest"] == 0 for r in old))
        self.assertEqual(sorted(report["papers"]["demo"]["superseded_ids"]), sorted(r["id"] for r in old))
        new = self.current()
        self.assertEqual(len(new), n_new)
        self.assertTrue(all((r["rev"], r["first_import"], r["superseded_by"]) == (1, report["import_id"], None)
                            for r in new.values()))
        revs = self.written()
        self.assertEqual(sorted(r["entity_id"] for r in revs if r["entity"] == "reaction"),
                         sorted(str(r["id"]) for r in new.values()))
        self.assertTrue(all(r["action"] == "import" for r in revs if r["entity"] == "reaction"))

    def test_unchanged_paper_is_skipped(self):
        rows = [tuple(r) for r in self.conn.execute("SELECT * FROM reactions ORDER BY id")]
        report = self.run_import()
        res = report["papers"]["demo"]
        self.assertEqual((res["outcome"], res["unchanged"]), ("skipped", True))
        self.assertIn("没有变化", res["reason"])
        self.assertIn("--force", res["reason"])
        self.assertEqual(report["totals"]["unchanged"], 1)
        self.assertEqual([tuple(r) for r in self.conn.execute("SELECT * FROM reactions ORDER BY id")], rows)
        self.assertEqual(self.written(), [])
        self.assertTrue(self.lines[0].startswith("文献 demo：跳过"), self.lines[0])
        self.assertIn("没有变化", self.lines[-1])

    def test_force_replaces_an_unchanged_paper(self):
        report = self.run_import(force=True)
        self.replaced(report, 5, 5)
        self.assertEqual(set(self.current()), set(self.first))
        self.assertEqual(db.loads(self.conn.execute("SELECT options FROM imports WHERE import_id = ?",
                                                    (report["import_id"],)).fetchone()[0])["force"], True)

    def test_changed_paper_replaces_its_reactions(self):
        data = self.rerun(E1, "rerun")
        report = self.run_import()
        self.replaced(report, 5, 5)
        cur = self.current()
        self.assertEqual(db.loads(cur[E1]["data"]), data)
        old = self.conn.execute("SELECT * FROM reactions WHERE id = ?", (self.first[E1],)).fetchone()
        self.assertNotEqual(db.loads(old["data"])["notes"], "rerun")  # the old version keeps what it was
        self.assertEqual((old["superseded_by"], old["rev"]), (report["import_id"], 1))
        self.assertTrue(self.lines[0].startswith("文献 demo：已覆盖导入"), self.lines[0])
        self.assertIn("替换旧版本的反应 5", self.lines[0])
        self.assertNotIn("人工", self.lines[0])

    def test_peoples_work_is_replaced_and_reported(self):
        e1, e3, e4 = self.first[E1], self.first[E3], self.first[E4]
        cur = store.get_reaction(self.conn, e1)
        store.update(self.conn, e1, base_rev=1, data={**cur["data"], "notes": "mine"}, author="ann")
        store.review(self.conn, e3, base_rev=1, status="reviewed", note=None, author="ann")
        copy = store.copy(self.conn, e4, author="ann")["id"]
        made = store.create(self.conn, paper_id="demo", author="ann")["id"]
        history = {rid: store.history(self.conn, rid) for rid in (e1, e3, copy, made)}
        self.written()
        self.rerun(E5, "rerun")
        report = self.run_import()
        self.replaced(report, 7, 5)
        c = self.counts(report)
        self.assertEqual((c["superseded_touched"], c["superseded_created"]), (4, 2))
        self.assertIn("4 条有人工修改或审核", self.lines[0])
        self.assertIn("2 条是人工新建或复制的", self.lines[0])
        for rid, revs in history.items():  # the old versions keep their history, read-only
            self.assertEqual(store.history(self.conn, rid), revs)
        self.assertEqual(db.loads(self.current()[E1]["data"])["notes"],
                         records.normalize(next(r for r in fx.load_records(self.work)
                                                if r["reaction_id"] == E1))["notes"])
        self.assertEqual(self.current()[E3]["review_status"], "unreviewed")

    def test_old_versions_are_hidden_and_read_only(self):
        self.rerun(E1, "rerun")
        report = self.run_import()
        old = sorted(self.first.values())
        listed = lambda **p: [r["id"] for r in store.list_reactions(self.conn, p)["rows"]]
        self.assertEqual(sorted(listed()), sorted(r["id"] for r in self.current().values()))
        self.assertEqual(sorted(listed(latest="0")), old)
        self.assertEqual(len(listed(latest="all")), 10)
        self.assertEqual(store.facets(self.conn, {})["not_latest"], 5)
        self.assertEqual(store.facets(self.conn, {})["total"], 5)
        self.assertEqual(store.get_paper(self.conn, "demo")["counts"]["reactions"], 5)
        e1 = self.first[E1]
        got = store.get_reaction(self.conn, e1)
        self.assertEqual((got["superseded_by"], got["superseded"]["import_id"]), (report["import_id"], report["import_id"]))
        for change in (lambda: store.update(self.conn, e1, base_rev=1, data=got["data"], author="ann"),
                       lambda: store.review(self.conn, e1, base_rev=1, status="reviewed", note=None, author="ann"),
                       lambda: store.delete(self.conn, e1, base_rev=1, author="ann"),
                       lambda: store.revert(self.conn, e1, base_rev=1, to_rev=1, author="ann")):
            with self.assertRaises(store.BadRequest) as ctx:
                change()
            self.assertIn("旧版本", str(ctx.exception))
        rescued = store.copy(self.conn, e1, author="ann")  # how a person brings an old fix into the current set
        self.assertEqual((rescued["in_latest"], rescued["superseded_by"], rescued["origin_id"]), (True, None, None))
        self.assertIn(rescued["id"], listed())

    def test_record_gone_from_the_new_results(self):
        fx.remove_record(self.work, E3)
        report = self.run_import()
        self.replaced(report, 5, 4)
        self.assertNotIn(E3, self.current())

    def test_changed_document_replaces_the_stored_one(self):
        pdf = fx.main_pdf()  # another PDF, and the pipeline ran on it
        fx.replace_pdf(self.work, "main", pdf)
        report = self.run_import()
        self.replaced(report, 5, 5)
        self.assertTrue(any("换过" in w for w in report["papers"]["demo"]["warnings"]))
        doc = self.conn.execute("SELECT * FROM documents WHERE doc = 'main'").fetchone()
        self.assertEqual(doc["sha256"], db.sha_bytes(pdf))
        self.assertEqual(self.count("blobs"), 3)  # the old PDF stays: the old versions were drawn on it

    def test_results_of_another_pdf_are_refused(self):
        # A `pipeline run` rewrites paper.json documents; extract keeps the hashes of what it read.
        before = self.dump()
        fx.replace_pdf(self.work, "main", fx.main_pdf(), rerun=False)
        self.refused_cleanly(self.run_import(), "extract 的结果已过期", "文档 main")
        after = self.dump()
        self.assertEqual({t: after[t] for t in TABLES if not t.startswith("import")},
                         {t: before[t] for t in TABLES if not t.startswith("import")})

    def test_dry_run_changes_nothing(self):
        self.rerun(E1, "rerun")
        fx.remove_record(self.work, E3)
        before = self.dump()
        report = self.run_import(dry_run=True)
        c = report["papers"]["demo"]["counts"]
        self.assertEqual((c["superseded"], c["inserted"]), (5, 4))
        self.assertEqual(self.dump(), before)

    def rename_main(self, journal: str) -> None:
        """The main PDF under another reference-manager name (same bytes, same sha)."""
        pdf = self.main_pdf()
        new = pdf.with_name(fx.MAIN_NAME.replace("J. Made-up Chem.", journal))
        pdf.rename(new)
        paper = self.paper_json()
        paper["documents"]["main"]["pdf"] = str(new)
        _write(self.paper_dir / "paper.json", paper)

    def test_automatic_metadata_follows_the_files(self):
        self.rename_main("Other J.")
        report = self.run_import()
        p = self.conn.execute("SELECT * FROM papers").fetchone()
        self.assertEqual((p["journal"], p["rev"], p["meta_origin"]), ("Other J.", 2, "auto"))
        (rev,) = [r for r in self.written() if r["entity"] == "paper"]
        self.assertEqual((rev["action"], rev["import_id"]), ("reimport", report["import_id"]))
        self.assertEqual([(d["path"], d["old"], d["new"]) for d in db.loads(rev["diff"])],
                         [(["journal"], "J. Made-up Chem.", "Other J.")])
        self.assertEqual(self.conn.execute("SELECT filename FROM documents WHERE doc = 'main'").fetchone()[0],
                         fx.MAIN_NAME.replace("J. Made-up Chem.", "Other J."))

    def test_edited_metadata_is_kept(self):
        store.update_paper(self.conn, "demo", base_rev=1, fields={"title": "Mine"}, author="curator")
        self.written()
        self.rename_main("Other J.")
        regions = _read(self.paper_dir / "step1" / "regions.json")
        regions["paper"] = {**regions["paper"], "notes": "rerun of Step 1"}
        _write(self.paper_dir / "step1" / "regions.json", regions)
        self.counts(self.run_import())
        p = self.conn.execute("SELECT * FROM papers").fetchone()
        self.assertEqual((p["title"], p["journal"], p["rev"], p["meta_origin"]),
                         ("Mine", "J. Made-up Chem.", 2, "edited"))
        self.assertEqual(db.loads(p["context"])["notes"], "rerun of Step 1")  # the pipeline's, always replaced
        self.assertEqual([r for r in self.written() if r["entity"] == "paper"], [])

    def test_block_left_out_keeps_its_pk(self):
        pks = {r["block_id"]: r["block_pk"] for r in self.conn.execute("SELECT * FROM blocks")}
        regions = _read(self.paper_dir / "step1" / "regions.json")
        (block,) = [b for reg in regions["regions"] for b in reg["blocks"] if reg["include"] and b["block_id"] == "2"]
        block["include"] = False
        _write(self.paper_dir / "step1" / "regions.json", regions)
        report = self.run_import()
        self.assertEqual(self.counts(report)["blocks"], 1)
        self.assertTrue(any("main:scheme2/2" in w for w in report["papers"]["demo"]["warnings"]))
        rows = {r["block_id"]: r for r in self.conn.execute("SELECT * FROM blocks")}
        self.assertEqual({k: r["block_pk"] for k, r in rows.items()}, pks)
        self.assertEqual((rows["1"]["in_latest"], rows["2"]["in_latest"]), (1, 0))
        self.assertEqual(rows["1"]["import_id"], report["import_id"])

    def test_validation_is_reported_not_blocking(self):
        def misplace(rec):
            (p,) = [p for st in rec["steps"] for p in st["products"] if isinstance(p.get("page"), int)][:1]
            p["bbox"] = [0, 0, 900, 900]
        fx.modify_record(self.work, E4, misplace)
        report = self.run_import()
        c = self.counts(report)
        self.assertEqual(c["inserted"], 5)
        self.assertGreaterEqual(c["validation_errors"], 1)
        self.assertTrue(any("框超出页面范围" in e for e in report["papers"]["demo"]["validation"][E4]["errors"]))
        self.assertEqual(db.loads(self.current()[E4]["data"]), records.normalize(
            next(r for r in fx.load_records(self.work) if r["reaction_id"] == E4)))

    def test_pipeline_info_of_the_new_results(self):
        path = self.paper_dir / "step2" / "blocks" / "main-scheme2__1" / "view.json"
        view = _read(path)
        (rv,) = [rv for e in view["entries"] for rv in e["reactions"] if rv["rid"] == "e001-5"]
        rv["warnings"] = ["the scale is read from the SI"]
        _write(path, view)
        self.replaced(self.run_import(), 5, 5)  # a view that changed is a change of the paper
        row = self.current()[E5]
        self.assertEqual(db.loads(row["pipeline_info"])["warnings"], ["the scale is read from the SI"])
        self.assertIn("warned", row["flags"].split())

    def test_check_after_overwrites(self):
        from curator.__main__ import check
        for notes in ("a", "b", "c"):
            self.rerun(E1, notes)
            self.counts(self.run_import())
        self.assertEqual(len(self.current()), 5)
        self.assertEqual(self.count("reactions"), 20)
        self.assertEqual(check(self.conn)[0], [])


class Metadata(unittest.TestCase):
    def test_filename(self):
        self.assertEqual(importer.filename_meta(fx.MAIN_NAME),
                         {"authors": "Demo et al.", "journal": "J. Made-up Chem.", "year": 2026,
                          "title": "Every state a reaction can be in"})
        self.assertEqual(importer.filename_meta("A - B - 2024 - Title - with a dash.pdf")["title"],
                         "Title - with a dash")
        self.assertEqual(importer.filename_meta("paper.pdf"), {})
        self.assertEqual(importer.filename_meta("A - B - year - C.pdf"), {})

    def test_doi(self):
        self.assertEqual(importer.find_doi("Read online: https://doi.org/10.1021/jacs.3c13374.\nNext"),
                         "10.1021/jacs.3c13374")
        self.assertEqual(importer.find_doi("(doi: 10.1016/0040-4039(95)00001-X)"), "10.1016/0040-4039(95)00001-X")
        self.assertEqual(importer.find_doi("DOI 10.5555/demo.2026.42, 2026"), "10.5555/demo.2026.42")
        self.assertIsNone(importer.find_doi("no identifier here 10.12/x"))

    def test_title_and_authors(self):
        name = "Zhang et al. - J. Am. Chem. Soc. - 2024 - Iron-Catalyzed C(sp3)-C(sp3) Coupling to Construct.pdf"
        full = "Iron-Catalyzed C(sp3)–C(sp3) Coupling to Construct Quaternary Carbon Centers"
        meta = importer.auto_meta(name, {"title": full, "author": "Qiao Zhang &amp; Shou-Fei Zhu"}, "")
        self.assertEqual(meta, {"title": full, "authors": "Qiao Zhang & Shou-Fei Zhu", "journal": "J. Am. Chem. Soc.",
                                "year": 2024, "doi": None})
        meta = importer.auto_meta(name, {"title": "Microsoft Word - draft.docx", "author": ""}, "")
        self.assertEqual((meta["title"], meta["authors"]),
                         ("Iron-Catalyzed C(sp3)-C(sp3) Coupling to Construct", "Zhang et al."))
        meta = importer.auto_meta("scan.pdf", {}, "")
        self.assertEqual((meta["title"], meta["journal"], meta["year"]), ("scan", None, None))


if __name__ == "__main__":
    unittest.main()
