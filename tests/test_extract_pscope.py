"""The product-scope path of Step 2 (pipeline/extract_pscope.py): validators, the participants the
pipeline builds from an entry, assembly into records and views.

A product scope is read as a table without a printed header (an entry is a row, each kind of thing
the entries print is a column), so the fixtures use the builders of the reactant-table tests. They
are small figures written out by hand as the two skills would answer, one per way a figure prints
its entries: paper 1, Scheme 3 (the fixture the path was built against), one drawing with a list of compounds, a
compound number printed with two results, results under protocol labels or tagged by a group of a
reactant, a byproduct reported by number, an entry that draws a reactant, a remark that names a
reactant, and reactions of two steps.

In every fixture the general reaction is drawn on page 1 and the entries are on page 2, so a record
shows which drawing each of its participants points at."""

import copy
import json
import logging
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pipeline import extract_rtable
from pipeline.extract_ctable import assemble_view
from pipeline.extract_pscope import (LAYOUT, OPS, base_row, entry_label, number_reactions, reaction_cells,
                                     resolve_cells, synthesize, validate_handles, validate_reaction, validate_table)
from pipeline.extract_view import block_view
from pipeline.schemas import build_extract
from pipeline.steps import s2_pscope, s2_rtable, s2_table
from pipeline.steps.s2_extract import _Job, eid_ranges, zoom_pieces
from tests.test_extract_records import cond, ov, step, tpart, variant
from tests.test_extract_rtable import (answer, cell, column, derivation, measure, numbered, out, parts_of,
                                       template)
from tests.test_extract_rtable import row as entry

ENTRIES_SCHEMA = s2_pscope.SPEC.schema("entries")
HANDLES_SCHEMA = s2_pscope.SPEC.schema("handles")
REACTION_SCHEMA = s2_pscope.SPEC.schema("reaction")
SIZES = {1: (600.0, 800.0), 2: (600.0, 800.0)}
DOC_PAGES = {"main": 4, "si": 40}
REGION = {"region_id": "main:scheme3", "doc": "main", "label": "Scheme 3", "first_page": 2,
          "caption": "Scheme 3. Scope of the Grignard reagents"}
BLOCK = {"block_id": "1", "kind": "substrate_scope", "layout": LAYOUT, "page": 2, "title": None,
         "bbox": [40, 170, 570, 545]}
TEMPLATE_CROPS = {k: f"c/_template__{k}.png" for k in ("1", "2", "3")}


# ------------------------------------------------------------------ builders

