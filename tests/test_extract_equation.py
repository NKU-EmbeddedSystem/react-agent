"""The equation path of Step 2 (pipeline/extract_equation.py): validators, the template of one
equation, assembly into records and views, and the driver's use of them.

The fixture is a made-up block written out by hand as the two skills would answer. It has the cases
an equation block is read for: a starting material at the centre of several arrows (one compound,
used by four equations), a two-step sequence over one arrow whose intermediate is not drawn, an
equation whose conditions are given by a reference plus a printed addition and whose two results
come from two protocols ("A or B" over the arrow), a drawing with a variable group whose results are
told apart by its values, and a starting material recovered at the end. Everything is on page 2."""

import copy
import tempfile
import unittest
from pathlib import Path

from pipeline.extract_ctable import assemble_view
from pipeline.extract_equation import (LAYOUT, OPS, compose, entry_label, number_reactions, prepare, template_of,
                                       validate_handles, validate_reaction, validate_table)
from pipeline.extract_view import block_view
from pipeline.steps import s2_ctable, s2_equation, s2_table
from tests.test_extract_pscope import StubJob, no_pdf
from tests.test_extract_records import cond, ov, step, variant

ENTRIES_SCHEMA = s2_equation.SPEC.schema("entries")
HANDLES_SCHEMA = s2_equation.SPEC.schema("handles")
REACTION_SCHEMA = s2_equation.SPEC.schema("reaction")
SIZES = {1: (600.0, 800.0), 2: (600.0, 800.0)}
DOC_PAGES = {"main": 4, "si": 40}
REGION = {"region_id": "main:scheme5", "doc": "main", "label": "Scheme 5", "first_page": 2,
          "caption": "Scheme 5. Transformations and control experiments"}
BLOCK = {"block_id": "A", "kind": "application", "layout": LAYOUT, "page": 2, "title": None,
         "bbox": [40, 40, 560, 500], "n_entries_est": 5}
STANDARD = {"doc": "main", "page": 2}


# ------------------------------------------------------------------ builders

def compound(key, label=None, text=None, bbox=None, generic=False, stated_at=None):
    return {"key": key, "label": label, "text": text, "generic": generic, "page": 2 if bbox else None,
            "bbox": bbox, "stated_at": stated_at}


def part(key, role, amount=None, isolated=None, stated_at=None):
    return {"key": key, "role": role, "amount": amount, "isolated": isolated, "alternatives": [],
            "stated_at": stated_at}


def equation(label, bbox, results, participants, steps, conditions=(), variants=(), markers=(), pointer=None,
             groups=(), descriptor="", general="a transformation"):
    return {"label": label, "page": 2, "bbox": bbox, "descriptor": descriptor or label or "equation",
            "general_reaction": general, "results": list(results), "footnote_markers": list(markers),
            "participants": list(participants), "steps": list(steps),
            "conditions": [{k: v for k, v in c.items() if k != "per_entry"} for c in conditions],
            "condition_pointer": pointer, "alternative_groups": list(groups), "preparations": [],
            "variable_defaults": [], "default_yield_type": "isolated", "variants": list(variants)}


def footnote(marker, text, overrides=(), notes=""):
    return {"marker": marker, "text": text, "overrides": list(overrides), "notes": notes}


