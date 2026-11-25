"""The reactant-table path of Step 2 (pipeline/extract_rtable.py): validators, the participants
the pipeline builds from a row, assembly into records and views.

The fixtures are small tables written out by hand as the two skills would answer, one per way a
reactant table prints its rows: both reactants drawn in every row with the product never drawn
(the fixture the path was built against), blanks that repeat the row above with a partly drawn product
column, one drawing shared by several rows with a variable value per row, and a "compound / R"
table with a result printed once for every row."""

import copy
import json
import unittest
from pathlib import Path

from pipeline.extract_ctable import assemble_view
from pipeline.extract_rtable import (OPS, base_row, number_reactions, reaction_cells, resolve_cells, synthesize,
                                     validate_handles, validate_reaction, validate_table)
from pipeline.extract_view import block_view
from pipeline.schemas import build_extract
from pipeline.steps.s2_rtable import stage2_task
from tests.test_extract_records import cond, ov, step, tpart

SCHEMA_DIR = Path(build_extract.__file__).parent
ENTRIES_SCHEMA = json.loads((SCHEMA_DIR / "rtable_entries.schema.json").read_text())
HANDLES_SCHEMA = json.loads((SCHEMA_DIR / "rtable_handles.schema.json").read_text())
REACTION_SCHEMA = json.loads((SCHEMA_DIR / "rtable_reaction.schema.json").read_text())
SIZES = {1: (600.0, 800.0), 2: (600.0, 800.0)}
DOC_PAGES = {"main": 2, "si": 20}
REGION = {"region_id": "main:table2", "doc": "main", "label": "Table 2", "first_page": 2,
          "caption": "Table 2. Cross-couplings of secondary alkyl halides (eq 1)"}
BLOCK = {"block_id": "1", "kind": "substrate_scope", "layout": "reactant_table", "page": 2, "title": None,
         "bbox": [80, 70, 270, 260]}


# ------------------------------------------------------------------ builders

def column(key, kind, header="", targets=(), measures=(), blank_means=None, variable_name=None, unit=None,
           values=()):
    return {"key": key, "header": header, "kind": kind, "targets": list(targets), "variable_name": variable_name,
            "unit": unit, "values": list(values), "measures": list(measures), "blank_means": blank_means, "notes": ""}


def measure(participant_key, kind="yield", yield_type=None):
    return {"participant_key": participant_key, "measure": kind, "yield_type": yield_type}


def cell(col, text="", markers=(), structure_bbox=None, same_as=None):
    return {"column": col, "text": text, "markers": list(markers), "structure_bbox": structure_bbox,
            "same_as": same_as}


def row(label, page, bbox, cells, descriptor="", lookup_hint=None):
    return {"label": label, "page": page, "bbox": bbox, "descriptor": descriptor or label or "", "cells": cells,
            "lookup_hint": lookup_hint}


def derivation(key, sources, how):
    return {"key": key, "from": list(sources), "how": how}


def template(participants, steps, conditions=(), derivations=(), shared_results=(), footnotes=(),
             variable_defaults=(), default_yield_type=None):
    return {"general_reaction": "test", "reading_guide": "test", "scheme": None,
            "participants": list(participants), "alternative_groups": [], "steps": list(steps),
            "conditions": list(conditions), "structures": [], "footnotes": list(footnotes), "preparations": [],
            "variable_defaults": list(variable_defaults), "default_yield_type": default_yield_type, "variants": [],
            "context": [], "derivations": list(derivations), "shared_results": list(shared_results),
            "lookup_guide": "SI pages 6-9: one paragraph per product, matched by the entry reference"}


def numbered(inv):
    inv = copy.deepcopy(inv)
    for i, en in enumerate(inv["entries"], 1):
        en["eid"] = f"e{i:03d}"
    return inv


def handle(entry, results, markers=(), distinguishing=None, cells=()):
    return {"entry": entry, "results": [{"column": c, "part": p} for c, p in results], "variant": None,
            "footnote_markers": list(markers), "distinguishing": distinguishing, "cells": list(cells)}


def out(value, column, text=None, product_key=None, yield_type=None, qualifier=None, measure=None, selectivity=()):
    return {"product_key": product_key, "yield_text": text if text is not None else str(value), "yield_value": value,
            "yield_qualifier": qualifier, "yield_type": yield_type, "selectivity": list(selectivity),
            "footnote_markers": [], "notes": None, "column": column, "measure": measure}


def answer(outcomes, overrides=(), lookup=(), labels=(), template_check=(), issues=()):
    return {"template_check": list(template_check), "overrides": list(overrides), "outcomes": list(outcomes),
            "lookup": list(lookup), "labels": list(labels), "related": [], "notes": "", "issues": list(issues)}


def assemble(inv, handles, answers, template_crops=None, cell_crops=None):
    """Records and view of a table, as publish() builds them from what is on disk."""
    inv = {**inv, "_meta": {"status": "ok", "errors": [], "warnings": [], "overlays": []}}
    reactions = number_reactions(inv, handles)
    handles = {**handles, "reactions": reactions, "_meta": {"status": "ok", "errors": [], "warnings": []}}
    stored = {r["rid"]: ({**answers[r["rid"]], "_meta": {"errors": [], "warnings": [], "seconds": 1}}, "ok")
              for r in reactions if r["rid"] in answers}
    if cell_crops is None:
        cell_crops = {f"{en['eid']}-{c['column']}": f"c/_cell__{en['eid']}-{c['column']}.png"
                      for en in inv["entries"] for c in en["cells"] if c["structure_bbox"] is not None}
    return assemble_view(REGION, BLOCK, "main-table2__1", inv, "ok", handles, "ok", stored, template_crops or {}, {},
                         cell_crops, ops=OPS)