def slot(i, per_line=5):
    """The i-th place of the figure (0-based, reading order): (box of the entry, box of its drawing)."""
    x, y = 45 + 104 * (i % per_line), 180 + 90 * (i // per_line)
    return [x, y, x + 100, y + 86], [x + 8, y + 4, x + 92, y + 56]


def scope_template(conditions=None, reagent="R–M", **kw):
    """1 + 2 -> 3, drawn once and generically; both reactants follow from the product."""
    return template(
        [tpart("1", "reactant", "1", amount="0.2 mmol", bbox=[60, 60, 150, 100]),
         tpart("2", "reactant", "2", reagent, "0.4 mmol, 2.0 equiv", bbox=[170, 65, 230, 95]),
         tpart("3", "product", "3", bbox=[400, 60, 520, 100])],
        [step(1, ["1", "2"], ["3"])],
        conditions if conditions is not None else [cond("cat", "catalyst", "Fe(acac)3", "5 mol%"),
                                                   cond("solvent", "solvent", "THF"),
                                                   cond("temp", "temperature", "25 °C")],
        derivations=[derivation("1", ["3"], "the part of the product that is not blue, with X on the carbon that "
                                            "carries the blue group"),
                     derivation("2", ["3"], f"the blue group of the product, as {reagent}")],
        default_yield_type="isolated", **kw)


def fields(*extra):
    """The fields of an entry as columns: its drawing, its compound number, `extra`, its yield."""
    return [column("product", "participant", targets=["3"]), column("label", "label", targets=["3"]), *extra,
            column("yield", "outcome", measures=[measure("3", "yield", "isolated")])]


def figure(t, columns, entries):
    return {"template": t, "columns": columns, "entries": entries, "ignored": [], "notes": ""}


def handle(n, results, markers=(), distinguishing=None, cells=(), variant=None):
    return {"entry": n, "results": [{"column": c, "part": p} for c, p in results], "variant": variant,
            "footnote_markers": list(markers), "distinguishing": distinguishing, "cells": list(cells)}


def listed(*reactions):
    return {"reactions": list(reactions), "notes": [], "issues": []}


def assemble(inv, handles, answers):
    """Records and view of a figure, as publish() builds them from what is on disk."""
    inv = {**inv, "_meta": {"status": "ok", "errors": [], "warnings": [], "overlays": []}}
    reactions = number_reactions(inv, handles)
    handles = {**handles, "reactions": reactions, "_meta": {"status": "ok", "errors": [], "warnings": []}}
    stored = {r["rid"]: ({**answers[r["rid"]], "_meta": {"errors": [], "warnings": [], "seconds": 1}}, "ok")
              for r in reactions if r["rid"] in answers}
    cell_crops = {f"{en['eid']}-{c['column']}": f"c/_cell__{en['eid']}-{c['column']}.png"
                  for en in inv["entries"] for c in en["cells"] if c["structure_bbox"] is not None}
    crops = {p["key"]: f"c/_template__{p['key']}.png" for p in inv["template"]["participants"] if p["bbox"]}
    return assemble_view(REGION, BLOCK, "main-scheme3__1", inv, "ok", handles, "ok", stored, crops, {}, cell_crops,
                         ops=OPS)


def by_rid(records):
    return {r["source"]["reaction_id"]: r for r in records}


def variables_of(participant):
    return [(v["name"], v["value"], v["origin"]) for v in participant["variables"]]


class Case(unittest.TestCase):
    def read(self, inv, handles, answers, warnings=()):
        """The three answers through their validators, then assembled: no errors, and no warnings
        of stage 1 but those that contain one of `warnings`; nothing at all from stage 2.
        Returns (numbered inventory, view, records by reaction id)."""
        expected = lambda found: [w for w in found if not any(x in w for x in warnings)]
        errors, warned = validate_table(inv, ENTRIES_SCHEMA, SIZES, len(inv["entries"]), DOC_PAGES)
        self.assertEqual((errors, expected(warned)), ([], []))
        inv = numbered(inv)
        errors, warned = validate_handles(handles, inv, HANDLES_SCHEMA)
        self.assertEqual((errors, expected(warned)), ([], []))
        reactions = number_reactions(inv, handles)
        self.assertEqual(sorted(answers), sorted(r["rid"] for r in reactions))
        for r in reactions:
            self.assertEqual(validate_reaction(answers[r["rid"]], REACTION_SCHEMA, inv, r, DOC_PAGES), ([], []),
                             r["rid"])
        view, records, counts = assemble(inv, handles, answers)
        self.assertEqual((len(records), counts["reactions_ok"]), (len(reactions), len(reactions)))
        json.dumps(block_view(view))
        return inv, view, by_rid(records)


# ------------------------------------------------------------------ paper 1, Scheme 3

# label, isolated yield (%), footnote marker on the yield, "X = …" and "Ar = …" as printed with the entry
SCHEME3 = [
    ("3at", 80, "", "", ""), ("3au", 71, "", "", ""), ("3av", 0, "", "", ""), ("3aw", 56, "", "", ""),
    ("3ax", 59, "", "", ""), ("3ay", 33, "b", "", ""), ("3az", 66, "", "", ""),
    ("3aaa", 61, "c", "", "Ar = 4-OMeC6H4"), ("3aab", 26, "c", "", ""), ("3aac", 29, "b", "", ""),
    ("3aad", 33, "b", "", ""), ("3aae", 26, "d", "X = Cl", ""), ("3aaf", 42, "e", "", ""),
    ("3aag", 69, "e", "", ""), ("3aag", 51, "e", "X = Cl", ""),  # one drawing, two lines under it
    ("3aah", 25, "d", "X = Cl", ""), ("3aai", 31, "d", "", ""), ("3aaj", 29, "d", "X = Cl", ""),
    ("3aak", 55, "e", "", ""), ("3aal", 43, "f", "X = Cl", ""),
]


def scheme3_template():
    """α-Haloamide 1 (X) + Grignard reagent 2 (through ZnCl2) -> 3; X = Br unless an entry says otherwise."""
    def footnote(marker, text, *overrides):
        return {"marker": marker, "text": text, "notes": "", "overrides": list(overrides)}

    def more(amount_2, amount_salts):
        return [ov("2", "replace", amount=amount_2), ov("zncl2", "replace", amount=amount_salts),
                ov("licl", "replace", amount=amount_salts)]

    return scope_template(
        [cond("cat", "catalyst", "Fe(BF-Phos)Cl2", "0.5 mol%"), cond("zncl2", "reagent", "ZnCl2", "1.0 equiv"),
         cond("licl", "additive", "LiCl", "1.0 equiv"), cond("solvent", "solvent", "THF"),
         cond("temp", "temperature", "22-25 °C"), cond("time", "time", "6 h")],
        reagent="RMgBr",
        footnotes=[
            footnote("a", "Reaction conditions: 1, 2, Fe(BF-Phos)Cl2 (0.5 mol %), ZnCl2 (1.0 equiv), LiCl (1.0 equiv) "
                          "in THF at 22-25 °C for 6 h; isolated yields; X = Br unless otherwise noted."),
            footnote("b", "35 °C, 36 h.", ov("temp", "replace", "35 °C"), ov("time", "replace", "36 h")),
            footnote("c", "2 (0.6 mmol, 3.0 equiv), ZnCl2 (0.3 mmol, 1.5 equiv), LiCl (0.3 mmol, 1.5 equiv), 60 °C.",
                     *more("0.6 mmol, 3.0 equiv", "0.3 mmol, 1.5 equiv"), ov("temp", "replace", "60 °C")),
            footnote("d", "60 °C.", ov("temp", "replace", "60 °C")),
            footnote("e", "24 h.", ov("time", "replace", "24 h")),
            footnote("f", "2 (0.8 mmol, 4.0 equiv), ZnCl2 (0.4 mmol, 2.0 equiv), LiCl (0.4 mmol, 2.0 equiv), 35 °C, "
                          "48 h.", *more("0.8 mmol, 4.0 equiv", "0.4 mmol, 2.0 equiv"), ov("temp", "replace", "35 °C"),
                     ov("time", "replace", "48 h")),
        ],
        variable_defaults=[{"name": "X", "value": "Br", "participant_key": "1", "basis": "footnote a"}])


def scheme3_figure():
    """Stage 1, turn 1: one entry per printed line. X is a group of reactant 1 only; "Ar = …" spells
    out the entry's own drawing; the second line of 3aag repeats the drawing and the number above it."""
    entries, place = [], -1
    for n, (label, y, marker, x, ar) in enumerate(SCHEME3, 1):
        again = n > 1 and SCHEME3[n - 2][0] == label
        place += not again
        box, drawing = slot(place)
        shown = [cell("product", same_as=n - 1), cell("label", same_as=n - 1)] if again else \
            [cell("product", structure_bbox=drawing), cell("label", label)]
        entries.append(entry(label, 2, box, shown + [cell("X", x), cell("Ar", ar),
                                                     cell("yield", f"{y}%", [marker] if marker else [])],
                             lookup_hint={"doc": "si", "page": 12, "note": f"paragraph of {label}"}))
    return figure(scheme3_template(),
                  fields(column("X", "variable", targets=["1"], variable_name="X"),
                         column("Ar", "variable", targets=["3"], variable_name="Ar")),
                  entries)


def scheme3_handles():
    """Stage 1, turn 2: one reaction per entry."""
    return listed(*[handle(n, [("yield", None)], [marker] if marker else [])
                    for n, (_, _, marker, _, _) in enumerate(SCHEME3, 1)])


def scheme3_answers(inv, handles):
    """Stage 2: the yield, and the name the SI paragraph gives the product."""
    return {r["rid"]: answer([out(y, "yield", f"{y}%", product_key="3")],
                             lookup=[ov("3", "replace", f"name of {label} in its paragraph", basis="SI paragraph",
                                        stated_at={"doc": "si", "page": 12})])
            for r, (label, y, _, _, _) in zip(number_reactions(inv, handles), SCHEME3)}


class Scheme3(Case):
    def setUp(self):
        self.inv = numbered(scheme3_figure())
        self.handles = scheme3_handles()
        self.answers = scheme3_answers(self.inv, self.handles)

    def test_reproduces_the_scope(self):
        _, view, by = self.read(scheme3_figure(), self.handles, self.answers)
        records = list(by.values())
        self.assertEqual(len(records), 20)
        self.assertTrue(all(sorted(p["source"] for p in r["steps"][0]["reactants"]) == ["derived", "derived"]
                            and r["steps"][0]["products"][0]["source"] == "drawn" for r in records))
        self.assertEqual([e["entry"]["label"] for e in view["entries"]], [x[0] for x in SCHEME3])
        self.assertTrue(all(not r["issues"] for r in records), [r["issues"] for r in records])

    def test_product_drawn_reactants_unknown(self):
        _, records, _ = assemble(self.inv, self.handles, self.answers)
        rec = records[0]
        p = parts_of(rec)
        # The entry's drawing and number, and the name the SI gives it.
        self.assertEqual((p["3"]["source"], p["3"]["unknown"], p["3"]["page"], p["3"]["bbox"], p["3"]["crop"]),
                         ("drawn", False, 2, slot(0)[1], "c/_cell__e001-product.png"))
        self.assertEqual((p["3"]["label"], p["3"]["text"], p["3"]["stated_at"]),
                         ("3at", "name of 3at in its paragraph", {"doc": "si", "page": 12}))
        self.assertEqual([(o["yield"]["value"], o["yield"]["type"]) for o in p["3"]["outcomes"]], [(80, "isolated")])
        # The reactants: the generic drawings of the general reaction, and how each follows from the product.
        for key, how in (("1", "not blue"), ("2", "blue group")):
            self.assertEqual((p[key]["source"], p[key]["unknown"], p[key]["generic"], p[key]["page"], p[key]["bbox"],
                              p[key]["crop"]),
                             ("derived", True, True, 1, self.inv["template"]["participants"][int(key) - 1]["bbox"],
                              f"c/_template__{key}.png"), key)
            self.assertIn("unknown, to be derived", p[key]["basis"])
            self.assertIn(how, p[key]["basis"])
        self.assertEqual((p["1"]["label"], p["2"]["text"], p["2"]["amount"]), ("1", "RMgBr", "0.4 mmol, 2.0 equiv"))
        self.assertEqual((rec["label"], rec["source"]["entry_bbox"], rec["source"]["page"]), ("3at", slot(0)[0], 2))

    def test_variables_sit_where_they_belong(self):
        _, records, _ = assemble(self.inv, self.handles, self.answers)
        by = {(r["label"], r["results"][0]): parts_of(r) for r in records}
        # X is on reactant 1 only: Br by default, Cl where the entry prints it.
        self.assertEqual(variables_of(by["3at", "80%"]["1"]), [("X", "Br", "default")])
        self.assertEqual(variables_of(by["3aae", "26%"]["1"]), [("X", "Cl", "stated")])
        self.assertTrue(all(not p["2"]["variables"] and not any(v["name"] == "X" for v in p["3"]["variables"])
                            for p in by.values()))
        # "Ar = …" is about the entry's own drawing.
        self.assertEqual(variables_of(by["3aaa", "61%"]["3"]), [("Ar", "4-OMeC6H4", "stated")])
        self.assertEqual(variables_of(by["3aaa", "61%"]["1"]), [("X", "Br", "default")])
        self.assertEqual(base_row(self.inv, number_reactions(self.inv, self.handles)[7])["variables"],
                         [{"name": "Ar", "value": "4-OMeC6H4"}])

    def test_two_lines_under_one_drawing(self):
        cells = resolve_cells(self.inv, 15)
        self.assertEqual((cells["product"]["structure_key"], cells["product"]["from_row"], cells["label"]["text"]),
                         ("e014-product", 14, "3aag"))
        self.assertEqual(self.inv["entries"][13]["bbox"], self.inv["entries"][14]["bbox"])
        _, records, _ = assemble(self.inv, self.handles, self.answers)
        first, second = [r for r in records if r["label"] == "3aag"]
        for rec in (first, second):
            p = parts_of(rec)
            self.assertEqual((p["3"]["source"], p["3"]["bbox"], p["3"]["crop"], p["3"]["label"]),
                             ("drawn", slot(13)[1], "c/_cell__e014-product.png", "3aag"))
            self.assertEqual((p["1"]["unknown"], p["2"]["unknown"]), (True, True))
            self.assertEqual([f["marker"] for f in rec["footnotes"]], ["e"])
        self.assertEqual((first["source"]["entry_id"], second["source"]["entry_id"]), ("e014", "e015"))
        self.assertEqual(first["source"]["entry_bbox"], second["source"]["entry_bbox"])
        self.assertEqual([variables_of(parts_of(r)["1"]) for r in (first, second)],
                         [[("X", "Br", "default")], [("X", "Cl", "stated")]])
        self.assertEqual([parts_of(r)["3"]["outcomes"][0]["yield"]["value"] for r in (first, second)], [69, 51])

    def test_footnotes_change_conditions_and_amounts(self):
        _, records, _ = assemble(self.inv, self.handles, self.answers)
        by = {(r["label"], r["results"][0]): r for r in records}
        conditions = lambda rec: {c["key"]: (c["text"], c["amount"], c["origin"])
                                  for c in rec["steps"][0]["conditions"]}
        base = conditions(by["3at", "80%"])
        self.assertEqual((base["temp"], base["time"], base["zncl2"]),
                         (("22-25 °C", None, "base"), ("6 h", None, "base"), ("ZnCl2", "1.0 equiv", "base")))
        f = conditions(by["3aal", "43%"])
        self.assertEqual((f["temp"], f["time"], f["licl"]),
                         (("35 °C", None, "footnote:f"), ("48 h", None, "footnote:f"),
                          ("LiCl", "0.4 mmol, 2.0 equiv", "footnote:f")))
        # A footnote that changes the amount of a reactant leaves it unknown.
        two = parts_of(by["3aal", "43%"])["2"]
        self.assertEqual((two["amount"], two["amount_origin"], two["unknown"]),
                         ("0.8 mmol, 4.0 equiv", "footnote:f", True))

    def test_stage2_task(self):
        r = number_reactions(self.inv, self.handles)[14]
        extra = s2_pscope.SPEC.stage2_task({"entry": {"eid": "e015"}}, self.inv, self.handles, r)
        states = {p["key"]: (p["source"], p["state"]) for p in extra["participants"]}
        self.assertEqual(states, {"1": ("derived", "unknown"), "2": ("derived", "unknown"), "3": ("drawn", "cell")})
        self.assertEqual(extra["cannot_derive"], [])
        self.assertEqual(extra["entry"]["lookup_hint"]["page"], 12)
        self.assertEqual([(c["structure_key"], c["from_row"]) for c in extra["row_cells"] if c["column"] == "product"],
                         [("e014-product", 14)])

    def test_unknown_reactant_needs_a_derivation(self):
        inv = scheme3_figure()
        inv["template"]["derivations"].pop()
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 20, DOC_PAGES)
        self.assertTrue(any("participant '2' is generic and rows" in e for e in errors), errors)
        # The reactant-table check reports it already: the product scope's own check does not say it again.
        self.assertEqual([e for e in errors if e.startswith("participant '2' is generic")],
                         [e for e in errors if e.startswith("participant '2' is generic and rows")])
        self.assertEqual(len([e for e in errors if e.startswith("participant '2'")]), 1, errors)

    def test_a_default_group_does_not_name_the_reactant(self):
        # X = Br by default on reactant 1 names its leaving group, not the compound: without its derivation the
        # reading fails, although the reactant-table check alone takes the default as enough.
        inv = scheme3_figure()
        inv["template"]["derivations"] = [d for d in inv["template"]["derivations"] if d["key"] != "1"]
        self.assertEqual(extract_rtable.validate_table(inv, ENTRIES_SCHEMA, SIZES, 20, DOC_PAGES)[0], [])
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 20, DOC_PAGES)
        self.assertEqual(len(errors), 1, errors)
        self.assertTrue(errors[0].startswith("participant '1' is generic and not every entry draws it"), errors)
        # With its derivation the same reactant, default and all, passes.
        self.assertEqual(validate_table(scheme3_figure(), ENTRIES_SCHEMA, SIZES, 20, DOC_PAGES)[0], [])