def block_answer():
    """Five equations around the starting material 8 (drawn once at the centre)."""
    compounds = [
        compound("8", "8", bbox=[260, 200, 340, 260]),
        compound("9", "9", bbox=[60, 60, 140, 120]),
        compound("reagent-a", text="LiCH2Cl"),
        compound("int", text="the boronate formed in step 1"),
        compound("10", "10", bbox=[440, 60, 540, 120]),
        compound("tempo", text="TEMPO"),
        compound("11", "11", bbox=[60, 300, 140, 360]),
        compound("adduct", bbox=[150, 300, 230, 360]),
        compound("13", "13", text="Ar–XH", bbox=[440, 300, 520, 360], generic=True),
        compound("14", "14", bbox=[440, 400, 540, 460], generic=True),
        compound("15", "15", bbox=[60, 400, 140, 460]),
    ]
    eqs = [
        equation(None, [50, 50, 350, 270], ["9, 74% b"],
                 [part("8", "reactant", "0.15 mmol"), part("9", "product")], [step(1, ["8"], ["9"])],
                 [cond("ox", "reagent", "NaBO3·4H2O"), cond("solvent", "solvent", "THF/H2O"),
                  cond("temp", "temperature", "rt")], markers=["b"], descriptor="8 → 9; 74% b"),
        equation(None, [260, 50, 550, 270], ["10, 62% a"],
                 [part("8", "reactant"), part("reagent-a", "reactant"), part("int", "intermediate", isolated=False),
                  part("10", "product")],
                 [step(1, ["8", "reagent-a"], ["int"]), step(2, ["int"], ["10"])],
                 [cond("solvent", "solvent", "THF", step=1), cond("ox", "reagent", "NaBO3·4H2O", step=2)],
                 markers=["a"], descriptor="1) LiCH2Cl 2) NaBO3; 10, 62%"),
        equation(None, [50, 280, 350, 380], ["11, ND (TEMPO)", "11, 10% (BHT)", "adduct, 17%"],
                 [part("8", "reactant"), part("tempo", "reactant", "2.0 equiv"), part("11", "product"),
                  part("adduct", "byproduct")],
                 [step(1, ["8", "tempo"], ["11", "adduct"])],
                 [cond("cat", "catalyst", "FeCl3", "5 mol%", stated_at=STANDARD),
                  cond("solvent", "solvent", "THF", stated_at=STANDARD)],
                 variants=[variant("tempo", "TEMPO"),
                           variant("bht", "BHT", [ov("tempo", "remove"), ov("adduct", "remove"),
                                                  ov("bht", "add", "BHT", "2.0 equiv", "additive")])],
                 pointer={"printed": "standard conditions", "refers_to": "the optimized conditions of Table 1",
                          "found": True, "stated_at": STANDARD},
                 descriptor="standard conditions, TEMPO or BHT; 11 ND / 10%; adduct 17%"),
        equation(None, [360, 280, 550, 470], ["X = O: 89%", "X = NTs: 97%"],
                 [part("8", "reactant"), part("13", "reactant", "1.2 equiv"), part("14", "product")],
                 [step(1, ["8", "13"], ["14"])], [cond("cat", "catalyst", "CuI", "10 mol%")],
                 descriptor="X = O: 89%; X = NTs: 97%"),
        equation("(2)", [50, 390, 350, 490], ["15, 30%, 91% ee", "8, 55%, 99% ee (recovered)"],
                 [part("8", "reactant"), part("15", "product")], [step(1, ["8"], ["15"])],
                 [cond("cat", "catalyst", "NiBr2", "10 mol%"), cond("ligand", "ligand", "L*", "13 mol%", "L*")],
                 descriptor="(2) stopped at partial conversion"),
    ]
    return {"reading_guide": "The arrows start from 8; each arrow is one equation.", "compounds": compounds,
            "structures": [{"key": "L*", "label": "L*", "text": None, "page": 2, "bbox": [160, 400, 220, 440]}],
            "footnotes": [footnote("a", "Yield over two steps."),
                          footnote("b", "At 0 °C.", [ov("temp", "replace", "0 °C", basis="footnote b")])],
            "context": [{"doc": "main", "page": 2, "text": "…under the standard conditions…", "about": "the pointer"}],
            "equations": eqs, "ignored": [{"page": 2, "bbox": [400, 480, 550, 495], "reason": "photograph"}],
            "notes": ""}


def handle(n, results, variant=None, markers=(), distinguishing=None, variables=()):
    return {"entry": n, "results": list(results), "variant": variant, "footnote_markers": list(markers),
            "distinguishing": distinguishing, "variables": list(variables)}


def var(name, value, *keys):
    return {"name": name, "value": value, "participant_keys": list(keys)}


def block_handles():
    return {"reactions": [
        handle(1, [1], markers=["b"]),
        handle(2, [1], markers=["a"]),
        handle(3, [1, 3], "tempo", distinguishing="TEMPO"),
        handle(3, [2], "bht", distinguishing="BHT"),
        handle(4, [1], distinguishing="X = O", variables=[var("X", "O", "13", "14")]),
        handle(4, [2], distinguishing="X = NTs", variables=[var("X", "NTs", "13", "14")]),
        handle(5, [1, 2]),
    ], "notes": [], "issues": []}


def out(result, value, text, product_key=None, qualifier=None, selectivity=(), notes=None, markers=()):
    return {"product_key": product_key, "yield_text": text, "yield_value": value, "yield_qualifier": qualifier,
            "yield_type": None, "selectivity": list(selectivity), "footnote_markers": list(markers), "notes": notes,
            "result": result}


def answer(outcomes, lookup=(), labels=(), template_check=(), issues=(), notes=""):
    return {"template_check": list(template_check), "outcomes": list(outcomes), "lookup": list(lookup),
            "labels": list(labels), "related": [], "notes": notes, "issues": list(issues)}


SI = {"doc": "si", "page": 21}