def parts_of(record):
    return {p["key"]: p for st in record["steps"] for p in st["reactants"] + st["products"]}


# ------------------------------------------------------------------ both reactants drawn, product never drawn

YIELDS_T2 = [66, 62, 68, 62, 78, 88]


def coupling_template():
    """eq 1: R–X + YZn–R1 -> R–R1 with a Ni/Pybox catalyst, drawn on page 1."""
    return template(
        [tpart("rx", "reactant", text="R_alkyl–X", bbox=[310, 600, 345, 615]),
         tpart("rzn", "reactant", text="YZn–R1_alkyl", amount="1.6 equiv", bbox=[350, 600, 395, 615]),
         tpart("product", "product", text="R_alkyl–R1_alkyl", bbox=[470, 600, 530, 615])],
        [step(1, ["rx", "rzn"], ["product"])],
        [cond("cat", "catalyst", "Ni(cod)2", "4%"), cond("ligand", "ligand", "s-Bu-Pybox", "8%"),
         cond("solvent", "solvent", "DMA"), cond("temp", "temperature", "r.t.")],
        derivations=[derivation("product", ["rx", "rzn"],
                                "the carbon that carries X bonds to the carbon that carries Zn; X and ZnY leave")],
        default_yield_type="isolated")


def coupling_table(yields=YIELDS_T2):
    rows = []
    for i, y in enumerate(yields):
        top = 90 + 25 * i
        rows.append(row(str(i + 1), 2, [85, top, 265, top + 22],
                        [cell("entry", str(i + 1)),
                         cell("rx", structure_bbox=[110, top + 2, 160, top + 20]),
                         cell("rzn", structure_bbox=[170, top + 2, 230, top + 20]),
                         cell("yield", str(y))]))
    return {"template": coupling_template(),
            "columns": [column("entry", "entry_number", "entry"),
                        column("rx", "participant", "R_alkyl–X", ["rx"]),
                        column("rzn", "participant", "YZn–R1_alkyl", ["rzn"]),
                        column("yield", "outcome", "yield (%)", measures=[measure("product", "yield", "isolated")])],
            "entries": rows, "ignored": [], "notes": ""}


def coupling_handles(n=6):
    return {"reactions": [handle(i, [("yield", None)]) for i in range(1, n + 1)], "notes": [], "issues": []}


def coupling_answers(inv, handles, names=True):
    out_ = {}
    for r, y in zip(number_reactions(inv, handles), YIELDS_T2):
        lookup = [ov("product", "replace", f"product of entry {r['entry']}", basis="SI paragraph",
                     stated_at={"doc": "si", "page": 6})] if names else []
        out_[r["rid"]] = answer([out(y, "yield", product_key="product")], lookup=lookup)
    return out_


