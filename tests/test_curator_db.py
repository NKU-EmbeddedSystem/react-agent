import ast
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pymupdf

from curator import db, records
from curator.config import ROOT
from tests import curator_fixture as fx
from tests.curator_fixture import seed_db


class Schema(unittest.TestCase):
    def test_create_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "c.sqlite"
            with self.assertRaises(FileNotFoundError):
                db.connect(path)
            conn = db.connect(path, create=True)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertLessEqual({"blobs", "papers", "documents", "imports", "import_papers", "blocks", "reactions",
                                  "revisions"}, tables)
            conn.close()
            conn = db.connect(path)  # the schema is there: nothing to do
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            conn.close()

    def test_newer_schema_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.sqlite"
            conn = db.connect(path, create=True)
            conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
            conn.close()
            with self.assertRaises(db.SchemaError):
                db.connect(path)

    def test_json_helpers(self):
        self.assertEqual(db.dumps({"b": "α", "a": 1}), '{"b":"α","a":1}')
        self.assertEqual(db.canonical_json({"b": "α", "a": 1}), '{"a":1,"b":"α"}')
        self.assertEqual(db.sha_json({"b": 1, "a": [1, 2]}), db.sha_json({"a": [1, 2], "b": 1}))
        self.assertNotEqual(db.sha_json({"a": [1, 2]}), db.sha_json({"a": [2, 1]}))
        self.assertIsNone(db.loads(None))

    def test_numbers_are_hashed_by_value(self):
        # What a browser sends back (JSON.parse, then JSON.stringify) hashes like what was stored.
        stored = {"bbox": [323.9, 126.0, 532.8, 137.0], "n": -0.0, "big": 1e21, "flag": True}
        browser = {"bbox": [323.9, 126, 532.8, 137], "n": 0, "big": 1e21, "flag": True}
        self.assertEqual(db.sha_json(stored), db.sha_json(browser))
        self.assertEqual(db.canonical_json(stored), '{"bbox":[323.9,126,532.8,137],"big":1e+21,"flag":true,"n":0}')
        self.assertNotEqual(db.sha_json({"a": 126.5}), db.sha_json({"a": 126}))
        self.assertNotEqual(db.sha_json({"a": True}), db.sha_json({"a": 1}))
        self.assertEqual(db.dumps({"a": 126.0}), '{"a":126.0}')  # stored as written
        for bad in (float("nan"), float("inf")):  # no JSON: refused where it would enter
            with self.assertRaises(ValueError):
                db.dumps({"a": bad})
            with self.assertRaises(ValueError):
                db.sha_json({"a": bad})

    def test_saves_are_synced(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "c.sqlite", create=True)
            self.assertEqual(conn.execute("PRAGMA synchronous").fetchone()[0], 2)  # FULL
            conn.close()