def block_answers():
    return {
        "e001-1": answer([out(1, 74, "74%", "9", markers=["b"])],
                         lookup=[ov("8", "replace", amount="0.15 mmol (43 mg)", stated_at=SI),
                                 ov("time", "add", "16 h", role="time", stated_at=SI)]),
        "e002-1": answer([out(1, 62, "62%", "10", markers=["a"])]),
        "e003-1": answer([out(1, None, "ND", "11", qualifier="ND"), out(3, 17, "17%", "adduct")],
                         labels=[{"key": "adduct", "label": "11-T", "stated_at": SI}]),
        "e003-2": answer([out(2, 10, "10%", "11")]),
        "e004-1": answer([out(1, 89, "89%")], lookup=[ov("13", "replace", "2-iodophenol", stated_at=SI)]),
        "e004-2": answer([out(2, 97, "97%")]),
        "e005-1": answer([out(1, 30, "30%", "15", selectivity=[{"type": "ee", "text": "91% ee"}]),
                          out(2, 55, "55%", "8", selectivity=[{"type": "ee", "text": "99% ee"}],
                              notes="recovered starting material")]),
    }


def read_block():
    """The fixture through the three validators, prepared and numbered as the driver stores it."""
    data = block_answer()
    errors, warnings = validate_table(data, ENTRIES_SCHEMA, SIZES, BLOCK["n_entries_est"], DOC_PAGES)
    assert errors == [], errors
    inv = prepare(data)
    for i, en in enumerate(inv["entries"], 1):
        en["eid"] = f"e{i:03d}"
    return inv


def assemble(inv, handles, answers):
    inv = {**inv, "_meta": {"status": "ok", "errors": [], "warnings": [], "overlays": []}}
    reactions = number_reactions(inv, handles)
    handles = {**handles, "reactions": reactions, "_meta": {"status": "ok", "errors": [], "warnings": []}}
    stored = {r["rid"]: ({**answers[r["rid"]], "_meta": {"errors": [], "warnings": [], "seconds": 1}}, "ok")
              for r in reactions if r["rid"] in answers}
    crops = {p["key"]: f"c/_template__{p['key']}.png" for p in inv["template"]["participants"] if p["bbox"]}
    structures = {x["key"]: f"c/_structure__{x['key']}.png" for x in inv["template"]["structures"]}
    return assemble_view(REGION, BLOCK, "main-scheme5__A", inv, "ok", handles, "ok", stored, crops, structures, {},
                         ops=OPS)


def parts_of(record):
    return {p["key"]: p for st in record["steps"] for p in st["reactants"] + st["products"]}


def conds(record):
    return {c["key"]: c for st in record["steps"] for c in st["conditions"]} | {c["key"]: c for c in record["conditions"]}


# ------------------------------------------------------------------ tests