class BothReactantsDrawn(unittest.TestCase):
    def test_reproduces_the_table(self):
        inv = coupling_table()
        self.assertEqual(validate_table(inv, ENTRIES_SCHEMA, SIZES, 6, DOC_PAGES), ([], []))
        inv = numbered(inv)
        handles = coupling_handles()
        self.assertEqual(validate_handles(handles, inv, HANDLES_SCHEMA), ([], []))
        answers = coupling_answers(inv, handles)
        for r in number_reactions(inv, handles):
            self.assertEqual(validate_reaction(answers[r["rid"]], REACTION_SCHEMA, inv, r, DOC_PAGES), ([], []))
        crops = {"rx": "c/_template__rx.png", "rzn": "c/_template__rzn.png", "product": "c/_template__product.png"}
        view, records, counts = assemble(inv, handles, answers, template_crops=crops)
        self.assertEqual((len(records), counts["reactions_ok"]), (6, 6))
        parts = parts_of(records[0])
        rx, product = parts["rx"], parts["product"]
        # The row's drawing of the bromide, not the generic one of eq 1, and no name copied from the template.
        self.assertEqual((rx["source"], rx["page"], rx["bbox"], rx["crop"]),
                         ("drawn", 2, [110, 92, 160, 110], "c/_cell__e001-rx.png"))
        self.assertFalse(rx["text"])
        self.assertEqual(parts["rzn"]["amount"], "1.6 equiv")
        # The product is unknown: the generic drawing, how it follows, and the name the SI gives.
        self.assertEqual((product["source"], product["generic"], product["unknown"], product["crop"]),
                         ("derived", True, True, "c/_template__product.png"))
        self.assertFalse(rx["unknown"])
        self.assertIn("unknown, to be derived", product["basis"])
        self.assertEqual((product["text"], product["stated_at"]), ("product of entry 1", {"doc": "si", "page": 6}))
        self.assertEqual(product["outcomes"][0]["yield"]["type"], "isolated")
        self.assertEqual(records[0]["issues"], [])
        json.dumps(block_view(view))

    def test_unknown_participant_needs_a_derivation(self):
        inv = coupling_table()
        inv["template"]["derivations"] = []
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 6, DOC_PAGES)
        self.assertTrue(any("participant 'product' is generic and rows" in e for e in errors), errors)
        inv["template"]["derivations"] = [derivation("product", ["rx", "product"], "x")]
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 6, DOC_PAGES)
        self.assertTrue(any("does not follow from itself" in e for e in errors), errors)
        inv["template"]["derivations"] = [derivation("product", ["rx", "rzn"], "x")]
        inv["template"]["participants"][2]["generic"] = False
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 6, DOC_PAGES)
        self.assertTrue(any("generic true" in e for e in errors), errors)

    def test_columns_point_at_positions(self):
        inv = coupling_table()
        inv["columns"][1]["targets"] = ["rx", "rzn"]
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 6, DOC_PAGES)
        self.assertTrue(any("exactly one target" in e for e in errors), errors)
        inv = coupling_table()
        inv["columns"][3]["kind"] = "other"
        inv["columns"][3]["measures"] = []
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 6, DOC_PAGES)
        self.assertTrue(any("no outcome column" in e for e in errors), errors)

    def test_the_row_compounds_are_the_pipelines(self):
        inv = numbered(coupling_table())
        handles = coupling_handles()
        r = number_reactions(inv, handles)[0]
        a = answer([out(66, "yield", product_key="product")],
                   overrides=[ov("rx", "replace", "cycloheptyl bromide", basis="row")])
        errors, _ = validate_reaction(a, REACTION_SCHEMA, inv, r, DOC_PAGES)
        self.assertTrue(any("the pipeline applies it" in e for e in errors), errors)
        # A name found in the SI is a lookup, and keeps the row's drawing.
        a = answer([out(66, "yield", product_key="product")],
                   lookup=[ov("rx", "replace", "4-bromo-1-tosylpiperidine", basis="SI", stated_at={"doc": "si", "page": 6})])
        self.assertEqual(validate_reaction(a, REACTION_SCHEMA, inv, r, DOC_PAGES), ([], []))
        _, records, _ = assemble(inv, handles, {r["rid"]: a})
        rx = parts_of(records[0])["rx"]
        self.assertEqual((rx["source"], rx["bbox"], rx["text"]), ("drawn", [110, 92, 160, 110], "4-bromo-1-tosylpiperidine"))

    def test_labels_found_in_the_si(self):
        inv = numbered(coupling_table())
        handles = coupling_handles()
        r = number_reactions(inv, handles)[0]
        a = answer([out(66, "yield", product_key="product")],
                   labels=[{"key": "product", "label": "5a", "stated_at": {"doc": "si", "page": 7}}])
        self.assertEqual(validate_reaction(a, REACTION_SCHEMA, inv, r, DOC_PAGES), ([], []))
        _, records, _ = assemble(inv, handles, {r["rid"]: a})
        product = parts_of(records[0])["product"]
        self.assertEqual((product["label"], product["stated_at"], product["source"]),
                         ("5a", {"doc": "si", "page": 7}, "derived"))
        bad = answer([out(66, "yield", product_key="product")],
                     labels=[{"key": "nope", "label": "5a", "stated_at": None}])
        errors, _ = validate_reaction(bad, REACTION_SCHEMA, inv, r, DOC_PAGES)
        self.assertEqual(len([e for e in errors if e.startswith("labels[0]")]), 2, errors)

    def test_stage2_task(self):
        inv = numbered(coupling_table())
        handles = coupling_handles()
        r = number_reactions(inv, handles)[2]
        extra = stage2_task({"entry": {"eid": "e003"}}, inv, handles, r)
        states = {p["key"]: (p["source"], p["state"]) for p in extra["participants"]}
        self.assertEqual(states, {"rx": ("drawn", "cell"), "rzn": ("drawn", "cell"), "product": ("derived", "unknown")})
        self.assertEqual(extra["cannot_derive"], [])
        self.assertIsNone(extra["entry"]["lookup_hint"])
        self.assertEqual([c["structure_key"] for c in extra["row_cells"]], [None, "e003-rx", "e003-rzn", None])


# ------------------------------------------------------------------ blanks repeat the row above

def ditto_table():
    """Substrate and product drawn, blanks meaning 'as above'; the diarylzinc has no column and is
    seen only in the product drawings. Footnotes change an amount, swap the reagent, or mark a second
    experiment of the row (a value in parentheses)."""
    t = template(
        [tpart("bnx", "reactant", text="benzyl halide"),
         tpart("ar2zn", "reactant", text="Ar2Zn", amount="1.0 mmol"),
         tpart("product", "product", text="diarylmethane")],
        [step(1, ["bnx", "ar2zn"], ["product"])],
        [cond("cat", "catalyst", "6", "5 mol%"), cond("solvent", "solvent", "toluene"), cond("temp", "temperature", "45 °C")],
        derivations=[derivation("ar2zn", ["bnx", "product"], "Ar is the aryl group of the product that is not the benzyl part")],
        footnotes=[{"marker": "d", "text": "30 mmol scale.", "notes": "",
                    "overrides": [ov("bnx", "replace", amount="30 mmol", basis="footnote d")]},
                   {"marker": "e", "text": "0.5 mmol Ar2Zn.", "notes": "",
                    "overrides": [ov("ar2zn", "replace", amount="0.5 mmol", basis="footnote e")]},
                   {"marker": "g", "text": "ArZnCl (2.0 mmol).", "notes": "",
                    "overrides": [ov("ar2zn", "replace", "ArZnCl", "2.0 mmol", basis="footnote g")]}])

    def r(n, sub, prod, conv, iso="", conv_markers=()):
        top = 80 + 40 * (n - 1)
        return row(str(n), 2, [50, top, 290, top + 36],
                   [cell("entry", str(n)), sub(top), prod(top), cell("conv", conv, conv_markers), cell("iso", iso)])

    drawn = lambda col, x0: (lambda top: cell(col, structure_bbox=[x0, top + 2, x0 + 60, top + 30]))
    same = lambda col, k: (lambda top: cell(col, same_as=k))
    return {"template": t,
            "columns": [column("entry", "entry_number", "Entry"),
                        column("sub", "participant", "Electrophilic substrate", ["bnx"], blank_means="as in the row above"),
                        column("prod", "participant", "Product", ["product"], blank_means="as in the row above"),
                        column("conv", "outcome", "Conv. to product (%)", measures=[measure("product", "yield", "NMR")]),
                        column("iso", "outcome", "Isolated yield (%)", measures=[measure("product", "yield", "isolated")])],
            "entries": [r(1, drawn("sub", 60), drawn("prod", 140), "94 (95)", "92", ["d"]),
                        r(2, same("sub", 1), same("prod", 1), "49", conv_markers=["e"]),
                        r(3, same("sub", 2), same("prod", 2), "50", conv_markers=["g"]),
                        r(4, drawn("sub", 60), same("prod", 3), "83"),
                        r(5, drawn("sub", 60), drawn("prod", 140), "97", "58")],
            "ignored": [], "notes": ""}


