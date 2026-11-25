"""The condition-table path of Step 2 (pipeline/extract_ctable.py): validators, assembly into
records, views. Paper 1, Table 1 is written out by hand as the two skills would answer, and its
records must reproduce the table's entries."""

import copy
import json
import unittest
from pathlib import Path

from pipeline.extract_ctable import (assemble_view, number_reactions, synthesize, validate_handles, validate_reaction,
                                     validate_table)
from pipeline.extract_view import block_head, block_view
from pipeline.schemas import build_extract
from tests.test_extract_records import cond, ov, step, tpart

SCHEMA_DIR = Path(build_extract.__file__).parent
ENTRIES_SCHEMA = json.loads((SCHEMA_DIR / "ctable_entries.schema.json").read_text())
HANDLES_SCHEMA = json.loads((SCHEMA_DIR / "ctable_handles.schema.json").read_text())
REACTION_SCHEMA = json.loads((SCHEMA_DIR / "ctable_reaction.schema.json").read_text())
SIZES = {1: (600.0, 800.0), 2: (600.0, 800.0)}
DOC_PAGES = {"main": 5, "si": 260}
REGION = {"region_id": "main:table1", "doc": "main", "label": "Table 1", "first_page": 2,
          "caption": "Table 1. Optimization of Reaction Conditions"}
BLOCK = {"block_id": "1", "kind": "optimization", "layout": "condition_table", "page": 2, "title": None,
         "bbox": [315, 60, 560, 330]}
LEGEND = {"C1": "Fe(BF-Phos)Cl2", "C2": "Fe(dppe)Cl2", "C3": "Fe(dppb)Cl2", "C4": "Fe(dpph)Cl2",
          "C5": "Fe(XantPhos)Cl2", "C6": "Fe(dppbz)Cl2"}
NAMES = {**LEGEND, "[Co]": "Co(BF-Phos)Cl2", "[Ni]": "Ni(BF-Phos)Cl2", "[Cu]": "Cu(BF-Phos)Cl2"}

# entry, cat., additive, conv. (%), 3a/3a'/1a' (yield, %), markers on the entry number
TABLE1 = [
    ("1", "", "", "75", "12/8/50", []),
    ("2", "FeCl2", "", ">98", "49/44/0", ["b"]),
    ("3", "C1", "", ">98", "78/19/0", ["c"]),
    ("4", "C1", "LiCl", ">98", "90/5/0", ["c"]),
    ("5", "C1", "LiCl", ">98", "90 (81)/4/0", []),
    ("6", "C2", "LiCl", ">98", "77/19/2", []),
    ("7", "C3", "LiCl", ">98", "72/25/2", []),
    ("8", "C4", "LiCl", ">98", "76/21/2", []),
    ("9", "C5", "LiCl", ">98", "66/29/2", []),
    ("10", "C6", "LiCl", ">98", "70/25/2", []),
    ("11", "[Co]", "LiCl", ">98", "3/72/18", ["d"]),
    ("12", "[Ni]", "LiCl", "96", "4/69/13", ["e"]),
    ("13", "[Cu]", "LiCl", "95", "6/56/32", ["f"]),
]


def column(key, kind, header="", target=None, measures=(), blank_means=None, variable_name=None, unit=None,
           values=()):
    return {"key": key, "header": header, "kind": kind, "target": target, "variable_name": variable_name,
            "unit": unit, "values": list(values), "measures": list(measures), "blank_means": blank_means, "notes": ""}


def value(printed, text=None, amount=None, structure_key=None, stated_at=None, basis="legend"):
    return {"printed": printed, "text": text, "amount": amount, "structure_key": structure_key,
            "stated_at": stated_at, "basis": basis}


def measure(participant_key, kind="yield", yield_type=None):
    return {"participant_key": participant_key, "measure": kind, "yield_type": yield_type}


def cell(col, text, markers=(), structure_bbox=None):
    return {"column": col, "text": text, "markers": list(markers), "structure_bbox": structure_bbox}


def table1_template():
    return {
        "general_reaction": "α-Bromoamide 1a couples with cyclopentylmagnesium bromide 2a (via ZnCl2) to 3a; 3a′ and "
                            "1a′ form by reduction and halide exchange.",
        "reading_guide": "Each row varies the catalyst and the additive; yields of 3a/3a′/1a′ by 1H NMR, the isolated "
                         "yield in parentheses.",
        "scheme": {"page": 2, "bbox": [315, 75, 560, 110]},
        "participants": [
            tpart("1a", "reactant", "1a", amount="0.2 mmol", generic=False, bbox=[315, 82, 350, 98]),
            tpart("2a", "reactant", "2a", amount="0.4 mmol, 2 equiv", generic=False, bbox=[355, 83, 380, 97]),
            tpart("3a", "product", "3a", generic=False, bbox=[434, 82, 476, 98]),
            tpart("3a-prime", "byproduct", "3a′", generic=False, bbox=[482, 82, 513, 98]),
            tpart("1a-prime", "byproduct", "1a′", generic=False, bbox=[521, 82, 556, 98]),
        ],
        "alternative_groups": [],
        "steps": [step(1, ["1a", "2a"], ["3a", "3a-prime", "1a-prime"])],
        "conditions": [
            cond("cat", "catalyst", "cat.", "0.5 mol%", per_entry=True),
            cond("zncl2", "reagent", "ZnCl2", "0.2 mmol, 1.0 equiv"),
            cond("additive", "additive", "additive", "1.0 equiv", per_entry=True),
            cond("solvent", "solvent", "THF"),
            cond("temp", "temperature", "22–25 °C"),
            cond("time", "time", "2 h"),
        ],
        "structures": [{"key": k, "label": k, "text": v, "page": 2, "bbox": [320 + 38 * i, 280, 352 + 38 * i, 320]}
                       for i, (k, v) in enumerate(LEGEND.items())],
        "footnotes": [
            {"marker": "a", "text": "Reaction conditions: 1a (0.2 mmol), 2a (0.4 mmol, 2 equiv), [M] (0.5 mol %), ZnCl2 "
                                    "(0.2 mmol, 1.0 equiv), and additive (1.0 equiv) in THF ...", "overrides": [],
             "notes": "base conditions; yields by 1H NMR (CH2Br2), isolated yield in parentheses"},
            {"marker": "b", "text": "FeCl2 (5 mol %).", "overrides": [ov("cat", "replace", amount="5 mol %")], "notes": ""},
            {"marker": "c", "text": "Fe(BF-Phos)Cl2 (1 mol %).", "overrides": [ov("cat", "replace", amount="1 mol %")],
             "notes": ""},
            {"marker": "d", "text": "[Co] = Co(BF-Phos)Cl2.", "overrides": [], "notes": "names the [Co] of the row"},
            {"marker": "e", "text": "[Ni] = Ni(BF-Phos)Cl2.", "overrides": [], "notes": "names the [Ni] of the row"},
            {"marker": "f", "text": "[Cu] = Cu(BF-Phos)Cl2.", "overrides": [], "notes": "names the [Cu] of the row"},
        ],
        "preparations": [],
        "variable_defaults": [],
        "default_yield_type": "NMR",
        "variants": [],
        "context": [],
    }