# ------------------------------------------------------------------ one drawing with a list of compounds

R_LIST = (("3a", "Me", 82), ("3b", "Et", 75), ("3c", "iPr", 68))


def r_list_figure():
    """One drawing that carries R, and under it '3a, R = Me, 82%', '3b, R = Et, 75%', …"""
    box, drawing = slot(0)
    entries = [entry(label, 2, box, [cell("product", structure_bbox=drawing) if n == 1 else cell("product", same_as=1),
                                     cell("label", label), cell("R", f"R = {r}"), cell("yield", f"{y}%")])
               for n, (label, r, y) in enumerate(R_LIST, 1)]
    return figure(scope_template(), fields(column("R", "variable", targets=["3"], variable_name="R")), entries)


class DrawingWithAList(Case):
    def test_each_compound_is_an_entry_of_the_one_drawing(self):
        handles = listed(*[handle(n, [("yield", None)]) for n in (1, 2, 3)])
        answers = {f"e00{n}-1": answer([out(y, "yield", f"{y}%", product_key="3")])
                   for n, (_, _, y) in enumerate(R_LIST, 1)}
        inv, view, by = self.read(r_list_figure(), handles, answers)
        self.assertEqual({tuple(en["bbox"]) for en in inv["entries"]}, {tuple(slot(0)[0])})
        for n, (label, r, y) in enumerate(R_LIST, 1):
            rec = by[f"e00{n}-1"]
            p = parts_of(rec)
            # The drawing of the first entry, with this entry's number and R.
            self.assertEqual((p["3"]["source"], p["3"]["page"], p["3"]["bbox"], p["3"]["crop"], p["3"]["label"]),
                             ("drawn", 2, slot(0)[1], "c/_cell__e001-product.png", label))
            self.assertEqual(variables_of(p["3"]), [("R", r, "stated")])
            self.assertEqual(p["3"]["outcomes"][0]["yield"]["value"], y)
            # R is a group of the drawing under which it is printed, not of the general reaction's reactants.
            for key in ("1", "2"):
                self.assertEqual((p[key]["source"], p[key]["unknown"], p[key]["page"], p[key]["variables"]),
                                 ("derived", True, 1, []))
            self.assertEqual((rec["label"], rec["source"]["entry_bbox"], rec["issues"]), (label, slot(0)[0], []))
        self.assertIn("as in row 1", view["entries"][2]["expansion"]["printed"])

    def test_the_drawing_is_given_once(self):
        inv = r_list_figure()
        inv["entries"][2]["cells"][0]["same_as"] = 3  # itself
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)
        self.assertTrue(any("same_as 3 must be the number of an earlier row (1..2)" in e for e in errors), errors)
        inv = r_list_figure()
        inv["entries"][1]["cells"][0]["structure_bbox"] = slot(0)[1]  # boxed again, and pointing at the first
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)
        self.assertTrue(any("prints nothing of its own" in e and "it repeats the cell of row 1" in e for e in errors),
                        errors)

    def test_an_entry_in_the_box_of_another_repeats_its_drawing(self):
        # The second compound under the drawing, its drawing field left empty instead of pointing at the first.
        inv = r_list_figure()
        inv["entries"][1]["cells"][0] = cell("product")
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)
        self.assertIn("entries[1] cell 'product': the entry has the box of row 1, which draws this field: repeat its "
                      "drawing with same_as 1", errors)
        # The third compound is pointed at the first entry with the box, the one that draws it.
        inv = r_list_figure()
        inv["entries"][2]["cells"][0] = cell("product")
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)
        self.assertTrue(any(e.startswith("entries[2] cell 'product': the entry has the box of row 1") and
                            e.endswith("same_as 1") for e in errors), errors)
        self.assertFalse(any("entries[1] cell 'product'" in e for e in errors), errors)
        # With same_as it passes; an entry in a box of its own that draws nothing in the field is not asked to.
        self.assertEqual(validate_table(r_list_figure(), ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES), ([], []))
        errors, _ = validate_table(unsuccessful_figure(), ENTRIES_SCHEMA, SIZES, 2, DOC_PAGES)
        self.assertFalse(any("repeat its drawing" in e for e in errors), errors)

    def test_a_position_drawn_in_every_entry_needs_no_derivation(self):
        # The product, drawn once and repeated by same_as, has no derivation: every entry draws it.
        inv = r_list_figure()
        self.assertNotIn("3", {d["key"] for d in inv["template"]["derivations"]})
        self.assertEqual(validate_table(inv, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)[0], [])
        # A reactant every entry draws in a field of its own needs none either; the reagent no entry draws does.
        t = scope_template()
        t["derivations"] = [d for d in t["derivations"] if d["key"] != "1"]
        entries = []
        for n, label in enumerate(("3a", "3b")):
            box, drawing = slot(n)
            substrate = [drawing[0], drawing[3] + 2, drawing[2], drawing[3] + 26]
            entries.append(entry(label, 2, box, [cell("product", structure_bbox=drawing), cell("label", label),
                                                 cell("substrate", structure_bbox=substrate), cell("yield", "70%")]))
        drawn = figure(t, fields(column("substrate", "participant", targets=["1"])), entries)
        self.assertEqual(validate_table(drawn, ENTRIES_SCHEMA, SIZES, 2, DOC_PAGES)[0], [])
        drawn["entries"][1]["cells"][2] = cell("substrate", same_as=1)
        self.assertEqual(validate_table(drawn, ENTRIES_SCHEMA, SIZES, 2, DOC_PAGES)[0], [])
        drawn["template"]["derivations"] = []
        errors, _ = validate_table(drawn, ENTRIES_SCHEMA, SIZES, 2, DOC_PAGES)
        self.assertEqual([e[:16] for e in errors], ["participant '2' "], errors)
        # A reactant only some entries draw, with a default group in the others, still needs its derivation.
        inv = unsuccessful_figure()
        inv["template"]["derivations"] = [d for d in inv["template"]["derivations"] if d["key"] != "1"]
        inv["template"]["variable_defaults"] = [{"name": "X", "value": "Br", "participant_key": "1", "basis": "caption"}]
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 2, DOC_PAGES)
        self.assertEqual(len(errors), 1, errors)
        self.assertTrue(errors[0].startswith("participant '1' is generic and not every entry draws it"), errors)


# ------------------------------------------------------------------ one number, two lines, a group of a reactant

def two_lines_figure():
    """'3a, 74%' and under it '3a (X = Cl), 52%': X sits on reactant 1 only and is Br unless stated."""
    box, drawing = slot(0)
    t = scope_template(variable_defaults=[{"name": "X", "value": "Br", "participant_key": "1", "basis": "caption"}])
    return figure(t, fields(column("X", "variable", targets=["1"], variable_name="X")),
                  [entry("3a", 2, box, [cell("product", structure_bbox=drawing), cell("label", "3a"), cell("X"),
                                        cell("yield", "74%")]),
                   entry("3a", 2, box, [cell("product", same_as=1), cell("label", "3a"), cell("X", "X = Cl"),
                                        cell("yield", "52%")])])


class TwoLinesOneNumber(Case):
    def test_reactant_only_variable(self):
        handles = listed(handle(1, [("yield", None)]), handle(2, [("yield", None)]))
        answers = {"e001-1": answer([out(74, "yield", "74%", product_key="3")]),
                   "e002-1": answer([out(52, "yield", "52%", product_key="3")])}
        _, _, by = self.read(two_lines_figure(), handles, answers)
        first, second = parts_of(by["e001-1"]), parts_of(by["e002-1"])
        self.assertEqual((by["e001-1"]["label"], by["e002-1"]["label"]), ("3a", "3a"))
        self.assertEqual((variables_of(first["1"]), variables_of(second["1"])),
                         ([("X", "Br", "default")], [("X", "Cl", "stated")]))
        for p in (first, second):
            self.assertEqual((p["1"]["source"], p["1"]["unknown"], p["2"]["unknown"]), ("derived", True, True))
            self.assertEqual((p["3"]["source"], p["3"]["bbox"], p["3"]["label"], p["3"]["variables"]),
                             ("drawn", slot(0)[1], "3a", []))
            self.assertEqual(p["2"]["variables"], [])
        self.assertEqual([p["3"]["outcomes"][0]["yield"]["value"] for p in (first, second)], [74, 52])


# ------------------------------------------------------------------ results under protocol labels

def protocol_figure():
    """One compound, three results in one line, each under the label of its protocol; the last one
    carries a footnote marker."""
    box, drawing = slot(0)
    t = scope_template(footnotes=[{"marker": "b", "text": "At 60 °C.", "notes": "",
                                   "overrides": [ov("temp", "replace", "60 °C", basis="footnote b")]}])
    t["variants"] = [variant("fe-isolated", "[isolated] [Fe]"),
                     variant("fe-in-situ", "[in situ] [Fe]",
                             [ov("activator", "add", "HATU", "1.0 equiv", role="reagent")]),
                     variant("ni", "[Ni]", [ov("cat", "replace", "NiCl2·glyme", "20 mol%")])]
    return figure(t, fields(), [entry("3a", 2, box, [
        cell("product", structure_bbox=drawing), cell("label", "3a"),
        cell("yield", "[isolated] [Fe] 81% / [in situ] [Fe] 71% / [Ni] 85%", ["b"])])])


def protocol_handles():
    return listed(handle(1, [("yield", "[isolated] [Fe] 81%")], variant="fe-isolated"),
                  handle(1, [("yield", "[in situ] [Fe] 71%")], variant="fe-in-situ"),
                  handle(1, [("yield", "[Ni] 85%")], ["b"], variant="ni"))


