import copy
import json
import random
import unittest

from curator import records
from curator.records import KNOWN, RECORD_KEYS, TEMPLATES, normalize, skeleton, summarize, validate
from tests.curator_fixture import demo_records, second_record
from tests.test_extract_records import demo_views

PAGES = [[600.0, 800.0, 0, [1, 0, 0, -1, 0, 800]]]
DOCS = {"main": {"page_count": 1, "pages": PAGES},
        "si": {"page_count": 40, "pages": [[595.0, 842.0, 0, [1, 0, 0, -1, 0, 842]]] * 40}}


def rec(i=1):
    """A demo record: 0 two esters [Fe], 1 single step, 2 'A or B' catalyst, 3 sequence [Ni], 4 undecided."""
    return copy.deepcopy(demo_records()[i][0])


def has(messages, *parts):
    return any(all(p in m for p in parts) for m in messages)


class Normalize(unittest.TestCase):
    def test_crops_go_at_any_depth(self):
        raw = demo_views()[0]["entries"][0]["reactions"][0]["record"]
        self.assertIn('"crop"', json.dumps(raw))
        out = normalize(raw)
        self.assertNotIn('"crop"', json.dumps(out))
        self.assertIn('"crop"', json.dumps(raw))  # the input is left alone
        self.assertEqual(normalize(out), out)
        # Nothing else changes.
        out["steps"][0]["reactants"][0]["preparation"]["items"][0]["structure"]["crop"] = "x.png"
        self.assertEqual(set(normalize(out)["steps"][0]["reactants"][0]["preparation"]["items"][0]["structure"]),
                         {"key", "label", "text", "page", "bbox"})
        self.assertEqual(list(out), list(RECORD_KEYS))