def table1_entries():
    """Stage 1, turn 1 (with the entry ids the pipeline assigns)."""
    columns = [
        column("entry", "entry_number", "entry"),
        column("cat", "condition", "cat.", "cat", blank_means="no catalyst"),
        column("additive", "condition", "additive", "additive", blank_means="no additive"),
        column("conv", "outcome", "conv. (%)", measures=[measure("1a", "conversion")]),
        column("yields", "outcome", "3a/3a′/1a′ (yield, %)",
               measures=[measure("3a", yield_type="NMR"), measure("3a-prime", yield_type="NMR"),
                         measure("1a-prime", yield_type="NMR")]),
    ]
    entries = []
    for i, (label, cat, additive, conv, yields, markers) in enumerate(TABLE1, 1):
        y = 126 + 11 * (i - 1)
        entries.append({"label": label, "page": 2, "bbox": [320, y, 555, y + 9], "eid": f"e{i:03d}",
                        "descriptor": f"{label}; {cat}; {additive}; {conv}; {yields}",
                        "cells": [cell("entry", label, markers), cell("cat", cat), cell("additive", additive),
                                  cell("conv", conv), cell("yields", yields)]})
    return {"template": table1_template(), "columns": columns, "entries": entries, "ignored": [], "notes": ""}


def strip_ids(inv):
    """As Codex returns it (the entry ids are added by the pipeline)."""
    inv = copy.deepcopy(inv)
    for en in inv["entries"]:
        del en["eid"]
    return inv


def table1_handles():
    return {"reactions": [{"entry": i, "results": [{"column": "conv", "part": None}, {"column": "yields", "part": None}],
                           "variant": None, "footnote_markers": list(row[5]), "distinguishing": None}
                          for i, row in enumerate(TABLE1, 1)],
            "notes": [], "issues": []}


def out(value, column, text=None, product_key=None, yield_type=None, qualifier=None, measure=None, selectivity=()):
    return {"product_key": product_key, "yield_text": text if text is not None else str(value), "yield_value": value,
            "yield_qualifier": qualifier, "yield_type": yield_type, "selectivity": list(selectivity),
            "footnote_markers": [], "notes": None, "column": column, "measure": measure}


def table1_answer(row):
    """Stage 2 for one row of Table 1."""
    label, cat, additive, conv, yields, _ = row
    overrides = []
    if cat:
        overrides.append(ov("cat", "replace", NAMES.get(cat, cat), structure_key=cat if cat in LEGEND else None,
                            basis=f"row cell cat.: {cat}"))
    else:
        overrides.append(ov("cat", "remove", basis="empty cell: no catalyst"))
    overrides.append(ov("additive", "replace", additive, basis="row cell additive") if additive
                     else ov("additive", "remove", basis="empty cell: no additive"))
    outcomes = [out(98, "conv", ">98", qualifier=">") if conv.startswith(">") else out(int(conv), "conv")]
    if "(" in yields:
        outcomes += [out(90, "yields", product_key="3a", measure=1),
                     out(81, "yields", "(81)", product_key="3a", yield_type="isolated", measure=1),
                     out(4, "yields", product_key="3a-prime", measure=2), out(0, "yields", product_key="1a-prime", measure=3)]
    else:
        for i, (key, v) in enumerate(zip(("3a", "3a-prime", "1a-prime"), yields.split("/")), 1):
            outcomes.append(out(int(v), "yields", product_key=key, measure=i))
    return {"template_check": [], "overrides": overrides, "outcomes": outcomes, "lookup": [], "related": [],
            "notes": "", "issues": []}


def table1_reactions():
    inv = table1_entries()
    return inv, number_reactions(inv, table1_handles())


TEMPLATE_CROPS = {"1a": "c/_template__1a.png", "2a": "c/_template__2a.png", "3a": "c/_template__3a.png",
                  "3a-prime": "c/_template__3a-prime.png", "1a-prime": "c/_template__1a-prime.png"}