class ProtocolLabels(Case):
    def test_one_reaction_per_label(self):
        answers = {f"e001-{i}": answer([out(y, "yield", f"{y}%", product_key="3")])
                   for i, y in enumerate((81, 71, 85), 1)}
        _, view, by = self.read(protocol_figure(), protocol_handles(), answers)
        self.assertEqual([(r["label"], r["variant"]["key"], r["variant"]["title"], r["results"]) for r in by.values()],
                         [("3a", "fe-isolated", "[isolated] [Fe]", ["[isolated] [Fe] 81%"]),
                          ("3a", "fe-in-situ", "[in situ] [Fe]", ["[in situ] [Fe] 71%"]),
                          ("3a", "ni", "[Ni]", ["[Ni] 85%"])])
        self.assertEqual([parts_of(r)["3"]["outcomes"][0]["yield"]["value"] for r in by.values()], [81, 71, 85])
        # The marker belongs to the result it is printed on.
        self.assertEqual([[f["marker"] for f in r["footnotes"]] for r in by.values()], [[], [], ["b"]])
        conditions = lambda rec: {c["key"]: (c["text"], c["origin"]) for c in rec["steps"][0]["conditions"]}
        self.assertEqual([conditions(r)["temp"] for r in by.values()],
                         [("25 °C", "base"), ("25 °C", "base"), ("60 °C", "footnote:b")])
        self.assertEqual([conditions(r)["cat"] for r in by.values()],
                         [("Fe(acac)3", "base"), ("Fe(acac)3", "base"), ("NiCl2·glyme", "variant:ni")])
        self.assertEqual(["activator" in conditions(r) for r in by.values()], [False, True, False])
        for rec in by.values():
            p = parts_of(rec)
            self.assertEqual((p["3"]["source"], p["3"]["bbox"], p["1"]["unknown"], p["2"]["unknown"]),
                             ("drawn", slot(0)[1], True, True))
        self.assertEqual(len(view["entries"][0]["reactions"]), 3)

    def test_each_result_under_its_own_label(self):
        inv = numbered(protocol_figure())
        handles = protocol_handles()
        handles["reactions"][2]["variant"] = "fe-isolated"
        errors, _ = validate_handles(handles, inv, HANDLES_SCHEMA)
        self.assertTrue(any("prints the label of variant ['ni']" in e for e in errors), errors)
        handles = protocol_handles()
        handles["reactions"][1]["results"][0]["part"] = None
        errors, _ = validate_handles(handles, inv, HANDLES_SCHEMA)
        self.assertTrue(any("each gives the part of the cell that is its own" in e for e in errors), errors)


# ------------------------------------------------------------------ results tagged by a group of a reactant

def boron_figure(tagged="BNeo / BPin", results="86% / 64%"):
    """'BNeo: 86% / BPin: 64%' under one product: two reactions that differ in the boron group of
    reactant 2, which the product does not show."""
    box, drawing = slot(0)
    return figure(scope_template(), fields(column("boron", "variable", targets=["2"], variable_name="[B]")),
                  [entry("3a", 2, box, [cell("product", structure_bbox=drawing), cell("label", "3a"),
                                        cell("boron", tagged), cell("yield", results)])])


def boron_handles():
    return listed(handle(1, [("yield", "86%")], distinguishing="BNeo", cells=[{"column": "boron", "part": "BNeo"}]),
                  handle(1, [("yield", "64%")], distinguishing="BPin", cells=[{"column": "boron", "part": "BPin"}]))


class ResultsByReactantGroup(Case):
    def test_each_reaction_has_its_value(self):
        answers = {"e001-1": answer([out(86, "yield", "86%", product_key="3")]),
                   "e001-2": answer([out(64, "yield", "64%", product_key="3")])}
        inv, _, by = self.read(boron_figure(), boron_handles(), answers)
        reactions = number_reactions(inv, boron_handles())
        self.assertEqual([reaction_cells(inv, r)["boron"]["text"] for r in reactions], ["BNeo", "BPin"])
        for rid, group, y in (("e001-1", "BNeo", 86), ("e001-2", "BPin", 64)):
            p = parts_of(by[rid])
            # The value is on the reactant that carries the group; the reactant itself is still to be worked out.
            self.assertEqual((p["2"]["source"], p["2"]["unknown"], variables_of(p["2"])),
                             ("derived", True, [("[B]", group, "stated")]))
            self.assertEqual((p["1"]["unknown"], p["1"]["variables"], p["3"]["variables"]), (True, [], []))
            self.assertEqual((p["3"]["source"], p["3"]["label"], p["3"]["outcomes"][0]["yield"]["value"]),
                             ("drawn", "3a", y))
            self.assertEqual((by[rid]["label"], by[rid]["issues"]), ("3a", []))

    def test_values_without_their_results(self):
        # The cell of the variable holds the values only: with the results in it, it reads as another group.
        inv = boron_figure("BNeo: 86% / BPin: 64%")
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 1, DOC_PAGES)
        self.assertTrue(any("column 'boron'" in e and "one variable column per group" in e for e in errors), errors)

    def test_a_value_may_contain_an_equals_sign(self):
        # A bare group with a double bond in it is a value, not "another group = value".
        for text, value in (("CH=CH2", "CH=CH2"), ("R = CH=CH2", "CH=CH2"), ("R: C≡CH", "C≡CH")):
            inv = r_list_figure()
            inv["entries"][0]["cells"][2]["text"] = text
            self.assertEqual(validate_table(inv, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)[0], [], text)
            r = number_reactions(numbered(inv), listed(handle(1, [("yield", None)])))[0]
            self.assertEqual(base_row(numbered(inv), r)["variables"], [{"name": "R", "value": value}], text)
        # Another group in the field of X is still one field too many, and so is a value with its result.
        inv = two_lines_figure()
        inv["entries"][1]["cells"][2]["text"] = "R3Si = SiMe3"
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 2, DOC_PAGES)
        self.assertTrue(any(e.startswith("column 'X': its cells also give ['R3Si']") for e in errors), errors)
        errors, _ = validate_table(boron_figure("BNeo: 86%", "86%"), ENTRIES_SCHEMA, SIZES, 1, DOC_PAGES)
        self.assertTrue(any(e.startswith("column 'boron': its cells also give ['BNeo']") for e in errors), errors)

    def test_every_reaction_takes_its_part(self):
        inv = numbered(boron_figure())
        handles = boron_handles()
        handles["reactions"][1]["cells"] = []
        errors, _ = validate_handles(handles, inv, HANDLES_SCHEMA)
        self.assertTrue(any("must each give their part" in e for e in errors), errors)
        handles = boron_handles()
        handles["reactions"][0]["cells"][0]["part"] = "BCat"
        errors, _ = validate_handles(handles, inv, HANDLES_SCHEMA)
        self.assertTrue(any("part 'BCat' is not in the text" in e for e in errors), errors)


# ------------------------------------------------------------------ a byproduct reported by number

def byproduct_figure():
    """'3a: 61% (60%) / 4a: 35%': the homocoupling product 4 of reactant 2 is given by its number and
    its yield only. Its number is the first thing the entry's cells list, and the entry has no label."""
    box, drawing = slot(0)
    t = scope_template()
    t["participants"].append(tpart("4", "byproduct", "4", bbox=[530, 65, 580, 95]))
    t["steps"] = [step(1, ["1", "2"], ["3", "4"])]
    t["derivations"].append(derivation("4", ["2"], "two of the blue groups of reactant 2, joined"))
    columns = [column("byproduct", "label", targets=["4"]), column("label", "label", targets=["3"]),
               column("product", "participant", targets=["3"]),
               column("yield", "outcome", measures=[measure("3", "yield", "NMR"), measure("3", "yield", "isolated"),
                                                    measure("4", "yield", "NMR")])]
    return figure(t, columns, [entry(None, 2, box, [cell("byproduct", "4a"), cell("label", "3a"),
                                                    cell("product", structure_bbox=drawing),
                                                    cell("yield", "3a: 61% (60%) / 4a: 35%")])])


class ByproductByNumber(Case):
    def test_number_and_yield_on_an_unknown_byproduct(self):
        handles = listed(handle(1, [("yield", None)]))
        answers = {"e001-1": answer([out(61, "yield", "61%", measure=1), out(60, "yield", "(60%)", measure=2),
                                     out(35, "yield", "35%", measure=3)])}
        inv, view, by = self.read(byproduct_figure(), handles, answers)
        rec = by["e001-1"]
        p = parts_of(rec)
        self.assertEqual((p["4"]["role"], p["4"]["source"], p["4"]["unknown"], p["4"]["label"]),
                         ("byproduct", "derived", True, "4a"))
        self.assertIn("joined (from 2)", p["4"]["basis"])
        self.assertEqual([(o["yield"]["value"], o["yield"]["type"]) for o in p["4"]["outcomes"]], [(35, "NMR")])
        self.assertEqual((p["3"]["source"], p["3"]["label"], p["3"]["bbox"]), ("drawn", "3a", slot(0)[1]))
        self.assertEqual([(o["yield"]["value"], o["yield"]["type"]) for o in p["3"]["outcomes"]],
                         [(61, "NMR"), (60, "isolated")])
        self.assertEqual((p["1"]["unknown"], p["2"]["unknown"], rec["other_outcomes"], rec["issues"]),
                         (True, True, [], []))
        # The reaction is called by the number of its product, although the byproduct's comes first.
        self.assertEqual((rec["label"], view["entries"][0]["entry"]["label"]), ("3a", "3a"))
        self.assertEqual((entry_label(inv, inv["entries"][0]), extract_rtable.entry_label(inv, inv["entries"][0])),
                         ("3a", "4a"))

    def test_byproduct_needs_its_derivation(self):
        inv = byproduct_figure()
        inv["template"]["derivations"].pop()
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 1, DOC_PAGES)
        self.assertTrue(any("participant '4' is generic and rows" in e for e in errors), errors)

    def test_split_on_its_numbers_called_by_the_products(self):
        # '3a / 3b' and '4a / 4b' in one unlabelled entry, two reactions: each is called by its product's number,
        # whichever of the two number fields the columns list first.
        for product_first in (False, True):
            inv = byproduct_figure()
            texts = {"byproduct": "4a / 4b", "label": "3a / 3b", "yield": "3a: 61% / 4a: 35% / 3b: 55% / 4b: 30%"}
            for c in inv["entries"][0]["cells"]:
                c["text"] = texts.get(c["column"], c["text"])
            if product_first:
                inv["columns"][0], inv["columns"][1] = inv["columns"][1], inv["columns"][0]
            inv = numbered(inv)
            handles = listed(*[handle(1, [("yield", f"{p}: {y}% / {b}: {z}%")], distinguishing=p,
                                      cells=[{"column": "byproduct", "part": b}, {"column": "label", "part": p}])
                               for p, b, y, z in (("3a", "4a", 61, 35), ("3b", "4b", 55, 30))])
            self.assertEqual(validate_handles(handles, inv, HANDLES_SCHEMA)[0], [], product_first)
            reactions = number_reactions(inv, handles)
            self.assertEqual([base_row(inv, r)["label"] for r in reactions], ["3a", "3b"], product_first)
            answers = {r["rid"]: answer([out(y, "yield", f"{y}%", measure=1)]) for r, y in zip(reactions, (61, 55))}
            _, records, _ = assemble(inv, handles, answers)
            self.assertEqual([rec["label"] for rec in records], ["3a", "3b"], product_first)
            self.assertEqual([parts_of(rec)["4"]["label"] for rec in records], ["4a", "4b"], product_first)