class Summarize(unittest.TestCase):
    def test_columns(self):
        s = summarize(rec(1), paper_id="7", pipeline_info={"errors": [], "warnings": ["w"]})
        self.assertEqual(set(s), {"label", "kind", "figure", "doc", "page", "entry_id", "reactants", "products",
                                  "conditions", "yields", "flags", "thumb", "search", "sort_key"})
        self.assertEqual((s["label"], s["kind"], s["figure"], s["doc"], s["page"], s["entry_id"]),
                         ("3fa", "substrate_scope", "Scheme 2", "main", 1, "e001"))
        self.assertEqual((s["reactants"], s["products"]), ("1 + 2", "3fa"))
        self.assertEqual(s["conditions"], "Fe(BF-Phos)Cl2 0.5 mol%; LiCl 1.0 equiv; THF; 22-25 °C; 24 h")
        self.assertEqual(s["yields"], "3fa 42%")
        self.assertEqual(s["flags"], "warned")
        self.assertEqual(s["thumb"], {"doc": "main", "page": 1, "bbox": [55, 102, 145, 140]})
        self.assertIn("fe(bf-phos)cl2", s["search"])
        self.assertIn("main:scheme2/1/e001-3", s["search"])
        self.assertEqual(s["search"], s["search"].casefold())
        self.assertEqual(s["sort_key"], "000007|0|00001|main:scheme000002|000001|e000001|e000001-000003")

    def test_condition_amount_that_repeats_the_text(self):
        # Equation blocks write a temperature or time as text and amount alike (paper 1, Scheme 4).
        r = rec(1)
        conds = r["steps"][0]["conditions"]
        temp = next(c for c in conds if c["role"] == "temperature")
        temp["amount"] = temp["text"]
        self.assertEqual(summarize(r, paper_id="x")["conditions"],
                         "Fe(BF-Phos)Cl2 0.5 mol%; LiCl 1.0 equiv; THF; 22-25 °C; 24 h")
        temp["amount"] = " 22-25 °C "  # the same once trimmed
        self.assertIn("; 22-25 °C; ", summarize(r, paper_id="x")["conditions"])

    def test_flags(self):
        self.assertEqual(summarize(rec(0), paper_id="x")["flags"], "inferred unresolved")
        self.assertEqual(summarize(rec(2), paper_id="x")["flags"], "unresolved")  # condition 'A or B'
        self.assertEqual(summarize(rec(3), paper_id="x")["flags"], "inferred")
        self.assertEqual(summarize(rec(4), paper_id="x", pipeline_info={"errors": ["e"]})["flags"],
                         "unresolved issues warned")  # undecided_with

    def test_steps_and_other_outcomes(self):
        s = summarize(rec(4), paper_id="x")
        # The first step's reactants, the last step's products.
        self.assertEqual((s["reactants"], s["products"]), ("acid + HATU", "3"))
        r = rec(1)
        r["other_outcomes"] = [{"yield": {"text": "75", "value": 75, "type": "conversion"}, "participant_key": None},
                               {"yield": {"text": "10%", "value": 10, "type": "isolated"}, "participant_key": "1"}]
        r["steps"][0]["products"][0]["outcomes"].append({"yield": {"text": None, "value": None}})
        self.assertEqual(summarize(r, paper_id="x")["yields"], "3fa 42%; 75%（转化率）; 1 10%")
        r["steps"].append(copy.deepcopy(r["steps"][0]))  # alternative steps with the same product and value
        self.assertEqual(summarize(r, paper_id="x")["yields"], "3fa 42%; 75%（转化率）; 1 10%")

    def test_thumb_prefers_a_product_of_the_last_step(self):
        r = rec(4)
        self.assertEqual(summarize(r, paper_id="x")["thumb"]["bbox"], [55, 102, 145, 140])
        r["steps"][-1]["products"][0]["bbox"] = None
        # Else the first participant with a box.
        self.assertEqual(summarize(r, paper_id="x")["thumb"]["bbox"], [50, 55, 80, 85])
        for p in records.participants(r):
            p["bbox"] = None
        self.assertIsNone(summarize(r, paper_id="x")["thumb"])

    def test_sort_key_follows_print_order(self):
        def key(paper, doc, page, region, entry, rid):
            r = rec(1)
            r["source"].update(doc=doc, page=page, region_id=region, entry_id=entry, reaction_id=rid)
            return summarize(r, paper_id=paper)["sort_key"]
        ordered = [key("2", "main", 1, "main:scheme2", "e001", "e001-1"),
                   key("2", "main", 1, "main:scheme2", "e001", "e001-2"),
                   key("2", "main", 1, "main:scheme2", "e001", "e001-10"),
                   key("2", "main", 1, "main:scheme2", "e001", None),  # a copy: after its entry's own
                   key("2", "main", 1, "main:scheme2", None, None),    # made by hand without an entry
                   key("2", "main", 3, "main:scheme10", "e001", "e001-1"),
                   key("2", "main", None, "main:x", "e001", "e001-1"),
                   key("2", "si", 1, "si:table1", "e001", "e001-1"),
                   key("10", "main", 1, "main:scheme1", "e001", "e001-1"),
                   key("demo", "main", 1, "main:scheme1", "e001", "e001-1")]
        self.assertEqual(sorted(ordered), ordered)

    def test_search_keeps_primes_and_chinese(self):
        s = summarize(second_record(), paper_id="12")["search"]
        self.assertIn("3a′", s)
        self.assertIn("产率由核磁测定", s)

    def test_any_input(self):
        for data in (None, {}, [], "x", {"steps": "x", "source": [], "issues": "boom"},
                     {"steps": [None, {"reactants": [1, None], "products": {"a": 1}}], "label": 5}):
            s = summarize(data, paper_id="1")
            self.assertEqual(s["thumb"], None)
            self.assertIsInstance(s["sort_key"], str)