class EndToEnd(unittest.TestCase):
    def test_table1_reproduces_the_entries(self):
        inv, reactions = table1_reactions()
        self.assertEqual(validate_table(strip_ids(inv), ENTRIES_SCHEMA, SIZES, 13, DOC_PAGES), ([], []))
        self.assertEqual(validate_handles(table1_handles(), inv, HANDLES_SCHEMA), ([], []))
        answers = {}
        for r, row in zip(reactions, TABLE1):
            answer = table1_answer(row)
            self.assertEqual(validate_reaction(answer, REACTION_SCHEMA, inv, r, DOC_PAGES), ([], []), r["rid"])
            answers[r["rid"]] = ({**answer, "_meta": {"errors": [], "warnings": [], "seconds": 3}}, "ok")
        handles = {**table1_handles(), "reactions": reactions, "_meta": {"status": "ok", "errors": [], "warnings": []}}
        inv["_meta"] = {"status": "ok", "errors": [], "warnings": [], "overlays": []}
        view, records, counts = assemble_view(REGION, BLOCK, "main-table1__1", inv, "ok", handles, "ok", answers,
                                              TEMPLATE_CROPS, {}, {})
        self.assertEqual(len(records), 13)
        self.assertEqual((counts["entries_ok"], counts["reactions_ok"]), (13, 13))
        rec = records[4]  # entry 5: C1 + LiCl, NMR 90 and isolated 81
        self.assertEqual((rec["reaction_id"], rec["label"]), ("main:table1/1/e005-1", "5"))
        conds = {c["key"]: c for c in rec["steps"][0]["conditions"]}
        self.assertEqual((conds["cat"]["text"], conds["cat"]["amount"], conds["cat"]["origin"]),
                         ("Fe(BF-Phos)Cl2", "0.5 mol%", "entry"))
        self.assertEqual(conds["additive"]["text"], "LiCl")
        p3a = next(p for p in rec["steps"][0]["products"] if p["key"] == "3a")
        self.assertEqual([(o["yield"]["value"], o["yield"]["type"]) for o in p3a["outcomes"]],
                         [(90, "NMR"), (81, "isolated")])
        self.assertEqual((p3a["source"], p3a["label"], p3a["crop"]), ("drawn", "3a", "c/_template__3a.png"))
        self.assertEqual(rec["other_outcomes"][0]["yield"]["type"], "conversion")
        rec2 = records[1]  # footnote b changes the catalyst loading of entry 2
        cat2 = {c["key"]: c for c in rec2["steps"][0]["conditions"]}["cat"]
        self.assertEqual((cat2["text"], cat2["amount"]), ("FeCl2", "5 mol %"))
        self.assertEqual([x["key"] for x in records[0]["removed_conditions"]], ["cat", "additive"])

    def test_view_renders(self):
        inv, reactions = table1_reactions()
        inv["_meta"] = {"status": "ok", "errors": [], "warnings": [], "overlays": ["overlay_p002.png"]}
        handles = {**table1_handles(), "reactions": reactions, "_meta": {"status": "ok", "errors": [], "warnings": []}}
        answer = table1_answer(TABLE1[1])
        answer["template_check"] = [{"target": "cat", "stage1": "0.5 mol%", "seen": "5 mol% for FeCl2",
                                     "evidence": "footnote b"}]
        answers = {"e002-1": ({**answer, "_meta": {"errors": [], "warnings": [], "seconds": 2}}, "ok"),
                   "e003-1": (None, "skipped")}
        view, records, counts = assemble_view(REGION, BLOCK, "main-table1__1", inv, "ok", handles, "ok", answers,
                                              TEMPLATE_CROPS, {}, {})
        self.assertEqual((len(records), counts["reactions_ok"], counts["reactions_pending"], counts["reactions_skipped"]),
                         (1, 1, 11, 1))
        self.assertTrue(any("questioned for 'cat' by 1 reaction(s): e002-1" in w for w in view["meta"]["warnings"]))
        self.assertTrue(any("table reading questioned for cat" in x for x in records[0]["issues"]))
        data = block_view(view)
        json.dumps(data)
        rv = data["entries"][1]["reactions"][0]
        cat = {c["key"]: c for st in rv["record"]["steps"] for c in st["conditions"]}["cat"]
        self.assertEqual((rv["rid"], cat["text"], cat["amount"]), ("e002-1", "FeCl2", "5 mol %"))
        head = block_head(data)
        self.assertEqual((head["entries"]["listed"], head["reactions"]["listed"], head["reactions"]["ok"]), (13, 13, 1))
        self.assertEqual(data["block"]["layout"], "condition_table")

    def test_view_before_the_reactions_are_listed(self):
        inv = table1_entries()
        inv["_meta"] = {"status": "ok", "errors": [], "warnings": []}
        view, records, counts = assemble_view(REGION, BLOCK, "s", inv, "ok", None, None, {}, {}, {}, {})
        self.assertEqual((records, counts["entries_pending"], view["entries"][0]["reactions"]), ([], 13, []))
        failed = {"reactions": [], "notes": [], "issues": [], "_meta": {"status": "failed", "errors": ["boom"], "warnings": []}}
        view, _, counts = assemble_view(REGION, BLOCK, "s", inv, "ok", failed, "failed", {}, {}, {}, {})
        self.assertEqual((counts["entries_failed"], view["meta"]["errors"]), (13, ["reactions: boom"]))
        view, _, counts = assemble_view(REGION, BLOCK, "s", {**inv, "_meta": {"errors": ["x"], "warnings": []}},
                                        "failed", None, None, {}, {}, {}, {})
        self.assertEqual((view["template"], view["entries"], counts["inventories_failed"]), (None, [], 1))
        for v in (view,):
            block_view(v)


class TableValidation(unittest.TestCase):
    def errors(self, inv):
        return validate_table(strip_ids(inv), ENTRIES_SCHEMA, SIZES, 13, DOC_PAGES)[0]

    def assertHas(self, errors, fragment):
        self.assertTrue(any(fragment in e for e in errors), f"no error containing {fragment!r}: {errors}")

    def test_columns_point_into_the_template(self):
        inv = table1_entries(); inv["columns"][1]["target"] = "catalyst"
        self.assertHas(self.errors(inv), "target 'catalyst' is not a template condition")
        inv = table1_entries(); inv["template"]["conditions"][0]["per_entry"] = False
        self.assertHas(self.errors(inv), "needs per_entry true")
        inv = table1_entries(); inv["template"]["conditions"][3]["per_entry"] = True
        self.assertHas(self.errors(inv), "template condition 'solvent' has per_entry true, but no condition column")
        inv = table1_entries(); inv["columns"][3]["kind"] = "other"
        self.assertHas(self.errors(inv), "measures are only for outcome columns")
        inv = table1_entries(); inv["columns"] = [c for c in inv["columns"] if c["kind"] != "outcome"]
        for en in inv["entries"]:
            en["cells"] = [c for c in en["cells"] if c["column"] not in ("conv", "yields")]
        self.assertHas(self.errors(inv), "no outcome column")
        inv = table1_entries(); inv["columns"][4]["measures"][0]["participant_key"] = "3b"
        self.assertHas(self.errors(inv), "measure on unknown participant '3b'")
        inv = table1_entries(); inv["columns"].append(column("x", "variable", "X", "1a"))
        for en in inv["entries"]:
            en["cells"].append(cell("x", "Br"))
        self.assertHas(self.errors(inv), "needs variable_name")

    def test_rows_of_cells(self):
        inv = table1_entries(); inv["entries"][2]["cells"].pop(2)
        self.assertHas(self.errors(inv), "no cell for column(s) ['additive']")
        inv = table1_entries(); inv["entries"][2]["cells"].append(cell("ligand", "L1"))
        self.assertHas(self.errors(inv), "cell of unknown column 'ligand'")
        inv = table1_entries(); inv["entries"][2]["cells"][0]["markers"] = ["z"]
        self.assertHas(self.errors(inv), "footnote marker 'z' is not defined")
        inv = table1_entries(); inv["entries"][2]["cells"][3]["structure_bbox"] = [400, 140, 420, 150]
        self.assertHas(self.errors(inv), "only a condition or participant cell can be a drawing")
        inv = table1_entries(); inv["entries"][2]["cells"][1]["structure_bbox"] = [400, 140, 420]
        self.assertHas(self.errors(inv), "schema at /entries/2/cells/1/structure_bbox")

    def test_a_table_without_entries_is_an_error(self):
        inv = table1_entries(); inv["entries"] = []
        self.assertHas(self.errors(inv), "no entries listed")


