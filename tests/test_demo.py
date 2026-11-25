"""The public demo builds a work dir that the curator imports without warnings."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from curator import db, importer
from demo import make


class Demo(unittest.TestCase):
    def test_builds_an_importable_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make.build(Path(tmp) / "demo", quiet=True)
            self.assertTrue((root / "Data" / "1" / make.MAIN_NAME).is_file())
            self.assertTrue((root / "Data" / "1" / make.SI_NAME).is_file())

            conn = db.connect(root / "db" / "curator.sqlite", create=True)
            try:
                report = importer.import_work(conn, root / "work", log=lambda *a: None)
                paper = report["papers"]["1"]
                self.assertEqual((paper["outcome"], paper["counts"]["inserted"]), ("imported", 5))
                self.assertEqual((paper["counts"]["validation_errors"], paper["counts"]["validation_warnings"]),
                                 (0, 0))
                self.assertEqual(conn.execute("SELECT count(*) FROM reactions").fetchone()[0], 5)
                self.assertEqual(conn.execute("SELECT count(*) FROM blocks").fetchone()[0], 1)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