class Validate(unittest.TestCase):
    def test_demo_records_are_valid(self):
        for r, _ in demo_records():
            self.assertEqual(validate(r, DOCS), ([], []), r["reaction_id"])
        self.assertEqual(validate(second_record(), DOCS), ([], []))

    def test_structure_errors(self):
        self.assertEqual(validate([], DOCS)[0], ["记录应为一个 JSON 对象"])
        r = rec(1)
        del r["issues"]
        r["results"] = "42%"
        r["label"] = 3
        r["conditions_given"] = "yes"
        errors, _ = validate(r, DOCS)
        self.assertEqual(errors, ["issues: 缺少字段", "results: 应为列表", "label: 应为字符串或 null",
                                  "conditions_given: 应为 true 或 false"])
        r = rec(1)
        r["steps"] = []
        self.assertEqual(validate(r, DOCS)[0], ["steps: 至少需要一个步骤"])
        r["steps"] = [{"step": 1, "reactants": [], "products": None}]
        self.assertEqual(validate(r, DOCS)[0], ["steps[0].products: 应为列表", "steps[0].conditions: 应为列表"])
        r = rec(1)
        r["source"] = "main"
        self.assertEqual(validate(r, DOCS)[0], ["source: 应为对象"])

    def test_item_errors(self):
        r = rec(1)
        st = r["steps"][0]
        st["reactants"][0]["key"] = ""
        del st["reactants"][1]["role"]
        st["conditions"][1]["text"] = None
        st["conditions"].append(dict(st["conditions"][0]))
        out = st["products"][0]["outcomes"][0]
        out["yield"]["value"] = "42"
        st["products"].append({**st["products"][0], "key": "4", "outcomes": [{"yield": "42%"}]})
        errors, _ = validate(r, DOCS)
        self.assertEqual(errors, [
            "steps[0].reactants[0].key: 缺少 key（应为非空字符串）",
            "steps[0].reactants[2].role: 缺少 role（应为字符串）",
            "steps[0].products[3].outcomes[0].yield.value: 应为数字或 null",
            "steps[0].products[4].outcomes[0].yield: 应为对象",
            "steps[0].conditions[licl].text: 缺少 text（应为字符串）",
            "steps[0].conditions: key 'cat' 重复"])

    def test_pages_and_boxes(self):
        r = rec(1)
        r["source"]["doc"] = "si2"
        self.assertEqual(validate(r, DOCS)[0], ["source.doc: 文档 'si2' 不是这篇文献的文档（main、si）"])
        r = rec(1)
        p = r["steps"][0]["reactants"]
        p[0]["page"] = 2
        p[1]["bbox"] = [120, 55, 160]
        r["steps"][0]["products"][0]["bbox"] = [145, 102, 55, 140]
        r["steps"][0]["conditions"][0]["structure"]["bbox"] = [50, 600, 110, 805]
        r["source"]["page"] = None
        errors, _ = validate(r, DOCS)
        self.assertEqual(errors, [
            "source.entry_bbox: 有框但没有页码",
            "steps[0].reactants[1].page: 页码 2 超出文档 main 的范围（1–1）",
            "steps[0].reactants[2].bbox: 框应为 4 个有限数字 [x0, y0, x1, y1]",
            "steps[0].products[3].bbox: 框应满足 x0 < x1 且 y0 < y1",
            "steps[0].conditions[cat].structure.bbox: 框超出页面范围（页面 600 × 800 pt）"])
        # Up to 2 pt over the edge is fine (boxes trimmed to the ink sit on it).
        r = rec(1)
        r["steps"][0]["products"][0]["bbox"] = [-1.5, 102, 601.9, 140]
        self.assertEqual(validate(r, DOCS), ([], []))
        r["steps"][0]["products"][0]["bbox"] = [0, 102, float("nan"), 140]
        self.assertEqual(len(validate(r, DOCS)[0]), 1)
        # A box on an SI page is checked against that page: the reaction's document is the SI.
        r = rec(1)
        r["source"].update(doc="si", page=12)
        self.assertEqual(validate(r, DOCS), ([], []))
        r["steps"][0]["products"][0].update(page=41)
        self.assertEqual(validate(r, DOCS)[0], ["steps[0].products[3].page: 页码 41 超出文档 si 的范围（1–40）"])

    def test_preparation_boxes(self):
        r = rec(0)
        prep = r["steps"][0]["reactants"][0]["preparation"]
        prep["from"][0]["bbox"] = [50, 55, 80, 900]
        prep["items"][0]["structure"]["page"] = 0
        errors, _ = validate(r, DOCS)
        self.assertEqual(errors, ["steps[0].reactants[ester-a].preparation.from[acid].bbox: 框超出页面范围（页面 600 × 800 pt）",
                                  "steps[0].reactants[ester-a].preparation.items[0].structure.page: 页码应为正整数"])

    def test_warnings(self):
        r = rec(1)
        st = r["steps"][0]
        st["reactants"][0]["role"] = "solvent"
        st["reactants"][1]["source"] = "drawn"
        st["reactants"][1]["bbox"] = None
        st["reactants"][1]["page"] = None
        st["reactants"][1]["stated_at"] = {"doc": "si", "page": 99}
        st["conditions"][0]["amount_stated_at"] = {"doc": "si3", "page": 1}
        st["conditions"][1]["origin"] = "guess"
        st["products"][0]["outcomes"][0]["yield"]["type"] = "HPLC-MS"
        r["unresolved"] = ["cat", "nothing"]
        r["other_outcomes"] = [{"yield": {"text": "5%", "value": 5, "type": "NMR"}, "participant_key": "9"}]
        r["related"] = [{"doc": "si", "page": 31, "text": "", "about": ""}, {"doc": "si", "page": "x"}]
        r["kind"] = "survey"
        errors, warnings = validate(r, DOCS)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [
            "kind: 'survey' 不是已知的取值",
            "steps[0].reactants[1].role: 'solvent' 不是已知的取值",
            "steps[0].reactants[2]: 标为画出的结构（drawn），但没有框",
            "steps[0].reactants[2].stated_at.page: 页码 99 超出文档 si 的范围（1–40）",
            "steps[0].products[3].outcomes[0].yield.type: 'HPLC-MS' 不是已知的取值",
            "steps[0].conditions[cat].amount_stated_at.doc: 文档 'si3' 没有导入",
            "steps[0].conditions[licl].origin: 'guess' 不是已知的来源",
            "other_outcomes[0].participant_key: '9' 不是任何参与物的 key",
            "unresolved[1]: 'nothing' 不是任何参与物或条件的 key",
            "related[1].page: 页码应为正整数"])
        # NMR, the pipeline's own word, is known; a missing SI only warns.
        self.assertEqual(validate(r, {"main": DOCS["main"]})[0], [])
        self.assertTrue(has(validate(r, {"main": DOCS["main"]})[1], "related[0].doc", "没有导入"))

    def test_errors_of_the_base_do_not_block(self):
        base = rec(1)
        base["steps"][0]["products"][0]["bbox"] = [55, 102, 145, 900]
        edited = copy.deepcopy(base)
        edited["notes"] = "checked"
        errors, warnings = validate(edited, DOCS, base=base)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, ["steps[0].products[3].bbox: 框超出页面范围（页面 600 × 800 pt）（原有问题）"])
        edited["steps"][0]["reactants"][0]["bbox"] = [50, 55, 100, 850]
        errors, warnings = validate(edited, DOCS, base=base)
        self.assertEqual(errors, ["steps[0].reactants[1].bbox: 框超出页面范围（页面 600 × 800 pt）"])
        self.assertEqual(len(warnings), 1)

    def test_errors_of_the_base_that_moved_do_not_block(self):
        # rec(4) has two steps; a box the pipeline left off the page sits in the second one.
        base = rec(4)
        base["steps"][1]["products"][-1]["bbox"] = [55, 102, 145, 900]
        self.assertEqual(validate(base, DOCS)[0], ["steps[1].products[product].bbox: 框超出页面范围（页面 600 × 800 pt）"])
        edited = copy.deepcopy(base)
        del edited["steps"][0]  # the first step deleted: the same box is now steps[0]
        errors, warnings = validate(edited, DOCS, base=base)
        self.assertEqual(errors, [])
        self.assertIn("steps[0].products[product].bbox: 框超出页面范围（页面 600 × 800 pt）（原有问题）", warnings)
        edited = copy.deepcopy(base)
        edited["steps"][1]["products"][-1]["key"] = "P"  # its key renamed
        self.assertEqual(validate(edited, DOCS, base=base)[0], [])
        # The same message for a box the edit put there blocks the save.
        edited["steps"][1]["reactants"][0]["bbox"] = [90, 55, 130, 900]
        self.assertEqual(validate(edited, DOCS, base=base)[0],
                         ["steps[1].reactants[ester-a].bbox: 框超出页面范围（页面 600 × 800 pt）"])
        # ... as does the base's bad box copied onto another participant of the same step.
        edited = copy.deepcopy(base)
        edited["steps"][1]["reactants"][0]["bbox"] = [55, 102, 145, 900]
        self.assertEqual(len(validate(edited, DOCS, base=base)[0]), 1)

    def test_numbers_too_large_for_a_float(self):
        # json.loads reads a 401-digit literal as an int: reported, not an OverflowError.
        r = rec(1)
        r["steps"][0]["products"][0]["bbox"] = [0, 0, 10 ** 400, 5]
        r["steps"][0]["products"][0]["outcomes"][0]["yield"]["value"] = 10 ** 400
        errors, _ = validate(r, DOCS)
        self.assertEqual(errors, ["steps[0].products[3].bbox: 框应为 4 个有限数字 [x0, y0, x1, y1]",
                                  "steps[0].products[3].outcomes[0].yield.value: 应为数字或 null"])
        self.assertEqual(summarize(r, paper_id="1")["thumb"]["bbox"], [50, 55, 100, 85])  # the next one with a box

    def test_choice_stated_at(self):
        r = rec(0)
        r["steps"][0]["reactants"][0]["choice"]["stated_at"] = {"doc": "main", "page": 999}
        self.assertEqual(validate(r, DOCS), ([], ["steps[0].reactants[ester-a].choice.stated_at.page: "
                                                  "页码 999 超出文档 main 的范围（1–1）"]))

    def test_never_raises(self):
        garbage = [None, 0, -1, 1.5, float("inf"), True, "x", "", [], [1, None], {}, {"key": ["k"]},
                   {"doc": ["main"], "page": {"a": 1}}, [[1, 2, 3, 4]]]
        rnd = random.Random(7)

        def nodes(node, path=()):
            yield path
            if isinstance(node, dict):
                for k, v in node.items():
                    yield from nodes(v, path + (k,))
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    yield from nodes(v, path + (i,))

        for base_rec, _ in demo_records():
            paths = [p for p in nodes(base_rec) if p]
            for _ in range(150):
                r = copy.deepcopy(base_rec)
                for path in rnd.sample(paths, 3):
                    try:
                        target = r
                        for seg in path[:-1]:
                            target = target[seg]
                        target[path[-1]] = copy.deepcopy(rnd.choice(garbage))
                    except (KeyError, IndexError, TypeError):
                        pass
                errors, warnings = validate(r, DOCS, base=base_rec)
                self.assertTrue(all(isinstance(m, str) for m in errors + warnings))
                summarize(r, paper_id="1", pipeline_info=rnd.choice(garbage))
        for docs in (None, {}, {"main": None}, {"main": {"page_count": "1", "pages": "x"}}):
            validate(rec(1), docs)