class Triggers(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.ids = seed_db(self.conn)
        self.rid = self.ids["ids"]["main:scheme2/1/e001-3"]

    def tearDown(self):
        self.conn.close()

    def test_revisions_are_append_only(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE revisions SET author = 'x' WHERE rev_id = 1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM revisions WHERE rev_id = 1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM revisions")
        self.assertEqual(self.conn.execute("SELECT author FROM revisions WHERE rev_id = 1").fetchone()[0], "import")

    def test_reaction_state_needs_a_revision(self):
        for sql in ("UPDATE reactions SET data = '{}' WHERE id = ?",
                    "UPDATE reactions SET review_status = 'reviewed' WHERE id = ?",
                    "UPDATE reactions SET review_note = 'x' WHERE id = ?",
                    "UPDATE reactions SET deleted = 1 WHERE id = ?",
                    "UPDATE reactions SET rev = 2 WHERE id = ?"):
            with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                self.conn.execute(sql, (self.rid,))
        # List columns and the pipeline's bookkeeping are not state.
        self.conn.execute("UPDATE reactions SET label = 'x', pending_sha = 'abc', in_latest = 0 WHERE id = ?",
                          (self.rid,))
        self.conn.execute("UPDATE reactions SET deleted = deleted, data = data WHERE id = ?", (self.rid,))
        with db.write(self.conn):
            db.insert_revision(self.conn, entity="reaction", entity_id=self.rid, rev=2, action="review",
                               author="t", snapshot={}, diff=[])
            self.conn.execute("UPDATE reactions SET rev = 2, review_status = 'reviewed' WHERE id = ?", (self.rid,))
        self.assertEqual(self.conn.execute("SELECT review_status FROM reactions WHERE id = ?",
                                           (self.rid,)).fetchone()[0], "reviewed")
        # A revision of another entity or rev does not count.
        db.insert_revision(self.conn, entity="paper", entity_id=str(self.rid), rev=3, action="meta", author="t",
                           snapshot={}, diff=[])
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE reactions SET rev = 3 WHERE id = ?", (self.rid,))

    def test_paper_needs_a_revision(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE papers SET title = 'x' WHERE paper_id = 'demo'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE papers SET rev = 2 WHERE paper_id = 'demo'")
        self.conn.execute("UPDATE papers SET context = '{}', meta_origin = 'edited' WHERE paper_id = 'demo'")
        db.insert_revision(self.conn, entity="paper", entity_id="demo", rev=2, action="meta", author="t",
                           snapshot={}, diff=[])
        self.conn.execute("UPDATE papers SET title = 'x', rev = 2 WHERE paper_id = 'demo'")

    def test_checks(self):
        with self.assertRaises(sqlite3.IntegrityError):
            db.insert_revision(self.conn, entity="reaction", entity_id=self.rid, rev=9, action="fix", author="t",
                               snapshot={}, diff=[])
        with self.assertRaises(sqlite3.IntegrityError):  # one revision per rev
            db.insert_revision(self.conn, entity="reaction", entity_id=self.rid, rev=1, action="edit", author="t",
                               snapshot={}, diff=[])

    def test_replace_does_not_rewrite_history(self):
        # REPLACE deletes the row it replaces without firing the delete trigger.
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT OR REPLACE INTO revisions (entity, entity_id, rev, action, author, created_at,"
                              " snapshot, diff) VALUES ('reaction', ?, 1, 'import', 'mallory', 'x', '{}', '[]')",
                              (str(self.rid),))
        self.assertEqual(self.conn.execute("SELECT author FROM revisions WHERE entity = 'reaction' AND entity_id = ?"
                                           " AND rev = 1", (str(self.rid),)).fetchone()[0], "import")

    def test_rev_only_moves_on_by_one(self):
        with db.write(self.conn):
            for rev in (2, 3):
                db.insert_revision(self.conn, entity="reaction", entity_id=self.rid, rev=rev, action="review",
                                   author="t", snapshot={}, diff=[])
            self.conn.execute("UPDATE reactions SET rev = 2 WHERE id = ?", (self.rid,))
            self.conn.execute("UPDATE reactions SET rev = 3 WHERE id = ?", (self.rid,))
        for rev in (1, 2, 5):  # back to an older rev that has its revision row, or past the next one
            with self.assertRaises(sqlite3.IntegrityError, msg=rev):
                self.conn.execute("UPDATE reactions SET data = '{\"x\": 1}', rev = ? WHERE id = ?", (rev, self.rid))

    def test_what_protects_peoples_work_stays(self):
        self.conn.execute("UPDATE reactions SET touched = 1 WHERE id = ?", (self.rid,))
        for sql in ("UPDATE reactions SET touched = 0 WHERE id = ?", "UPDATE reactions SET touched = NULL WHERE id = ?",
                    "DELETE FROM reactions WHERE id = ?"):
            with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                self.conn.execute(sql, (self.rid,))
        self.conn.execute("UPDATE papers SET meta_origin = 'edited' WHERE paper_id = 'demo'")
        for sql in ("UPDATE papers SET meta_origin = 'auto' WHERE paper_id = 'demo'",
                    "DELETE FROM papers WHERE paper_id = 'demo'"):
            with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                self.conn.execute(sql)
        self.assertEqual(self.conn.execute("SELECT touched FROM reactions WHERE id = ?", (self.rid,)).fetchone()[0], 1)


# The triggers of schema 1, as databases made before schema 2 have them.
V1_GUARDS = """
CREATE TRIGGER revisions_no_update BEFORE UPDATE ON revisions
BEGIN SELECT RAISE(ABORT, 'revisions are append-only'); END;
CREATE TRIGGER revisions_no_delete BEFORE DELETE ON revisions
BEGIN SELECT RAISE(ABORT, 'revisions are append-only'); END;
CREATE TRIGGER reactions_need_revision
BEFORE UPDATE OF data, review_status, review_note, deleted, rev ON reactions
WHEN (NEW.rev IS OLD.rev AND (NEW.data IS NOT OLD.data OR NEW.review_status IS NOT OLD.review_status
                              OR NEW.review_note IS NOT OLD.review_note OR NEW.deleted IS NOT OLD.deleted))
  OR (SELECT count(*) FROM revisions
      WHERE entity = 'reaction' AND entity_id = CAST(NEW.id AS TEXT) AND rev = NEW.rev) = 0
BEGIN SELECT RAISE(ABORT, 'reaction changed without a revision'); END;
CREATE TRIGGER papers_need_revision
BEFORE UPDATE OF title, authors, journal, year, doi, note, rev ON papers
WHEN (NEW.rev IS OLD.rev AND (NEW.title IS NOT OLD.title OR NEW.authors IS NOT OLD.authors
                              OR NEW.journal IS NOT OLD.journal OR NEW.year IS NOT OLD.year
                              OR NEW.doi IS NOT OLD.doi OR NEW.note IS NOT OLD.note))
  OR (SELECT count(*) FROM revisions
      WHERE entity = 'paper' AND entity_id = NEW.paper_id AND rev = NEW.rev) = 0
BEGIN SELECT RAISE(ABORT, 'paper changed without a revision'); END;
"""


def floats(data):
    """data with every box as the pipeline writes it: whole numbers as floats (126.0)."""
    if isinstance(data, dict):
        return {k: [float(x) for x in v] if k in ("bbox", "entry_bbox") and isinstance(v, list) else floats(v)
                for k, v in data.items()}
    if isinstance(data, list):
        return [floats(v) for v in data]
    return data


class UpgradeTo3(unittest.TestCase):
    """A database of schema 2: a pipeline id was unique per paper for good (a table constraint), and nothing
    marked old versions. The upgrade rebuilds `reactions` and keeps every row and revision as it was."""

    def test_schema_2_is_upgraded(self):
        from curator.__main__ import check
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.sqlite"
            conn = db.connect(path, create=True)
            seeded = seed_db(conn)
            conn.close()
            raw = sqlite3.connect(path, isolation_level=None)
            raw.execute("BEGIN")
            for name in re.findall(r"CREATE TRIGGER (\w+)", db.GUARDS):
                raw.execute(f"DROP TRIGGER {name}")
            raw.execute("DROP INDEX reactions_origin")
            raw.execute("ALTER TABLE reactions DROP COLUMN superseded_by")
            raw.execute("ALTER TABLE import_papers DROP COLUMN content_sha")
            raw.execute("CREATE UNIQUE INDEX schema2_unique ON reactions(paper_id, origin_id)")  # its UNIQUE
            for stmt in db._statements(db.GUARDS_V2):
                raw.execute(stmt)
            raw.execute("PRAGMA user_version = 2")
            raw.execute("COMMIT")
            names = [r[1] for r in raw.execute("PRAGMA table_info(reactions)")]
            select = f"SELECT {', '.join(names)} FROM reactions ORDER BY id"
            rows, revisions = raw.execute(select).fetchall(), raw.execute("SELECT * FROM revisions").fetchall()
            raw.close()

            conn = db.connect(path)
            try:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)
                triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
                self.assertEqual(triggers, set(re.findall(r"CREATE TRIGGER (\w+)", db.GUARDS)))
                self.assertEqual([tuple(r) for r in conn.execute(select)], [tuple(r) for r in rows])
                self.assertEqual([tuple(r) for r in conn.execute("SELECT * FROM revisions")],
                                 [tuple(r) for r in revisions])
                self.assertEqual(conn.execute("SELECT count(*) FROM reactions WHERE superseded_by IS NOT NULL")
                                 .fetchone()[0], 0)
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(check(conn)[0], [])
                # A pipeline id may come back once its row is an old version, and only then.
                r = conn.execute("SELECT id, paper_id, origin_id, data FROM reactions WHERE origin_id IS NOT NULL"
                                 " ORDER BY id").fetchone()
                again = ("INSERT INTO reactions (paper_id, origin_id, data, data_sha, rev, created_at, updated_at)"
                         " VALUES (?, ?, ?, 'x', 1, 'now', 'now')")
                with self.assertRaises(sqlite3.IntegrityError):
                    with db.write(conn):
                        conn.execute(again, (r["paper_id"], r["origin_id"], r["data"]))
                with db.write(conn):
                    conn.execute("UPDATE reactions SET in_latest = 0, superseded_by = ? WHERE id = ?",
                                 (seeded["import_id"], r["id"]))
                    conn.execute(again, (r["paper_id"], r["origin_id"], r["data"]))
            finally:
                conn.close()

    def test_an_old_version_is_read_only(self):
        from curator import store
        conn = db.connect(":memory:")
        seeded = seed_db(conn)
        rid = seeded["ids"]["main:scheme2/1/e001-1"]
        with db.write(conn):
            conn.execute("UPDATE reactions SET in_latest = 0, superseded_by = ? WHERE id = ?", (seeded["import_id"], rid))
        state = store.state_of(store._row(conn, rid))
        for change in ({"review_status": "reviewed"}, {"deleted": True}, {"data": {**state["data"], "notes": "x"}}):
            with self.assertRaises(sqlite3.IntegrityError):
                with db.write(conn):
                    store.apply_state(conn, rid, {**state, **change}, action="edit", author="ann")
        for back in ("in_latest = 1", "superseded_by = NULL"):
            with self.assertRaises(sqlite3.IntegrityError):
                with db.write(conn):
                    conn.execute(f"UPDATE reactions SET {back} WHERE id = ?", (rid,))
        conn.close()


class Upgrade(unittest.TestCase):
    """A database of schema 1: the pipeline's floats were stored and hashed as written (126.0 apart from
    126), and its triggers let REPLACE and older revs through."""

    def test_schema_1_is_upgraded(self):
        from curator import store
        from curator.__main__ import check
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.sqlite"
            conn = db.connect(path, create=True)
            ids = seed_db(conn)["ids"]
            a, b, c = ids["main:scheme2/1/e001-1"], ids["main:scheme2/1/e001-3"], ids["main:scheme2/1/e001-4"]
            data_b = store.get_reaction(conn, b)["data"]
            store.update(conn, b, base_rev=1, data={**data_b, "notes": "mine"}, author="ann")  # pipeline_sha: rev 1
            conn.close()

            raw = sqlite3.connect(path, isolation_level=None)
            raw.execute("BEGIN")
            for (name,) in raw.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
                raw.execute(f"DROP TRIGGER {name}")
            for rid in (a, b, c):
                for rev_id, snapshot in raw.execute("SELECT rev_id, snapshot FROM revisions WHERE entity = 'reaction'"
                                                    " AND entity_id = ?", (str(rid),)).fetchall():
                    snap = json.loads(snapshot)
                    raw.execute("UPDATE revisions SET snapshot = ? WHERE rev_id = ?",
                                (json.dumps({**snap, "data": floats(snap["data"])}), rev_id))
                (data,) = raw.execute("SELECT data FROM reactions WHERE id = ?", (rid,)).fetchone()
                data = floats(json.loads(data))
                (first,) = raw.execute("SELECT snapshot FROM revisions WHERE entity = 'reaction' AND entity_id = ?"
                                       " AND rev = 1", (str(rid),)).fetchone()
                raw.execute("UPDATE reactions SET data = ?, data_sha = ?, pipeline_sha = ? WHERE id = ?",
                            (json.dumps(data), db._sha_v1(data), db._sha_v1(json.loads(first)["data"]), rid))
            pending = {**data, "notes": "v2"}  # c's
            raw.execute("UPDATE reactions SET pending_data = ?, pending_sha = ?, pending_import = 1, touched = 1"
                        " WHERE id = ?", (json.dumps(pending), db._sha_v1(pending), c))
            for stmt in db._statements(V1_GUARDS):
                raw.execute(stmt)
            raw.execute("PRAGMA user_version = 1")
            raw.execute("COMMIT")
            raw.close()

            conn = db.connect(path)
            try:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)
                triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
                self.assertEqual(triggers, set(re.findall(r"CREATE TRIGGER (\w+)", db.GUARDS)))
                rows = {r["id"]: r for r in conn.execute("SELECT * FROM reactions")}
                for rid in (a, b, c):
                    data = json.loads(rows[rid]["data"])
                    # The data is not rewritten (it is guarded by its revisions): only the hashes are.
                    self.assertIsInstance(data["steps"][0]["products"][0]["bbox"][0], float)
                    self.assertNotEqual(db._sha_v1(data), db.sha_json(data))
                    self.assertEqual(rows[rid]["data_sha"], db.sha_json(data))
                self.assertEqual(rows[a]["pipeline_sha"], rows[a]["data_sha"])
                self.assertFalse(store.get_reaction(conn, a)["edited"])
                self.assertTrue(store.get_reaction(conn, b)["edited"])
                self.assertEqual([o["path"] for o in store.diff_between(conn, b, "pipeline", "current")],
                                 [["data", "notes"]])
                self.assertEqual(rows[c]["pending_sha"], db.sha_json(pending))
                self.assertEqual(check(conn)[0], [])
                # What a browser sends back is no change.
                got = store.get_reaction(conn, a)
                store.update(conn, a, base_rev=got["rev"], data=db.plain_numbers(got["data"]), author="ann")
                self.assertEqual(store.get_reaction(conn, a)["rev"], got["rev"])
            finally:
                conn.close()


class Write(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.conn.execute("CREATE TABLE t (x INTEGER)")

    def tearDown(self):
        self.conn.close()

    def count(self):
        return self.conn.execute("SELECT count(*) FROM t").fetchone()[0]

    def test_commit_and_rollback_on_error(self):
        with db.write(self.conn):
            self.conn.execute("INSERT INTO t VALUES (1)")
        self.assertEqual(self.count(), 1)
        with self.assertRaises(RuntimeError):
            with db.write(self.conn):
                self.conn.execute("INSERT INTO t VALUES (2)")
                raise RuntimeError("boom")
        self.assertEqual(self.count(), 1)
        self.assertFalse(self.conn.in_transaction)

    def test_dry_run(self):
        with db.write(self.conn, rollback=True):
            self.conn.execute("INSERT INTO t VALUES (1)")
            self.assertEqual(self.count(), 1)
        self.assertEqual(self.count(), 0)
        self.assertFalse(self.conn.in_transaction)

    def test_nested_joins_the_outer_transaction(self):
        with self.assertRaises(RuntimeError):
            with db.write(self.conn):
                with db.write(self.conn):
                    self.conn.execute("INSERT INTO t VALUES (1)")
                self.assertTrue(self.conn.in_transaction)  # the inner block did not commit
                raise RuntimeError("boom")
        self.assertEqual(self.count(), 0)
        with db.write(self.conn, rollback=True):
            with db.write(self.conn):
                self.conn.execute("INSERT INTO t VALUES (1)")
        self.assertEqual(self.count(), 0)
        with db.write(self.conn):
            with self.assertRaises(RuntimeError):
                with db.write(self.conn):
                    raise RuntimeError("inner")
            self.conn.execute("INSERT INTO t VALUES (1)")
        self.assertEqual(self.count(), 1)


class Fixture(unittest.TestCase):
    """The work dir the import tests start from is what the pipeline would have left."""

    def test_build_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = fx.build_work(Path(tmp))
            ws = work / "demo"
            paper = json.loads((ws / "paper.json").read_text())
            self.assertEqual(paper["steps"]["extract"]["status"], "done")
            docs = {}
            for name, doc in paper["documents"].items():
                pdf = Path(doc["pdf"])
                self.assertTrue(pdf.is_absolute())
                self.assertEqual(db.sha_bytes(pdf.read_bytes()), doc["sha256"])
                with pymupdf.open(pdf) as d:
                    docs[name] = {"page_count": d.page_count,
                                  "pages": [[p.rect.width, p.rect.height, p.rotation, None] for p in d]}
                    if name == "main":
                        self.assertIn(fx.DOI, d[0].get_text())
            self.assertEqual(Path(paper["documents"]["main"]["pdf"]).name, fx.MAIN_NAME)
            self.assertEqual((docs["main"]["page_count"], docs["si"]["page_count"]), (1, 2))
            self.assertEqual(docs["main"]["pages"][0][:2], list(fx.PAGE))

            recs = fx.load_records(work)
            self.assertEqual([r["reaction_id"] for r in recs], list(fx.ORIGIN_IDS))
            for r in recs:
                self.assertEqual(validate_errors(r, docs), [], r["reaction_id"])
            views = {}
            for path in (ws / "step2" / "blocks").glob("*/view.json"):
                view = json.loads(path.read_text())
                views[view["ref"]] = view
                for e in view["entries"]:
                    for rv in e["reactions"]:
                        if rv["record"]:
                            self.assertEqual(rv["record"]["reaction_id"], f"{view['ref']}/{rv['rid']}")
            regions = json.loads((ws / "step1" / "regions.json").read_text())
            included = {f"{reg['region_id']}/{b['block_id']}": b for reg in regions["regions"] if reg["include"]
                        for b in reg["blocks"] if b["include"]}
            self.assertEqual(set(included), set(views))
            for ref, block in included.items():
                self.assertEqual((block["layout"], block["kind"], block["page"], block["bbox"]),
                                 tuple(views[ref]["block"][k] for k in ("layout", "kind", "page", "bbox")))

            fx.modify_record(work, fx.ORIGIN_IDS[0], lambda r: r.update(notes="rerun"))
            self.assertEqual(fx.load_records(work)[0]["notes"], "rerun")
            view = json.loads((ws / "step2" / "blocks" / "main-scheme2__1" / "view.json").read_text())
            self.assertEqual(view["entries"][0]["reactions"][0]["record"]["notes"], "rerun")
            fx.remove_record(work, fx.ORIGIN_IDS[1])
            self.assertNotIn(fx.ORIGIN_IDS[1], [r["reaction_id"] for r in fx.load_records(work)])
            fx.rename_ids(work, "main:scheme2/", "main:scheme3/")
            self.assertTrue(all(r["reaction_id"].startswith("main:scheme3/") for r in fx.load_records(work)))
            fx.set_step(work, "extract", status="running")
            self.assertEqual(json.loads((ws / "paper.json").read_text())["steps"]["extract"]["status"], "running")


def validate_errors(record, docs):
    return records.validate(records.normalize(record), docs)[0]


class Imports(unittest.TestCase):
    def test_curator_never_imports_pipeline(self):
        files = sorted((ROOT / "curator").rglob("*.py"))
        self.assertTrue(files)
        for path in files:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    self.assertNotIn(name.split(".")[0], ("pipeline",), f"{path}: import {name}")
                    self.assertNotEqual(name.split(".")[0], "fitz", f"{path}: import pymupdf, not fitz")


if __name__ == "__main__":
    unittest.main()
