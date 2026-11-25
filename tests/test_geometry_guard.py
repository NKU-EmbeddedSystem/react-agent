"""Offline geometry guard regressions, executed on the server only."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pymupdf

from pipeline import codex
from pipeline.steps.s1_locate import scheme_edges
from pipeline.steps.s2_table import _box_edges


class GeometryGuard(unittest.TestCase):
    def test_missing_worker_environment_fails_before_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex.page_environment.cache_clear()
            with self.assertRaisesRegex(codex.CodexError, "interpreter is missing"):
                codex.page_environment(Path(tmp))
            codex.page_environment.cache_clear()

    def test_missing_image_is_rejected(self):
        with self.assertRaisesRegex(codex.CodexError, "attachment is missing"):
            codex._images([Path("/nonexistent/image.png")])

    def test_attachment_audit_preserves_bytes_and_does_not_claim_delivery(self):
        from PIL import Image
        import hashlib, json
        from pipeline.config import CodexConfig
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "picture.png"
            Image.new("RGB", (20, 20), "red").save(path)
            codex._record_attachments(root / "answer.json", [path], CodexConfig())
            audit = json.loads((root / "answer.attachments.json").read_text())
            self.assertFalse(audit["upstream_receipt_verified"])
            self.assertEqual(audit["attachments"][0]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            codex._record_attachments(root / "answer.json", [], CodexConfig())
            history = json.loads((root / "answer.attachments.json").read_text())["calls"]
            self.assertEqual(len(history), 2)
            self.assertEqual(len(history[0]["attachments"]), 1)
            self.assertEqual(history[1]["attachments"], [])

    def test_scheme_cut_at_edge_is_a_blocking_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = pymupdf.open()
            page = pdf.new_page()
            page.draw_line((30, 70), (180, 70), width=3)
            path = Path(tmp) / "doc.pdf"
            pdf.save(path)
            data = {"schemes": [{"doc": "si", "page": 1, "scheme_id": "s1", "bbox": [90, 50, 200, 90]}]}
            self.assertTrue(scheme_edges(data, {"si": {"pdf": str(path)}}))
            data["schemes"][0]["bbox"] = [20, 50, 200, 90]
            self.assertEqual(scheme_edges(data, {"si": {"pdf": str(path)}}), [])

    def test_full_page_context_survives_a_bad_locate_crop(self):
        from pipeline.steps.s2_extract import _Job
        import threading
        pdf = pymupdf.open()
        page = pdf.new_page()
        page.draw_line((20, 70), (180, 70), width=3)
        job = SimpleNamespace(pdf_lock=threading.Lock(), _page=lambda doc, n: page)
        with tempfile.TemporaryDirectory() as tmp:
            images, note = _Job._block_images(job, "si", {"page": 1, "bbox": [90, 50, 200, 90]},
                                             None, Path(tmp), "table")
            self.assertEqual(len(images), 2)
            self.assertTrue(images[-1].name.endswith("__page.png"))
            self.assertIn("complete source page", note)

    def test_structure_errors_cannot_be_softened_into_success(self):
        from pipeline.steps.s2_extract import _Job
        meta = {"status": "failed", "errors": ["box edge: participant 1 cuts drawing", "uncovered area on page 1"],
                "warnings": []}
        _Job._soften_coverage(meta)
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(len(meta["errors"]), 2)

    def test_geometry_repair_can_only_change_existing_boxes(self):
        from pipeline.geometry_repair import apply
        inv = {"template": {"participants": [{"key": "1", "page": 1, "bbox": [1, 2, 3, 4]}],
                             "structures": []}, "entries": [], "notes": "chemical values preserved"}
        fixed = apply(inv, {"boxes": [{"id": "template/participants/0", "bbox": [10, 20, 30, 40]}]},
                      {1: [595, 842]})
        self.assertEqual(fixed["template"]["participants"][0]["bbox"], [10, 20, 30, 40])
        self.assertEqual(inv["template"]["participants"][0]["bbox"], [1, 2, 3, 4])
        self.assertEqual(fixed["notes"], inv["notes"])
        with self.assertRaises(ValueError):
            apply(inv, {"boxes": [], "notes": "overwrite"}, {1: [595, 842]})
        with self.assertRaises(ValueError):
            apply(inv, {"boxes": []}, {1: [595, 842]})
        with self.assertRaises(ValueError):
            apply(inv, {"boxes": [{"id": "template/participants/0", "bbox": [-1, 0, 30, 40]}]}, {1: [595, 842]})

    def test_geometry_audit_lists_all_structures_and_requires_visual_review(self):
        import json
        from pipeline.geometry_audit import run
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = pymupdf.open()
            page = pdf.new_page()
            page.draw_rect(pymupdf.Rect(30, 40, 80, 75), width=1)
            pdf.save(root / "source.pdf")
            (root / "si").mkdir()
            (root / "si/manifest.json").write_text(json.dumps({"pdf": str(root / "source.pdf")}))
            block = root / "step2/blocks/table"
            block.mkdir(parents=True)
            (block / "view.json").write_text(json.dumps({"region": {"doc": "si"}}))
            (block / "inventory.json").write_text(json.dumps({
                "template": {"participants": [{"key": "1", "page": 1, "bbox": [20, 30, 90, 85]}], "structures": []},
                "entries": []}))
            output = run(root, "table")
            report = json.loads((output / "report.json").read_text())
            self.assertTrue(report["visual_review_required"])
            self.assertTrue(report["all_edges_clear"])
            self.assertEqual(len(report["structures"]), 1)
            self.assertTrue((output / "contact-sheet.png").is_file())

    def test_participant_edge_detection(self):
        pdf = pymupdf.open()
        page = pdf.new_page()
        page.draw_line((30, 70), (180, 70), width=3)
        job = SimpleNamespace(_page=lambda doc, n: page, _page_sizes=lambda doc: {1: [595, 842]})
        inv = {"template": {"participants": [{"key": "1", "page": 1, "bbox": [90, 50, 200, 90]}],
                            "structures": []}, "entries": []}
        self.assertEqual(len(_box_edges(job, "si", inv)), 1)

    def test_tight_box_gets_a_white_margin_from_trim(self):
        from pipeline.pagetools.trim import ink_edges, trim_bbox
        pdf = pymupdf.open()
        page = pdf.new_page()
        page.draw_line((30, 70), (180, 70), width=3)
        tight = [30, 68.5, 180, 71.5]  # the line touches the top and bottom edge
        self.assertTrue(ink_edges(page, tight))
        padded = trim_bbox(page, tight)
        self.assertLess(padded.y0, tight[1])
        self.assertGreater(padded.y1, tight[3])
        self.assertEqual(ink_edges(page, list(padded)), [])
        # The pad is not a licence to cross the page edge.
        self.assertGreaterEqual(padded.x0, 0)
        self.assertLessEqual(padded.x1, page.rect.width)

    def test_geometry_repair_relocates_only_the_failed_targets(self):
        from pipeline.geometry_repair import apply
        inv = {"template": {"participants": [{"key": "1", "page": 1, "bbox": [1, 2, 3, 4]},
                                             {"key": "2", "page": 1, "bbox": [5, 6, 7, 8]}],
                             "structures": []}, "entries": []}
        fixed = apply(inv, {"boxes": [{"id": "template/participants/1", "bbox": [10, 20, 30, 40],
                                       "page": 2}]}, {1: [595, 842], 2: [595, 842]},
                      only_ids=["template/participants/1"])
        self.assertEqual(fixed["template"]["participants"][0]["bbox"], [1, 2, 3, 4])
        self.assertEqual(fixed["template"]["participants"][1]["bbox"], [10, 20, 30, 40])
        self.assertEqual(fixed["template"]["participants"][1]["page"], 2)
        self.assertEqual(inv["template"]["participants"][1]["page"], 1)
        with self.assertRaises(ValueError):
            apply(inv, {"boxes": [{"id": "template/participants/0", "bbox": [10, 20, 30, 40]}]},
                  {1: [595, 842]}, only_ids=["template/participants/1"])

    def test_a4_page_grid_is_fine_enough(self):
        from pipeline.pagetools.grid import nice_step
        self.assertEqual(nice_step(842), 50)
        self.assertEqual(nice_step(297), 20)
        self.assertEqual(nice_step(60), 5)

    def test_tight_boxes_are_settled_by_widening(self):
        from pipeline.steps.s2_table import _settle_box_edges
        pdf = pymupdf.open()
        page = pdf.new_page()
        page.draw_line((30, 70), (180, 70), width=3)
        job = SimpleNamespace(_page=lambda doc, n: page, _page_sizes=lambda doc: {1: [595, 842]})
        inv = {"template": {"participants": [{"key": "1", "page": 1, "bbox": [30, 68.5, 180, 71.5]}],
                            "structures": []}, "entries": []}
        errors, warnings = _settle_box_edges(job, "si", inv)
        self.assertEqual(errors, [])
        box = inv["template"]["participants"][0]["bbox"]
        self.assertLess(box[1], 68.5)
        self.assertGreater(box[3], 71.5)
        self.assertTrue(warnings)

    def test_a_real_cut_still_fails_after_bounded_widening(self):
        from pipeline.steps.s2_table import _settle_box_edges
        pdf = pymupdf.open()
        page = pdf.new_page()
        page.draw_rect(pymupdf.Rect(30, 60, 90, 220), fill=(0, 0, 0))
        job = SimpleNamespace(_page=lambda doc, n: page, _page_sizes=lambda doc: {1: [595, 842]})
        inv = {"template": {"participants": [{"key": "1", "page": 1, "bbox": [30, 100, 90, 150]}],
                            "structures": []}, "entries": []}
        errors, _ = _settle_box_edges(job, "si", inv)
        self.assertEqual(len(errors), 1)
        self.assertIn("box edge", errors[0])

    def test_continuation_pages_are_attached_for_a_multipage_block(self):
        from pipeline.steps.s2_extract import _Job
        import threading
        pdf = pymupdf.open()
        pdf.new_page()
        pdf.new_page()
        pages = [pdf[0], pdf[1]]
        job = SimpleNamespace(pdf_lock=threading.Lock(), _page=lambda doc, n: pages[n - 1])
        with tempfile.TemporaryDirectory() as tmp:
            images, note = _Job._block_images(
                job, "si",
                {"page": 1, "bbox": [50, 50, 300, 300],
                 "entries_first_page": 1, "entries_last_page": 2},
                None, Path(tmp), "table")
            names = [path.name for path in images]
            self.assertIn("table__continued-2.png", names)
            self.assertTrue(images[-1].name.endswith("__page.png"))
            self.assertIn("page 2", note)

    def test_failed_block_reader_retries_are_bounded_and_configurable(self):
        from pipeline.config import ExtractConfig
        self.assertEqual(ExtractConfig().retries, 2)
        self.assertEqual(ExtractConfig(retries=0).to_dict()["retries"], 0)
        self.assertEqual(ExtractConfig(retries=3).to_dict()["retries"], 3)

    def test_a_table_rule_is_not_an_uncovered_area(self):
        import pymupdf
        from pipeline.pagetools.trim import uncovered_blobs
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=300)
        page.draw_rect(pymupdf.Rect(20, 20, 80, 80), fill=(0, 0, 0))
        page.draw_line(pymupdf.Point(100, 120), pymupdf.Point(160, 120), color=(0, 0, 0), width=2)
        self.assertEqual(uncovered_blobs(page, [0, 0, 300, 300], [[15, 15, 85, 85]]), [])

    def test_edge_severity_tells_a_cut_from_a_neighbour(self):
        import pymupdf
        from pipeline.pagetools.trim import edge_severity
        doc = pymupdf.open()
        page = doc.new_page(width=200, height=200)
        page.draw_rect(pymupdf.Rect(20, 20, 150, 100), fill=(0, 0, 0))
        page.draw_rect(pymupdf.Rect(150, 20, 180, 100), fill=(0, 0, 0))
        self.assertEqual(edge_severity(page, [20, 20, 150, 100]).get("right"), "cut")
        page2 = doc.new_page(width=200, height=200)
        page2.draw_rect(pymupdf.Rect(20, 20, 80, 100), fill=(0, 0, 0))
        page2.draw_line(pymupdf.Point(120, 20), pymupdf.Point(120, 100), color=(0, 0, 0), width=1)
        self.assertEqual(edge_severity(page2, [20, 20, 120, 100]).get("right"), "touch")

    def test_block_level_warnings_are_not_repeated_in_every_record(self):
        from pipeline.steps.s2_extract import _record_warnings
        warnings = ["box edge: entries[9] cell 'product': ink still runs to the bottom edge",
                    "cannot be derived from this row: product not given",
                    "outcomes[3]: '100' has no product_key, but the reaction has several products"]
        self.assertEqual(_record_warnings(warnings),
                         ["outcomes[3]: '100' has no product_key, but the reaction has several products"])


if __name__ == "__main__":
    unittest.main()
