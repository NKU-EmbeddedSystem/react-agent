import copy
import io
import json
import unittest
import zipfile

import pymupdf

from curator import db, export, store
from curator.store import BadRequest, NotFound
from tests.curator_fixture import seed_db

E1, E3, E4, E5, E6 = (f"main:scheme2/1/e001-{n}" for n in (1, 3, 4, 5, 6))


class Export(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.seed = seed_db(self.conn)
        self.ids = self.seed["ids"]
        self.other = self.seed["other"]

    def tearDown(self):
        self.conn.close()

    def rev(self, rid):
        return store.get_reaction(self.conn, rid)["rev"]

    def set_data(self, rid, change):
        """Change a reaction's data without validation (as an import may have stored it)."""
        row = self.conn.execute("SELECT * FROM reactions WHERE id = ?", (rid,)).fetchone()
        state = store.state_of(row)
        change(state["data"])
        store.apply_state(self.conn, rid, state, action="edit", author="ann")

    def test_record(self):
        rid = self.ids[E3]
        store.review(self.conn, rid, base_rev=1, status="problem", note="看不清", author="ann")
        rec = export.export_record(self.conn, rid)
        self.assertEqual(list(rec), ["id", "paper", "review", "provenance", "record"])
        self.assertEqual(rec["id"], f"R{rid:06d}")
        self.assertEqual(rec["paper"], {"paper_id": "demo", "title": "Every state a reaction can be in",
                                        "authors": "Demo et al.", "journal": "J. Made-up Chem.", "year": 2026,
                                        "doi": "10.5555/demo.2026.42"})
        self.assertEqual(rec["review"], {"status": "problem", "note": "看不清", "deleted": False})
        self.assertEqual(rec["provenance"], {
            "origin_id": E3, "region_id": "main:scheme2", "block_id": "1", "figure": "Scheme 2",
            "layout": "product_scope", "first_import": self.seed["import_id"], "last_import": self.seed["import_id"],
            "rev": 2, "edited": False, "updated_at": rec["provenance"]["updated_at"], "updated_by": "ann",
            "copied_from": None, "pending": False, "superseded_by": None,
            # how the data was collected, readable outside this database
            "data_import": {"import_id": self.seed["import_id"], "imported_at": rec["provenance"]["data_import"]
                            ["imported_at"], "repo_commit": "0" * 40, "repo_dirty": 0,
                            "steps": {"extract": {"version": 6, "finished_at": None, "codex": None}}}})
        self.assertEqual(rec["record"], store.get_reaction(self.conn, rid)["data"])
        self.assertEqual(export.export_record(self.conn, f"R{rid:06d}"), rec)

        # A reaction without a block says where it came from with its record's source; a copy is edited.
        other = export.export_record(self.conn, self.other)
        self.assertEqual({k: other["provenance"][k] for k in ("region_id", "block_id", "figure", "layout")},
                         {"region_id": "main:table1", "block_id": "1", "figure": "Table 1", "layout": None})
        copied = store.copy(self.conn, rid, author="ann")
        prov = export.export_record(self.conn, copied["id"])["provenance"]
        self.assertEqual((prov["origin_id"], prov["edited"], prov["copied_from"], prov["data_import"]),
                         (None, True, f"R{rid:06d}", None))
        for missing in (999, "R000999", "x", None, 10 ** 20, "9" * 25, "R" + "9" * 5000):
            with self.assertRaises(NotFound):
                export.export_record(self.conn, missing)

    def test_deleted_and_pending_are_marked(self):
        # With include_deleted, a deleted reaction must not look live.
        a, b = self.ids[E1], self.ids[E3]
        store.delete(self.conn, b, base_rev=1, author="ann", comment="duplicate of E1")
        self.conn.execute("UPDATE reactions SET pending_data = data, pending_sha = 'x', pending_import = ?"
                          " WHERE id = ?", (self.seed["import_id"], a))
        buf = io.BytesIO()
        export.write_jsonl(self.conn, export.select_ids(self.conn, ids=[a, b], include_deleted=True), buf)
        lines = {r["id"]: r for r in map(json.loads, buf.getvalue().splitlines())}
        self.assertEqual((lines[f"R{a:06d}"]["review"]["deleted"], lines[f"R{b:06d}"]["review"]["deleted"]),
                         (False, True))
        self.assertEqual((lines[f"R{a:06d}"]["provenance"]["pending"], lines[f"R{b:06d}"]["provenance"]["pending"]),
                         (True, False))

    def test_select(self):
        everything = export.select_ids(self.conn)
        self.assertEqual(sorted(everything), sorted([*self.ids.values(), self.other]))
        # printed order (sort_key: paper '12' as '000012' comes before 'demo')
        self.assertEqual(everything, [r[0] for r in self.conn.execute("SELECT id FROM reactions ORDER BY sort_key, id")])
        a, b = self.ids[E3], self.ids[E4]
        store.review(self.conn, a, base_rev=1, status="excluded", note=None, author="ann")
        store.delete(self.conn, b, base_rev=1, author="ann")
        self.assertNotIn(a, export.select_ids(self.conn))
        self.assertNotIn(b, export.select_ids(self.conn))
        self.assertIn(a, export.select_ids(self.conn, include_excluded=True))
        self.assertIn(b, export.select_ids(self.conn, include_deleted=True))
        self.assertEqual(len(export.select_ids(self.conn, include_excluded=True, include_deleted=True)), 6)
        # The list's own filters, paging ignored; deleted=1 with include_deleted gives only the deleted ones.
        self.assertEqual(export.select_ids(self.conn, {"paper": "12", "limit": "1", "offset": "5"}), [self.other])
        self.assertEqual(export.select_ids(self.conn, {"deleted": "1"}, include_deleted=True), [b])
        self.assertEqual(export.select_ids(self.conn, {"deleted": "1"}), [])
        self.assertEqual(export.select_ids(self.conn, {"status": "excluded"}), [])
        # ids and filters both apply; ids may be display ids
        self.assertEqual(export.select_ids(self.conn, {"paper": "demo"}, [f"R{self.other:06d}", self.ids[E1]]),
                         [self.ids[E1]])
        self.assertEqual(export.select_ids(self.conn, ids=[]), [])
        with self.assertRaises(BadRequest):
            export.select_ids(self.conn, ids=["x1"])
        with self.assertRaises(BadRequest):
            export.select_ids(self.conn, {"status": "bogus"})

    def test_jsonl(self):
        ids = export.select_ids(self.conn)
        buf = io.BytesIO()
        self.assertEqual(export.write_jsonl(self.conn, ids, buf), len(ids))
        lines = buf.getvalue().decode("utf-8").splitlines()
        self.assertEqual([json.loads(line)["id"] for line in lines], [f"R{i:06d}" for i in ids])
        self.assertIn("产率由核磁测定".encode("utf-8"), buf.getvalue())  # UTF-8, not \u escapes
        self.assertEqual(export.write_jsonl(self.conn, [], io.BytesIO()), 0)

    def test_zip(self):
        rid = self.ids[E1]
        buf = io.BytesIO()
        flt = {"paper": "demo"}
        self.assertEqual(export.write_zip(self.conn, [rid, self.other], buf, filter=flt), 2)
        with zipfile.ZipFile(buf) as z:
            self.assertEqual(sorted(z.namelist()), ["manifest.json", f"reactions/R{rid:06d}.json",
                                                    f"reactions/R{self.other:06d}.json"])
            manifest = json.loads(z.read("manifest.json"))
            self.assertEqual({k: manifest[k] for k in ("count", "ids", "filter")},
                             {"count": 2, "ids": [f"R{rid:06d}", f"R{self.other:06d}"], "filter": flt})
            self.assertIn("created_at", manifest)
            self.assertNotIn("images", manifest)
            self.assertEqual(json.loads(z.read(f"reactions/R{rid:06d}.json")), export.export_record(self.conn, rid))

    def test_cross_document_review_evidence_images(self):
        self.conn.execute("INSERT INTO documents (paper_id, doc, filename, sha256, page_count, pages, pdf_meta) "
                          "SELECT paper_id, 'si', filename, sha256, page_count, pages, pdf_meta FROM documents "
                          "WHERE paper_id = 'demo' AND doc = 'main'")
        rid = self.ids[E3]
        self.set_data(rid, lambda r: r.update(review={"evidence": [
            {"id": "si-ligand", "doc": "si", "page": 1, "bbox": [50, 60, 180, 100], "quote": "L6"}]}))
        buf = io.BytesIO()
        export.write_zip(self.conn, [rid], buf, images=True)
        with zipfile.ZipFile(buf) as z:
            manifest = json.loads(z.read("manifest.json"))
            self.assertEqual(manifest["image_errors"], [])
            image = next(x for x in manifest["images"][f"R{rid:06d}"] if x["key"] == "si-ligand")
            self.assertEqual(image["doc"], "si")
            self.assertTrue(z.read(image["file"]).startswith(b"\x89PNG"))

    def test_zip_images(self):
        rid = self.ids[E1]

        def change(data):
            st = data["steps"][0]
            st["reactants"][0]["key"] = "ester/a b"  # not a file name as it is
            st["conditions"][0]["structure"] = {"key": "cat", "label": None, "page": 1, "bbox": [300, 300, 336, 318],
                                                "text": None}
            st["reactants"][1]["bbox"] = [700, 700, 800, 750]  # off the 600 x 800 page: cannot be rendered
        self.set_data(rid, change)
        data = store.get_reaction(self.conn, rid)["data"]
        product = data["steps"][0]["products"][0]
        buf = io.BytesIO()
        export.write_zip(self.conn, [rid], buf, images=True)
        with zipfile.ZipFile(buf) as z:
            names = sorted(n for n in z.namelist() if n.startswith("images/"))
            folder = f"images/R{rid:06d}/"
            # 'acid': what the ester's preparation starts from; 'nhpi': the drawn reagent of one of its items
            self.assertEqual(names, sorted(folder + n for n in ("ester_a_b.png", "acid.png", "nhpi.png",
                                                                f"{product['key']}.png", "cat.png")))
            manifest = json.loads(z.read("manifest.json"))
            self.assertEqual({x["key"]: x["file"] for x in manifest["images"][f"R{rid:06d}"]},
                             {"ester/a b": folder + "ester_a_b.png", "acid": folder + "acid.png",
                              "nhpi": folder + "nhpi.png", product["key"]: folder + f"{product['key']}.png",
                              "cat": folder + "cat.png"})
            (err,) = manifest["image_errors"]
            self.assertEqual((err["id"], err["key"], err["bbox"]), (f"R{rid:06d}", "zn", [700, 700, 800, 750]))
            self.assertEqual(z.getinfo(folder + "cat.png").compress_type, zipfile.ZIP_STORED)
            # 200 dpi of the box: 36 x 18 pt -> 100 x 50 px (+1 where the clip is rounded outwards)
            pix = pymupdf.Pixmap(z.read(folder + "cat.png"))
            self.assertAlmostEqual(pix.width, 100, delta=1)
            self.assertAlmostEqual(pix.height, 50, delta=1)
            box = product["bbox"]
            pix = pymupdf.Pixmap(z.read(folder + f"{product['key']}.png"))
            self.assertAlmostEqual(pix.width, (box[2] - box[0]) * 200 / 72, delta=1.5)

    def test_zip_images_unknown_document(self):
        rid = self.ids[E3]
        self.set_data(rid, lambda d: d["source"].update(doc="si"))  # the seeded paper has no SI
        buf = io.BytesIO()
        export.write_zip(self.conn, [rid], buf, images=True)
        with zipfile.ZipFile(buf) as z:
            manifest = json.loads(z.read("manifest.json"))
            self.assertEqual(manifest["images"], {f"R{rid:06d}": []})
            self.assertTrue(manifest["image_errors"])
            self.assertTrue(all("si" in e["error"] for e in manifest["image_errors"]))

    def test_boxed_items(self):
        data = copy.deepcopy(store.get_reaction(self.conn, self.ids[E1])["data"])
        st = data["steps"][0]
        st["products"][0]["preparation"] = {"from": [{"key": "pre", "page": 1, "bbox": [1, 2, 3, 4]}]}
        st["conditions"][0]["alternatives"] = [{"text": "x", "structure": {"key": None, "page": 1,
                                                                           "bbox": [5, 6, 7, 8]}}]
        data["conditions"] = [{"key": "loose", "structure": {"key": "s", "page": 1, "bbox": [9, 9, 10, 10]}}]
        # Structures the pipeline boxes for a participant's alternatives and a preparation's items.
        st["reactants"][1]["alternatives"] = [{"text": "Ar2Zn", "structure": {"key": "s1", "page": 1,
                                                                              "bbox": [11, 12, 13, 14]}}, "ArZnCl"]
        st["products"][0]["preparation"]["items"] = [{"role": "reagent", "text": "NHPI", "amount": None,
                                                      "structure": {"key": None, "page": 1, "bbox": [15, 16, 17, 18]}}]
        boxed = export._boxed(data)
        keys = [k for k, _, _ in boxed]
        self.assertIn("pre", keys)
        self.assertIn(st["conditions"][0]["key"], keys)  # an unnamed structure is named after its condition
        self.assertIn("s", keys)
        self.assertIn(("s1", 1, [11, 12, 13, 14]), boxed)
        self.assertIn((st["products"][0]["key"], 1, [15, 16, 17, 18]), boxed)  # ... or after its participant
        self.assertEqual(export._file_name("../x"), "x")
        self.assertEqual(export._file_name("3a′"), "3a′")
        self.assertEqual(export._file_name("///"), "item")


if __name__ == "__main__":
    unittest.main()