class Reading(unittest.TestCase):
    def test_valid_block(self):
        errors, warnings = validate_table(block_answer(), ENTRIES_SCHEMA, SIZES, 5, DOC_PAGES)
        self.assertEqual((errors, warnings), ([], []))

    def test_prepare_and_the_template_of_one_equation(self):
        inv = read_block()
        self.assertEqual(sorted(inv), ["columns", "entries", "ignored", "notes", "template"])
        self.assertEqual(len(inv["entries"]), 5)
        flat = inv["template"]
        self.assertEqual([p["key"] for p in flat["participants"]][:3], ["8", "9", "reagent-a"])
        self.assertEqual({p["key"]: p["role"] for p in flat["participants"]}["int"], "intermediate")
        # The compound keeps one box; a box the driver trims is the box of every equation that uses it.
        flat["participants"][0]["bbox"] = [262, 202, 338, 258]
        t = compose(inv, inv["entries"][1])
        eight = next(p for p in t["participants"] if p["key"] == "8")
        self.assertEqual((eight["bbox"], eight["label"], eight["role"]), ([262, 202, 338, 258], "8", "reactant"))
        self.assertEqual([f["marker"] for f in t["footnotes"]], ["a"])  # only the footnotes it prints
        self.assertEqual(t["structures"][0]["key"], "L*")
        self.assertEqual([c["per_entry"] for c in t["conditions"]], [False, False])
        self.assertEqual(compose(inv, inv["entries"][2])["condition_pointer"]["printed"], "standard conditions")

    def test_compounds_are_listed_once_and_used(self):
        data = block_answer()
        data["compounds"].append(compound("9", "9", bbox=[60, 60, 140, 120]))
        data["compounds"].append(compound("16", "16", bbox=[300, 400, 340, 440]))
        data["equations"][0]["participants"].append(part("17", "byproduct"))
        errors, _ = validate_table(data, ENTRIES_SCHEMA, SIZES, 5, DOC_PAGES)
        self.assertTrue(any(e.startswith("compounds: key '9' is used more than once") for e in errors), errors)
        self.assertTrue(any(e.startswith("compound '16' takes part in no equation") for e in errors), errors)
        self.assertTrue(any(e.startswith("equations[0] participant '17' is not one of the compounds") for e in errors),
                        errors)

    def test_equation_templates_are_checked_one_by_one(self):
        data = block_answer()
        data["equations"][0]["conditions"].append({**data["equations"][0]["conditions"][0], "key": "9"})
        data["equations"][1]["steps"] = [step(1, ["8", "reagent-a"], ["10"])]  # the intermediate in no step
        data["equations"][2]["condition_pointer"]["stated_at"] = None
        data["footnotes"].append(footnote("c", "With 3 equiv.", [ov("tempo", "replace", amount="3 equiv")]))
        data["compounds"].append(compound("loose"))
        data["equations"][4]["participants"].append(part("loose", "byproduct"))
        data["equations"][4]["steps"][0]["products"].append("loose")
        errors, _ = validate_table(data, ENTRIES_SCHEMA, SIZES, 5, DOC_PAGES)
        expect = ["equations[0]: key '9' is used more than once",
                  "equations[1] participant 'int' does not appear in any step",
                  "equations[2]: condition_pointer has found true: say where",
                  "footnote 'c' has overrides, but no equation prints its marker",
                  "compound 'loose': a compound that is not drawn needs the number or the name"]
        for e in expect:
            self.assertTrue(any(x.startswith(e) for x in errors), (e, errors))

    def test_a_protocol_does_not_take_all_products_of_a_step_away(self):
        data = block_answer()
        data["equations"][2]["variants"][1]["overrides"].append(ov("11", "remove"))
        data["equations"][1]["variants"] = [variant("x", "X", [ov("10", "remove")])]  # the last step of a sequence
        data["equations"][1]["variants"].append(variant("iso", "from the isolated boronate",
                                                        [ov("8", "remove"), ov("reagent-a", "remove")]))  # fine
        errors, _ = validate_table(data, ENTRIES_SCHEMA, SIZES, 5, DOC_PAGES)
        self.assertEqual(sorted(e.split(":")[0] for e in errors if "removes every product" in e),
                         ["equations[1] variant 'x'", "equations[2] variant 'bht'"], errors)

    def test_an_undrawn_intermediate_needs_no_name(self):
        data = block_answer()
        data["compounds"][3]["text"] = None  # 'int' takes part only as an intermediate
        self.assertEqual(validate_table(data, ENTRIES_SCHEMA, SIZES, 5, DOC_PAGES)[0], [])

    def test_alternatives_need_a_default(self):
        data = block_answer()
        data["compounds"].append(compound("8b", "8b", bbox=[260, 270, 340, 290]))
        eq = data["equations"][0]
        eq["participants"].append(part("8b", "reactant"))
        eq["steps"][0]["reactants"].append("8b")
        eq["alternative_groups"] = [{"keys": ["8", "8b"], "default": None, "basis": "", "stated_at": None,
                                     "inferred": False}]
        errors, _ = validate_table(data, ENTRIES_SCHEMA, SIZES, 5, DOC_PAGES)
        self.assertTrue(any(e.startswith("equations[0]: the alternatives ['8', '8b'] have no default") for e in errors),
                        errors)


class Handles(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate_handles(block_handles(), read_block(), HANDLES_SCHEMA), ([], []))

    def test_every_result_once_and_every_equation_read(self):
        inv = read_block()
        handles = block_handles()
        handles["reactions"][3]["results"] = [2, 3]  # the adduct's yield given to both protocols
        del handles["reactions"][1]  # equation 2 has no reaction
        handles["reactions"].append(handle(4, [1], distinguishing="X = O", variables=[var("X", "O", "13", "14")]))
        handles["reactions"].append(handle(1, [4]))
        errors, _ = validate_handles(handles, inv, HANDLES_SCHEMA)
        expect = ["equation 3: result 3 ('adduct, 17%') is given to reactions",
                  "equation 2 (1) LiCH2Cl 2) NaBO3; 10, 62%) has no reaction",
                  "reactions[7] (equation 4) and reactions[4] run the same equation",
                  "reactions[8] (equation 1): the equation has no result 4"]
        for e in expect:
            self.assertTrue(any(x.startswith(e) for x in errors), (e, errors))

    def test_what_a_handle_refers_to_belongs_to_its_equation(self):
        inv = read_block()
        handles = block_handles()
        handles["reactions"][0]["footnote_markers"] = ["a"]
        handles["reactions"][2]["variant"] = "air"
        handles["reactions"][4]["variables"][0]["participant_keys"] = ["13", "9"]
        errors, _ = validate_handles(handles, inv, HANDLES_SCHEMA)
        expect = ["reactions[1] (equation 1): footnote marker 'a' is not printed in this equation",
                  "reactions[3] (equation 3): unknown variant 'air'",
                  "reactions[5] (equation 4): variable X: '9' is not a participant of the equation"]
        for e in expect:
            self.assertTrue(any(x.startswith(e) for x in errors), (e, errors))

    def test_a_variant_that_leaves_no_step(self):
        data = block_answer()
        data["equations"][2]["variants"][1]["overrides"].append(ov("11", "remove"))  # the only main product
        inv = prepare(data)
        for i, en in enumerate(inv["entries"], 1):
            en["eid"] = f"e{i:03d}"
        errors, _ = validate_handles(block_handles(), inv, HANDLES_SCHEMA)
        self.assertTrue(any(e.startswith("reactions[4] (equation 3): under its variant and footnotes no step") for e in errors),
                        errors)

    def test_numbering(self):
        inv = read_block()
        reactions = number_reactions(inv, block_handles())
        self.assertEqual([r["rid"] for r in reactions],
                         ["e001-1", "e002-1", "e003-1", "e003-2", "e004-1", "e004-2", "e005-1"])
        self.assertEqual(reactions[2]["results_text"], ["11, ND (TEMPO)", "adduct, 17%"])