class HandleValidation(unittest.TestCase):
    def errors(self, handles, inv=None):
        return validate_handles(handles, inv or table1_entries(), HANDLES_SCHEMA)[0]

    def assertHas(self, errors, fragment):
        self.assertTrue(any(fragment in e for e in errors), f"no error containing {fragment!r}: {errors}")

    def test_every_row_and_result_belongs_to_a_reaction(self):
        h = table1_handles(); h["reactions"].pop(3)
        self.assertHas(self.errors(h), "row 4 (4) has no reaction")
        h = table1_handles(); h["reactions"][0]["results"].pop()
        self.assertHas(self.errors(h), "result cell 'yields' ('12/8/50') belongs to no reaction")
        h = table1_handles(); h["reactions"][0]["results"].append({"column": "cat", "part": None})
        self.assertHas(self.errors(h), "'cat' is not an outcome column")
        h = table1_handles(); h["reactions"][0]["entry"] = 14
        self.assertHas(self.errors(h), "there is no row 14")
        h = table1_handles(); h["reactions"][0]["variant"] = "ni"
        self.assertHas(self.errors(h), "unknown variant 'ni'")

    def test_split_rows_give_their_parts(self):
        inv = table1_entries()
        inv["entries"][4]["cells"][4]["text"] = "rt: 40, 60 °C: 80"
        h = table1_handles()
        second = copy.deepcopy(h["reactions"][4])
        h["reactions"].insert(5, second)
        self.assertHas(self.errors(h, inv), "and reactions[5] are the same reaction")
        h["reactions"][4]["results"][1]["part"] = "rt: 40"
        h["reactions"][5]["results"][1]["part"] = "60 °C: 80"
        h["reactions"][5]["distinguishing"] = "60 °C"
        errors = self.errors(h, inv)
        self.assertHas(errors, "result cell 'conv' is shared by reactions [5, 6]")
        h["reactions"][5]["results"] = [h["reactions"][5]["results"][1]]
        self.assertEqual(self.errors(h, inv), [])
        h["reactions"][5]["results"][0]["part"] = "90 °C: 80"
        self.assertHas(self.errors(h, inv), "part '90 °C: 80' is not in the text")

    def test_numbering(self):
        inv = table1_entries()
        h = table1_handles()
        h["reactions"].insert(5, {**copy.deepcopy(h["reactions"][4]), "distinguishing": "x"})
        rids = [r["rid"] for r in number_reactions(inv, h)]
        self.assertEqual(rids[3:7], ["e004-1", "e005-1", "e005-2", "e006-1"])
        self.assertEqual(number_reactions(inv, h)[0]["results_text"], ["75", "12/8/50"])


class ReactionValidation(unittest.TestCase):
    def check(self, answer, n=1):
        inv, reactions = table1_reactions()
        return validate_reaction(answer, REACTION_SCHEMA, inv, reactions[n - 1], DOC_PAGES)

    def assertHas(self, errors, fragment):
        self.assertTrue(any(fragment in e for e in errors), f"no message containing {fragment!r}: {errors}")

    def test_open_points_are_settled(self):
        a = table1_answer(TABLE1[0]); a["overrides"].pop()
        self.assertHas(self.check(a)[0], "condition 'additive' ('additive') is given row by row")
        a = table1_answer(TABLE1[0]); a["overrides"].append(ov("ligand", "replace", "dppe"))
        self.assertHas(self.check(a)[0], "targets an unknown key")

    def test_outcomes(self):
        a = table1_answer(TABLE1[0]); a["outcomes"][1]["product_key"] = "1a"
        self.assertHas(self.check(a)[0], "product_key '1a' is not a product or byproduct")
        a = table1_answer(TABLE1[0]); a["outcomes"][1]["column"] = "cat"
        self.assertHas(self.check(a)[0], "column 'cat' is not one of this reaction's result cells")
        a = table1_answer(TABLE1[0]); a["outcomes"][1]["measure"] = None
        self.assertHas(self.check(a)[0], "holds several measures ['3a', '3a-prime', '1a-prime']: say with `measure`")
        a = table1_answer(TABLE1[0]); a["outcomes"][1]["measure"] = 4
        self.assertHas(self.check(a)[0], "measure 4 is not one of the column's measures (1..3)")
        a = table1_answer(TABLE1[0]); a["outcomes"] = a["outcomes"][:1]
        self.assertHas(self.check(a)[1], "no outcome read from result cell 'yields'")

    def test_lookup_and_check(self):
        a = table1_answer(TABLE1[0]); a["lookup"] = [ov("time", "replace", "3 h")]
        self.assertHas(self.check(a)[0], "has neither stated_at nor inferred")
        a = table1_answer(TABLE1[0]); a["lookup"] = [ov("time", "replace", "3 h", stated_at={"doc": "si", "page": 999})]
        self.assertHas(self.check(a)[0], "page 999 is not a page of 'si'")
        a = table1_answer(TABLE1[0]); a["template_check"] = [{"target": "colour", "stage1": "", "seen": "", "evidence": ""}]
        self.assertHas(self.check(a)[1], "unknown target 'colour'")


def drawn_ligand_table():
    """Paper 9, Fig. 2b style: the varied condition is a drawn ligand, one drawing per entry."""
    inv = table1_entries()
    t = inv["template"]
    t["conditions"][0] = cond("cat", "catalyst", "Fe salt")
    t["conditions"][2] = cond("ligand", "ligand", "NHC·HCl", per_entry=True)
    t["steps"] = [step(1, ["1a", "2a"], ["3a", "3a-prime"])]
    t["participants"] = t["participants"][:4]
    t["footnotes"] = t["footnotes"][:1]
    inv["columns"] = [column("ligand", "condition", "", "ligand"),
                      column("yields", "outcome", "", measures=[measure("3a", yield_type="GC"),
                                                                measure("3a-prime", yield_type="GC")])]
    inv["entries"] = [{"label": None, "page": 2, "bbox": [320, 120 + 60 * i, 400, 175 + 60 * i], "eid": f"e{i + 1:03d}",
                       "descriptor": f"{name}; 3a: {a}%, 3a′: {b}%",
                       "cells": [cell("ligand", name, structure_bbox=[325, 122 + 60 * i, 395, 160 + 60 * i]),
                                 cell("yields", f"3a: {a}%  3a′: {b}%")]}
                      for i, (name, a, b) in enumerate([("IPr", 3, 14), ("IMes", 24, 20)])]
    return inv


