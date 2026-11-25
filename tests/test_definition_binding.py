"""核查结构显式绑定，含跨文档显示数据、导出与保守跳过。"""
import copy
import unittest
from pipeline.consolidate import materialize_condition_definitions
from curator import records, export


class Binding(unittest.TestCase):
    def raw(self):
        return {'source': {'doc': 'si'}, 'steps': [{'conditions': [
            {'key': 'ligand', 'role': 'ligand', 'text': 'L4', 'amount': '12 mol%', 'structure': None}]}],
            'review': {'definitions': [{'field': '/steps/0/conditions/0', 'label': 'L4',
                                       'text': 'defined ligand', 'evidence_ids': ['r#L4']}],
                       'evidence': [{'id': 'r#L4', 'doc': 'main', 'page': 2, 'bbox': [10, 20, 50, 60]}],
                       'findings': [{'field': '/steps/0/conditions/0', 'code': 'reference_unresolved',
                                     'status': 'resolved'}]}}

    def test_exact_unique_definition_is_persisted_without_changing_label_or_amount(self):
        raw = self.raw()
        rec, changes, decisions = materialize_condition_definitions(raw)
        c = rec['steps'][0]['conditions'][0]
        self.assertEqual(c['text'], 'L4')
        self.assertEqual(c['amount'], '12 mol%')
        self.assertEqual(c['structure']['doc'], 'main')
        self.assertEqual(c['structure']['bbox'], [10, 20, 50, 60])
        self.assertEqual(c['definition']['text'], 'defined ligand')
        self.assertIsNone(raw['steps'][0]['conditions'][0]['structure'])
        self.assertEqual(len(changes), 2)
        self.assertEqual(decisions[0]['status'], 'applied')
        again, changes, _ = materialize_condition_definitions(rec)
        self.assertEqual(again, rec)
        self.assertEqual(changes, [])
        self.assertEqual(export._boxed(rec, with_doc=True), [('main', 'ligand', 2, [10, 20, 50, 60])])

    def test_mismatch_open_or_multiple_definitions_do_not_bind(self):
        for mode in ('label', 'open', 'duplicate'):
            r = self.raw()
            if mode == 'label': r['steps'][0]['conditions'][0]['text'] = 'L5'
            if mode == 'open': r['review']['findings'][0]['status'] = 'open'
            if mode == 'duplicate': r['review']['definitions'] *= 2
            rec, changes, _ = materialize_condition_definitions(r)
            self.assertEqual(changes, [])
            self.assertIsNone(rec['steps'][0]['conditions'][0]['structure'])

    def test_text_pointer_definition_without_redundant_resolved_finding(self):
        r = self.raw()
        r['review']['definitions'][0]['field'] += '/text'
        r['review']['findings'] = [{'field': '/conditions', 'code': 'reference_unresolved',
                                     'status': 'open', 'message': 'unrelated L1'}]
        rec, changes, _ = materialize_condition_definitions(r)
        self.assertEqual(rec['steps'][0]['conditions'][0]['structure']['label'], 'L4')
        self.assertEqual(changes[0]['path'], '/steps/0/conditions/0/definition')
        self.assertEqual(rec['review']['findings'], r['review']['findings'])

    def test_equivalent_pointers_are_duplicates_and_missing_evidence_is_rejected(self):
        r = self.raw()
        other = copy.deepcopy(r['review']['definitions'][0])
        other['field'] += '/text'
        r['review']['definitions'].append(other)
        self.assertEqual(materialize_condition_definitions(r)[1], [])
        r = self.raw()
        r['review']['definitions'][0]['evidence_ids'] = ['missing']
        self.assertEqual(materialize_condition_definitions(r)[1], [])

    def test_multiple_boxes_only_add_text_and_existing_structure_is_preserved(self):
        r = self.raw()
        r['review']['evidence'].append({'id': 'r#other', 'doc': 'main', 'page': 1, 'bbox': [1, 2, 3, 4]})
        r['review']['definitions'][0]['evidence_ids'].append('r#other')
        rec, _, _ = materialize_condition_definitions(r)
        self.assertIsNone(rec['steps'][0]['conditions'][0]['structure'])
        self.assertIn('definition', rec['steps'][0]['conditions'][0])
        r = self.raw()
        original = {'page': 1, 'bbox': [2, 3, 4, 5]}
        r['steps'][0]['conditions'][0]['structure'] = original
        rec, _, _ = materialize_condition_definitions(r)
        self.assertEqual(rec['steps'][0]['conditions'][0]['structure'], original)

    def test_cross_document_validation_uses_structure_document(self):
        docs = {'main': {'page_count': 2, 'pages': [[100, 100], [100, 100]]},
                'si': {'page_count': 1, 'pages': [[10, 10]]}}
        check = records._Check(docs, 'si')
        check.structure(['structure'], {'doc': 'main', 'page': 2, 'bbox': [10, 20, 50, 60]})
        self.assertEqual(check.errors, [])
        check.structure(['structure'], {'doc': 'unknown', 'page': 2, 'bbox': [10, 20, 50, 60]})
        self.assertTrue(check.errors)


if __name__ == '__main__':
    unittest.main()