class Reaction(unittest.TestCase):
    def setUp(self):
        self.inv = read_block()
        self.reactions = {r["rid"]: r for r in number_reactions(self.inv, block_handles())}

    def check(self, rid, ans):
        return validate_reaction(ans, REACTION_SCHEMA, self.inv, self.reactions[rid], DOC_PAGES)

    def test_valid(self):
        for rid, ans in block_answers().items():
            self.assertEqual(self.check(rid, ans), ([], []), rid)

    def test_outcomes_come_from_its_results_and_sit_on_its_compounds(self):
        errors, _ = self.check("e003-2", answer([out(1, 10, "10%", "11")]))  # result 1 is the TEMPO run's
        self.assertTrue(any(e.startswith("outcomes[0]: result 1 is not one of this reaction's results") for e in errors))
        errors, _ = self.check("e003-2", answer([out(2, 17, "17%", "adduct")]))  # removed under BHT
        self.assertTrue(any("product_key 'adduct' is not a participant of this reaction" in e for e in errors), errors)
        errors, _ = self.check("e005-1", answer([out(1, 30, "30%", "15"), out(2, 55, "55%", "8")]))
        self.assertTrue(any(e.startswith("outcomes[1]: '8' is a starting material") for e in errors), errors)
        # A result printed for an intermediate stays on it; stage 1 should have split the steps.
        errors, warnings = self.check("e002-1", answer([out(1, 62, "62%", "int")]))
        self.assertEqual(errors, [])
        self.assertTrue(any(w.startswith("outcomes[0]: 'int' is an intermediate") for w in warnings), warnings)
        flagged = answer([out(1, 62, "62%", "int")], template_check=[
            {"target": "steps", "stage1": "one equation", "seen": "the intermediate has its own yield", "evidence": "p2"}])
        self.assertEqual(self.check("e002-1", flagged), ([], []))

    def test_a_reaction_without_results(self):
        handles = block_handles()
        inv = copy.deepcopy(self.inv)
        inv["entries"][0]["results"] = []
        handles["reactions"][0]["results"] = []
        reaction = number_reactions(inv, handles)[0]
        errors, _ = validate_reaction(answer([out(1, 74, "74%", "9")]), REACTION_SCHEMA, inv, reaction, DOC_PAGES)
        self.assertTrue(any("prints no result for this reaction" in e for e in errors), errors)
        self.assertEqual(validate_reaction(answer([]), REACTION_SCHEMA, inv, reaction, DOC_PAGES), ([], []))

    def test_lookup_and_labels_say_where(self):
        errors, warnings = self.check("e001-1", answer([], lookup=[ov("time", "add", "16 h", role="time")],
                                                       labels=[{"key": "9", "label": "9", "stated_at": None}]))
        self.assertTrue(any(e.startswith("lookup: override add 'time' has neither stated_at nor inferred") for e in errors))
        self.assertTrue(any(e.startswith("labels[0]: say where") for e in errors))
        self.assertIn("no outcome read from result 1 ('9, 74% b')", warnings)