def ditto_handles():
    return {"reactions": [
        handle(1, [("conv", "94"), ("iso", None)], distinguishing="standard scale"),
        handle(1, [("conv", "(95)")], markers=["d"], distinguishing="30 mmol scale"),
        handle(2, [("conv", None)], markers=["e"]),
        handle(3, [("conv", None)], markers=["g"]),
        handle(4, [("conv", None)]),
        handle(5, [("conv", None), ("iso", None)]),
    ], "notes": [{"entry": 1, "text": "the value in parentheses is the 30 mmol run (footnote d)"}], "issues": []}


def ditto_answers(reactions):
    values = {"e001-1": [out(94, "conv", product_key="product"), out(92, "iso", product_key="product")],
              "e001-2": [out(95, "conv", "(95)", product_key="product")],
              "e002-1": [out(49, "conv", product_key="product")], "e003-1": [out(50, "conv", product_key="product")],
              "e004-1": [out(83, "conv", product_key="product")],
              "e005-1": [out(97, "conv", product_key="product"), out(58, "iso", product_key="product")]}
    return {r["rid"]: answer(values[r["rid"]]) for r in reactions}


class NoEntries(unittest.TestCase):
    def test_a_table_without_entries_is_an_error(self):
        inv = coupling_table(); inv["entries"] = []
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 6, DOC_PAGES)
        self.assertTrue(any("no entries listed" in e for e in errors), errors)


class RepeatedCells(unittest.TestCase):
    def test_validates(self):
        inv = ditto_table()
        self.assertEqual(validate_table(inv, ENTRIES_SCHEMA, SIZES, 5, DOC_PAGES), ([], []))
        inv = numbered(inv)
        self.assertEqual(validate_handles(ditto_handles(), inv, HANDLES_SCHEMA), ([], []))
        reactions = number_reactions(inv, ditto_handles())
        answers = ditto_answers(reactions)
        for r in reactions:
            errors, warnings = validate_reaction(answers[r["rid"]], REACTION_SCHEMA, inv, r, DOC_PAGES)
            self.assertEqual(errors, [], r["rid"])
            # The run of the split row that keeps the template has nothing to write: a reminder, not an error.
            self.assertEqual(len(warnings), r["rid"] == "e001-1", (r["rid"], warnings))

    def test_repeats_resolve_to_the_printed_cell(self):
        inv = numbered(ditto_table())
        cells = resolve_cells(inv, 3)  # row 3 -> row 2 -> row 1
        self.assertEqual((cells["sub"]["structure_key"], cells["sub"]["from_row"], cells["sub"]["structure_bbox"]),
                         ("e001-sub", 1, [60, 82, 120, 110]))
        self.assertEqual(cells["conv"]["markers"], ["g"])
        self.assertEqual(resolve_cells(inv, 4)["prod"]["structure_key"], "e001-prod")
        self.assertIsNone(resolve_cells(inv, 4)["sub"]["from_row"])

    def test_records(self):
        inv = numbered(ditto_table())
        reactions = number_reactions(inv, ditto_handles())
        view, records, counts = assemble(inv, ditto_handles(), ditto_answers(reactions))
        self.assertEqual((len(records), counts["reactions_ok"]), (6, 6))
        by = {r["source"]["reaction_id"]: r for r in records}
        # Row 2 repeats the substrate and product of row 1; footnote e changes the amount of the reagent,
        # which the row does not print and which follows from the product.
        p = parts_of(by["e002-1"])
        self.assertEqual((p["bnx"]["source"], p["bnx"]["bbox"], p["bnx"]["crop"]),
                         ("drawn", [60, 82, 120, 110], "c/_cell__e001-sub.png"))
        self.assertEqual((p["product"]["source"], p["product"]["crop"]), ("drawn", "c/_cell__e001-prod.png"))
        self.assertEqual((p["ar2zn"]["source"], p["ar2zn"]["amount"]), ("derived", "0.5 mmol"))
        self.assertIn("aryl group of the product", p["ar2zn"]["basis"])
        # Footnote g puts a class name in place of the reagent: named, but its aryl group is still to be derived.
        p = parts_of(by["e003-1"])
        self.assertEqual((p["ar2zn"]["source"], p["ar2zn"]["unknown"], p["ar2zn"]["text"], p["ar2zn"]["amount"]),
                         ("derived", True, "ArZnCl", "2.0 mmol"))
        self.assertIn("aryl group of the product", p["ar2zn"]["basis"])
        self.assertEqual(p["ar2zn"]["amount_origin"], "footnote:g")
        self.assertEqual(parts_of(by["e004-1"])["ar2zn"]["amount_origin"], "base")
        # The 30 mmol run of row 1 is its own reaction, with footnote d.
        p = parts_of(by["e001-2"])
        self.assertEqual((p["bnx"]["amount"], by["e001-2"]["footnotes"][0]["marker"]), ("30 mmol", "d"))
        self.assertEqual([o["yield"]["type"] for o in parts_of(by["e001-1"])["product"]["outcomes"]], ["NMR", "isolated"])
        self.assertTrue(all(not r["issues"] for r in records), [r["issues"] for r in records])
        printed = view["entries"][2]["expansion"]["printed"]
        self.assertIn("as in row 1", printed)
        json.dumps(block_view(view))

    def test_bad_repeats(self):
        inv = ditto_table()
        inv["entries"][1]["cells"][1]["same_as"] = 3
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 5, DOC_PAGES)
        self.assertTrue(any("must be the number of an earlier row" in e for e in errors), errors)
        inv = ditto_table()
        inv["entries"][3]["cells"][1]["same_as"] = 1  # a cell that prints its own drawing
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 5, DOC_PAGES)
        self.assertTrue(any("prints nothing of its own" in e for e in errors), errors)
        inv = ditto_table()
        inv["entries"][1]["cells"][4]["same_as"] = 1  # a result
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 5, DOC_PAGES)
        self.assertTrue(any("not for results" in e for e in errors), errors)

    def test_underivable_is_marked_not_refused(self):
        # Without its product, row 4 leaves the reagent without what it follows from.
        inv = ditto_table()
        inv["template"]["derivations"].append(derivation("product", ["bnx", "ar2zn"], "the benzyl carbon bonds to Ar"))
        inv["entries"][3]["cells"][2]["same_as"] = None
        errors, warnings = validate_table(inv, ENTRIES_SCHEMA, SIZES, 5, DOC_PAGES)
        self.assertEqual(errors, [])
        self.assertTrue(any("cannot be derived from this row" in w for w in warnings), warnings)
        inv = numbered(inv)
        reactions = number_reactions(inv, ditto_handles())
        _, records, _ = assemble(inv, ditto_handles(), ditto_answers(reactions))
        rec = next(r for r in records if r["source"]["reaction_id"] == "e004-1")
        self.assertTrue(any("cannot be derived from this row" in x for x in rec["issues"]), rec["issues"])
        self.assertEqual(parts_of(rec)["product"]["source"], "derived")


