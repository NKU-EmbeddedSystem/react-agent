"""No model calls: self-sufficiency, measured values, provenance and import integration."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import consolidate as co
from pipeline.codex import CodexResult
from curator import db, importer, records, export, store
from tests import curator_fixture as fx


def review(raw):
    rid = raw["reaction_id"]
    return {"record_id": rid, "findings": [], "patches": [], "definitions": [], "measurements": [],
            "evidence": [], "category": "core"}


def evidence(raw, **kw):
    return {"id": raw["reaction_id"] + "#e1", "doc": "si", "page": 1, "bbox": None,
            "quote": "NMR integral 0.35", **kw}


class Review(unittest.TestCase):
    def setUp(self):
        self.raw = copy.deepcopy(fx.demo_records()[1][0])
        self.docs = {"main": {}, "si": {}}
        self.sizes = {"main": [[600, 800]], "si": [[595, 842], [595, 842]]}

    def validate(self, r):
        return co.validate_review({"records": [r]}, [self.raw], self.docs, self.sizes)

    def test_bound_variables_pass_without_extra_structure(self):
        self.raw["steps"][0]["reactants"][0]["variables"] = [
            {"name": "R", "value": "H", "origin": "entry"}, {"name": "X", "value": "Br", "origin": "entry"}]
        r = review(self.raw)
        self.assertEqual(self.validate(r), [])
        effective = co.apply_review(self.raw, r)
        self.assertEqual(effective["steps"], self.raw["steps"])
        self.assertEqual(effective["review"]["findings"], [])

    def test_ligand_definition_is_self_contained_and_cross_document(self):
        r = review(self.raw)
        e = evidence(self.raw, quote="L6: explicitly named ligand", bbox=[1, 2, 30, 40])
        r["evidence"] = [e]
        r["definitions"] = [{"field": "/steps/0/conditions/0", "label": "L6", "text": "explicitly named ligand",
                             "evidence_ids": [e["id"]]}]
        self.assertEqual(self.validate(r), [])
        effective = co.apply_review(self.raw, r)
        self.assertEqual(effective["review"]["definitions"][0]["text"], "explicitly named ligand")
        r["evidence"][0]["bbox"] = [1, 2, 900, 40]
        self.assertEqual(self.validate(r), [])  # a box outside the page is dropped, the quote stays
        self.assertIsNone(r["evidence"][0]["bbox"])

    def test_unexplained_reference_is_marked_open(self):
        raw = copy.deepcopy(self.raw)
        raw["notes"] = "The ligand L6 was used; no definition is printed in this entry."
        effective = co.apply_review(raw, review(raw))
        codes = [(f["code"], f["status"]) for f in effective["review"]["findings"]]
        self.assertIn(("reference_unresolved", "open"), codes)

    def test_explained_reference_is_not_marked(self):
        raw = copy.deepcopy(self.raw)
        raw["notes"] = "L6 = dppf; the ligand L6 was used."
        effective = co.apply_review(raw, review(raw))
        self.assertNotIn("reference_unresolved", [f["code"] for f in effective["review"]["findings"]])

    def test_integral_is_not_a_yield_and_original_is_untouched(self):
        path = "/steps/0/products/0/outcomes/0/yield"
        y = self.raw["steps"][0]["products"][0]["outcomes"][0]["yield"]
        y.update(text="0.35", value=None, qualifier=None)
        r = review(self.raw)
        e = evidence(self.raw)
        r["evidence"] = [e]
        r["measurements"] = [{"kind": "nmr_integral", "field": path, "text": "0.35", "evidence_ids": [e["id"]]}]
        self.assertTrue(self.validate(r))  # cannot merely label a wrongly displayed yield
        r["patches"] = [{"path": path + "/text", "value_json": "null", "reason": "积分不能作为产率",
                         "evidence_ids": [e["id"]]}]
        r["findings"] = [{"code": "yield_unspecified", "field": path, "message": "仅有积分，未明确产率",
                          "status": "open", "evidence_ids": [e["id"]]}]
        self.assertEqual(self.validate(r), [])
        effective = co.apply_review(self.raw, r)
        self.assertEqual(y["text"], "0.35")
        self.assertIsNone(effective["steps"][0]["products"][0]["outcomes"][0]["yield"]["text"])
        summary = records.summarize(effective, paper_id="demo")
        self.assertIn("yield_unspecified", summary["flags"])
        self.assertNotIn("0.35%", summary["yields"])
        self.assertEqual(effective["review"]["changes"][0]["old_value"], "0.35")

    def test_reject_unknown_reference_identity_and_bad_scalar(self):
        r = review(self.raw)
        e = evidence(self.raw)
        r["evidence"] = [e]
        for path, value in (("/reaction_id", '"changed"'), ("/steps/0/products/0/bbox", "null"),
                            ("/steps/0/products/0/unknown", '"false"'), ("/steps/0/products/0/text", "5")):
            r["patches"] = [{"path": path, "value_json": value, "reason": "x", "evidence_ids": [e["id"]]}]
            self.assertEqual(self.validate(r), [], path)  # an unapplicable patch is dropped, not applied
            self.assertEqual(r["patches"], [])
        r["patches"] = [{"path": "/steps/0/products/0/text", "value_json": "null",
                         "reason": "x", "evidence_ids": ["missing"]}]
        self.assertEqual(self.validate(r), [])  # an unknown reference is dropped, not applied
        self.assertEqual(r["patches"], [])

    def test_measurement_kind_patch_changes_effective_export_and_preserves_raw(self):
        self.raw['other_outcomes'] = [{'yield': {'text': '75', 'value': 75, 'type': 'conversion'},
                                      'notes': 'Conversion of reactant 1a.',
                                      'measurement_kind': 'recovered_starting_material'}]
        r = review(self.raw)
        e = evidence(self.raw, quote='conv. (%) 75')
        r['evidence'] = [e]
        path = '/other_outcomes/0/measurement_kind'
        r['patches'] = [{'path': path, 'value_json': '"conversion"', 'reason': '明确转化率',
                         'evidence_ids': [e['id']]}]
        r['findings'] = [{'code': 'other_review', 'field': path, 'message': '已修正测量类别',
                          'status': 'resolved', 'evidence_ids': [e['id']]}]
        audit = []
        self.assertEqual(co.validate_review({'records': [r]}, [self.raw], self.docs, self.sizes, audit=audit), [])
        result = co.apply_review(self.raw, r, audit)
        self.assertEqual(result['other_outcomes'][0]['measurement_kind'], 'conversion')
        self.assertEqual(self.raw['other_outcomes'][0]['measurement_kind'], 'recovered_starting_material')
        self.assertEqual(result['review']['patch_results'][0]['status'], 'applied')
        self.assertEqual(result['review']['resolution_checks'][0]['state'], 'verified')
        self.assertIn('转化率', records.summarize(result, paper_id='demo')['yields'])
        self.assertNotIn('回收起始物', records.summarize(result, paper_id='demo')['yields'])

    def test_rejected_patch_reopens_finding_and_keeps_audit(self):
        r = review(self.raw)
        e = evidence(self.raw)
        r['evidence'] = [e]
        r['patches'] = [{'path': '/reaction_id', 'value_json': '"changed"', 'reason': 'x',
                         'evidence_ids': [e['id']]}]
        r['findings'] = [{'code': 'other_review', 'field': '/reaction_id', 'message': '已修正',
                          'status': 'resolved', 'evidence_ids': [e['id']]}]
        audit = []
        self.assertEqual(co.validate_review({'records': [r]}, [self.raw], self.docs, self.sizes, audit=audit), [])
        result = co.apply_review(self.raw, r, audit)
        self.assertEqual(result['review']['findings'][0]['status'], 'open')
        self.assertEqual(result['review']['patch_results'][0]['status'], 'rejected')
        self.assertEqual(result['reaction_id'], self.raw['reaction_id'])

    def test_missing_patch_cannot_claim_field_was_changed(self):
        r = review(self.raw)
        r['findings'] = [{'code': 'other_review', 'field': '/steps/0/products/0/text',
                          'message': '已修正错误文本', 'status': 'resolved', 'evidence_ids': []}]
        result = co.apply_review(self.raw, r)
        self.assertEqual(result['review']['findings'][0]['status'], 'open')
        self.assertEqual(result['review']['resolution_checks'][0]['state'], 'unverified')

    def test_confirmation_with_negated_change_stays_confirmation(self):
        for message in ('现有字段已正确，无需修正。', '不能改为其他条件，保留当前值。',
                        '各时间点产率保留，不以100%转化率或标准1 h反应时间替换。'):
            r = review(self.raw)
            r['findings'] = [{'code': 'other_review', 'field': '/steps/0/products/0/text',
                              'message': message, 'status': 'resolved', 'evidence_ids': []}]
            result = co.apply_review(self.raw, r)
            self.assertEqual(result['review']['findings'][0]['status'], 'resolved')
            self.assertEqual(result['review']['resolution_checks'][0]['state'], 'model_confirmation')

    def test_controlled_label_and_yield_type_patch(self):
        r = review(self.raw)
        e = evidence(self.raw)
        r['evidence'] = [e]
        for path, value in [('/steps/0/products/0/label', '"41"'),
                            ('/steps/0/products/0/outcomes/0/yield/type', '"GC"')]:
            r['patches'] = [{'path': path, 'value_json': value, 'reason': '明确原文', 'evidence_ids': [e['id']]}]
            self.assertEqual(self.validate(r), [])
            self.assertEqual(len(r['patches']), 1)
        r['patches'][0]['value_json'] = '"made_up_type"'
        self.assertEqual(self.validate(r), [])
        self.assertEqual(r['patches'], [])

    def test_recovery_and_explicit_compound_results_are_not_product_yield(self):
        product = self.raw["steps"][0]["products"][0]
        reactant = self.raw["steps"][0]["reactants"][0]
        original = product["outcomes"][0]
        original.update(notes=f"38% recovered starting material {reactant['label']}")
        original["yield"].update(text="38", value=38)
        self.raw["other_outcomes"] = [{"yield": {"text": "43", "value": 43, "type": "conversion"},
                                      "notes": f"Conversion to compound {product['label']}."}]
        effective = co.apply_review(self.raw, review(self.raw))
        self.assertEqual(effective["steps"][0]["products"][0]["outcomes"][0]["yield"]["value"], 43)
        recovery = effective["other_outcomes"][0]
        self.assertEqual(recovery["participant_key"], reactant["key"])
        self.assertEqual(recovery["measurement_kind"], "recovered_starting_material")
        self.assertIn("回收起始物", records.summarize(effective, paper_id="demo")["yields"])
        self.assertEqual(original["yield"]["value"], 38)
        self.assertEqual(len(effective["review"]["changes"]), 2)

    def test_explicit_product_and_remaining_annotations_from_si(self):
        product = self.raw["steps"][0]["products"][0]
        reactant = self.raw["steps"][0]["reactants"][0]
        product["outcomes"] = []
        self.raw["other_outcomes"] = [
            {"yield": {"text": "43", "value": 43, "type": "conversion"},
             "notes": f"Conversion to homocoupling product {product['label']}; explicit annotation."},
            {"yield": {"text": "38", "value": 38, "type": "conversion"},
             "notes": f"Remaining starting material {reactant['label']}; explicit annotation."}]
        effective = co.apply_review(self.raw, review(self.raw))
        self.assertEqual(effective["steps"][0]["products"][0]["outcomes"][0]["yield"]["value"], 43)
        self.assertEqual(effective["other_outcomes"][0]["measurement_kind"], "recovered_starting_material")
        self.assertEqual(self.raw["steps"][0]["products"][0]["outcomes"], [])

    def test_variable_patch_is_text_and_negative_index_is_rejected(self):
        self.raw["steps"][0]["reactants"][0]["variables"] = [{"name": "R", "value": "?"}]
        r = review(self.raw)
        e = evidence(self.raw, quote="R = H")
        r["evidence"] = [e]
        r["patches"] = [{"path": "/steps/0/reactants/0/variables/0/value", "value_json": '\"H\"',
                         "reason": "明确赋值", "evidence_ids": [e["id"]]}]
        self.assertEqual(self.validate(r), [])
        r["patches"][0]["path"] = "/steps/-1/reactants/0/text"
        self.assertEqual(self.validate(r), [])  # an unresolvable pointer is dropped, not applied
        self.assertEqual(r["patches"], [])

    def test_unsupplied_evidence_page_is_dropped(self):
        r = review(self.raw)
        r["evidence"] = [evidence(self.raw)]
        self.assertEqual(co.validate_review({"records": [r]}, [self.raw], self.docs, self.sizes, {("main", 1)}), [])
        self.assertEqual(r["evidence"], [])  # a page the task did not supply cannot be shown

    def test_identical_experiments_merge_but_keep_raw_sources(self):
        a = co.apply_review(self.raw, review(self.raw))
        braw = copy.deepcopy(self.raw)
        braw["reaction_id"] = "si::copy"
        braw["steps"][0]["products"][0]["bbox"] = [1, 2, 30, 40]
        b = co.apply_review(braw, review(braw))
        a["review"]["evidence"] = [evidence(self.raw)]
        answer = {"relations": [{"left": a["reaction_id"], "right": b["reaction_id"], "relation": "same_experiment",
                                 "reason": "明确重复报道", "evidence_ids": [a["review"]["evidence"][0]["id"]]}]}
        self.assertEqual(co.validate_summary(answer, [a, b]), [])
        merged, mapping, _ = co.merge_records([a, b], answer)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]["review"]["raw_records"]), 2)
        self.assertEqual(mapping[b["reaction_id"]], a["reaction_id"])

    def test_summary_never_merges_different_effective_fields(self):
        a = co.apply_review(self.raw, review(self.raw))
        b = copy.deepcopy(a)
        b["reaction_id"] = "second"
        b["steps"][0]["products"][0]["outcomes"][0]["yield"]["value"] = 74
        answer = {"relations": [{"left": a["reaction_id"], "right": "second", "relation": "same_experiment",
                                 "reason": "same label", "evidence_ids": []}]}
        self.assertEqual(co.validate_summary(answer, [a, b]), [])  # no evidence: kept as a candidate, never merged
        result, mapping, relations = co.merge_records([a, b], answer)
        self.assertEqual(len(result), 2)
        self.assertEqual(relations[0]["relation"], "candidate")


class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = fx.build_work(self.root)
        # The production preprocess has tag/text/page images; extend the importer fixture accordingly.
        import pymupdf
        for doc in ("main", "si"):
            manifest_path = self.work / "demo" / doc / "manifest.json"
            manifest = co.read_json(manifest_path)
            pdf = pymupdf.open(co.read_json(self.work / "demo/paper.json")["documents"][doc]["pdf"])
            for i, p in enumerate(manifest["pages"]):
                p["tag"] = f"p{i + 1:03d}"
                for name in ("pages", "text"):
                    (manifest_path.parent / name).mkdir(exist_ok=True)
                pdf[i].get_pixmap().save(manifest_path.parent / "pages" / f"{p['tag']}.png")
                (manifest_path.parent / "text" / f"{p['tag']}.txt").write_text(pdf[i].get_text())
            co.write_json(manifest_path, manifest)
        self.output = self.root / "consolidated"

    @staticmethod
    def fake_codex(prompt, **kw):
        task = co.read_json(kw["out_json"].parent / "task.json")
        if "known_records" in task:
            answer = {"records": [review(r) for r in task["records"]]}
        else:
            answer = {"relations": []}
        return CodexResult(answer, "fake", {"input_tokens": 1, "output_tokens": 1})

    def test_pipeline_cache_raw_preservation_and_curator_import(self):
        before = (self.work / "demo/step2/reactions.json").read_bytes()
        with patch.object(co, "run_codex", side_effect=self.fake_codex) as model:
            report = co.run([("main", self.work)], "demo", self.output, max_calls=2)
            self.assertEqual(model.call_count, 2)
            self.assertEqual(report["records"], 5)
            co.run([("main", self.work)], "demo", self.output, max_calls=2)
            self.assertEqual(model.call_count, 2)
        with patch.object(co, "run_codex", side_effect=AssertionError("republish must not call model")):
            self.assertEqual(co.republish(self.output, "demo")["records"], 5)
        self.assertEqual(before, (self.work / "demo/step2/reactions.json").read_bytes())
        conn = db.connect(self.root / "new.sqlite", create=True)
        self.addCleanup(conn.close)
        imported = importer.import_work(conn, self.output, papers=["demo"], log=lambda _: None)
        self.assertEqual(imported["totals"]["inserted"], 5)
        self.assertEqual(imported["totals"]["validation_errors"], 0)
        row = conn.execute("SELECT id FROM reactions LIMIT 1").fetchone()
        exported = export.export_record(conn, row[0])
        self.assertIn("raw_records", exported["record"]["review"])
        self.assertEqual(exported["record"]["review"]["source_ids"][0].split("::")[0], "main")
        region_path = self.output / "demo/step1/regions.json"
        region_path.write_text(region_path.read_text() + " ")
        tampered = importer.import_work(conn, self.output, papers=["demo"], log=lambda _: None)
        self.assertEqual(tampered["totals"]["refused"], 1)
        co.write_json(self.output / "demo/consolidation.json", {"status": "failed"})
        rejected = importer.import_work(conn, self.output, papers=["demo"], log=lambda _: None)
        self.assertEqual(rejected["totals"]["refused"], 1)

    def test_replay_reads_original_answer_without_model_calls(self):
        with patch.object(co, 'run_codex', side_effect=self.fake_codex):
            co.run([('main', self.work)], 'demo', self.output, max_calls=2)
        directory = self.output / 'demo/review/batch-000'
        saved = co.read_json(directory / 'result.json')['answer']
        raw_answer = copy.deepcopy(saved)
        item = raw_answer['records'][0]
        raw = co.read_json(directory / 'task.json')['records'][0]
        e = evidence(raw, doc='main', quote='product 41', page=1)
        item['evidence'] = [e]
        item['patches'] = [{'path': '/steps/0/products/0/label', 'value_json': '"41"',
                            'reason': '原文编号', 'evidence_ids': [e['id']]}]
        co.write_json(directory / 'answer.json', raw_answer)
        before = (self.output / 'demo/step2/reactions.json').read_bytes()
        destination = self.root / 'replayed'
        with patch.object(co, 'run_codex', side_effect=AssertionError('no model')):
            report = co.replay_retained(self.output, destination, 'demo')
        result = co.read_json(destination / 'demo/step2/reactions.json')['records'][0]
        self.assertEqual(result['steps'][0]['products'][0]['label'], '41')
        self.assertEqual(report['replay_model_calls'], 0)
        self.assertEqual(before, (self.output / 'demo/step2/reactions.json').read_bytes())
        self.assertEqual(co.read_json(directory / 'result.json')['answer'], saved)
        conn = db.connect(self.root / 'replayed.sqlite', create=True)
        self.addCleanup(conn.close)
        imported = importer.import_work(conn, destination, papers=['demo'], log=lambda _: None)
        self.assertEqual(imported['totals']['inserted'], 5)
        row = conn.execute('SELECT id FROM reactions WHERE origin_id = ?', (result['reaction_id'],)).fetchone()
        exported = export.export_record(conn, row['id'])
        self.assertEqual(exported['record']['steps'][0]['products'][0]['label'], '41')
        self.assertEqual(exported['record']['review']['patch_results'][0]['status'], 'applied')
        with self.assertRaisesRegex(ValueError, 'retained raw answers'):
            co.republish(destination, 'demo')
        with self.assertRaisesRegex(ValueError, 'new and separate'):
            co.replay_retained(self.output, destination, 'demo')

    def test_budget_failure_cannot_publish_partial_success(self):
        with patch.object(co, "run_codex", side_effect=self.fake_codex):
            with self.assertRaisesRegex(ValueError, "budget exhausted"):
                co.run([("main", self.work)], "demo", self.output, batch_size=1, max_calls=1)
        self.assertEqual(co.read_json(self.output / "demo/consolidation.json")["status"], "failed")

    def test_output_cannot_overlap_input_and_pdf_identity_is_checked(self):
        with self.assertRaisesRegex(ValueError, "separate"):
            co.run([("main", self.work)], "demo", self.work)
        state = co.read_json(self.work / "demo/paper.json")
        state["documents"]["si"]["sha256"] = "wrong"
        co.write_json(self.work / "demo/paper.json", state)
        with self.assertRaisesRegex(ValueError, "identity"):
            co.load_inputs([("main", self.work)], "demo")

    def test_auxiliary_export_and_finding_filter(self):
        importer.import_work(conn := db.connect(self.root / "flags.sqlite", create=True), self.work, log=lambda _: None)
        self.addCleanup(conn.close)
        r = conn.execute("SELECT id, data FROM reactions LIMIT 1").fetchone()
        data = json.loads(r["data"])
        data["review"] = {"category": "auxiliary", "findings": [{"code": "conditions_unspecified", "status": "open",
                            "message": "未明确条件", "field": "/conditions", "evidence_ids": []}]}
        store.update(conn, r["id"], data=data, base_rev=1, author="test")
        self.assertNotIn(r["id"], export.select_ids(conn))
        self.assertIn(r["id"], export.select_ids(conn, {"flag": "auxiliary"}))
        self.assertIn(r["id"], export.select_ids(conn, ids=[r["id"]]))
        self.assertEqual(store.list_reactions(conn, {"flag": "conditions_unspecified"})["total"], 1)
        self.assertEqual(store.list_reactions(conn, {"scope": "core"})["total"], 4)


if __name__ == "__main__":
    unittest.main()