class Records(unittest.TestCase):
    def setUp(self):
        self.inv = read_block()
        self.view, records, self.counts = assemble(self.inv, block_handles(), block_answers())
        self.records = {r["reaction_id"]: r for r in records}

    def rec(self, rid):
        return self.records[f"main:scheme5/A/{rid}"]

    def test_labels(self):
        self.assertEqual([r["label"] for r in self.records.values()], ["9", "10", "11", "11", "14", "14", "15"])
        self.assertEqual(entry_label(self.inv, {**self.inv["entries"][4], "participants": []}), "(2)")

    def test_the_shared_compound_keeps_its_drawing(self):
        for rid in ("e001-1", "e002-1", "e004-1", "e005-1"):
            eight = parts_of(self.rec(rid))["8"]
            self.assertEqual((eight["source"], eight["bbox"], eight["crop"]),
                             ("drawn", [260, 200, 340, 260], "c/_template__8.png"), rid)
        self.assertEqual(parts_of(self.rec("e001-1"))["8"]["amount"], "0.15 mmol (43 mg)")
        self.assertEqual(parts_of(self.rec("e003-1"))["tempo"]["source"], "text")

    def test_footnote_and_lookup_layers(self):
        c = conds(self.rec("e001-1"))
        self.assertEqual((c["temp"]["text"], c["temp"]["origin"]), ("0 °C", "footnote:b"))
        self.assertEqual((c["time"]["text"], c["time"]["origin"], c["time"]["stated_at"]), ("16 h", "lookup", SI))

    def test_sequence_with_an_intermediate(self):
        r = self.rec("e002-1")
        self.assertEqual([(len(st["reactants"]), len(st["products"])) for st in r["steps"]], [(2, 1), (1, 1)])
        self.assertEqual(r["steps"][0]["products"][0]["role"], "intermediate")
        self.assertEqual([c["key"] for c in r["steps"][1]["conditions"]], ["ox"])

    def test_two_protocols_of_one_equation(self):
        tempo, bht = self.rec("e003-1"), self.rec("e003-2")
        self.assertEqual(sorted(parts_of(tempo)), ["11", "8", "adduct", "tempo"])
        self.assertEqual(sorted(parts_of(bht)), ["11", "8"])
        self.assertEqual((conds(bht)["bht"]["text"], conds(bht)["bht"]["amount"]), ("BHT", "2.0 equiv"))
        self.assertEqual(conds(tempo)["cat"]["stated_at"], STANDARD)
        self.assertEqual(parts_of(tempo)["adduct"]["label"], "11-T")  # the number the SI gives it
        self.assertEqual([o["yield"]["qualifier"] for o in parts_of(tempo)["11"]["outcomes"]], ["ND"])
        self.assertEqual([o["yield"]["value"] for o in parts_of(tempo)["adduct"]["outcomes"]], [17])
        self.assertEqual((tempo["variant"]["title"], bht["variant"]["title"]), ("TEMPO", "BHT"))

    def test_variable_values_on_the_drawings_that_carry_them(self):
        for rid, value in (("e004-1", "O"), ("e004-2", "NTs")):
            parts = parts_of(self.rec(rid))
            for key in ("13", "14"):
                self.assertEqual([(v["name"], v["value"]) for v in parts[key]["variables"]], [("X", value)], rid)
            self.assertEqual(parts["8"]["variables"], [])
        self.assertEqual(parts_of(self.rec("e004-1"))["13"]["text"], "2-iodophenol")
        self.assertEqual([o["yield"]["value"] for o in parts_of(self.rec("e004-1"))["14"]["outcomes"]], [89])

    def test_sources_of_a_name_and_of_an_amount_stay_apart(self):
        data = block_answer()
        drawn = copy.deepcopy(data)
        drawn["compounds"][6]["stated_at"] = {"doc": "main", "page": 3}
        self.assertTrue(any(e.startswith("compound '11': the block draws it, so it has no stated_at")
                            for e in validate_table(drawn, ENTRIES_SCHEMA, SIZES, 5, DOC_PAGES)[0]))
        # 11 printed only as a number here, drawn in another figure; the trap's amount stated in the SI.
        data["compounds"][6] = compound("11", "11", stated_at={"doc": "main", "page": 3})
        data["ignored"].append({"page": 2, "bbox": [60, 300, 140, 360], "reason": "test"})
        data["equations"][2]["participants"][1]["stated_at"] = {"doc": "si", "page": 30}
        self.assertEqual(validate_table(data, ENTRIES_SCHEMA, SIZES, 5, DOC_PAGES)[0], [])
        inv = prepare(data)
        for i, en in enumerate(inv["entries"], 1):
            en["eid"] = f"e{i:03d}"
        t = compose(inv, inv["entries"][2])
        parts = {p["key"]: p for p in t["participants"]}
        self.assertEqual((parts["11"]["stated_at"], parts["11"]["amount_stated_at"]), ({"doc": "main", "page": 3}, None))
        self.assertEqual((parts["tempo"]["stated_at"], parts["tempo"]["amount_stated_at"]), (None, {"doc": "si", "page": 30}))
        _, records, _ = assemble(inv, block_handles(), block_answers())
        rec = next(r for r in records if r["reaction_id"].endswith("e003-1"))
        self.assertEqual(parts_of(rec)["11"]["stated_at"], {"doc": "main", "page": 3})
        self.assertEqual(parts_of(rec)["tempo"]["amount_stated_at"], {"doc": "si", "page": 30})
        self.assertIsNone(parts_of(rec)["tempo"]["stated_at"])

    def test_a_result_on_an_intermediate_stays_on_it(self):
        answers = block_answers()
        answers["e002-1"] = answer([out(1, 62, "62%", "int")])
        _, records, _ = assemble(self.inv, block_handles(), answers)
        rec = next(r for r in records if r["reaction_id"].endswith("e002-1"))
        formed = {p["key"]: p for p in rec["steps"][0]["products"]}  # the intermediate, where step 1 forms it
        self.assertEqual([o["yield"]["value"] for o in formed["int"]["outcomes"]], [62])
        self.assertEqual(parts_of(rec)["10"]["outcomes"], [])

    def test_a_protocol_with_its_own_product(self):
        """The other option ends up in the product: it replaces the first option, and the product it gives
        replaces the drawn one, which then loses its number."""
        data = block_answer()
        data["equations"][2]["variants"][1] = variant("bht", "BHT", [
            ov("tempo", "replace", "BHT"), ov("adduct", "remove"),
            ov("11", "replace", "the product with BHT, not drawn", inferred=True, basis="not drawn")])
        self.assertEqual(validate_table(data, ENTRIES_SCHEMA, SIZES, 5, DOC_PAGES)[0], [])
        inv = prepare(data)
        for i, en in enumerate(inv["entries"], 1):
            en["eid"] = f"e{i:03d}"
        answers = block_answers()
        answers["e003-2"] = answer([out(2, 10, "10%", "11")], labels=[{"key": "11", "label": "11′", "stated_at": SI}])
        _, records, _ = assemble(inv, block_handles(), answers)
        rec = next(r for r in records if r["reaction_id"].endswith("e003-2"))
        parts = parts_of(rec)
        self.assertEqual((parts["tempo"]["text"], parts["tempo"]["role"]), ("BHT", "reactant"))
        self.assertEqual((parts["11"]["label"], parts["11"]["text"], parts["11"]["source"]),
                         ("11′", "the product with BHT, not drawn", "text"))
        self.assertEqual(rec["label"], "equation 3")  # not the number of the drawn product it replaced
        self.assertEqual(next(r for r in records if r["reaction_id"].endswith("e003-1"))["label"], "11")

    def test_an_unresolved_reference_is_an_issue(self):
        data = block_answer()
        data["equations"][2]["condition_pointer"] = {"printed": "as reported before", "refers_to": "outside the paper",
                                                     "found": False, "stated_at": None}
        self.assertEqual(validate_table(data, ENTRIES_SCHEMA, SIZES, 5, DOC_PAGES)[0], [])
        inv = prepare(data)
        for i, en in enumerate(inv["entries"], 1):
            en["eid"] = f"e{i:03d}"
        _, records, _ = assemble(inv, block_handles(), block_answers())
        rec = next(r for r in records if r["reaction_id"].endswith("e003-1"))
        self.assertTrue(any(i.startswith("the conditions are given by a reference the paper does not resolve: "
                                         "'as reported before'") for i in rec["issues"]), rec["issues"])

    def test_a_number_from_the_si_does_not_take_over_the_source_of_a_name(self):
        answers = block_answers()
        named_at = {"doc": "si", "page": 22}
        answers["e003-1"]["lookup"] = [ov("adduct", "replace", "the adduct's name", stated_at=named_at)]
        _, records, _ = assemble(self.inv, block_handles(), answers)
        adduct = parts_of(next(r for r in records if r["reaction_id"].endswith("e003-1")))["adduct"]
        self.assertEqual((adduct["label"], adduct["text"], adduct["stated_at"]), ("11-T", "the adduct's name", named_at))

    def test_recovered_starting_material(self):
        r = self.rec("e005-1")
        self.assertEqual([o["yield"]["value"] for o in parts_of(r)["15"]["outcomes"]], [30])
        self.assertEqual([(o["participant_key"], o["yield"]["value"]) for o in r["other_outcomes"]], [("8", 55)])
        self.assertEqual(parts_of(r)["8"]["role"], "reactant")
        self.assertEqual(conds(r)["ligand"]["structure"]["key"], "L*")

    def test_view(self):
        self.assertEqual(self.counts["reactions_ok"], 7)
        self.assertEqual([eq["eid"] for eq in self.view["equations"]], ["e001", "e002", "e003", "e004", "e005"])
        data = block_view(self.view)
        self.assertEqual(data["equations"][2]["template"]["participants"][0]["crop"], "c/_template__8.png")
        self.assertEqual([p["key"] for p in data["template"]["participants"]][:2], ["8", "9"])
        self.assertTrue(all(r["record"] for e in data["entries"] for r in e["reactions"]))

    def test_drafts_use_their_equation(self):
        inv = read_block()
        view, records, counts = assemble(inv, block_handles(), {})
        self.assertEqual((records, counts["reactions_pending"]), ([], 7))
        data = block_view(view)
        bht = data["entries"][2]["reactions"][1]
        self.assertEqual(bht["draft"]["variant"]["title"], "BHT")
        self.assertEqual([p["key"] for p in bht["draft"]["steps"][0]["reactants"]], ["8"])

    def test_questioned_reading_names_the_equation(self):
        answers = block_answers()
        answers["e004-2"]["template_check"] = [{"target": "13", "stage1": "Ar–XH", "seen": "Ar–I", "evidence": "p2"}]
        view, records, _ = assemble(self.inv, block_handles(), answers)
        self.assertTrue(any(w.startswith("the table reading is questioned for 'e004: 13'") for w in view["meta"]["warnings"]))
        rec = next(r for r in records if r["source"]["reaction_id"].endswith("e004-2"))
        self.assertTrue(any(i.startswith("reading questioned for 13") for i in rec["issues"]))