class Skeleton(unittest.TestCase):
    def test_blank_record_is_valid(self):
        s = skeleton()
        self.assertEqual(list(s), list(RECORD_KEYS))
        self.assertEqual(validate(s, DOCS), ([], []))
        self.assertEqual((s["source"]["doc"], s["kind"], s["reaction_id"], s["conditions_given"]),
                         ("main", None, None, True))
        self.assertEqual(s["steps"], [{"step": 1, "description": "", "reactants": [], "products": [],
                                       "conditions": []}])
        s["steps"][0]["reactants"].append(1)
        self.assertEqual(skeleton()["steps"][0]["reactants"], [])  # templates are not shared

    def test_source_from_a_block(self):
        src = {"doc": "si", "page": 3, "figure": "Table S1", "caption": "c", "region_id": "si:tables1",
               "block_id": "1", "entry_id": "e002", "entry_bbox": [10, 10, 50, 20], "reaction_id": "e002-1",
               "crop": "x.png"}
        s = skeleton(source=src, kind="optimization")
        self.assertEqual(s["source"], {**{k: v for k, v in src.items() if k != "crop"}, "section": None,
                                       "reaction_id": None})
        self.assertEqual(s["kind"], "optimization")
        self.assertEqual(validate(s, DOCS), ([], []))

    def test_templates_make_valid_items(self):
        s = skeleton()
        st = s["steps"][0]
        st["reactants"].append({**copy.deepcopy(TEMPLATES["participant"]), "key": "r1", "text": "PhBr"})
        st["products"].append({**copy.deepcopy(TEMPLATES["participant"]), "key": "p1", "role": "product",
                               "outcomes": [copy.deepcopy(TEMPLATES["outcome"])]})
        st["conditions"].append({**copy.deepcopy(TEMPLATES["condition"]), "key": "c1", "text": "THF"})
        s["steps"].append({**copy.deepcopy(TEMPLATES["step"]), "step": 2})
        self.assertEqual(validate(s, DOCS), ([], []))
        self.assertEqual(TEMPLATES["condition"]["origin"], "curator")
        self.assertIn("curator", KNOWN["origin_prefix"])
        # A blank item without its key does not save.
        st["conditions"].append(copy.deepcopy(TEMPLATES["condition"]))
        self.assertEqual(validate(s, DOCS)[0], ["steps[0].conditions[1].key: 缺少 key（应为非空字符串）"])


if __name__ == "__main__":
    unittest.main()