# ------------------------------------------------------------------ an entry that draws a reactant

def unsuccessful_figure(forward=True):
    """A product entry, then an 'unsuccessful substrate': the drawing is reactant 1 (numbered 1x),
    there is no product drawing, and the result is the word."""
    t = scope_template()
    if forward:
        t["derivations"].append(derivation("3", ["1", "2"], "the carbon that carries X bonds to the blue group"))
    (box1, drawing1), (box2, drawing2) = slot(0), slot(1)
    return figure(t, fields(column("substrate", "participant", targets=["1"])),
                  [entry("3a", 2, box1, [cell("product", structure_bbox=drawing1), cell("label", "3a"),
                                         cell("substrate"), cell("yield", "78%")]),
                   entry(None, 2, box2, [cell("product"), cell("label"),
                                         cell("substrate", "1x", structure_bbox=drawing2),
                                         cell("yield", "unsuccessful")])])


class EntryDrawsAReactant(Case):
    def test_needs_the_forward_derivation(self):
        errors, _ = validate_table(unsuccessful_figure(forward=False), ENTRIES_SCHEMA, SIZES, 2, DOC_PAGES)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("participant '3' is generic and rows ['2'] do not print it", errors[0])
        # With it the derivations run in a circle (1 <- 3, 2 <- 3, 3 <- 1 + 2); each entry enters it where it draws.
        errors, warnings = validate_table(unsuccessful_figure(), ENTRIES_SCHEMA, SIZES, 2, DOC_PAGES)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(warnings), ["entries[1]: '2' cannot be derived from this row: 3 not given",
                                            "entries[1]: '3' cannot be derived from this row: 2 not given"])

    def test_record(self):
        handles = listed(handle(1, [("yield", None)]), handle(2, [("yield", None)]))
        answers = {"e001-1": answer([out(78, "yield", "78%", product_key="3")]),
                   "e002-1": answer([out(None, "yield", "unsuccessful", product_key="3")])}
        _, view, by = self.read(unsuccessful_figure(), handles, answers, warnings=["cannot be derived from this row"])
        rec = by["e002-1"]
        p = parts_of(rec)
        self.assertEqual((p["1"]["source"], p["1"]["unknown"], p["1"]["page"], p["1"]["bbox"], p["1"]["label"],
                          p["1"]["crop"]),
                         ("drawn", False, 2, slot(1)[1], "1x", "c/_cell__e002-substrate.png"))
        for key in ("2", "3"):
            self.assertEqual((p[key]["source"], p[key]["unknown"], p[key]["page"]), ("derived", True, 1), key)
        self.assertIn("bonds to the blue group (from 1, 2)", p["3"]["basis"])
        # The result is what the entry prints: a word, no number.
        self.assertEqual([(o["yield"]["text"], o["yield"]["value"]) for o in p["3"]["outcomes"]],
                         [("unsuccessful", None)])
        self.assertEqual(rec["results"], ["unsuccessful"])
        # Nothing in the entry says which reagent 2 was tried: the record says so.
        self.assertEqual(sorted(rec["issues"]), ["'2' cannot be derived from this row: 3 not given",
                                                 "'3' cannot be derived from this row: 2 not given"])
        self.assertEqual((rec["label"], view["entries"][1]["entry"]["label"]), ("1x", "1x"))
        # The product entry next to it is read as usual.
        first = parts_of(by["e001-1"])
        self.assertEqual((first["1"]["unknown"], first["2"]["unknown"], first["3"]["source"], by["e001-1"]["issues"]),
                         (True, True, "drawn", []))

    def test_the_word_is_a_result(self):
        # In a remark field instead of the yield field, the entry has no result to hand to its reaction.
        inv = unsuccessful_figure()
        inv["columns"].append(column("remark", "other"))
        inv["entries"][0]["cells"].append(cell("remark"))
        inv["entries"][1]["cells"][3] = cell("yield")
        inv["entries"][1]["cells"].append(cell("remark", "unsuccessful"))
        _, warnings = validate_table(inv, ENTRIES_SCHEMA, SIZES, 2, DOC_PAGES)
        self.assertIn("entries[1]: prints no result", warnings)
        inv = numbered(inv)
        r = number_reactions(inv, listed(handle(1, [("yield", None)]), handle(2, [])))[1]
        errors, _ = validate_reaction(answer([out(None, "remark", "unsuccessful", product_key="3")]), REACTION_SCHEMA,
                                      inv, r, DOC_PAGES)
        self.assertTrue(any("column 'remark' is not one of this reaction's result cells" in e for e in errors), errors)


# ------------------------------------------------------------------ a remark that names a reactant

REMARK = "from the branched bromide"


def remark_figure():
    box, drawing = slot(0)
    return figure(scope_template(), fields(column("remark", "other")),
                  [entry("3a", 2, box, [cell("product", structure_bbox=drawing), cell("label", "3a"),
                                        cell("remark", REMARK), cell("yield", "74%")])])


class RemarkNamesAReactant(Case):
    def setUp(self):
        self.inv = numbered(remark_figure())
        self.handles = listed(handle(1, [("yield", None)]))
        self.r = number_reactions(self.inv, self.handles)[0]

    def errors(self, *overrides, validate=validate_reaction):
        a = answer([out(74, "yield", "74%", product_key="3")], overrides=overrides)
        return validate(a, REACTION_SCHEMA, self.inv, self.r, DOC_PAGES)[0]

    def test_printed_words_on_the_unknown_reactant(self):
        a = answer([out(74, "yield", "74%", product_key="3")],
                   overrides=[ov("1", "replace", REMARK, basis="remark under the drawing")])
        _, _, by = self.read(remark_figure(), self.handles, {"e001-1": a})
        one = parts_of(by["e001-1"])["1"]
        # Its words, not its structure: still to be worked out, from the product as before.
        self.assertEqual((one["source"], one["unknown"], one["text"], one["bbox"]),
                         ("derived", True, REMARK, self.inv["template"]["participants"][0]["bbox"]))
        self.assertIn("unknown, to be derived", one["basis"])
        self.assertEqual(by["e001-1"]["issues"], [])

    def test_a_reactant_table_takes_no_remark(self):
        errors = self.errors(ov("1", "replace", REMARK), validate=extract_rtable.validate_reaction)
        self.assertTrue(any("worked out later" in e for e in errors), errors)

    def test_only_what_the_entry_prints(self):
        errors = self.errors(ov("1", "replace", "2-bromobutane"))
        self.assertTrue(any("replace '1'" in e and "worked out later" in e for e in errors), errors)

    def test_only_the_words(self):
        for extra in ({"structure_key": "e001-product"}, {"stated_at": {"doc": "si", "page": 5}},
                      {"inferred": True}, {"role": "reactant"}):
            errors = self.errors(ov("1", "replace", REMARK, **extra))
            self.assertTrue(any("replace '1'" in e and "worked out later" in e for e in errors), (extra, errors))

    def test_not_on_the_product(self):
        errors = self.errors(ov("3", "replace", REMARK))
        self.assertTrue(any("replace '3'" in e and "the pipeline applies it" in e for e in errors), errors)

    def test_not_without_a_remark_field(self):
        # The same words in a field of another kind are not a remark about a reactant.
        self.inv["columns"][2]["kind"] = "deviation"
        errors = self.errors(ov("1", "replace", REMARK))
        self.assertTrue(any("worked out later" in e for e in errors), errors)


ISO = "from isopropyl bromide"


def remarks_figure(*remarks, notes=None, amount=None, forward=False):
    """One entry per remark ('3a', '3b', …), each with a drawing and a box of its own. `notes`: a second
    remark field, one text per entry; `amount`: a field that prints the amount of reactant 1 in every
    entry; `forward`: the product follows from the reactants too."""
    t = scope_template()
    if forward:
        t["derivations"].append(derivation("3", ["1", "2"], "the carbon that carries X bonds to the blue group"))
    extra = [column("remark", "other")]
    if notes is not None:
        extra.append(column("note", "other"))
    if amount is not None:
        extra.append(column("amount", "amount", targets=["1"]))
    entries = []
    for n, remark in enumerate(remarks):
        box, drawing = slot(n)
        label = f"3{'abcde'[n]}"
        cells = [cell("product", structure_bbox=drawing), cell("label", label), cell("remark", remark)]
        if notes is not None:
            cells.append(cell("note", notes[n]))
        if amount is not None:
            cells.append(cell("amount", amount))
        entries.append(entry(label, 2, box, cells + [cell("yield", "74%")]))
    return figure(t, fields(*extra), entries)


