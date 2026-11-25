import copy
import unittest

from curator import block_geometry as bg, db, store
from tests.curator_fixture import seed_db


class BlockGeometry(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.seed = seed_db(self.conn)
        self.block = dict(self.conn.execute("select * from blocks where exists "
            "(select 1 from reactions where reactions.block_pk=blocks.block_pk) limit 1").fetchone())
        self.view = db.loads(self.block["view"])
        self.correction = {"reason": "visual check", "entries": [
            {"eid": e["eid"], "page": e["page"], "bbox": [10,20,100,40], "note": "n=1 only"}
            for e in self.view["entries"]]}

    def tearDown(self):
        self.conn.close()

    def test_correction_is_audited_and_does_not_mutate_imported_view(self):
        before = self.conn.execute("select count(*) from revisions").fetchone()[0]
        bg.save(self.conn, self.block["block_pk"], self.correction, author="test", base_sha=db.sha_json(self.view))
        result = store.get_block(self.conn, self.block["block_pk"])
        self.assertEqual(result["view"]["entries"][0]["bbox"], [10,20,100,40])
        self.assertEqual(result["source_view"], self.view)
        self.assertEqual(self.conn.execute("select view from blocks where block_pk=?", (self.block["block_pk"],)).fetchone()[0], self.block["view"])
        self.assertEqual(self.conn.execute("select count(*) from revisions").fetchone()[0], before+1)
        self.assertEqual(result["view"]["geometry_correction"]["method"], "visual-review")
        # A later imported source has a different hash and must not inherit the old overlay.
        changed = copy.deepcopy(self.view); changed["notes"] = "new source"
        self.assertEqual(bg.effective(self.conn,self.block,changed),changed)

    def test_rejects_stale_geometry_and_partial_entry_coverage(self):
        with self.assertRaisesRegex(ValueError,"changed"):
            bg.save(self.conn,self.block["block_pk"],self.correction,author="test",base_sha="stale")
        self.correction["entries"] = []
        with self.assertRaises(ValueError):
            bg.save(self.conn,self.block["block_pk"],self.correction,author="test",base_sha=db.sha_json(self.view))

    def test_refuses_chemistry_edit_and_invalid_box(self):
        p=copy.deepcopy(self.correction);p["entries"][0]["outcomes"] = []
        docs=store.docs_for(self.conn,self.block["paper_id"])
        with self.assertRaises(ValueError):bg.apply(self.view,p,docs,self.block["doc"])
        p=copy.deepcopy(self.correction);p["entries"][0]["bbox"]=[0,0,float("inf"),100]
        with self.assertRaises(ValueError):bg.apply(self.view,p,docs,self.block["doc"])


if __name__ == "__main__":
    unittest.main()