# ------------------------------------------------------------------ one drawing for several rows

def shared_drawing_table():
    t = template(
        [tpart("elec", "reactant", text="R3Si–CH(Br)–alkyl", bbox=[310, 80, 360, 100]),
         tpart("nuc", "reactant", label=None, text="(2-(1,3-dioxolan-2-yl)ethyl)zinc bromide", generic=False,
               bbox=[370, 80, 410, 100]),
         tpart("product", "product", text="R3Si–CH(alkyl)–CH2CH2-dioxolane", bbox=[470, 80, 530, 100])],
        [step(1, ["elec", "nuc"], ["product"])],
        derivations=[derivation("product", ["elec", "nuc"], "the C–Br carbon of the electrophile bonds to the CH2 "
                                                             "that carries Zn; the red alkyl part carries over")],
        default_yield_type="isolated")
    t["participants"][1]["page"] = t["participants"][0]["page"] = t["participants"][2]["page"] = 2
    rows = []
    for n, x, ee, y in ((1, "X = H", "93", "74"), (2, "X = OMe", "92", "86"), (3, "X = Cl", "91", "55")):
        top = 300 + 18 * (n - 1)
        sub = cell("elec", structure_bbox=[340, 300, 420, 350]) if n == 1 else cell("elec", same_as=1)
        rows.append(row(str(n + 3), 2, [310, top, 560, top + 16] if n > 1 else [310, 300, 560, 352],
                        [cell("entry", str(n + 3)), sub, cell("x", x), cell("ee", ee), cell("yield", y)]))
    return {"template": t,
            "columns": [column("entry", "entry_number", "Entry"),
                        column("elec", "participant", "Electrophile", ["elec"]),
                        column("x", "variable", "", ["elec"], variable_name="X"),
                        column("ee", "outcome", "ee [%]", measures=[measure("product", "ee")]),
                        column("yield", "outcome", "Yield [%]", measures=[measure("product", "yield", "isolated")])],
            "entries": rows, "ignored": [], "notes": ""}


class SharedDrawing(unittest.TestCase):
    def test_variable_per_row(self):
        inv = shared_drawing_table()
        self.assertEqual(validate_table(inv, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES), ([], []))
        inv = numbered(inv)
        handles = {"reactions": [handle(i, [("ee", None), ("yield", None)]) for i in (1, 2, 3)], "notes": [], "issues": []}
        self.assertEqual(validate_handles(handles, inv, HANDLES_SCHEMA), ([], []))
        reactions = number_reactions(inv, handles)
        answers = {}
        for r, (ee, y) in zip(reactions, (("93", 74), ("92", 86), ("91", 55))):
            answers[r["rid"]] = answer([out(y, "yield", product_key="product",
                                            selectivity=[{"type": "ee", "text": f"{ee}% ee"}])])
            self.assertEqual(validate_reaction(answers[r["rid"]], REACTION_SCHEMA, inv, r, DOC_PAGES), ([], []))
        self.assertEqual(base_row(inv, reactions[1])["variables"], [{"name": "X", "value": "OMe"}])
        _, records, _ = assemble(inv, handles, answers, template_crops={"nuc": "c/_template__nuc.png"})
        p = parts_of(records[1])
        self.assertEqual((p["elec"]["source"], p["elec"]["bbox"], p["elec"]["crop"]),
                         ("drawn", [340, 300, 420, 350], "c/_cell__e001-elec.png"))
        self.assertEqual([(v["name"], v["value"], v["origin"]) for v in p["elec"]["variables"]], [("X", "OMe", "stated")])
        self.assertEqual((p["nuc"]["source"], p["nuc"]["crop"]), ("drawn", "c/_template__nuc.png"))
        self.assertEqual(p["product"]["source"], "derived")
        self.assertEqual(p["product"]["outcomes"][0]["selectivity"], [{"type": "ee", "text": "92% ee"}])
        self.assertEqual(records[1]["label"], "5")

    def test_variable_targets_generic_positions(self):
        inv = shared_drawing_table()
        inv["columns"][2]["targets"] = ["nuc"]
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)
        self.assertTrue(any("generic true" in e for e in errors), errors)