class DrawnValues(unittest.TestCase):
    def test_drawn_ligand_becomes_a_structure_of_the_reaction(self):
        inv = drawn_ligand_table()
        self.assertEqual(validate_table(strip_ids(inv), ENTRIES_SCHEMA, SIZES, 2, DOC_PAGES)[0], [])
        handles = {"reactions": [{"entry": n, "results": [{"column": "yields", "part": None}], "variant": None,
                                  "footnote_markers": [], "distinguishing": None} for n in (1, 2)],
                   "notes": [], "issues": []}
        self.assertEqual(validate_handles(handles, inv, HANDLES_SCHEMA)[0], [])
        imes = number_reactions(inv, handles)[1]
        answer = {"template_check": [], "lookup": [], "related": [], "notes": "", "issues": [],
                  "overrides": [ov("ligand", "replace", "IMes·HCl", structure_key="e002-ligand", basis="drawn ligand")],
                  "outcomes": [out(24, "yields", "24%", "3a", measure=1), out(20, "yields", "20%", "3a-prime", measure=2)]}
        self.assertEqual(validate_reaction(answer, REACTION_SCHEMA, inv, imes, DOC_PAGES)[0], [])
        unit, row, child, crops = synthesize(inv, imes, answer, TEMPLATE_CROPS, {"e002-ligand": "c/_cell__e002-ligand.png"})
        self.assertEqual(row["drawn_structures"], [{"key": "e002-ligand", "label": "IMes", "text": None}])
        self.assertEqual(child["structures"][0]["bbox"], [325, 182, 395, 220])
        self.assertEqual(crops["s:e002-ligand"], "c/_cell__e002-ligand.png")
        self.assertEqual([o["yield_type"] for o in child["outcomes"]], ["GC", "GC"])
        unused = {**answer, "overrides": [ov("ligand", "replace", "IMes·HCl", basis="drawn ligand")]}
        self.assertTrue(any("drawn structure 'e002-ligand' is not used" in w
                            for w in validate_reaction(unused, REACTION_SCHEMA, inv, imes, DOC_PAGES)[1]))
        # Paper 9: stage 1 also boxed the drawings as legend structures and its values point there.
        inv["template"]["structures"].append({"key": "IMes", "label": "IMes", "text": None, "page": 2,
                                              "bbox": [325, 182, 395, 220]})
        inv["columns"][0]["values"] = [value("IMes", "IMes·HCl", structure_key="IMes", basis="caption: HCl salts")]
        for skey in ("IMes", "e002-ligand"):
            a = {**answer, "overrides": [ov("ligand", "replace", "IMes·HCl", structure_key=skey, basis="drawn ligand")]}
            self.assertEqual(validate_reaction(a, REACTION_SCHEMA, inv, imes, DOC_PAGES)[0], [])
        a = {**answer, "overrides": [ov("ligand", "replace", "IMes", structure_key="IMes", basis="drawn ligand")]}
        self.assertTrue(any("stands for text 'IMes·HCl', structure_key 'e002-ligand' or 'IMes'" in e
                            for e in validate_reaction(a, REACTION_SCHEMA, inv, imes, DOC_PAGES)[0]))


class SwappedParticipant(unittest.TestCase):
    def test_row_that_replaces_the_substrate(self):
        """Paper 5, entry 10: "alkyl-I instead of alkyl-Br" under a deviation column."""
        inv = table1_entries()
        inv["columns"][1] = column("change", "deviation", "variation from the standard conditions",
                                   blank_means="the standard conditions")
        t = inv["template"]
        t["conditions"][0] = cond("cat", "catalyst", "Fe(BF-Phos)Cl2", "0.5 mol%")
        t["conditions"][2] = cond("additive", "additive", "LiCl", "1.0 equiv")
        for en in inv["entries"]:
            en["cells"][1] = cell("change", "")
            en["cells"][2] = cell("additive", "")
        inv["columns"].pop(2)
        for en in inv["entries"]:
            en["cells"].pop(2)
        inv["entries"][9]["cells"][1]["text"] = "alkyl-I instead of alkyl-Br"
        self.assertEqual(validate_table(strip_ids(inv), ENTRIES_SCHEMA, SIZES, 13, DOC_PAGES)[0], [])
        r10 = number_reactions(inv, table1_handles())[9]
        answer = table1_answer(TABLE1[9])
        answer["overrides"] = []
        self.assertTrue(any("names a change, but there are no overrides" in w
                            for w in validate_reaction(answer, REACTION_SCHEMA, inv, r10, DOC_PAGES)[1]))
        answer["overrides"] = [ov("1a", "replace", "alkyl-I", basis="deviation: alkyl-I instead of alkyl-Br")]
        self.assertEqual(validate_reaction(answer, REACTION_SCHEMA, inv, r10, DOC_PAGES)[0], [])
        _, _, child, crops = synthesize(inv, r10, answer, TEMPLATE_CROPS, {})
        p1a = next(p for p in child["participants"] if p["key"] == "1a")
        self.assertEqual((p1a["source"], p1a["bbox"]), ("text", None))
        self.assertNotIn("1a", crops)
        view_inv = {**inv, "_meta": {"status": "ok", "errors": [], "warnings": []}}
        handles = {**table1_handles(), "reactions": number_reactions(inv, table1_handles()),
                   "_meta": {"status": "ok", "errors": [], "warnings": []}}
        _, records, _ = assemble_view(REGION, BLOCK, "s", view_inv, "ok", handles, "ok",
                                      {"e010-1": ({**answer, "_meta": {}}, "ok")}, TEMPLATE_CROPS, {}, {})
        rec_1a = next(p for p in records[0]["steps"][0]["reactants"] if p["key"] == "1a")
        # the template's label "1a" named the bromide; the row put the iodide in its place
        self.assertEqual((rec_1a["text"], rec_1a["label"], rec_1a["crop"]), ("alkyl-I", None, None))


def answer_with(overrides=None, outcomes=None, lookup=(), row=TABLE1[0]):
    a = table1_answer(row)
    if overrides is not None:
        a["overrides"] = overrides
    if outcomes is not None:
        a["outcomes"] = outcomes
    a["lookup"] = list(lookup)
    return a


