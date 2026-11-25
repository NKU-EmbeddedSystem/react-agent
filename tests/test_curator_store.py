import copy
import unittest

from curator import db, store, records
from curator.diff import render_path
from curator.store import BadRequest, Conflict, Invalid, NotFound
from tests.curator_fixture import seed_db
from tests.test_curator_db import floats

E1, E3, E4, E5, E6 = (f"main:scheme2/1/e001-{n}" for n in (1, 3, 4, 5, 6))


class Base(unittest.TestCase):
    """A seeded database; every test checks that the revision log only ever grows."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        self.seed = seed_db(self.conn)
        self.ids = self.seed["ids"]
        self.a = self.ids[E3]  # one step, nothing open
        self.other = self.seed["other"]
        self.log = self.revisions()

    def tearDown(self):
        self.consistent()
        self.conn.close()

    def revisions(self):
        return [tuple(r) for r in self.conn.execute("SELECT * FROM revisions ORDER BY rev_id")]

    def written(self, n=1):
        """Exactly n revisions were appended since the last call, and none of the earlier ones changed."""
        now = self.revisions()
        self.assertEqual(now[:len(self.log)], self.log)
        self.assertEqual(len(now) - len(self.log), n)
        new, self.log = now[len(self.log):], now
        cols = [d[0] for d in self.conn.execute("SELECT * FROM revisions LIMIT 0").description]
        return [dict(zip(cols, r)) for r in new]

    def consistent(self):
        """What `python -m curator check` verifies: rev, latest snapshot and sha agree with the row."""
        for r in self.conn.execute("SELECT * FROM reactions"):
            last = self.conn.execute("SELECT rev, snapshot FROM revisions WHERE entity = 'reaction' AND entity_id = ?"
                                     " ORDER BY rev DESC LIMIT 1", (str(r["id"]),)).fetchone()
            snap = db.loads(last["snapshot"])
            self.assertEqual(last["rev"], r["rev"])
            self.assertEqual(db.canonical_json(snap["data"]), db.canonical_json(db.loads(r["data"])))
            self.assertEqual((snap["review_status"], snap["review_note"], snap["deleted"]),
                             (r["review_status"], r["review_note"], bool(r["deleted"])))
            self.assertEqual(r["data_sha"], db.sha_json(snap["data"]))
        for p in self.conn.execute("SELECT * FROM papers"):
            last = self.conn.execute("SELECT rev, snapshot FROM revisions WHERE entity = 'paper' AND entity_id = ?"
                                     " ORDER BY rev DESC LIMIT 1", (p["paper_id"],)).fetchone()
            self.assertEqual(last["rev"], p["rev"])
            self.assertEqual(db.loads(last["snapshot"]), {k: p[k] for k in store.PAPER_FIELDS})

    def get(self, rid):
        return store.get_reaction(self.conn, rid)

    def data(self, rid):
        return copy.deepcopy(self.get(rid)["data"])

    def edit(self, rid, change, author="ann", **kw):
        data = self.data(rid)
        change(data)
        return store.update(self.conn, rid, base_rev=self.get(rid)["rev"], data=data, author=author, **kw)

    def listed(self, **params):
        return [r["id"] for r in store.list_reactions(self.conn, params)["rows"]]

    def set_pending(self, rid, change, touched=1):
        data = self.data(rid)
        change(data)
        self.conn.execute("UPDATE reactions SET pending_data = ?, pending_sha = ?, pending_import = ?, touched = ?"
                          " WHERE id = ?", (db.dumps(data), db.sha_json(data), self.seed["import_id"], touched, rid))
        return data


class Update(Base):
    def test_save(self):
        before = self.get(self.a)

        def change(d):
            d["notes"] = "checked"
            d["steps"][0]["reactants"][0]["label"] = "1b"
            d["reaction_id"] = "someone/else"  # server-owned: ignored
        out = self.edit(self.a, change, comment="label of the bromide")
        self.assertEqual((out["rev"], out["warnings"], out["touched"], out["edited"], out["updated_by"]),
                         (2, [], True, True, "ann"))
        self.assertEqual(out["data"]["reaction_id"], before["data"]["reaction_id"])
        self.assertEqual(out["reactants"], "1b + 2")  # list columns follow the data
        (rev,) = self.written()
        self.assertEqual((rev["action"], rev["author"], rev["comment"], rev["base_rev"], rev["rev"]),
                         ("edit", "ann", "label of the bromide", 1, 2))
        self.assertEqual(sorted(render_path(op["path"]) for op in db.loads(rev["diff"])),
                         ["data.notes", "data.steps[0].reactants[1].label"])
        self.assertEqual(self.listed(q="1b"), [self.a])
        self.assertEqual(self.get(self.a)["review_status"], "unreviewed")

    def test_conflict(self):
        self.edit(self.a, lambda d: d.update(notes="first"))
        self.written()
        data = self.data(self.a)
        data["notes"] = "second"
        with self.assertRaises(Conflict) as cm:
            store.update(self.conn, self.a, base_rev=1, data=data, author="bob")
        self.assertEqual((cm.exception.current["rev"], cm.exception.current["data"]["notes"]), (2, "first"))
        self.written(0)

    def test_no_change_writes_nothing(self):
        out = store.update(self.conn, self.a, base_rev=1, data=self.data(self.a), author="ann")
        self.assertEqual((out["rev"], out["touched"], out["warnings"]), (1, False, []))
        self.written(0)

    def test_what_a_browser_sends_back(self):
        # The pipeline writes boxes as floats (126.0); JSON.parse + JSON.stringify make them 126.
        data = floats(self.data(self.a))
        rid = store.insert_reaction(self.conn, paper_id="demo", block_pk=self.seed["block_pk"], origin_id="x/1/e9",
                                    data=data, action="import", author="import", pipeline_sha=db.sha_json(data))
        self.written()
        self.assertIsInstance(self.get(rid)["data"]["steps"][0]["products"][0]["bbox"][0], float)
        out = store.update(self.conn, rid, base_rev=1, data=db.plain_numbers(self.data(rid)), author="ann")
        self.assertEqual((out["rev"], out["edited"], out["touched"]), (1, False, False))  # no change at all
        self.written(0)
        browser = db.plain_numbers(self.data(rid))
        browser["steps"][0]["reactants"][0]["amount"] = "0.4 mmol"
        store.update(self.conn, rid, base_rev=1, data=browser, author="ann")
        (rev,) = self.written()
        self.assertEqual([render_path(o["path"]) for o in db.loads(rev["diff"])],
                         ["data.steps[0].reactants[1].amount"])  # the edit only, no 126.0 → 126
        self.assertEqual(len(store.diff_between(self.conn, rid, "pipeline", "current")), 1)
        browser["steps"][0]["reactants"][0]["amount"] = data["steps"][0]["reactants"][0]["amount"]
        out = store.update(self.conn, rid, base_rev=2, data=browser, author="ann")  # undone by hand
        self.written()
        self.assertFalse(out["edited"])
        self.assertEqual(self.listed(edited="1"), [])

    def test_invalid(self):
        def change(d):
            d["steps"][0]["products"][0]["bbox"] = [55, 102, 145, 900]
        with self.assertRaises(Invalid) as cm:
            self.edit(self.a, change)
        self.assertEqual(cm.exception.errors, ["steps[0].products[3].bbox: 框超出页面范围（页面 600 × 800 pt）"])
        with self.assertRaises(Invalid) as cm:
            store.update(self.conn, self.a, base_rev=1, data=[1], author="ann")
        self.assertEqual(cm.exception.errors, ["记录应为一个 JSON 对象"])
        self.written(0)
        self.assertEqual(self.get(self.a)["rev"], 1)

    def test_errors_already_there_do_not_block(self):
        data = self.data(self.a)
        data["steps"][0]["products"][0]["bbox"] = [55, 102, 145, 900]  # as the pipeline left it
        rid = store.insert_reaction(self.conn, paper_id="demo", block_pk=self.seed["block_pk"], origin_id="x/1/e9",
                                    data=data, action="import", author="import", pipeline_sha=db.sha_json(data))
        self.written()
        out = self.edit(rid, lambda d: d.update(notes="ok"))
        self.assertEqual(out["warnings"], ["steps[0].products[3].bbox: 框超出页面范围（页面 600 × 800 pt）（原有问题）"])
        self.written()
        with self.assertRaises(Invalid):
            self.edit(rid, lambda d: d["steps"][0]["reactants"][0].update(page=5))
        self.written(0)

    def test_author_and_ids(self):
        with self.assertRaises(BadRequest):
            store.update(self.conn, self.a, base_rev=1, data=self.data(self.a), author="  ")
        with self.assertRaises(NotFound):
            store.update(self.conn, 999, base_rev=1, data={}, author="ann")
        with self.assertRaises(BadRequest):
            store.update(self.conn, self.a, base_rev="one", data=self.data(self.a), author="ann")
        self.assertEqual(self.get(f"R{self.a:06d}")["id"], self.a)
        self.assertEqual(self.get(str(self.a))["rid"], f"R{self.a:06d}")
        with self.assertRaises(NotFound):
            self.get("x1")
        self.written(0)


class Review(Base):
    def test_review(self):
        out = store.review(self.conn, self.a, base_rev=1, status="reviewed", note=" looks fine ", author="ann")
        self.assertEqual((out["review_status"], out["review_note"], out["rev"], out["touched"], out["edited"]),
                         ("reviewed", "looks fine", 2, True, False))  # touched, but the data is the pipeline's
        (rev,) = self.written()
        self.assertEqual(rev["action"], "review")
        self.assertEqual(db.loads(rev["diff"]), [
            {"op": "change", "path": ["review_note"], "old": None, "new": "looks fine"},
            {"op": "change", "path": ["review_status"], "old": "unreviewed", "new": "reviewed"}])
        store.review(self.conn, self.a, base_rev=2, status="reviewed", note="looks fine", author="ann")
        self.written(0)
        with self.assertRaises(BadRequest):
            store.review(self.conn, self.a, base_rev=2, status="great", note=None, author="ann")
        with self.assertRaises(Conflict):
            store.review(self.conn, self.a, base_rev=1, status="problem", note=None, author="ann")
        self.written(0)


class Revert(Base):
    def test_revert_keeps_review_and_clears_edited(self):
        original = self.data(self.a)
        self.edit(self.a, lambda d: d.update(notes="wrong"))
        self.assertTrue(self.get(self.a)["edited"])
        store.review(self.conn, self.a, base_rev=2, status="problem", note="notes", author="ann")
        self.written(2)
        out = store.revert(self.conn, self.a, base_rev=3, to_rev=1, author="bob", comment="back")
        (rev,) = self.written()
        self.assertEqual((rev["action"], rev["target_rev"], rev["base_rev"], rev["rev"]), ("revert", 1, 3, 4))
        self.assertEqual(out["data"], original)
        self.assertEqual((out["review_status"], out["review_note"]), ("problem", "notes"))
        self.assertFalse(out["edited"])  # back at the pipeline's version
        self.assertEqual(self.listed(edited="1"), [])
        store.revert(self.conn, self.a, base_rev=4, to_rev=1, author="bob")  # already there
        self.written(0)
        with self.assertRaises(NotFound):
            store.revert(self.conn, self.a, base_rev=4, to_rev=99, author="bob")


class CopyCreate(Base):
    def test_copy(self):
        store.review(self.conn, self.a, base_rev=1, status="reviewed", note=None, author="ann")
        self.written()
        original = self.get(self.a)
        out = store.copy(self.conn, self.a, author="bob")
        (rev,) = self.written()
        self.assertNotEqual(out["id"], self.a)
        self.assertEqual((out["copied_from"], out["origin_id"], out["review_status"], out["rev"], out["touched"],
                          out["edited"], out["block_pk"], out["paper_id"]),
                         (self.a, None, "unreviewed", 1, True, True, self.seed["block_pk"], "demo"))
        self.assertEqual((out["data"]["reaction_id"], out["data"]["source"]["reaction_id"]), (None, None))
        expected = copy.deepcopy(original["data"])
        expected["reaction_id"] = None
        expected["source"]["reaction_id"] = None
        self.assertEqual(out["data"], expected)
        self.assertEqual((rev["action"], rev["comment"], rev["entity_id"]),
                         ("copy", f"复制自 R{self.a:06d}（第 2 版）", str(out["id"])))
        self.assertEqual(self.get(self.a), original)
        self.assertEqual(store.copy(self.conn, self.a, author="bob", comment="variant b")["id"], out["id"] + 1)
        self.assertEqual(self.written()[0]["comment"], "variant b")

    def test_create_from_a_block_entry(self):
        out = store.create(self.conn, paper_id="demo", block_pk=self.seed["block_pk"], entry_id="e001", author="ann")
        (rev,) = self.written()
        self.assertEqual((rev["action"], rev["rev"]), ("create", 1))
        self.assertEqual(out["data"]["source"], {
            "doc": "main", "page": 1, "figure": "Scheme 2", "section": None, "caption": "Scheme 2. Scope",
            "region_id": "main:scheme2", "block_id": "1", "entry_id": "e001", "reaction_id": None,
            "entry_bbox": [50, 100, 150, 160]})
        self.assertEqual((out["kind"], out["layout"], out["origin_id"], out["touched"], out["edited"], out["label"]),
                         ("substrate_scope", "product_scope", None, True, True, None))
        self.assertEqual(out["block"]["block_pk"], self.seed["block_pk"])
        out = store.create(self.conn, paper_id=12, author="ann")  # an id from JSON may be a number
        self.written()
        self.assertEqual((out["data"]["source"]["doc"], out["block"], out["data"]["steps"][0]["reactants"]),
                         ("main", None, []))

    def test_create_refusals(self):
        bp = self.seed["block_pk"]
        for kw, error in (({"paper_id": "nope"}, NotFound), ({"paper_id": "demo", "entry_id": "e001"}, BadRequest),
                          ({"paper_id": "demo", "block_pk": bp, "entry_id": "e404"}, NotFound),
                          ({"paper_id": "demo", "block_pk": 404}, NotFound),
                          ({"paper_id": "12", "block_pk": bp}, BadRequest),
                          ({"paper_id": "demo", "author": ""}, BadRequest)):
            with self.assertRaises(error, msg=kw):
                store.create(self.conn, **{"author": "ann", **kw})
        self.written(0)


class DeleteRestore(Base):
    def test_delete_and_restore(self):
        self.assertEqual(store.list_reactions(self.conn, {})["total"], 6)
        out = store.delete(self.conn, self.a, base_rev=1, author="ann", comment="duplicate")
        (rev,) = self.written()
        self.assertEqual((out["deleted"], rev["action"], db.loads(rev["diff"])[0]["path"]),
                         (True, "delete", ["deleted"]))
        self.assertNotIn(self.a, self.listed())
        self.assertEqual(self.listed(deleted="1"), [self.a])
        self.assertEqual(len(self.listed(deleted="all")), 6)
        store.delete(self.conn, self.a, base_rev=2, author="ann")
        self.written(0)
        out = store.restore(self.conn, self.a, base_rev=2, author="ann")
        self.assertEqual((out["deleted"], self.written()[0]["action"]), (False, "restore"))
        self.assertIn(self.a, self.listed())


class Listing(Base):
    def test_default_order_is_print_order(self):
        self.assertEqual(self.listed(), [self.other] + [self.ids[k] for k in (E1, E3, E4, E5, E6)])
        rows = store.list_reactions(self.conn, {})["rows"]
        row = next(r for r in rows if r["id"] == self.a)
        self.assertEqual(set(row), {"id", "rid", "paper_id", "block_pk", "origin_id", "figure", "label", "layout",
                                    "kind", "doc", "page", "reactants", "products", "conditions", "yields",
                                    "review_status", "flags", "thumb", "deleted", "edited", "pending", "in_latest",
                                    "superseded_by", "rev", "updated_at", "updated_by"})
        self.assertEqual((row["flags"], row["thumb"], row["yields"]),
                         (["warned"], {"doc": "main", "page": 1, "bbox": [55, 102, 145, 140], "doc_id": 1}, "3fa 42%"))

    def test_filters(self):
        ids, a, other = self.ids, self.a, self.other
        demo = [ids[k] for k in (E1, E3, E4, E5, E6)]
        self.assertEqual(self.listed(paper="demo"), demo)
        self.assertEqual(len(self.listed(paper="demo,12")), 6)
        self.assertEqual(len(self.listed(paper=" ")), 6)  # empty values are no filter
        self.assertEqual(self.listed(figure="Table 1"), [other])
        self.assertEqual(self.listed(block=str(self.seed["block_pk"])), demo)
        self.assertEqual(self.listed(layout="product_scope"), demo)
        self.assertEqual(self.listed(kind="optimization"), [other])
        self.assertEqual(self.listed(flag="inferred"), [ids[E1], ids[E5]])
        self.assertEqual(self.listed(flag="inferred,unresolved"), [ids[E1]])
        self.assertEqual(self.listed(flag="warned"), [a])
        self.assertEqual(self.listed(flag="issues"), [ids[E6]])
        self.assertEqual(len(self.listed(**{"import": str(self.seed["import_id"])})), 6)
        self.assertEqual(self.listed(**{"import": "999"}), [])
        self.assertEqual(self.listed(ids=f"R{a:06d},{other}"), [other, a])
        self.assertEqual(self.listed(q="3a′"), [other])
        self.assertEqual(self.listed(q="核磁"), [other])
        self.assertEqual(self.listed(q="FE(BF-PHOS)CL2 lICl"), [other, a])  # the second paper's is a copy of a
        self.assertEqual(self.listed(q="scheme 3fa"), demo)
        self.assertEqual(len(self.listed(q="2%")), 6)  # the results: '42% b'
        self.assertEqual(self.listed(q="4_%"), [])  # % and _ are literal

        store.review(self.conn, a, base_rev=1, status="problem", note=None, author="ann")
        self.assertEqual(self.listed(status="problem"), [a])
        self.assertEqual(len(self.listed(status="unreviewed,reviewed")), 5)
        self.edit(ids[E1], lambda d: d.update(notes="x"))
        self.assertEqual(self.listed(edited="1"), [ids[E1]])
        self.assertEqual(len(self.listed(edited="0")), 5)
        self.set_pending(ids[E4], lambda d: d.update(notes="v2"))
        self.assertEqual(self.listed(pending="1"), [ids[E4]])
        self.assertEqual(len(self.listed(pending="0")), 5)
        self.conn.execute("UPDATE reactions SET in_latest = 0 WHERE id = ?", (other,))
        self.assertEqual(self.listed(latest="0"), [other])
        self.assertEqual(len(self.listed(latest="1")), 5)
        self.written(2)

    def test_bad_values(self):
        for params in ({"status": "done"}, {"flag": "odd"}, {"edited": "2"}, {"pending": "yes"}, {"latest": "1,0"},
                       {"deleted": "x"}, {"sort": "title"}, {"order": "up"}, {"limit": "many"}, {"offset": "-1"},
                       {"block": "x"}, {"import": "first"}, {"ids": "R12x"}):
            with self.assertRaises(BadRequest, msg=params):
                store.list_reactions(self.conn, params)

    def test_sort_and_pages(self):
        default = self.listed()
        self.assertEqual(self.listed(sort="id", order="desc"), sorted(default, reverse=True))
        self.assertEqual(self.listed(sort="paper", order="desc"), list(reversed(default)))
        self.assertEqual(self.listed(sort="label")[0], self.other)  # 3a′ before 3fa
        self.edit(self.ids[E1], lambda d: d.update(notes="x"))
        self.conn.execute("UPDATE reactions SET updated_at = '2999-01-01T00:00:00+00:00' WHERE id = ?",
                          (self.ids[E1],))  # timestamps have whole seconds
        self.assertEqual(self.listed(sort="updated")[-1], self.ids[E1])
        self.assertEqual(self.listed(sort="updated", order="desc")[0], self.ids[E1])
        for sort in store.SORTS:
            self.assertEqual(len(self.listed(sort=sort)), 6)
        page = store.list_reactions(self.conn, {"offset": "1", "limit": "2"})
        self.assertEqual((page["total"], [r["id"] for r in page["rows"]]), (6, default[1:3]))
        self.assertEqual(len(self.listed(limit="5000")), 6)
        self.assertEqual(self.listed(limit="0"), [])
        self.written()

    def test_list_columns_follow_edits(self):
        def change(d):
            d["label"] = "3zz"
            d["steps"][0]["products"][0]["outcomes"][0]["yield"]["text"] = "77%"
            d["steps"][0]["conditions"] = []
            d["issues"] = ["checked against SI"]
        self.edit(self.a, change)
        row = store.list_reactions(self.conn, {"ids": str(self.a)})["rows"][0]
        self.assertEqual((row["label"], row["yields"], row["conditions"], row["flags"]),
                         ("3zz", "3fa 77%", "", ["issues", "warned"]))
        self.assertEqual(self.listed(q="3zz"), [self.a])
        self.assertEqual(self.listed(q="fe(bf-phos)cl2"), [self.other])
        self.written()


class Neighbours(Base):
    def test_prev_next(self):
        order = self.listed()
        self.assertEqual(store.neighbours(self.conn, order[0], {}), {"prev": None, "next": order[1]})
        self.assertEqual(store.neighbours(self.conn, order[2], {}), {"prev": order[1], "next": order[3]})
        self.assertEqual(store.neighbours(self.conn, order[-1], {}), {"prev": order[-2], "next": None})
        self.assertEqual(store.neighbours(self.conn, order[1], {"paper": "demo"}), {"prev": None, "next": order[2]})
        self.assertEqual(store.neighbours(self.conn, order[1], {"sort": "id", "order": "desc"}),
                         {"prev": order[2], "next": None})
        # A reaction an edit has just taken out of the filter keeps its place.
        store.review(self.conn, order[2], base_rev=1, status="reviewed", note=None, author="ann")
        self.written()
        self.assertEqual(store.neighbours(self.conn, order[2], {"status": "unreviewed"}),
                         {"prev": order[1], "next": order[3]})
        with self.assertRaises(NotFound):
            store.neighbours(self.conn, 999, {})


class Pending(Base):
    def test_accept(self):
        new = self.set_pending(self.a, lambda d: d.update(notes="pipeline v2"))
        got = self.get(self.a)
        self.assertEqual(got["pending"], {"import_id": self.seed["import_id"], "sha": db.sha_json(new), "diff": [
            {"op": "change", "path": ["data", "notes"], "old": "", "new": "pipeline v2"}]})
        self.assertEqual(store.diff_between(self.conn, self.a, "current", "pending"), got["pending"]["diff"])
        self.assertTrue(store.list_reactions(self.conn, {"ids": str(self.a)})["rows"][0]["pending"])
        with self.assertRaises(Conflict):
            store.accept_pending(self.conn, self.a, base_rev=0, author="ann")
        out = store.accept_pending(self.conn, self.a, base_rev=1, author="ann")
        (rev,) = self.written()
        self.assertEqual((rev["action"], rev["import_id"], rev["author"]),
                         ("accept_import", self.seed["import_id"], "ann"))
        self.assertEqual((out["data"], out["pending"], out["edited"], out["rev"]), (new, None, False, 2))
        row = self.conn.execute("SELECT * FROM reactions WHERE id = ?", (self.a,)).fetchone()
        self.assertEqual((row["pipeline_sha"], row["pending_data"], row["pending_import"]),
                         (db.sha_json(new), None, None))
        self.assertEqual(store.diff_between(self.conn, self.a, "pipeline", "current"), [])
        with self.assertRaises(BadRequest):
            store.accept_pending(self.conn, self.a, base_rev=2, author="ann")
        with self.assertRaises(NotFound):
            store.diff_between(self.conn, self.a, "current", "pending")

    def test_accept_does_not_touch(self):
        self.set_pending(self.a, lambda d: d.update(notes="v2"), touched=0)
        self.assertFalse(store.accept_pending(self.conn, self.a, base_rev=1, author="ann")["touched"])
        self.written()

    def test_dismiss(self):
        self.edit(self.a, lambda d: d.update(notes="mine"))
        self.written()
        new = self.set_pending(self.a, lambda d: d.update(notes="pipeline v2", label="3fb"))
        out = store.dismiss_pending(self.conn, self.a, base_rev=2, author="ann", comment="ours is right")
        (rev,) = self.written()
        self.assertEqual((rev["action"], db.loads(rev["diff"]), rev["comment"], rev["rev"]),
                         ("dismiss_import", [], "ours is right", 3))
        self.assertEqual((out["data"]["notes"], out["pending"], out["edited"]), ("mine", None, True))
        row = self.conn.execute("SELECT pipeline_sha, pending_sha FROM reactions WHERE id = ?", (self.a,)).fetchone()
        self.assertEqual(tuple(row), (db.sha_json(new), None))
        self.assertEqual(self.listed(pending="1"), [])
        # The dismissed version is kept: it is what the reaction is now compared with.
        self.assertEqual(db.loads(rev["snapshot"])["dismissed"], {"sha": db.sha_json(new), "data": new})
        self.assertEqual(sorted(render_path(o["path"]) for o in store.diff_between(self.conn, self.a, "pipeline",
                                                                                    "current")),
                         ["data.label", "data.notes"])
        self.assertEqual(store.diff_between(self.conn, self.a, 3, "current"), [])  # states only

    def test_dismiss_after_a_review_only(self):
        # Nothing edited by hand: after the dismissal the reaction is 已修改, and the diff says why.
        store.review(self.conn, self.a, base_rev=1, status="reviewed", note=None, author="ann")
        self.written()
        self.set_pending(self.a, lambda d: d.update(label="PIPELINE-C"))
        out = store.dismiss_pending(self.conn, self.a, base_rev=2, author="ann")
        self.written()
        self.assertTrue(out["edited"])
        self.assertEqual([(render_path(o["path"]), o["new"]) for o in
                          store.diff_between(self.conn, self.a, "pipeline", "current")], [("data.label", "3fa")])

    def test_pipeline_version_not_kept_is_not_made_up(self):
        # A version dismissed before revisions kept it: no other version is shown in its place.
        self.conn.execute("UPDATE reactions SET pipeline_sha = ? WHERE id = ?", ("0" * 64, self.a))
        with self.assertRaises(NotFound):
            store.diff_between(self.conn, self.a, "pipeline", "current")


class History(Base):
    def test_history_and_diffs(self):
        self.edit(self.a, lambda d: d.update(notes="x"))
        store.review(self.conn, self.a, base_rev=2, status="reviewed", note=None, author="bob")
        self.written(2)
        hist = store.history(self.conn, self.a)
        self.assertEqual([(h["rev"], h["action"], h["author"]) for h in hist],
                         [(3, "review", "bob"), (2, "edit", "ann"), (1, "import", "import")])
        self.assertEqual(set(hist[0]), {"rev", "action", "author", "comment", "created_at", "import_id", "base_rev",
                                        "target_rev", "diff"})
        self.assertEqual(hist[1]["diff"], [{"op": "change", "path": ["data", "notes"], "old": "", "new": "x"}])
        self.assertEqual(hist[2]["diff"], [])
        self.assertEqual(store.revision(self.conn, self.a, 2)["snapshot"]["data"]["notes"], "x")
        both = store.diff_between(self.conn, self.a, 1, "3")
        self.assertEqual([render_path(o["path"]) for o in both], ["data.notes", "review_status"])
        self.assertEqual(store.diff_between(self.conn, self.a, "1", "current"), both)
        # Against the pipeline's version: the data only.
        self.assertEqual([render_path(o["path"]) for o in store.diff_between(self.conn, self.a, "pipeline", "current")],
                         ["data.notes"])
        with self.assertRaises(BadRequest):
            store.diff_between(self.conn, self.a, "x", "current")
        with self.assertRaises(NotFound):
            store.diff_between(self.conn, self.a, 9, "current")
        with self.assertRaises(NotFound):
            store.revision(self.conn, self.a, 9)
        created = store.create(self.conn, paper_id="demo", author="ann")["id"]
        self.written()
        with self.assertRaises(NotFound):  # made by hand: no pipeline version
            store.diff_between(self.conn, created, "pipeline", "current")
        with self.assertRaises(NotFound):
            store.history(self.conn, 999)


class Papers(Base):
    def test_update_paper(self):
        out = store.update_paper(self.conn, "demo", base_rev=1, fields={"title": " New title ", "year": "2025",
                                                                        "doi": ""}, author="ann", comment="typo")
        (rev,) = self.written()
        self.assertEqual((out["title"], out["year"], out["doi"], out["rev"], out["meta_origin"]),
                         ("New title", 2025, None, 2, "edited"))
        self.assertEqual((rev["entity"], rev["action"], rev["comment"]), ("paper", "meta", "typo"))
        self.assertEqual([o["path"] for o in db.loads(rev["diff"])], [["doi"], ["title"], ["year"]])
        self.assertEqual([h["rev"] for h in store.paper_history(self.conn, "demo")], [2, 1])
        with self.assertRaises(Conflict) as cm:
            store.update_paper(self.conn, "demo", base_rev=1, fields={"title": "Other"}, author="bob")
        self.assertEqual((cm.exception.current["rev"], cm.exception.current["title"]), (2, "New title"))
        store.update_paper(self.conn, "demo", base_rev=2, fields={"title": "New title"}, author="bob")
        self.written(0)
        for fields in ({"context": "x"}, {"year": "MMXXVI"}, {"title": 5}):
            with self.assertRaises(BadRequest, msg=fields):
                store.update_paper(self.conn, "demo", base_rev=2, fields=fields, author="bob")
        with self.assertRaises(NotFound):
            store.update_paper(self.conn, "nope", base_rev=1, fields={}, author="bob")
        with self.assertRaises(NotFound):
            store.paper_history(self.conn, "nope")
        self.written(0)

    def test_papers(self):
        store.delete(self.conn, self.a, base_rev=1, author="ann")
        self.written()
        papers = store.list_papers(self.conn)
        self.assertEqual([p["paper_id"] for p in papers], ["12", "demo"])
        self.assertEqual(papers[1]["counts"], {"reactions": 4, "unreviewed": 4, "reviewed": 0, "problem": 0,
                                               "excluded": 0, "pending": 0, "edited": 0, "deleted": 1, "old": 0})
        self.assertEqual([d["doc"] for d in papers[1]["documents"]], ["main"])
        paper = store.get_paper(self.conn, "demo")
        self.assertEqual((paper["doi"], paper["context"]["numbering_convention"], paper["rev"]),
                         ("10.5555/demo.2026.42", "", 1))
        self.assertEqual(paper["documents"]["main"]["page_count"], 1)
        self.assertEqual([(b["figure"], b["reactions"]) for b in paper["blocks"]], [("Scheme 2", 4)])
        self.assertEqual([i["outcome"] for i in paper["imports"]], ["imported"])
        with self.assertRaises(NotFound):
            store.get_paper(self.conn, "nope")


class Queries(Base):
    def test_get_reaction(self):
        r = self.get(self.a)
        self.assertEqual((r["rid"], r["origin_id"], r["paper"]["title"], r["block"]["figure"], r["pending"]),
                         (f"R{self.a:06d}", E3, "Every state a reaction can be in", "Scheme 2", None))
        self.assertEqual(r["documents"]["main"]["pages"], [[600.0, 800.0, 0, [1, 0, 0, -1, 0, 800]]])
        self.assertEqual(r["pipeline_info"]["warnings"], ["the scale is read from the SI"])
        self.assertEqual(r["provenance"]["first_import"]["steps"]["extract"]["version"], 6)
        self.assertEqual((r["first_import"], r["last_import"]), (self.seed["import_id"],) * 2)
        self.assertNotIn("crop", db.dumps(r["data"]))

    def test_data_import(self):
        """provenance.data_import: the import the data comes from, also when a later one only offered a
        version, through edits and reverts."""
        first = self.seed["import_id"]
        with db.write(self.conn):
            second = self.conn.execute("INSERT INTO imports (started_at, work_dir, author, options)"
                                       " VALUES ('2026-02-01T00:00:00+00:00', '/w', 'import', '{}')").lastrowid
            self.conn.execute("INSERT INTO import_papers (import_id, paper_id, outcome, steps) VALUES (?, 'demo',"
                              " 'imported', ?)", (second, db.dumps({"extract": {"version": 7}})))

        def came_from():
            return self.get(self.a)["provenance"]["data_import"]["import_id"]
        self.assertEqual(came_from(), first)
        self.edit(self.a, lambda d: d.update(notes="mine"))  # an edit of import 1's data
        self.conn.execute("UPDATE reactions SET last_import = ? WHERE id = ?", (second, self.a))
        self.set_pending(self.a, lambda d: d.update(notes="v2"))
        self.conn.execute("UPDATE reactions SET pending_import = ? WHERE id = ?", (second, self.a))
        self.assertEqual((came_from(), self.get(self.a)["provenance"]["last_import"]["import_id"]), (first, second))
        store.accept_pending(self.conn, self.a, base_rev=2, author="ann")
        self.assertEqual(came_from(), second)
        self.assertEqual(self.get(self.a)["provenance"]["data_import"]["steps"]["extract"]["version"], 7)
        store.revert(self.conn, self.a, base_rev=3, to_rev=2, author="ann")  # back to the edit of import 1's
        self.assertEqual(came_from(), first)
        self.assertIsNone(store.copy(self.conn, self.a, author="ann")["provenance"]["data_import"])
        self.written(4)

    def test_facet_for_no_figure(self):
        self.conn.execute("UPDATE reactions SET figure = NULL WHERE id = ?", (self.a,))
        self.conn.execute("UPDATE reactions SET figure = '' WHERE id = ?", (self.ids[E1],))
        f = store.facets(self.conn, {})
        self.assertEqual(f["figure"][-1], {"value": store.NONE_VALUE, "count": 2, "label": "（无）"})
        self.assertEqual(sorted(self.listed(figure=store.NONE_VALUE)), sorted([self.a, self.ids[E1]]))
        self.assertEqual(len(self.listed(figure=f"{store.NONE_VALUE},Table 1")), 3)
        self.assertEqual(self.listed(layout=store.NONE_VALUE), [self.other])  # no block, no layout
        self.assertEqual({x["value"]: x["count"] for x in f["layout"]}, {"product_scope": 5, store.NONE_VALUE: 1})

    def test_ids_beyond_sqlite(self):
        # Not an OverflowError from binding a 20-digit number (a 500): not found, or a bad request.
        for rid in (10 ** 20, "99999999999999999999", "R" + "9" * 20, "9" * 5000):
            with self.assertRaises(NotFound, msg=rid):
                self.get(rid)
        for call in (lambda: store.revision(self.conn, self.a, 10 ** 20),
                     lambda: store.list_reactions(self.conn, {"offset": "9" * 20}),
                     lambda: store.list_reactions(self.conn, {"ids": "9" * 25}),
                     lambda: store.list_reactions(self.conn, {"import": "9" * 5000}),
                     lambda: store.get_block(self.conn, 10 ** 20),
                     lambda: store.review(self.conn, self.a, base_rev=10 ** 20, status="reviewed", note=None,
                                          author="ann")):
            with self.assertRaises(BadRequest):
                call()
        self.assertEqual(store.facets(self.conn, {"block": "1"})["total"], 5)

    def test_block(self):
        b = store.get_block(self.conn, self.seed["block_pk"])
        self.assertEqual([x["origin_id"] for x in b["reactions"]], [E1, E3, E4, E5, E6])
        self.assertEqual((b["layout"], b["in_latest"], b["region"]["boxes"][0]["page"]), ("product_scope", True, 1))
        self.assertEqual([e["eid"] for e in b["view"]["entries"]], ["e001", "e002"])
        with self.assertRaises(NotFound):
            store.get_block(self.conn, 404)

    def test_facets(self):
        f = store.facets(self.conn, {})
        self.assertEqual(f["total"], 6)
        self.assertEqual({x["value"]: x["count"] for x in f["paper"]}, {"12": 1, "demo": 5})
        self.assertEqual({x["value"]: x["count"] for x in f["flag"]},
                         dict.fromkeys(records.FLAGS, 0) | {"inferred": 2, "unresolved": 3, "issues": 1, "warned": 1})
        store.delete(self.conn, self.a, base_rev=1, author="ann")
        self.written()
        f = store.facets(self.conn, {"paper": "12", "flag": "inferred"})
        self.assertEqual(f["total"], 0)
        # A facet is counted without its own filter: the other paper stays on offer.
        self.assertEqual({x["value"]: x["count"] for x in f["paper"]}, {"12": 0, "demo": 2})
        self.assertEqual({x["value"]: x["count"] for x in f["flag"]},
                         dict.fromkeys(records.FLAGS, 0))
        f = store.facets(self.conn, {"flag": "inferred"})
        self.assertEqual({x["value"]: x["count"] for x in f["flag"]},
                         dict.fromkeys(records.FLAGS, 0) | {"inferred": 2, "unresolved": 1})
        self.assertEqual((f["deleted"], f["edited"], f["pending"], f["not_latest"]), (0, 0, 0, 0))
        f = store.facets(self.conn, {})
        self.assertEqual((f["total"], f["deleted"]), (5, 1))
        self.assertEqual({x["value"]: x["count"] for x in f["status"]},
                         {"unreviewed": 5, "reviewed": 0, "problem": 0, "excluded": 0})
        self.assertEqual(f["block"][0]["count"], 4)
        self.assertEqual(f["import"][0]["count"], 5)

    def test_facet_blocks_in_printed_order(self):
        # Not by region_id as text, which put Table 1 (page 2) after Scheme 4 (page 3) and scheme10 before scheme9.
        with db.write(self.conn):
            for paper, doc, page, region, block in (
                    ("demo", "si", 1, "si:scheme1", "1"), ("demo", "main", 3, "main:scheme10", "1"),
                    ("demo", "main", 3, "main:scheme9", "2"), ("demo", "main", 2, "main:table1", "1"),
                    ("12", "main", 5, "main:table1", "1")):
                self.conn.execute("INSERT INTO blocks (paper_id, region_id, block_id, doc, page, region, view, import_id)"
                                  " VALUES (?, ?, ?, ?, ?, '{}', '{}', ?)",
                                  (paper, region, block, doc, page, self.seed["import_id"]))
        got = [(b["paper_id"], b["label"]) for b in store.facets(self.conn, {})["block"]]
        self.assertEqual(got, [("12", "main:table1 / 1"), ("demo", "Scheme 2 / 1 Scope of the coupling"),
                               ("demo", "main:table1 / 1"), ("demo", "main:scheme9 / 2"),
                               ("demo", "main:scheme10 / 1"), ("demo", "si:scheme1 / 1")])

    def test_imports(self):
        (imp,) = store.list_imports(self.conn)
        self.assertEqual((imp["import_id"], [p["paper_id"] for p in imp["papers"]], imp["options"]),
                         (self.seed["import_id"], ["12", "demo"], {"papers": None}))


class Primitives(Base):
    def test_apply_state_extra_without_a_change(self):
        state = store.state_of(self.conn.execute("SELECT * FROM reactions WHERE id = ?", (self.a,)).fetchone())
        self.assertIsNone(store.apply_state(self.conn, self.a, state, action="reimport", author="import",
                                            extra={"in_latest": 0, "pipeline_info": {"errors": [], "warnings": []}}))
        self.written(0)
        row = self.get(self.a)
        self.assertEqual((row["in_latest"], row["flags"], row["pipeline_info"]["warnings"]), (False, [], []))
        with self.assertRaises(ValueError):
            store.apply_state(self.conn, self.a, state, action="reimport", author="import", extra={"rev": 5})

    def test_pipeline_changes_do_not_touch(self):
        state = store.state_of(self.conn.execute("SELECT * FROM reactions WHERE id = ?", (self.a,)).fetchone())
        state["data"]["notes"] = "rerun"
        rev = store.apply_state(self.conn, self.a, state, action="reimport", author="import",
                                import_id=self.seed["import_id"], extra={"pipeline_sha": db.sha_json(state["data"])})
        self.assertEqual(rev, 2)
        (r,) = self.written()
        self.assertEqual((r["action"], r["base_rev"], r["import_id"]), ("reimport", 1, self.seed["import_id"]))
        got = self.get(self.a)
        self.assertEqual((got["touched"], got["edited"], got["updated_by"]), (False, False, "import"))

    def test_every_mutation_writes_one_revision(self):
        a, b = self.a, self.ids[E1]
        steps = [
            lambda: self.edit(a, lambda d: d.update(notes="1")),
            lambda: store.review(self.conn, a, base_rev=2, status="reviewed", note="ok", author="ann"),
            lambda: store.revert(self.conn, a, base_rev=3, to_rev=1, author="ann"),
            lambda: store.delete(self.conn, a, base_rev=4, author="ann"),
            lambda: store.restore(self.conn, a, base_rev=5, author="ann"),
            lambda: store.copy(self.conn, a, author="ann"),
            lambda: store.create(self.conn, paper_id="demo", block_pk=self.seed["block_pk"], author="ann"),
            lambda: self.set_pending(b, lambda d: d.update(notes="v2")) and None,
            lambda: store.accept_pending(self.conn, b, base_rev=1, author="ann"),
            lambda: self.set_pending(b, lambda d: d.update(notes="v3")) and None,
            lambda: store.dismiss_pending(self.conn, b, base_rev=2, author="ann"),
            lambda: store.update_paper(self.conn, "12", base_rev=1, fields={"note": "检查过"}, author="ann"),
        ]
        for i, step in enumerate(steps):
            out = step()
            self.written(0 if out is None else 1)
            self.consistent()
        self.assertEqual([h["action"] for h in store.history(self.conn, a)],
                         ["restore", "delete", "revert", "review", "edit", "import"])


if __name__ == "__main__":
    unittest.main()