def each_entry(inv):
    return listed(*[handle(n, [("yield", None)]) for n in range(1, len(inv["entries"]) + 1)])


class RemarkInWholeWords(unittest.TestCase):
    """The words of a remark go onto an unknown reactant only as printed, whole, and with nothing else."""

    def errors(self, *overrides, inv=None, n=1, validate=validate_reaction):
        inv = numbered(inv or remarks_figure(ISO))
        r = number_reactions(inv, each_entry(inv))[n - 1]
        a = answer([out(74, "yield", "74%", product_key="3")], overrides=overrides)
        return validate(a, REACTION_SCHEMA, inv, r, DOC_PAGES)[0]

    def assertRejected(self, errors, key="1"):
        self.assertTrue(any(f"'{key}'" in e and "worked out later" in e for e in errors), errors)

    def test_the_figures_read(self):
        for inv in (remarks_figure(ISO), remarks_figure(ISO, "from the cyclic bromide"),
                    remarks_figure(ISO, forward=True), remarks_figure(ISO, amount="0.3 mmol"),
                    remarks_figure(ISO, notes=["gram scale"])):
            self.assertEqual(validate_table(inv, ENTRIES_SCHEMA, SIZES, len(inv["entries"]), DOC_PAGES)[0], [])

    def test_whole_words_are_accepted(self):
        for text in (ISO, "isopropyl bromide", "bromide", "from  isopropyl\nbromide"):
            self.assertEqual(self.errors(ov("1", "replace", text)), [], text)

    def test_a_cut_through_a_word_is_another_name(self):
        for text in ("propyl bromide",  # of "isopropyl": another compound
                     "i", "o",          # one letter of a word
                     "m isopropyl", "isopropyl bro", "rom isopropyl bromide"):  # cut across a word boundary
            self.assertRejected(self.errors(ov("1", "replace", text)))

    def test_not_on_a_drawn_product_that_has_a_derivation(self):
        inv = remarks_figure(ISO, forward=True)
        errors = self.errors(ov("3", "replace", ISO), inv=inv)
        self.assertTrue(any("replace '3'" in e and "the pipeline applies it" in e for e in errors), errors)
        self.assertEqual(self.errors(ov("1", "replace", ISO), inv=inv), [])

    def test_only_the_remark_of_its_own_entry(self):
        inv = remarks_figure(ISO, "from the cyclic bromide")
        self.assertRejected(self.errors(ov("1", "replace", "from the cyclic bromide"), inv=inv, n=1))
        self.assertRejected(self.errors(ov("1", "replace", ISO), inv=inv, n=2))
        self.assertEqual(self.errors(ov("1", "replace", "from the cyclic bromide"), inv=inv, n=2), [])

    def test_one_definite_replace(self):
        two = [{"text": ISO, "structure_key": None}, {"text": "from the cyclic bromide", "structure_key": None}]
        self.assertRejected(self.errors(ov("1", "replace", ISO, alternatives=two)))
        self.assertRejected(self.errors(ov("1", "remove", ISO)))
        self.assertRejected(self.errors(ov("1", "replace", ISO, step=1)))

    def test_with_the_amount_an_amount_field_prints(self):
        inv = remarks_figure(ISO, amount="0.3 mmol")
        self.assertTrue(any("gives the amount of '1'" in e for e in self.errors(ov("1", "replace", ISO), inv=inv)))
        both = (ov("1", "replace", ISO, amount="0.3 mmol"),)
        apart = (ov("1", "replace", ISO), ov("1", "replace", amount="0.3 mmol"))
        for overrides in (both, apart):
            self.assertEqual(self.errors(*overrides, inv=inv), [], overrides)
            a = answer([out(74, "yield", "74%", product_key="3")], overrides=overrides)
            _, records, _ = assemble(numbered(inv), each_entry(inv), {"e001-1": a})
            one = parts_of(records[0])["1"]
            self.assertEqual((one["text"], one["amount"], one["source"], one["unknown"], one["label"]),
                             (ISO, "0.3 mmol", "derived", True, "1"), overrides)


class RemarksInTheRecord(unittest.TestCase):
    """What synthesize keeps of an entry's remarks: the reactant they name keeps its number, and every
    remark nothing else carries reaches the notes."""

    def record(self, inv, overrides=(), notes="", n=1):
        a = {**answer([out(74, "yield", "74%", product_key="3")], overrides=overrides), "notes": notes}
        _, records, _ = assemble(numbered(inv), each_entry(inv), {f"e00{n}-1": a})
        return records[0]

    def test_remarks_that_tell_the_results_apart(self):
        """One entry, two results told apart by remarks about reactant 1 ("from A / from B"): each
        reaction writes its own remark onto the reactant, and the notes do not repeat the other's."""
        remark = "from the E isomer / from the Z isomer"
        inv = remarks_figure(remark)
        inv["entries"][0]["cells"][-1] = cell("yield", "80% / 60%")
        handles = listed(handle(1, [("yield", "80%")], distinguishing="from the E isomer"),
                         handle(1, [("yield", "60%")], distinguishing="from the Z isomer"))
        answers = {
            "e001-1": {**answer([out(80, "yield", "80%", product_key="3")],
                                overrides=[ov("1", "replace", "from the E isomer")]), "notes": ""},
            "e001-2": {**answer([out(60, "yield", "60%", product_key="3")],
                                overrides=[ov("1", "replace", "from the Z isomer")]), "notes": ""},
        }
        _, records, _ = assemble(numbered(inv), handles, answers)
        self.assertEqual([r["notes"] for r in records], ["", ""])
        self.assertEqual([parts_of(r)["1"]["text"] for r in records], ["from the E isomer", "from the Z isomer"])
        # Without an override neither reaction knows which remark is its own: both keep the whole cell.
        answers = {rid: {**a, "overrides": []} for rid, a in answers.items()}
        _, records, _ = assemble(numbered(inv), handles, answers)
        self.assertEqual([r["notes"] for r in records], [f"printed: {remark}"] * 2)

    def test_the_named_reactant_keeps_its_number(self):
        rec = self.record(remarks_figure(ISO), [ov("1", "replace", ISO, basis="remark under the drawing")])
        one = parts_of(rec)["1"]
        self.assertEqual((one["label"], one["text"], one["unknown"]), ("1", ISO, True))
        # The reactant-table synthesis alone leaves it without one.
        inv = numbered(remarks_figure(ISO))
        r = number_reactions(inv, each_entry(inv))[0]
        a = answer([out(74, "yield", "74%", product_key="3")], overrides=[ov("1", "replace", ISO)])
        child = extract_rtable.synthesize(inv, r, a, {}, {})[2]
        self.assertEqual({p["key"]: p["label"] for p in child["participants"]}["1"], None)
        self.assertEqual({p["key"]: p["label"] for p in synthesize(inv, r, a, {}, {})[2]["participants"]}["1"], "1")

    def test_every_remark_reaches_the_notes(self):
        inv = remarks_figure(ISO, "", notes=["gram scale", "under air"])
        # Written onto the reactant: only the other remark is added.
        self.assertEqual(self.record(inv, [ov("1", "replace", ISO)])["notes"], "printed: gram scale")
        # Nothing carries them: both, in field order.
        self.assertEqual(self.record(inv)["notes"], f"printed: {ISO}; printed: gram scale")
        # The session's notes come first and keep what they already say.
        self.assertEqual(self.record(inv, notes="run on gram scale in the SI")["notes"],
                         f"run on gram scale in the SI; printed: {ISO}")
        # An override that quotes whole words of the remark carries it.
        self.assertEqual(self.record(inv, [ov("1", "replace", "isopropyl bromide")], notes="gram scale")["notes"],
                         "gram scale")
        # An empty remark field adds nothing.
        self.assertEqual(self.record(inv, n=2)["notes"], "printed: under air")


# ------------------------------------------------------------------ reactions of two steps

def sequence_template(isolated=False):
    """Acid 1 -> (activation) -> ester -> (coupling with 2) -> 3. No entry draws the ester: it
    follows from the product, and the acid from the ester."""
    return template(
        [tpart("1", "reactant", "1", amount="0.2 mmol", bbox=[60, 60, 120, 100]),
         tpart("ester", "intermediate", "4", bbox=[190, 60, 260, 100], isolated=isolated),
         tpart("2", "reactant", "2", "R–M", "1.5 equiv", bbox=[280, 65, 330, 95]),
         tpart("3", "product", "3", bbox=[450, 60, 540, 100])],
        [step(1, ["1"], ["ester"], "activation"), step(2, ["ester", "2"], ["3"], "coupling")],
        [cond("activator", "reagent", "HATU", "1.0 equiv", step=1), cond("base", "base", "Et3N", "1.0 equiv", step=1),
         cond("cat", "catalyst", "Fe(acac)3", "10 mol%", step=2), cond("time", "time", "1 h", step=2)],
        derivations=[derivation("1", ["ester"], "the ester's activating group replaced by OH"),
                     derivation("ester", ["3"], "the part of the product that is not blue, as the activated ester"),
                     derivation("2", ["3"], "the blue group of the product, as R–M")],
        default_yield_type="isolated")


def sequence_figure():
    """Every entry is the two-step sequence; its yield is that of the product over both steps."""
    box, drawing = slot(0)
    return figure(sequence_template(), fields(),
                  [entry("3a", 2, box, [cell("product", structure_bbox=drawing), cell("label", "3a"),
                                        cell("yield", "72%")])])


def isolated_figure(ester_as_product=True):
    """The ester is isolated and has a number and a yield of its own ('4a, 85%; 3a, 72%'): each step
    is a reaction, picked by a variant that takes the other step away."""
    box, drawing = slot(0)
    t = sequence_template(isolated=True)
    first = [ov("3", "remove", basis="the first step alone")]
    if ester_as_product:
        first.append(ov("ester", "replace", role="product", basis="isolated: what the first step makes"))
    second = [ov("1", "remove", basis="starts from the isolated ester"),
              ov("ester", "replace", role="reactant", basis="isolated: what the second step starts from")]
    t["variants"] = [variant("activation", "first step", first), variant("coupling", "second step", second)]
    columns = fields(column("ester", "label", targets=["ester"]),
                     column("ester_yield", "outcome", measures=[measure("ester", "yield", "isolated")]))
    return figure(t, columns, [entry("3a", 2, box, [cell("product", structure_bbox=drawing), cell("label", "3a"),
                                                    cell("ester", "4a"), cell("ester_yield", "85%"),
                                                    cell("yield", "72%")])])