class ColumnKinds(unittest.TestCase):
    """Columns that give only an amount, a variable group, values a legend resolves, mixed measures."""

    def assertHas(self, messages, fragment):
        self.assertTrue(any(fragment in m for m in messages), f"no message containing {fragment!r}: {messages}")

    def test_amount_column(self):
        """Paper 7, 'PhCNBox (mol%)': the column gives only the ligand's loading."""
        inv = table1_entries()
        inv["template"]["conditions"].append(cond("ligand", "ligand", "PhCNBox"))
        inv["columns"].insert(3, column("ligand", "amount", "PhCNBox (mol%)", "ligand", unit="mol%"))
        for en, v in zip(inv["entries"], ["10", "20", "10", "10", "0"] + ["10"] * 8):
            en["cells"].insert(3, cell("ligand", v))
        self.assertEqual(validate_table(strip_ids(inv), ENTRIES_SCHEMA, SIZES, 13, DOC_PAGES)[0], [])
        r = number_reactions(inv, table1_handles())
        a = table1_answer(TABLE1[0])
        self.assertHas(validate_reaction(a, REACTION_SCHEMA, inv, r[0], DOC_PAGES)[0],
                       "column 'ligand' gives the amount of 'ligand' for this row ('10'): write a replace")
        a["overrides"].append(ov("ligand", "replace", amount="10 mol%", basis="cell PhCNBox (mol%)"))
        self.assertEqual(validate_reaction(a, REACTION_SCHEMA, inv, r[0], DOC_PAGES)[0], [])
        _, _, child, _ = synthesize(inv, r[0], a, TEMPLATE_CROPS, {})
        zero = table1_answer(TABLE1[4]); zero["overrides"].append(ov("ligand", "remove", basis="0 mol%"))
        self.assertEqual(validate_reaction(zero, REACTION_SCHEMA, inv, r[4], DOC_PAGES)[0], [])

    def test_amount_column_of_a_reactant_keeps_the_compound(self):
        """Paper 10, 'equiv. 3a': a per-row amount of a drawn reactant."""
        inv = table1_entries()
        inv["columns"].insert(3, column("equiv", "amount", "equiv. 2a", "2a", unit="equiv"))
        for en in inv["entries"]:
            en["cells"].insert(3, cell("equiv", "1.5"))
        r = number_reactions(inv, table1_handles())
        a = table1_answer(TABLE1[0]); a["overrides"].append(ov("2a", "replace", "1.5", basis="cell"))
        self.assertHas(validate_reaction(a, REACTION_SCHEMA, inv, r[0], DOC_PAGES)[0], "its replace sets `amount`, not `text`")
        a = table1_answer(TABLE1[0]); a["overrides"].append(ov("2a", "replace", amount="1.5 equiv", basis="cell"))
        self.assertEqual(validate_reaction(a, REACTION_SCHEMA, inv, r[0], DOC_PAGES)[0], [])
        _, _, child, crops = synthesize(inv, r[0], a, TEMPLATE_CROPS, {})
        p2a = next(p for p in child["participants"] if p["key"] == "2a")
        self.assertEqual((p2a["source"], crops["2a"]), ("drawn", "c/_template__2a.png"))

    def test_variable_column_keeps_the_drawing(self):
        inv = table1_entries()
        inv["columns"].insert(3, column("x", "variable", "X", "1a", variable_name="X"))
        for en, v in zip(inv["entries"], ["Br", "I"] + ["Br"] * 11):
            en["cells"].insert(3, cell("x", v))
        self.assertEqual(validate_table(strip_ids(inv), ENTRIES_SCHEMA, SIZES, 13, DOC_PAGES)[0], [])
        r = number_reactions(inv, table1_handles())
        wrong = table1_answer(TABLE1[1]); wrong["overrides"].append(ov("1a", "replace", "I", basis="X column"))
        self.assertHas(validate_reaction(wrong, REACTION_SCHEMA, inv, r[1], DOC_PAGES)[0], "do not replace the participant")
        right = table1_answer(TABLE1[1])
        self.assertEqual(validate_reaction(right, REACTION_SCHEMA, inv, r[1], DOC_PAGES)[0], [])
        _, row, child, crops = synthesize(inv, r[1], right, TEMPLATE_CROPS, {})
        p1a = next(p for p in child["participants"] if p["key"] == "1a")
        self.assertEqual((p1a["source"], p1a["variables"], crops["1a"]), ("drawn", [{"name": "X", "value": "I"}],
                                                                         "c/_template__1a.png"))
        self.assertEqual(row["variables"], [{"name": "X", "value": "I"}])

    def test_values_decided_by_stage_1(self):
        """Legend labels in the catalyst column: stage 1 says once what 'C1' stands for."""
        inv = table1_entries()
        inv["columns"][1]["values"] = [value("C1", "Fe(BF-Phos)Cl2", structure_key="C1")]
        self.assertEqual(validate_table(strip_ids(inv), ENTRIES_SCHEMA, SIZES, 13, DOC_PAGES)[0], [])
        r = number_reactions(inv, table1_handles())
        a = table1_answer(TABLE1[2]); a["overrides"][0] = ov("cat", "replace", "C1", basis="cell")
        self.assertHas(validate_reaction(a, REACTION_SCHEMA, inv, r[2], DOC_PAGES)[0],
                       "says the printed 'C1' stands for text 'Fe(BF-Phos)Cl2', structure_key 'C1'")
        self.assertEqual(validate_reaction(table1_answer(TABLE1[2]), REACTION_SCHEMA, inv, r[2], DOC_PAGES)[0], [])
        inv["columns"][1]["values"].append(value("C9", structure_key="C9"))
        errors, warnings = validate_table(strip_ids(inv), ENTRIES_SCHEMA, SIZES, 13, DOC_PAGES)
        self.assertHas(errors, "unknown structure_key 'C9'")
        self.assertHas(warnings, "no cell of the column prints it")

    def test_mixed_measures_and_selectivity(self):
        """One column 'conv./yield (%)': each value says which measure it is."""
        inv = table1_entries()
        inv["columns"][4]["measures"].insert(0, measure("1a", "conversion"))
        r = number_reactions(inv, table1_handles())
        a = table1_answer(TABLE1[1])
        a["outcomes"] = [out(98, "conv", ">98", qualifier=">"), out(98, "yields", "98", measure=1),
                         out(49, "yields", measure=2), out(44, "yields", measure=3), out(0, "yields", measure=4)]
        self.assertEqual(validate_reaction(a, REACTION_SCHEMA, inv, r[1], DOC_PAGES)[0], [])
        _, _, child, _ = synthesize(inv, r[1], a, TEMPLATE_CROPS, {})
        self.assertEqual([(o["product_key"], o["yield_type"]) for o in child["outcomes"]],
                         [(None, "conversion"), (None, "conversion"), ("3a", "NMR"), ("3a-prime", "NMR"), ("1a-prime", "NMR")])
        inv["columns"][4]["measures"].append(measure("3a", "ee"))
        a["outcomes"].append(out(92, "yields", "92", measure=5))
        self.assertHas(validate_reaction(a, REACTION_SCHEMA, inv, r[1], DOC_PAGES)[0], "an ee is not an outcome of its own")