# ------------------------------------------------------------------ "compound / R" table, one result for all rows

def r_table():
    t = template(
        [tpart("ligand", "reactant", text="phenoxyimine ligand", bbox=[320, 70, 380, 120]),
         tpart("fe", "reactant", text="(py)2Fe(CH2SiMe3)2", amount="1.05 equiv", generic=False, bbox=[390, 80, 450, 95]),
         tpart("complex", "product", text="(FI)Fe(CH2SiMe3)(py)", bbox=[470, 60, 550, 130])],
        [step(1, ["ligand", "fe"], ["complex"])],
        [cond("solvent", "solvent", "pentane"), cond("temp", "temperature", "23 °C"), cond("time", "time", "1 h")],
        shared_results=[">90% yields"])
    for p in t["participants"]:
        p["page"] = 2
    rows = [row(None, 2, [445, 150 + 12 * i, 550, 160 + 12 * i], [cell("compound", c), cell("r", rv)])
            for i, (c, rv) in enumerate((("1a", "DIPP"), ("1b", "Mes")))]
    return {"template": t,
            "columns": [column("compound", "label", "Compound", ["complex"]),
                        column("r", "variable", "R", ["ligand", "complex"], variable_name="R")],
            "entries": rows, "ignored": [], "notes": ""}


class CompoundTable(unittest.TestCase):
    def test_records(self):
        inv = r_table()
        errors, warnings = validate_table(inv, ENTRIES_SCHEMA, SIZES, 2, DOC_PAGES)
        self.assertEqual((errors, [w for w in warnings if "prints no result" in w]), ([], []))
        inv = numbered(inv)
        handles = {"reactions": [handle(1, []), handle(2, [])], "notes": [], "issues": []}
        self.assertEqual(validate_handles(handles, inv, HANDLES_SCHEMA), ([], []))
        reactions = number_reactions(inv, handles)
        self.assertEqual(reactions[0]["results_text"], [">90% yields"])
        answers = {r["rid"]: answer([out(90, None, ">90% yields", product_key="complex", qualifier=">")])
                   for r in reactions}
        for r in reactions:
            self.assertEqual(validate_reaction(answers[r["rid"]], REACTION_SCHEMA, inv, r, DOC_PAGES), ([], []))
        _, records, _ = assemble(inv, handles, answers, template_crops={"ligand": "l.png", "fe": "f.png", "complex": "c.png"})
        rec = records[0]
        self.assertEqual(rec["label"], "1a")
        p = parts_of(rec)
        self.assertEqual((p["complex"]["label"], p["complex"]["source"], p["complex"]["crop"]), ("1a", "derived", "c.png"))
        self.assertEqual([(v["name"], v["value"]) for v in p["ligand"]["variables"]], [("R", "DIPP")])
        self.assertEqual([(v["name"], v["value"]) for v in p["complex"]["variables"]], [("R", "DIPP")])
        self.assertIn("R = DIPP", p["complex"]["basis"])
        self.assertFalse(p["complex"]["unknown"])  # the generic drawing with R given is known
        self.assertEqual(p["complex"]["outcomes"][0]["yield"]["text"], ">90% yields")
        self.assertEqual(rec["issues"], [])

    def test_shared_results_only(self):
        inv = numbered(r_table())
        handles = {"reactions": [handle(1, []), handle(2, [])], "notes": [], "issues": []}
        r = number_reactions(inv, handles)[0]
        errors, _ = validate_reaction(answer([out(80, None, "80%", product_key="complex")]), REACTION_SCHEMA, inv, r,
                                      DOC_PAGES)
        self.assertTrue(any("not one of the results printed for the whole table" in e for e in errors), errors)
        inv["template"]["shared_results"] = []
        errors, _ = validate_reaction(answer([out(90, None, ">90% yields", product_key="complex")]), REACTION_SCHEMA,
                                      inv, r, DOC_PAGES)
        self.assertTrue(any("column null is only for" in e for e in errors), errors)


# ------------------------------------------------------------------ a row split on one cell