def isolated_handles():
    return listed(handle(1, [("ester_yield", None)], variant="activation"),
                  handle(1, [("yield", None)], variant="coupling"))


def isolated_answers():
    return {"e001-1": answer([out(85, "ester_yield", "85%")]),
            "e001-2": answer([out(72, "yield", "72%", product_key="3")])}


def laid_out(record):
    """The steps of a record: (description, reactant keys, product keys, condition keys)."""
    return [(st["description"], [p["key"] for p in st["reactants"]], [p["key"] for p in st["products"]],
             [c["key"] for c in st["conditions"]]) for st in record["steps"]]


class TwoSteps(Case):
    def test_every_entry_is_a_sequence(self):
        answers = {"e001-1": answer([out(72, "yield", "72%", product_key="3")])}
        _, _, by = self.read(sequence_figure(), listed(handle(1, [("yield", None)])), answers)
        rec = by["e001-1"]
        self.assertEqual(laid_out(rec), [("activation", ["1"], ["ester"], ["activator", "base"]),
                                         ("coupling", ["ester", "2"], ["3"], ["cat", "time"])])
        self.assertEqual(([st["step"] for st in rec["steps"]], rec["conditions"]), ([1, 2], []))
        made, used = rec["steps"][0]["products"][0], rec["steps"][1]["reactants"][0]
        for ester in (made, used):
            self.assertEqual((ester["role"], ester["isolated"], ester["source"], ester["unknown"]),
                             ("intermediate", False, "derived", True))
        self.assertEqual(made["outcomes"], [])  # the yield is the product's, over both steps
        p = parts_of(rec)
        self.assertEqual((p["3"]["source"], p["3"]["bbox"], p["3"]["outcomes"][0]["yield"]["value"]),
                         ("drawn", slot(0)[1], 72))
        self.assertEqual((p["1"]["unknown"], p["2"]["unknown"], rec["issues"]), (True, True, []))

    def test_isolated_intermediate_gives_a_reaction_per_step(self):
        # Two stage 1 warnings come with this reading: the ester's yield is measured on what the template calls
        # an intermediate, and the two variants are not labels the entry prints.
        _, _, by = self.read(isolated_figure(), isolated_handles(), isolated_answers(),
                             warnings=["a yield measured on 'ester'", "the label of variant"])
        first, second = by["e001-1"], by["e001-2"]
        self.assertEqual(laid_out(first), [("activation", ["1"], ["ester"], ["activator", "base"])])
        self.assertEqual(laid_out(second), [("coupling", ["ester", "2"], ["3"], ["cat", "time"])])
        self.assertEqual([(r["label"], r["variant"]["key"], r["results"]) for r in (first, second)],
                         [("3a", "activation", ["85%"]), ("3a", "coupling", ["72%"])])
        # The first step makes the ester: its number and its yield, on a compound still to be worked out.
        acid, ester = first["steps"][0]["reactants"][0], first["steps"][0]["products"][0]
        self.assertEqual((ester["role"], ester["label"], ester["source"], ester["unknown"]),
                         ("product", "4a", "derived", True))
        self.assertEqual([o["yield"]["value"] for o in ester["outcomes"]], [85])
        self.assertEqual((acid["source"], acid["unknown"]), ("derived", True))
        # The second step starts from it and ends in the entry's drawing.
        ester, product = second["steps"][0]["reactants"][0], second["steps"][0]["products"][0]
        self.assertEqual((ester["role"], ester["label"], ester["unknown"]), ("reactant", "4a", True))
        self.assertEqual((product["source"], product["bbox"], product["label"]), ("drawn", slot(0)[1], "3a"))
        self.assertEqual([o["yield"]["value"] for o in product["outcomes"]], [72])
        self.assertEqual(second["issues"], [])

    def test_first_step_follows_from_the_entrys_drawing(self):
        # The entry draws the product of the sequence: the ester follows from that drawing and the acid from the
        # ester, also in the record of the first step, whose variant took the product away. That record must not
        # call the product "not given".
        _, records, _ = assemble(numbered(isolated_figure()), isolated_handles(), isolated_answers())
        first = by_rid(records)["e001-1"]
        self.assertEqual([x for x in first["issues"] if "not given" in x], [])

    def test_first_step_task_has_nothing_it_cannot_derive(self):
        # The stage 2 task of the first step tells the session the same: nothing that cannot be derived.
        inv, handles = numbered(isolated_figure()), isolated_handles()
        r = number_reactions(inv, handles)[0]
        extra = s2_pscope.SPEC.stage2_task({"entry": {"eid": "e001"}}, inv, handles, r)
        self.assertEqual(extra["cannot_derive"], [])
        state = {p["key"]: p["state"] for p in extra["participants"]}
        self.assertEqual(state, {"1": "unknown", "ester": "unknown"})
        # It is the entry's drawing that makes them derivable: without it the ester would be "not given".
        self.assertEqual(extract_rtable.underivable(inv["template"], state),
                         ["'1' cannot be derived from this row: ester not given",
                          "'ester' cannot be derived from this row: 3 not given"])
        self.assertEqual(extract_rtable.row_prints(inv, reaction_cells(inv, r)), {"3"})

    def test_an_amount_of_one_step(self):
        # An amount the paper gives for the reagent of the second step: amount only, with its step; it stays unknown.
        inv = numbered(sequence_figure())
        r = number_reactions(inv, listed(handle(1, [("yield", None)])))[0]
        a = answer([out(72, "yield", "72%", product_key="3")],
                   overrides=[ov("2", "replace", amount="2.0 equiv", step=2, basis="general procedure")])
        for validate in (extract_rtable.validate_reaction, validate_reaction):
            self.assertEqual(validate(a, REACTION_SCHEMA, inv, r, DOC_PAGES), ([], []), validate.__module__)
        _, records, _ = assemble(inv, listed(handle(1, [("yield", None)])), {"e001-1": a})
        two = parts_of(records[0])["2"]
        self.assertEqual((two["amount"], two["unknown"], two["source"]), ("2.0 equiv", True, "derived"))
        # A name on it is still not the session's to write.
        a["overrides"][0]["text"] = "PhMgBr"
        errors, _ = extract_rtable.validate_reaction(a, REACTION_SCHEMA, inv, r, DOC_PAGES)
        self.assertTrue(any("replace '2'" in e and "worked out later" in e for e in errors), errors)

    def test_template_check_of_a_variant(self):
        inv = numbered(isolated_figure())
        r = number_reactions(inv, isolated_handles())[0]
        a = copy.deepcopy(isolated_answers()[r["rid"]])
        a["template_check"] = [{"target": "activation", "stage1": "the first step alone", "seen": "the first step alone",
                                "evidence": "the label over the ester's yield"}]
        self.assertEqual(extract_rtable.validate_reaction(a, REACTION_SCHEMA, inv, r, DOC_PAGES), ([], []))
        a["template_check"][0]["target"] = "first step"
        _, warnings = extract_rtable.validate_reaction(a, REACTION_SCHEMA, inv, r, DOC_PAGES)
        self.assertEqual(warnings, ["template_check: unknown target 'first step'"])

    def test_the_isolated_ester_is_made_a_product(self):
        # The variant of the first step also turns the ester into a product: left an intermediate, it cannot
        # take the yield the entry prints for it.
        inv = numbered(isolated_figure(ester_as_product=False))
        self.assertEqual(validate_handles(isolated_handles(), inv, HANDLES_SCHEMA)[0], [])
        r = number_reactions(inv, isolated_handles())[0]
        errors, _ = validate_reaction(isolated_answers()[r["rid"]], REACTION_SCHEMA, inv, r, DOC_PAGES)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("product_key 'ester' is not a product or byproduct of this reaction", errors[0])


# ------------------------------------------------------------------ a shared general scheme

class SharedScheme(unittest.TestCase):
    def test_a_leader_with_one_compound_in_a_position(self):
        # The driver validates, copies the leader's scheme participants over the template's, and validates again.
        inv = r_list_figure()
        self.assertEqual(validate_table(inv, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)[0], [])
        leader = [{**copy.deepcopy(p), "generic": False, "text": "the model compound"}
                  for p in inv["template"]["participants"] if p["key"] in ("1", "3")]
        self.assertEqual(_Job._apply_shared(inv, leader), [])
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)
        self.assertTrue(any("different compounds in position '3'" in e for e in errors), errors)
        self.assertTrue(any("derivations '1'" in e and "generic true" in e for e in errors), errors)

    def test_generic_positions_are_shared_unchanged(self):
        inv = r_list_figure()
        leader = [{**copy.deepcopy(p), "label": "S", "bbox": [50, 50, 160, 110]}
                  for p in inv["template"]["participants"] if p["key"] == "1"]
        self.assertEqual(_Job._apply_shared(inv, leader), [])
        self.assertEqual(validate_table(inv, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES), ([], []))
        self.assertEqual((inv["template"]["participants"][0]["label"], inv["template"]["participants"][0]["bbox"]),
                         ("S", [50, 50, 160, 110]))


# ------------------------------------------------------------------ the driver, without Codex or a PDF