class RowRules(unittest.TestCase):
    """Footnotes on the row, split rows, labels printed in the row, open alternatives."""

    def assertHas(self, messages, fragment):
        self.assertTrue(any(fragment in m for m in messages), f"no message containing {fragment!r}: {messages}")

    def test_cell_does_not_overwrite_its_footnote(self):
        inv, r = table1_reactions()
        a = table1_answer(TABLE1[1])  # entry 2, footnote b: FeCl2 (5 mol %)
        a["overrides"][0] = ov("cat", "replace", "FeCl2", "0.5 mol%", basis="cell + header")
        self.assertHas(validate_reaction(a, REACTION_SCHEMA, inv, r[1], DOC_PAGES)[0],
                       "footnote b already sets 'cat' for this reaction (amount '5 mol %')")
        self.assertEqual(validate_reaction(table1_answer(TABLE1[1]), REACTION_SCHEMA, inv, r[1], DOC_PAGES)[0], [])

    def test_split_row_writes_what_sets_it_apart(self):
        inv = table1_entries()
        inv["entries"][4]["cells"][4]["text"] = "rt: 40, 60 °C: 80"
        h = table1_handles()
        h["reactions"][4]["results"][1]["part"] = "rt: 40"
        h["reactions"][4]["distinguishing"] = "rt"
        second = copy.deepcopy(h["reactions"][4])
        second["results"] = [{"column": "yields", "part": "60 °C: 80"}]
        second["distinguishing"] = "60 °C"
        h["reactions"].insert(5, second)
        self.assertEqual(validate_handles(h, inv, HANDLES_SCHEMA)[0], [])
        r60 = number_reactions(inv, h)[5]
        a = answer_with(outcomes=[out(80, "yields", "80", "3a", measure=1)], row=TABLE1[4])
        self.assertHas(validate_reaction(a, REACTION_SCHEMA, inv, r60, DOC_PAGES)[0], "yours is set apart by '60 °C'")
        a["overrides"].append(ov("temp", "replace", "60 °C", basis="printed with the result"))
        self.assertEqual(validate_reaction(a, REACTION_SCHEMA, inv, r60, DOC_PAGES)[0], [])

    def test_equal_parts_when_the_cell_prints_them_twice(self):
        inv = table1_entries()
        inv["entries"][4]["cells"][4]["text"] = "45/45"
        h = table1_handles()
        h["reactions"][4]["results"][1]["part"] = "45"
        h["reactions"][4]["distinguishing"] = "[Fe]"
        second = {**copy.deepcopy(h["reactions"][4]), "distinguishing": "[Ni]",
                  "results": [{"column": "yields", "part": "45"}]}
        h["reactions"].insert(5, second)
        self.assertEqual(validate_handles(h, inv, HANDLES_SCHEMA)[0], [])
        inv["entries"][4]["cells"][4]["text"] = "45/50"
        self.assertHas(validate_handles(h, inv, HANDLES_SCHEMA)[0], "more often than the cell prints it")

    def test_protocol_label_printed_in_the_row(self):
        inv = table1_entries()
        inv["template"]["variants"] = [{"key": "in-situ", "title": "[in situ]", "conditions_given": True,
                                        "overrides": [], "notes": ""}]
        inv["entries"][12]["cells"][1]["text"] = "[Cu] [in situ]"
        h = table1_handles()
        self.assertHas(validate_handles(h, inv, HANDLES_SCHEMA)[0],
                       "prints the label of variant ['in-situ'] for this reaction, but its variant is None")
        h["reactions"][12]["variant"] = "in-situ"
        self.assertEqual(validate_handles(h, inv, HANDLES_SCHEMA)[0], [])
        h["reactions"][11]["variant"] = "in-situ"
        self.assertHas(validate_handles(h, inv, HANDLES_SCHEMA)[1], "the label of variant 'in-situ' is not printed in this row")

    def test_alternatives_need_a_default_and_header_footnotes_no_overrides(self):
        inv = table1_entries()
        t = inv["template"]
        t["participants"].append(tpart("1b", "reactant", "1b", generic=False, bbox=[315, 82, 350, 98]))
        t["steps"][0]["reactants"].append("1b")
        t["alternative_groups"] = [{"keys": ["1a", "1b"], "default": None, "basis": "x", "stated_at": None, "inferred": False}]
        self.assertTrue(any("have no default" in e for e in validate_table(strip_ids(inv), ENTRIES_SCHEMA, SIZES, 13, DOC_PAGES)[0]))
        inv = table1_entries()
        inv["template"]["footnotes"][0]["overrides"] = [ov("1a", "replace", amount="0.5 mmol")]
        self.assertHas(validate_table(strip_ids(inv), ENTRIES_SCHEMA, SIZES, 13, DOC_PAGES)[0],
                       "footnote 'a' has overrides, but no row prints its marker")

    def test_footnote_that_swaps_what_a_column_gives(self):
        """Paper 10, footnotes b and e: a row's footnote swaps the reactant an amount column gives, or
        names the catalyst whose printed value the column's values resolve; the cells apply through it."""
        inv = table1_entries()
        t = inv["template"]
        t["participants"].append(tpart("2b", "reactant", "2b", generic=False))
        t["steps"][0]["reactants"].append("2b")
        t["alternative_groups"] = [{"keys": ["2a", "2b"], "default": "2a", "basis": "header", "stated_at": None,
                                    "inferred": False}]
        t["footnotes"][1]["overrides"] = [ov("2b", "use")]                  # b (entry 2): 2b instead of 2a
        t["footnotes"][2]["overrides"] = [ov("cat", "replace", "FeBr2")]    # c (entries 3, 4): FeBr2 instead of C1
        inv["columns"][1]["values"] = [value("C1", "Fe(BF-Phos)Cl2", structure_key="C1")]
        inv["columns"].insert(3, column("equiv", "amount", "equiv. 2a", "2a", unit="equiv"))
        for en in inv["entries"]:
            en["cells"].insert(3, cell("equiv", "1.5"))
        r = number_reactions(inv, table1_handles())
        a = table1_answer(TABLE1[1])
        self.assertHas(validate_reaction(a, REACTION_SCHEMA, inv, r[1], DOC_PAGES)[0],
                       "gives the amount of '2b' for this row ('1.5') (the column's '2a' is '2b' in this reaction)")
        a["overrides"].append(ov("2b", "replace", amount="1.5 equiv", basis="cell equiv. 2a"))
        self.assertEqual(validate_reaction(a, REACTION_SCHEMA, inv, r[1], DOC_PAGES)[0], [])
        a = table1_answer(TABLE1[2])
        a["overrides"] = a["overrides"][1:] + [ov("2a", "replace", amount="1.5 equiv", basis="cell")]
        self.assertEqual(validate_reaction(a, REACTION_SCHEMA, inv, r[2], DOC_PAGES)[0], [])

    def test_condition_added_by_the_variant_can_be_changed(self):
        """Paper 2, entry 14: the [in situ] variant adds 'HATU or HBTU'; the row's lookup names HBTU."""
        inv = table1_entries()
        inv["template"]["variants"] = [{"key": "in-situ", "title": "[in situ]", "conditions_given": True, "notes": "",
                                        "overrides": [ov("activator", "add", "HATU or HBTU", role="reagent")]}]
        inv["entries"][12]["cells"][1]["text"] = "[Cu] [in situ]"
        h = table1_handles()
        h["reactions"][12]["variant"] = "in-situ"
        r = number_reactions(inv, h)
        a = table1_answer(TABLE1[12])
        a["lookup"] = [ov("activator", "replace", "HBTU", stated_at={"doc": "si", "page": 16}, basis="SI p16")]
        self.assertEqual(validate_reaction(a, REACTION_SCHEMA, inv, r[12], DOC_PAGES)[0], [])
        self.assertHas(validate_reaction(a, REACTION_SCHEMA, inv, r[11], DOC_PAGES)[0],
                       "override replace 'activator' targets an unknown key")

    def test_change_to_a_removed_compound_is_an_error(self):
        inv, r = table1_reactions()
        a = table1_answer(TABLE1[0])
        a["overrides"] = [ov("cat", "remove"), ov("additive", "remove"), ov("additive", "replace", "LiCl")]
        self.assertHas(validate_reaction(a, REACTION_SCHEMA, inv, r[0], DOC_PAGES)[0],
                       "entry: replace 'additive' has no effect: 'additive' was removed by entry")