class SplitCell(unittest.TestCase):
    def table(self):
        inv = coupling_table([70])
        en = inv["entries"][0]
        en["cells"][1] = cell("rx", "1b / 1c")
        en["cells"][3] = cell("yield", "70 / 65")
        return inv

    def test_each_reaction_has_its_part(self):
        inv = self.table()
        self.assertEqual(validate_table(inv, ENTRIES_SCHEMA, SIZES, 1, DOC_PAGES)[0], [])
        inv = numbered(inv)
        handles = {"reactions": [
            handle(1, [("yield", "70")], distinguishing="1b", cells=[{"column": "rx", "part": "1b"}]),
            handle(1, [("yield", "65")], distinguishing="1c", cells=[{"column": "rx", "part": "1c"}]),
        ], "notes": [], "issues": []}
        self.assertEqual(validate_handles(handles, inv, HANDLES_SCHEMA), ([], []))
        reactions = number_reactions(inv, handles)
        self.assertEqual(reaction_cells(inv, reactions[1])["rx"]["text"], "1c")
        answers = {r["rid"]: answer([out(v, "yield", product_key="product")]) for r, v in zip(reactions, (70, 65))}
        for r in reactions:
            self.assertEqual(validate_reaction(answers[r["rid"]], REACTION_SCHEMA, inv, r, DOC_PAGES), ([], []))
        _, records, _ = assemble(inv, handles, answers)
        # Compound numbers: the labels of the two reactions' reactants, their names left open.
        self.assertEqual([(parts_of(r)["rx"]["label"], parts_of(r)["rx"]["text"]) for r in records], [("1b", ""), ("1c", "")])

    def test_bad_parts(self):
        inv = numbered(self.table())
        handles = {"reactions": [
            handle(1, [("yield", "70")], distinguishing="1b", cells=[{"column": "rx", "part": "1d"}]),
            handle(1, [("yield", "65")], distinguishing="1c"),
        ], "notes": [], "issues": []}
        errors, _ = validate_handles(handles, inv, HANDLES_SCHEMA)
        self.assertTrue(any("part '1d' is not in the text" in e for e in errors), errors)
        self.assertTrue(any("must each give their part" in e for e in errors), errors)



# ------------------------------------------------------------------ review cases