class StubJob:
    """Just what s2_table.read_table and collect_reaction ask of s2_extract._Job. `_codex` runs the
    driver's check on the canned `answer` (None: the session gives nothing) and keeps the prompts."""
    _block_dir = _Job._block_dir
    _apply_shared = staticmethod(_Job._apply_shared)
    _soften_coverage = staticmethod(_Job._soften_coverage)

    def __init__(self, out: Path, answer=None, shared=None):
        self.out, self.answer, self.shared, self.prompts = out, answer, shared, []
        self.ws = SimpleNamespace(log_dir=out / "logs")
        self.cfg = SimpleNamespace(extract=SimpleNamespace(inventory_timeout_s=1, entry_timeout_s=1))
        self.log, self.codex_cfg, self.doc_pages = logging.getLogger("test_extract_pscope"), {}, DOC_PAGES
        self.pdf_lock = threading.Lock()

    def _base_task(self, mode, region, block):
        return {"mode": mode, "block": {"scheme": None}}

    def _shared_participants(self, region, block):
        return self.shared

    def _page_sizes(self, doc):
        return SIZES

    def _block_images(self, *args, **kw):
        return [], ""

    def _page(self, doc, page):
        return None

    def _inventory_geometry(self, doc, block, inv, coverage=True):
        self.coverage = coverage
        return []

    def _overlays(self, *args):
        return []

    def _template_crops(self, *args):
        pass

    def _codex(self, schema, prompt, images, raw_path, events, timeout, check, thread_id=None, prior=None,
               geometry_repair=None):
        self.prompts.append(prompt)
        data = copy.deepcopy(self.answer)
        errors, warnings = check(data) if data is not None else (["codex: no answer"], [])
        return data, {"status": "failed" if errors else "ok", "errors": errors, "warnings": warnings,
                      "seconds": 0.0, "thread_id": "thread"}


def no_pdf():
    """The driver's own helpers that open the PDF, patched out."""
    image = SimpleNamespace(save=lambda path: None)
    return mock.patch.multiple(s2_table, candidate_images=lambda *a, **kw: ([], ""),
                               _text_layer=lambda *a: None, _trim_cells=lambda *a: [],
                               _box_edges=lambda *a: [], _settle_box_edges=lambda *a: ([], []),
                               _cell_crops=lambda *a: None,
                               render_grid=lambda *a, **kw: (image, None, None))


class DriverRevalidates(unittest.TestCase):
    """read_table validates the answer, takes the leader's participants over and validates again."""
    BLOCK = {**BLOCK, "n_entries_est": 3}

    def read(self, shared):
        with tempfile.TemporaryDirectory() as tmp, no_pdf():
            job = StubJob(Path(tmp), r_list_figure(), shared)
            inv = s2_table.read_table(s2_pscope.SPEC, job, REGION, self.BLOCK)
            self.assertEqual(len(job.prompts), 1)
            return inv

    def leader(self, key, **change):
        return [{**copy.deepcopy(p), **change} for p in r_list_figure()["template"]["participants"] if p["key"] == key]

    def test_a_leader_with_one_compound_where_the_entries_draw_theirs(self):
        """The leader holds fixed what this block's entries vary: the block keeps its own participants (it
        validated on its own; the leader's would come back in every repair round) and says why."""
        self.assertEqual(validate_table(r_list_figure(), ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)[0], [])
        inv = self.read(self.leader("3", generic=False, text="the model compound"))
        meta = inv["_meta"]
        self.assertEqual((meta["status"], meta["errors"], len(inv["entries"])), ("ok", [], 3))
        three = next(p for p in inv["template"]["participants"] if p["key"] == "3")
        self.assertEqual((three["generic"], three["text"]), (True, r_list_figure()["template"]["participants"][2]["text"]))
        prefix = "the participants of the shared scheme were not taken over from the block that leads it"
        clash = [w for w in meta["warnings"] if w.startswith(prefix)]
        self.assertTrue(clash and any("different compounds in position '3'" in w for w in clash), meta["warnings"])

    def test_a_generic_leader_passes(self):
        inv = self.read(self.leader("1", label="S", bbox=[50, 50, 160, 110]))
        meta = inv["_meta"]
        self.assertEqual((meta["status"], meta["errors"], meta["warnings"]), ("ok", [], []))
        self.assertEqual([en["eid"] for en in inv["entries"]], ["e001", "e002", "e003"])
        one = inv["template"]["participants"][0]
        self.assertEqual((one["key"], one["label"], one["bbox"]), ("1", "S", [50, 50, 160, 110]))

    def test_without_a_leader(self):
        self.assertEqual(self.read(None)["_meta"]["status"], "ok")


def unlabelled_figure(n, unlabelled):
    """n entries, each with its own drawing and box; those numbered in `unlabelled` (1-based) print no
    compound number at all."""
    entries = []
    for i in range(1, n + 1):
        box, drawing = slot(i - 1)
        label = None if i in unlabelled else f"3{'abcdef'[i - 1]}"
        entries.append(entry(label, 2, box, [cell("product", structure_bbox=drawing), cell("label", label or ""),
                                             cell("yield", f"{60 + i}%")]))
    return figure(scope_template(), fields(), entries)


class UnlabelledEntries(unittest.TestCase):
    def test_called_entry_n(self):
        self.assertEqual(validate_table(unlabelled_figure(3, {3}), ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)[0], [])
        inv = numbered(unlabelled_figure(3, {3}))
        self.assertEqual([entry_label(inv, en) for en in inv["entries"]], ["3a", "3b", "entry 3"])
        self.assertEqual(extract_rtable.entry_label(inv, inv["entries"][2]), "row 3")
        handles = each_entry(inv)
        answers = {r["rid"]: answer([out(60 + r["entry"], "yield", f"{60 + r['entry']}%", product_key="3")])
                   for r in number_reactions(inv, handles)}
        view, records, _ = assemble(inv, handles, answers)
        self.assertEqual((records[2]["label"], view["entries"][2]["entry"]["label"]), ("entry 3", "entry 3"))

    def prompt(self, spec, inv, n):
        """The prompt collect_reaction gives the stage 2 session of entry n."""
        handles = each_entry(inv)
        reactions = spec.number_reactions(inv, handles)
        handles = {**handles, "reactions": reactions}
        with tempfile.TemporaryDirectory() as tmp, no_pdf():
            job = StubJob(Path(tmp))
            s2_table.collect_reaction(spec, job, REGION, BLOCK, inv, handles, reactions[n - 1])
        self.assertEqual(len(job.prompts), 1)
        return job.prompts[0]

    def test_how_the_prompt_calls_the_entry(self):
        inv = numbered(unlabelled_figure(5, {3, 5}))
        # A table row without a number gets no name (as before); a product scope calls it 'entry N'; never twice.
        self.assertIn("(reactant table, reaction e005-1; results: 65%)", self.prompt(s2_rtable.SPEC, inv, 5))
        self.assertIn("(product scope, reaction e003-1, entry 3; results: 63%)", self.prompt(s2_pscope.SPEC, inv, 3))
        prompt = self.prompt(s2_pscope.SPEC, inv, 1)
        self.assertIn("(product scope, reaction e001-1, entry 3a; results: 61%)", prompt)
        for p in (self.prompt(s2_rtable.SPEC, inv, 5), self.prompt(s2_pscope.SPEC, inv, 3)):
            self.assertNotIn("entry row", p)
            self.assertNotIn("entry entry", p)


# ------------------------------------------------------------------ schemas, driver helpers

class Schemas(unittest.TestCase):
    def test_the_three_schemas_are_generated(self):
        for name in ("entries", "handles", "reaction"):
            self.assertIn(f"pscope_{name}", build_extract.SCHEMAS)
            self.assertTrue(s2_pscope.SPEC.schema_path(name).exists(), name)
            self.assertEqual(s2_pscope.SPEC.schema(name), build_extract.SCHEMAS[f"pscope_{name}"], name)

    def test_the_data_model_is_the_reactant_tables(self):
        def shape(node):
            if isinstance(node, dict):
                return {k: shape(v) for k, v in node.items() if k != "description"}
            return [shape(v) for v in node] if isinstance(node, list) else node
        for name in ("entries", "handles", "reaction"):
            self.assertEqual(shape(build_extract.SCHEMAS[f"pscope_{name}"]),
                             shape(build_extract.SCHEMAS[f"rtable_{name}"]), name)

    def test_answers_fit_the_schemas(self):
        inv = scheme3_figure()
        self.assertEqual(validate_table(inv, ENTRIES_SCHEMA, SIZES, 20, DOC_PAGES), ([], []))
        del inv["template"]["derivations"]
        errors, _ = validate_table(inv, ENTRIES_SCHEMA, SIZES, 20, DOC_PAGES)
        self.assertTrue(errors and all(e.startswith("schema at") for e in errors), errors)
        inv, handles = numbered(scheme3_figure()), scheme3_handles()
        del handles["reactions"][0]["cells"]
        errors, _ = validate_handles(handles, inv, HANDLES_SCHEMA)
        self.assertTrue(errors and all(e.startswith("schema at") for e in errors), errors)
        r = number_reactions(inv, scheme3_handles())[0]
        a = answer([out(80, "yield", "80%", product_key="3")])
        del a["labels"]
        errors, _ = validate_reaction(a, REACTION_SCHEMA, inv, r, DOC_PAGES)
        self.assertTrue(errors and all(e.startswith("schema at") for e in errors), errors)


class DriverHelpers(unittest.TestCase):
    def test_one_tag_for_entries_with_one_box(self):
        self.assertEqual(eid_ranges(["e014", "e015"]), "e014-e015")
        self.assertEqual(eid_ranges(["e001", "e003", "e004", "e005", "e009"]), "e001, e003-e005, e009")
        self.assertEqual(eid_ranges(["e007"]), "e007")

    def test_closeups_of_a_large_figure(self):
        self.assertEqual(zoom_pieces([100, 100, 340, 280]), [])  # the overview is a close-up already
        area = [40, 60, 570, 700]
        pieces = zoom_pieces(area)
        self.assertEqual(len(pieces), 6)
        covered = [min(p[i] for p in pieces) for i in (0, 1)] + [max(p[i] for p in pieces) for i in (2, 3)]
        self.assertEqual(covered, area)
        self.assertTrue(all(area[0] <= x0 < x1 <= area[2] and area[1] <= y0 < y1 <= area[3]
                            for x0, y0, x1, y1 in pieces))
        # Left to right, top to bottom, and neighbours overlap.
        self.assertEqual(pieces, sorted(pieces, key=lambda p: (p[1], p[0])))
        self.assertTrue(pieces[0][2] > pieces[1][0] and pieces[0][3] > pieces[3][1])


if __name__ == "__main__":
    unittest.main()