class Provenance(unittest.TestCase):
    """A name found in the text or SI identifies a compound; it neither swaps it nor unlinks its drawing."""

    def record_of(self, answer, n=5, inv=None):
        inv = inv or table1_entries()
        r = number_reactions(inv, table1_handles())[n - 1]
        inv = {**inv, "_meta": {"status": "ok", "errors": [], "warnings": []}}
        handles = {**table1_handles(), "reactions": number_reactions(inv, table1_handles()),
                   "_meta": {"status": "ok", "errors": [], "warnings": []}}
        _, records, _ = assemble_view(REGION, BLOCK, "s", inv, "ok", handles, "ok",
                                      {r["rid"]: ({**answer, "_meta": {}}, "ok")}, TEMPLATE_CROPS,
                                      {k: f"c/_structure__{k}.png" for k in LEGEND}, {})
        return records[0]

    def test_lookup_name_keeps_drawing_and_label(self):
        a = table1_answer(TABLE1[4])
        a["lookup"] = [ov("2a", "replace", "cyclopentylmagnesium bromide", stated_at={"doc": "si", "page": 31})]
        p2a = next(p for p in self.record_of(a)["steps"][0]["reactants"] if p["key"] == "2a")
        self.assertEqual((p2a["source"], p2a["label"], p2a["text"], p2a["crop"]),
                         ("drawn", "2a", "cyclopentylmagnesium bromide", "c/_template__2a.png"))

    def test_lookup_amount_keeps_the_name_printed(self):
        a = table1_answer(TABLE1[4])
        a["lookup"] = [ov("cat", "replace", amount="0.001 mmol, 0.5 mol%", stated_at={"doc": "si", "page": 31})]
        cat = {c["key"]: c for c in self.record_of(a)["steps"][0]["conditions"]}["cat"]
        self.assertEqual((cat["text"], cat["structure"]["key"], cat["stated_at"], cat["amount_stated_at"]),
                         ("Fe(BF-Phos)Cl2", "C1", None, {"doc": "si", "page": 31}))

    def test_lookup_rename_keeps_the_drawn_condition(self):
        a = table1_answer(TABLE1[4])
        a["lookup"] = [ov("cat", "replace", "Fe(BF-Phos)Cl2 (CCDC 2302824)", stated_at={"doc": "si", "page": 29})]
        cat = {c["key"]: c for c in self.record_of(a)["steps"][0]["conditions"]}["cat"]
        self.assertEqual((cat["text"], cat["structure"]["key"]), ("Fe(BF-Phos)Cl2 (CCDC 2302824)", "C1"))

    def test_swap_stays_a_swap_after_a_lookup(self):
        a = table1_answer(TABLE1[4])
        a["overrides"].append(ov("1a", "replace", "alkyl-I", basis="deviation"))
        a["lookup"] = [ov("1a", "replace", amount="0.3 mmol", stated_at={"doc": "si", "page": 12})]
        p1a = next(p for p in self.record_of(a)["steps"][0]["reactants"] if p["key"] == "1a")
        self.assertEqual((p1a["label"], p1a["text"], p1a["source"], p1a["amount_origin"]), (None, "alkyl-I", "text", "lookup"))

    def test_swap_to_a_legend_drawing(self):
        inv = table1_entries()
        inv["template"]["structures"].append({"key": "1c", "label": "1c", "text": None, "page": 2, "bbox": [320, 330, 350, 350]})
        a = table1_answer(TABLE1[4])
        a["overrides"].append(ov("1a", "replace", "1c", structure_key="1c", basis="row"))
        p1a = next(p for p in self.record_of(a, inv=inv)["steps"][0]["reactants"] if p["key"] == "1a")
        self.assertEqual((p1a["label"], p1a["source"], p1a["bbox"], p1a["crop"]), ("1c", "drawn", [320, 330, 350, 350], None))

    def test_unnumbered_rows_are_labelled_by_their_drawing(self):
        inv = drawn_ligand_table()
        handles = {"reactions": [{"entry": n, "results": [{"column": "yields", "part": None}], "variant": None,
                                  "footnote_markers": [], "distinguishing": None} for n in (1, 2)],
                   "notes": [], "issues": []}
        reactions = number_reactions(inv, handles)
        a = {"template_check": [], "lookup": [], "related": [], "notes": "", "issues": [],
             "overrides": [ov("ligand", "replace", "IMes·HCl", structure_key="e002-ligand", basis="drawn")],
             "outcomes": [out(24, "yields", "24%", measure=1), out(20, "yields", "20%", measure=2)]}
        unit, row, child, crops = synthesize(inv, reactions[1], a, TEMPLATE_CROPS, {})
        self.assertEqual((unit["label"], row["label"]), ("IMes", None))


class StrictSchemas(unittest.TestCase):
    def test_every_object_is_closed_and_fully_required(self):
        """Codex's structured outputs: every property required, no extra properties."""
        def walk(node, path):
            if isinstance(node, dict):
                if "properties" in node:
                    self.assertIs(node.get("additionalProperties"), False, path)
                    self.assertEqual(sorted(node["required"]), sorted(node["properties"]), path)
                for k, v in node.items():
                    walk(v, f"{path}/{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")
        for name in build_extract.SCHEMAS:
            walk(json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text()), name)


if __name__ == "__main__":
    unittest.main()