class Guards(unittest.TestCase):
    """What the review of the first version found: stage 2 filling an unknown position, a deadlock
    between an amount column and a drawn reactant, mixed variable columns, model compounds taken
    as positions, alternative groups, labels of split rows, scheme leaders per sharing class."""

    def setUp(self):
        self.inv = numbered(coupling_table())
        self.handles = coupling_handles()
        self.r = number_reactions(self.inv, self.handles)[0]

    def test_unknown_positions_are_not_filled_in(self):
        named = answer([out(66, "yield", product_key="product")],
                       overrides=[ov("product", "replace", "cycloheptylcyclohexane", basis="C–Br bonds to C–Zn")])
        errors, _ = validate_reaction(named, REACTION_SCHEMA, self.inv, self.r, DOC_PAGES)
        self.assertTrue(any("worked out later" in e for e in errors), errors)
        guessed = answer([out(66, "yield", product_key="product")],
                         lookup=[ov("product", "replace", "cycloheptylcyclohexane", basis="my reasoning", inferred=True)])
        errors, _ = validate_reaction(guessed, REACTION_SCHEMA, self.inv, self.r, DOC_PAGES)
        self.assertTrue(any("never a name you work out" in e for e in errors), errors)

    def test_amount_of_a_drawn_reactant(self):
        inv = coupling_table()
        inv["columns"].append(column("eq", "amount", "equiv", ["rzn"], unit="equiv"))
        for en in inv["entries"]:
            en["cells"].append(cell("eq", "2.0"))
        self.assertEqual(validate_table(inv, ENTRIES_SCHEMA, SIZES, 6, DOC_PAGES)[0], [])
        inv = numbered(inv)
        r = number_reactions(inv, self.handles)[0]
        a = answer([out(66, "yield", product_key="product")], overrides=[ov("rzn", "replace", amount="2.0 equiv", basis="cell")])
        self.assertEqual(validate_reaction(a, REACTION_SCHEMA, inv, r, DOC_PAGES), ([], []))
        _, records, _ = assemble(inv, self.handles, {r["rid"]: a})
        rzn = parts_of(records[0])["rzn"]
        self.assertEqual((rzn["source"], rzn["amount"]), ("drawn", "2.0 equiv"))

    def test_one_group_per_variable_column(self):
        inv = shared_drawing_table()
        inv["entries"][2]["cells"][2]["text"] = "R = Et"
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)
        self.assertTrue(any("one variable column per group" in e for e in errors), errors)

    def test_partly_defined_product_stays_unknown(self):
        inv = shared_drawing_table()
        inv["columns"][2]["targets"] = ["elec", "product"]  # the product drawing carries X too
        self.assertEqual(validate_table(inv, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)[0], [])
        inv = numbered(inv)
        handles = {"reactions": [handle(i, [("ee", None), ("yield", None)]) for i in (1, 2, 3)], "notes": [], "issues": []}
        reactions = number_reactions(inv, handles)
        answers = {r["rid"]: answer([out(70, "yield", product_key="product")]) for r in reactions}
        _, records, _ = assemble(inv, handles, answers)
        product = parts_of(records[1])["product"]
        self.assertEqual((product["source"], product["unknown"]), ("derived", True))
        self.assertEqual([(v["name"], v["value"]) for v in product["variables"]], [("X", "OMe")])

    def test_model_compounds_are_not_positions(self):
        inv = coupling_table()
        inv["template"]["participants"][0]["generic"] = False  # the scheme's model bromide taken as the position
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 6, DOC_PAGES)
        self.assertTrue(any("is generic (generic true)" in e and "position 'rx'" in e for e in errors), errors)

    def test_a_footnote_picks_the_other_alternative(self):
        inv = coupling_table()
        t = inv["template"]
        t["participants"].append(tpart("rzn2", "reactant", text="R1_alkyl–ZnI"))
        t["steps"] = [step(1, ["rx", "rzn", "rzn2"], ["product"])]
        t["alternative_groups"] = [{"keys": ["rzn", "rzn2"], "default": "rzn", "basis": "header", "stated_at": None,
                                    "inferred": False}]
        t["footnotes"] = [{"marker": "b", "text": "With the alkylzinc iodide.", "notes": "",
                           "overrides": [ov("rzn2", "use", basis="footnote b")]}]
        inv["entries"][1]["cells"][2]["markers"] = ["b"]
        self.assertEqual(validate_table(inv, ENTRIES_SCHEMA, SIZES, 6, DOC_PAGES)[0], [])
        inv = numbered(inv)
        handles = coupling_handles()
        handles["reactions"][1]["footnote_markers"] = ["b"]
        r = number_reactions(inv, handles)[1]
        a = answer([out(62, "yield", product_key="product")])
        self.assertEqual(validate_reaction(a, REACTION_SCHEMA, inv, r, DOC_PAGES)[0], [])
        _, records, _ = assemble(inv, handles, {r["rid"]: a})
        p = parts_of(records[0])
        self.assertNotIn("rzn", p)
        self.assertEqual((p["rzn2"]["source"], p["rzn2"]["bbox"]), ("drawn", [170, 117, 230, 135]))
        self.assertEqual(records[0]["issues"], [])

    def test_split_label_cell(self):
        inv = r_table()
        inv["entries"][1]["cells"] = [cell("compound", "1c / 1d"), cell("r", "Cy / Ad")]
        inv = numbered(inv)
        handles = {"reactions": [handle(1, []),
                                 handle(2, [], distinguishing="1c", cells=[{"column": "compound", "part": "1c"},
                                                                          {"column": "r", "part": "Cy"}]),
                                 handle(2, [], distinguishing="1d", cells=[{"column": "compound", "part": "1d"},
                                                                          {"column": "r", "part": "Ad"}])],
                   "notes": [], "issues": []}
        self.assertEqual(validate_handles(handles, inv, HANDLES_SCHEMA), ([], []))
        reactions = number_reactions(inv, handles)
        answers = {r["rid"]: answer([out(90, None, ">90% yields", product_key="complex", qualifier=">")])
                   for r in reactions}
        _, records, _ = assemble(inv, handles, answers)
        self.assertEqual([r["label"] for r in records], ["1a", "1c", "1d"])
        self.assertEqual([parts_of(r)["complex"]["variables"][0]["value"] for r in records], ["DIPP", "Cy", "Ad"])

    def test_scheme_leaders_per_sharing_class(self):
        from pipeline.steps.s2_extract import scheme_leaders, sharing_class
        schemes = {"eq1": {"scheme_id": "eq1", "doc": "main", "page": 1, "bbox": [300, 600, 540, 640]}}
        region = {"region_id": "main:t", "doc": "main"}
        def blk(bid, layout, n):
            return {"block_id": bid, "layout": layout, "n_entries_est": n, "scheme_id": "eq1", "page": 2,
                    "bbox": [50, 50, 250, 250]}
        # A reactant table and a product scope read the scheme as positions their rows or entries fill in,
        # every other layout (and a block of an older run, without one) as specific compounds; an equation
        # block draws its own reactions, a prose passage names its own compounds, and neither shares anything.
        layouts = ("reactant_table", "product_scope", "condition_table", "other", None, "equation", "prose")
        self.assertEqual([sharing_class({"layout": x}) for x in layouts],
                         ["positions"] * 2 + ["compounds"] * 3 + [None] * 2)
        self.assertEqual(sharing_class({}), "compounds")
        self.assertEqual(scheme_leaders([(region, blk("e1", "equation", 1)), (region, blk("e2", "equation", 2))],
                                        schemes), {})
        self.assertEqual(scheme_leaders([(region, blk("p1", "prose", 1)), (region, blk("p2", "prose", 2)),
                                         (region, blk("c1", "condition_table", 12))], schemes), {})
        blocks = [(region, blk("ct", "condition_table", 12)), (region, blk("gen", "other", 1)),
                  (region, blk("t2", "reactant_table", 6)), (region, blk("t3", "reactant_table", 3)),
                  (region, blk("ps", "product_scope", 2)), (region, blk("ps2", "product_scope", 20)),
                  (region, blk("none", "other", 0))]
        pick = lambda *ids: [b for b in blocks if b[1]["block_id"] in ids]
        leaders = scheme_leaders(blocks, schemes)
        self.assertEqual(sorted(leaders), [("eq1", "compounds"), ("eq1", "positions")])
        self.assertEqual(leaders[("eq1", "positions")][1]["block_id"], "t3")  # a reactant table before a product scope
        self.assertEqual(leaders[("eq1", "compounds")][1]["block_id"], "ct")
        alone = scheme_leaders(pick("gen", "none", "t2"), schemes)
        self.assertEqual(alone[("eq1", "compounds")][1]["block_id"], "gen")  # one with entries leads
        self.assertNotIn(("eq1", "positions"), alone)  # a single reactant table needs no leader
        # A product scope and a condition table that follow one scheme have no leader in common: the scope
        # would take the table's model compounds for its positions.
        self.assertEqual(scheme_leaders(pick("ct", "ps"), schemes), {})
        self.assertEqual(sorted(scheme_leaders(pick("ct", "gen", "ps"), schemes)), [("eq1", "compounds")])
        # Product scopes share with each other (the smaller one leads) and with a reactant table (it leads).
        self.assertEqual({k: rb[1]["block_id"] for k, rb in scheme_leaders(pick("ps", "ps2"), schemes).items()},
                         {("eq1", "positions"): "ps"})
        self.assertEqual({k: rb[1]["block_id"] for k, rb in scheme_leaders(pick("t2", "ps"), schemes).items()},
                         {("eq1", "positions"): "t2"})


if __name__ == "__main__":
    unittest.main()