class Driver(unittest.TestCase):
    def test_read_table_prepares_the_answer(self):
        with tempfile.TemporaryDirectory() as tmp, no_pdf():
            job = StubJob(Path(tmp), block_answer(), shared=[{"key": "8"}])
            inv = s2_table.read_table(s2_equation.SPEC, job, REGION, BLOCK)
        meta = inv["_meta"]
        self.assertEqual((meta["status"], meta["errors"]), ("ok", []))
        self.assertEqual([en["eid"] for en in inv["entries"]], ["e001", "e002", "e003", "e004", "e005"])
        self.assertEqual(inv["columns"], [])
        self.assertIn("every equation with its own participants", job.prompts[0])

    def test_geometry_messages_speak_of_the_answer(self):
        msgs = ["template participant '8': bbox [1, 2, 3, 4] on page 2 contains no ink",
                "entries[1] (None): bbox [1, 2, 3, 4] on page 2 contains no ink",
                "uncovered area on page 2: [1, 2, 3, 4] is inside the block but in no entry, scheme, participant, "
                "structure or ignored box; add what is printed there (entries, drawn catalysts/ligands) or list the "
                "area under ignored with a reason",
                "box edge: template structure 'L*': ink runs to the left edge of [1, 2, 3, 4]"]
        self.assertEqual(s2_table._renamed(s2_equation.SPEC, msgs), [
            "compound '8': bbox [1, 2, 3, 4] on page 2 contains no ink",
            "equations[1]: bbox [1, 2, 3, 4] on page 2 contains no ink",
            "uncovered area on page 2: [1, 2, 3, 4] is inside the block but in no equation, compound, structure or "
            "ignored box; add what is printed there (an equation, a compound, a drawn catalyst or ligand) or list the "
            "area under ignored with a reason",
            "box edge: structure 'L*': ink runs to the left edge of [1, 2, 3, 4]"])
        self.assertEqual(s2_table._renamed(s2_ctable.SPEC, msgs), msgs)  # the tables keep the messages as they are

    def test_tasks(self):
        inv = read_block()
        reactions = number_reactions(inv, block_handles())
        with tempfile.TemporaryDirectory() as tmp, no_pdf():
            job = StubJob(Path(tmp))
            task, _ = s2_table.entries_task(s2_equation.SPEC, job, REGION, BLOCK)
            self.assertIsNone(task["shared_participants"])  # equation blocks share no scheme
            handles = {"reactions": reactions, "notes": [], "issues": []}
            task, _ = s2_table.reaction_task(s2_equation.SPEC, job, REGION, BLOCK, inv, handles, reactions[3])
        self.assertEqual(task["template"], template_of(inv, reactions[3]))
        self.assertEqual(task["reaction"]["variant_title"], "BHT")
        self.assertEqual(task["entry"]["results"], ["11, ND (TEMPO)", "11, 10% (BHT)", "adduct, 17%"])
        self.assertEqual(task["protocol"]["removed_participants"], ["tempo", "adduct"])
        self.assertEqual([r["rid"] for r in task["other_reactions_of_entry"]], ["e003-1"])
        task5, _ = s2_table.reaction_task(s2_equation.SPEC, job, REGION, BLOCK, inv, handles, reactions[4])
        self.assertEqual(task5["reaction"]["variables"], [var("X", "O", "13", "14")])


if __name__ == "__main__":
    unittest.main()
