"""The prose path of Step 2 (pipeline/extract_prose.py on pipeline/extract_equation.py): validators,
the template of one experiment, assembly into records and views, and the driver's use of them.

The fixture is a made-up passage written out by hand as the two skills would answer. It has the
cases a passage is read for: an experiment given by a reference to the standard conditions whose
runs differ in the solvent and an added reagent (three variants, one result stated only in words), a
failure stated for a class of substrates under "otherwise identical conditions", a value measured on
a starting material recovered at the end, compounds drawn on another page (one of them taken from the
reaction the passage refers to), and a statement set aside as the result of other work. The passage
is on page 2; the scheme it refers to on page 1."""

import dataclasses
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pipeline.extract_ctable import assemble_view
from pipeline.extract_prose import (LAYOUT, OPS, number_reactions, prepare, template_of, validate_handles,
                                    validate_reaction, validate_table)
from pipeline.extract_view import block_view
from pipeline.steps import s2_prose, s2_table
from pipeline.table_words import passage_text
from tests.test_extract_pscope import StubJob, no_pdf
from tests.test_extract_records import cond, ov, step, variant

ENTRIES_SCHEMA = s2_prose.SPEC.schema("entries")
HANDLES_SCHEMA = s2_prose.SPEC.schema("handles")
REACTION_SCHEMA = s2_prose.SPEC.schema("reaction")
SIZES = {1: (600.0, 800.0), 2: (600.0, 800.0)}
DOC_PAGES = {"main": 4, "si": 40}
REGION = {"region_id": "main:controls", "doc": "main", "label": None, "first_page": 2, "caption": None,
          "boxes": [{"page": 2, "bbox": [40, 300, 290, 420]}, {"page": 2, "bbox": [310, 40, 560, 80]}],
          "blocks": [{"block_id": "1", "page": 2, "bbox": [40, 300, 290, 420], "title": "Controls", "layout": LAYOUT}]}
BLOCK = {"block_id": "1", "kind": "mechanistic", "layout": LAYOUT, "page": 2, "title": "Controls",
         "bbox": [40, 300, 290, 420], "n_entries_est": 3, "entries_first_page": None}
SCHEME = {"doc": "main", "page": 1}
SI = {"doc": "si", "page": 21}


# ------------------------------------------------------------------ builders

def compound(key, label=None, text=None, bbox=None, generic=False, stated_at=None, page=1):
    return {"key": key, "label": label, "text": text, "generic": generic, "page": page if bbox else None,
            "bbox": bbox, "stated_at": stated_at}


def part(key, role, amount=None):
    return {"key": key, "role": role, "amount": amount, "isolated": None, "alternatives": [], "stated_at": None}


def experiment(bbox, statement, results, participants, steps, conditions=(), variants=(), markers=(), based_on=None,
               descriptor="an experiment", page=2):
    return {"label": None, "page": page, "bbox": bbox, "statement": statement, "descriptor": descriptor,
            "general_reaction": "a coupling", "results": list(results), "footnote_markers": list(markers),
            "participants": list(participants), "steps": list(steps),
            "conditions": [{k: v for k, v in c.items() if k != "per_entry"} for c in conditions],
            "based_on": based_on, "alternative_groups": [], "preparations": [], "variable_defaults": [],
            "default_yield_type": None, "variants": list(variants)}


STANDARD = {"printed": "under the standard conditions", "refers_to": "the optimized conditions of Scheme 1",
            "found": True, "stated_at": SCHEME}


def passage_answer():
    compounds = [
        compound("12", "12", bbox=[60, 100, 140, 160]),
        compound("13", "13", text="the arylzinc reagent", bbox=[160, 100, 240, 160], stated_at=SCHEME),
        compound("14", "14", bbox=[300, 100, 380, 160]),
        compound("alkyl-class", text="tertiary alkyl bromides", generic=True),
        compound("coupling-product", text="the cross-coupling product"),
        compound("chloride", text="the corresponding chloride"),
    ]
    std = [cond("cat", "catalyst", "FeCl3", "5 mol%", stated_at=SCHEME),
           cond("solvent", "solvent", "THF", stated_at=SCHEME), cond("temp", "temperature", "25 °C", stated_at=SCHEME)]
    exps = [
        experiment([40, 300, 290, 350], "Under the standard conditions 12 and 13 gave 14 in 70% and 64% yield in THF "
                   "and dioxane, respectively, while added TEMPO suppressed the coupling.",
                   ["70% of 14 in THF", "64% of 14 in dioxane", "TEMPO suppressed the coupling"],
                   [part("12", "reactant"), part("13", "reactant"), part("14", "product")], [step(1, ["12", "13"], ["14"])],
                   std, variants=[variant("thf", "in THF"),
                                  variant("dioxane", "in dioxane", [ov("solvent", "replace", "dioxane")]),
                                  variant("tempo", "with TEMPO", [ov("tempo", "add", "TEMPO", "1.0 equiv", "additive")])],
                   based_on=STANDARD, descriptor="12 + 13 → 14; standard conditions; THF / dioxane / TEMPO"),
        experiment([40, 350, 290, 380], "Under otherwise identical conditions tertiary alkyl bromides gave no product.",
                   ["no product"], [part("alkyl-class", "reactant"), part("13", "reactant"),
                                    part("coupling-product", "product")],
                   [step(1, ["alkyl-class", "13"], ["coupling-product"])], std,
                   based_on={**STANDARD, "printed": "under otherwise identical conditions"},
                   descriptor="tertiary alkyl bromides + 13; no product"),
        experiment([310, 40, 560, 80], "Heating 12 with FeCl3 in toluene gave the corresponding chloride; the ee of the "
                   "recovered 12 was unchanged.", ["the corresponding chloride was formed", "the ee of the recovered 12 "
                                                   "was unchanged"],
                   [part("12", "reactant"), part("chloride", "product")], [step(1, ["12"], ["chloride"])],
                   [cond("cat", "reagent", "FeCl3"), cond("solvent", "solvent", "toluene")],
                   descriptor="12 + FeCl3 → chloride; recovered 12"),
    ]
    return {"reading_guide": "Three experiments; the first has three runs.", "compounds": compounds, "structures": [],
            "footnotes": [], "context": [{"doc": "main", "page": 1, "text": "…standard conditions…", "about": "reference"}],
            "experiments": exps,
            "set_aside": [{"text": "Similar couplings have been reported with cobalt.", "reason": "result of other work"}],
            "notes": ""}


def handle(n, results, variant=None, distinguishing=None):
    return {"entry": n, "results": list(results), "variant": variant, "footnote_markers": [],
            "distinguishing": distinguishing, "variables": []}


def passage_handles():
    return {"reactions": [handle(1, [1], "thf", "in THF"), handle(1, [2], "dioxane", "in dioxane"),
                          handle(1, [3], "tempo", "with TEMPO"), handle(2, [1]), handle(3, [1, 2])],
            "notes": [], "issues": []}


def out(result, value, text, product_key=None, qualifier=None, notes=None, stated_at=None, selectivity=()):
    return {"product_key": product_key, "yield_text": text, "yield_value": value, "yield_qualifier": qualifier,
            "yield_type": None, "selectivity": list(selectivity), "footnote_markers": [], "notes": notes,
            "result": result, "stated_at": stated_at}


def answer(outcomes, lookup=(), labels=(), template_check=(), notes=""):
    return {"template_check": list(template_check), "outcomes": list(outcomes), "lookup": list(lookup),
            "labels": list(labels), "related": [], "notes": notes, "issues": []}


def passage_answers():
    return {
        "e001-1": answer([out(1, 70, "70%", "14")], lookup=[ov("12", "replace", amount="0.50 mmol", stated_at=SI)]),
        "e001-2": answer([out(2, 64, "64%", "14")]),
        # Stated only in words; the SI table gives the run's value.
        "e001-3": answer([out(3, 4, "4%", "14", notes="the passage: TEMPO suppressed the coupling", stated_at=SI)]),
        "e002-1": answer([out(1, None, "no product", "coupling-product", qualifier="NR")]),
        "e003-1": answer([out(1, None, None, "chloride", qualifier="other", notes="formed, not quantified"),
                          out(2, None, None, "12", qualifier="other", notes="recovered starting material",
                              selectivity=[{"type": "ee", "text": "unchanged"}])]),
    }


def read_passage(data=None):
    data = data or passage_answer()
    errors, _ = validate_table(data, ENTRIES_SCHEMA, SIZES, BLOCK["n_entries_est"], DOC_PAGES)
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
    return assemble_view(REGION, BLOCK, "main-controls__1", inv, "ok", handles, "ok", stored, crops, {}, {}, ops=OPS)


def parts_of(record):
    return {p["key"]: p for st in record["steps"] for p in st["reactants"] + st["products"]}


# ------------------------------------------------------------------ tests

class Reading(unittest.TestCase):
    def test_valid_passage(self):
        self.assertEqual(validate_table(passage_answer(), ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES), ([], []))

    def test_prepare_and_the_template_of_one_experiment(self):
        inv = read_passage()
        self.assertEqual(sorted(inv), ["columns", "entries", "ignored", "notes", "set_aside", "template"])
        self.assertEqual(inv["ignored"], [])
        self.assertEqual(inv["entries"][0]["condition_pointer"]["printed"], "under the standard conditions")
        t = template_of(inv, {"entry": 1})
        self.assertNotIn("condition_pointer", t)  # under the name stage 1 gave it
        self.assertEqual(t["based_on"]["refers_to"], "the optimized conditions of Scheme 1")
        # A compound drawn elsewhere keeps its box, and one taken from the reaction referred to its source.
        parts = {p["key"]: p for p in t["participants"]}
        self.assertEqual((parts["13"]["page"], parts["13"]["stated_at"]), (1, SCHEME))

    def test_a_compound_drawn_elsewhere_may_say_where_it_is_named(self):
        # Under the equation form a drawn compound has no stated_at; a passage's compound may have both.
        data = passage_answer()
        self.assertEqual(data["compounds"][1]["stated_at"], SCHEME)
        self.assertEqual(validate_table(data, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)[0], [])

    def test_messages_speak_of_experiments(self):
        data = passage_answer()
        data["compounds"].append(compound("16", "16", bbox=[300, 400, 340, 440]))
        data["experiments"][0]["participants"].append(part("17", "byproduct"))
        data["experiments"][1]["based_on"] = {**STANDARD, "stated_at": None}
        data["experiments"][2]["statement"] = " "
        data["set_aside"].append({"text": "", "reason": "x"})
        errors, _ = validate_table(data, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)
        expect = ["compound '16' takes part in no experiment",
                  "experiments[0] participant '17' is not one of the compounds",
                  "experiments[1]: based_on has found true: say where",
                  "experiments[2]: quote the sentences that report the experiment",
                  "set_aside[1]: quote the statement"]
        for e in expect:
            self.assertTrue(any(x.startswith(e) for x in errors), (e, errors))
        self.assertFalse(any("equation" in x for x in errors), errors)

    def test_a_passage_without_experiments(self):
        data = {**passage_answer(), "compounds": [], "experiments": []}
        errors, warnings = validate_table(data, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)
        self.assertEqual(errors, [])  # it says under set_aside what it reports instead
        self.assertTrue(any(w.startswith("no experiments listed, but Step 1 estimated") for w in warnings), warnings)
        errors, _ = validate_table({**data, "set_aside": []}, ENTRIES_SCHEMA, SIZES, 3, DOC_PAGES)
        self.assertTrue(any(e.startswith("no experiments: list every experiment") for e in errors), errors)


class Reactions(unittest.TestCase):
    def setUp(self):
        self.inv = read_passage()

    def test_handles(self):
        self.assertEqual(validate_handles(passage_handles(), self.inv, HANDLES_SCHEMA), ([], []))
        # A run the passage states no result for, beside runs that have one: a warning, not an error.
        inv = read_passage()
        inv["entries"][0]["variants"].append(variant("scale", "on a 5 mmol scale"))
        h = passage_handles()
        h["reactions"].insert(3, handle(1, [], "scale", "on a 5 mmol scale"))
        errors, warnings = validate_handles(h, inv, HANDLES_SCHEMA)
        self.assertEqual(errors, [])
        self.assertIn("reactions[4] (experiment 1): no result: right only when the passage states none for this run",
                      warnings)
        h = passage_handles()
        h["reactions"][2]["results"] = [2]
        errors, _ = validate_handles(h, self.inv, HANDLES_SCHEMA)
        self.assertTrue(any(e.startswith("experiment 1: result 3 ('TEMPO suppressed the coupling') belongs to no "
                                         "reaction") for e in errors), errors)
        self.assertTrue(any(e.startswith("experiment 1: result 2 ('64% of 14 in dioxane') is given to reactions")
                            for e in errors), errors)

    def reaction(self, n):
        return number_reactions(self.inv, passage_handles())[n]

    def check(self, n, a):
        return validate_reaction(a, REACTION_SCHEMA, self.inv, self.reaction(n), DOC_PAGES)

    def test_valid_answers(self):
        for n, (rid, a) in enumerate(passage_answers().items()):
            self.assertEqual(self.reaction(n)["rid"], rid)
            self.assertEqual(self.check(n, a), ([], []), rid)

    def test_a_value_found_in_the_si_is_not_checked_against_the_passage(self):
        errors, warnings = self.check(2, passage_answers()["e001-3"])
        self.assertEqual((errors, warnings), ([], []))
        # Without its source, the same value is not part of the passage's wording.
        bare = answer([out(3, 4, "4%", "14")])
        errors, _ = self.check(2, bare)
        self.assertTrue(any(e.startswith("outcomes[0]: result 3 ('TEMPO suppressed the coupling') does not print '4%'")
                            for e in errors), errors)
        quiet = answer([out(3, 4, "4%", "14", stated_at=SI)])
        self.assertIn("outcomes[0]: say in notes what the passage states for this result", self.check(2, quiet)[1])

    def test_a_printed_value_is_the_outcome(self):
        a = answer([out(1, 72, "72%", "14", stated_at=SI)])
        warnings = self.check(0, a)[1]
        self.assertTrue(any(w.startswith("outcomes[0]: result 1 ('70% of 14 in THF') prints a value") for w in warnings),
                        warnings)

    def test_messages_keep_the_answer_numbering(self):
        a = answer([out(1, 70, "70%", "14", stated_at=SI, notes="as printed"), out(1, 170, "170%", "14")])
        errors, _ = self.check(0, a)
        self.assertTrue(any(e.startswith("outcomes[1]: yield_value 170 is outside 0..100") for e in errors), errors)
        self.assertFalse(any(e.startswith("outcomes[0]: yield_value") for e in errors), errors)

    def test_a_value_must_stand_in_its_result(self):
        # '4%' is not in '64% of 14 in dioxane', and a value without its printed text has no source either.
        for o in (out(2, 4, "4%", "14"), out(2, 64, None, "14")):
            errors, _ = self.check(1, answer([o]))
            self.assertTrue(any("does not print" in e for e in errors), (o, errors))
        self.assertEqual(self.check(1, answer([out(2, 64, "64 %", "14")]))[0], [])

    def test_outcome_checks(self):
        a = answer([out(4, 70, "70%", "14"), out(1, 70, "70%", "12"), out(1, 70, "70%", "14", stated_at={"doc": "si", "page": 99})])
        errors, _ = self.check(0, a)
        for e in ["outcomes[0]: result 4 is not one of this reaction's results",
                  "outcomes[1]: '12' is a starting material of this reaction",
                  "outcomes[2] stated_at: page 99 is not a page of 'si'"]:
            self.assertTrue(any(x.startswith(e) for x in errors), (e, errors))

    def test_no_outcome_without_a_stated_result(self):
        h = passage_handles()
        h["reactions"][3]["results"] = []
        self.inv["entries"][1]["results"] = []
        r = number_reactions(self.inv, h)[3]
        a = answer([out(1, 12, "12%", "coupling-product", stated_at=SI)])
        errors, _ = validate_reaction(a, REACTION_SCHEMA, self.inv, r, DOC_PAGES)
        self.assertTrue(any(e.startswith("outcomes[0]: the passage states no result for this reaction") for e in errors),
                        errors)


class Records(unittest.TestCase):
    def setUp(self):
        self.inv = read_passage()
        self.view, self.records, self.counts = assemble(self.inv, passage_handles(), passage_answers())

    def test_records(self):
        self.assertEqual(self.counts["reactions_ok"], 5)
        self.assertEqual([r["label"] for r in self.records], ["14", "14", "14", "experiment 2", "experiment 3"])
        thf, dioxane, tempo, failure, chloride = self.records
        solvent = lambda rec: next(c["text"] for st in rec["steps"] for c in st["conditions"] if c["key"] == "solvent")
        self.assertEqual((solvent(thf), solvent(dioxane)), ("THF", "dioxane"))
        # A value the passage states has no source of its own; one the SI gives keeps where it is stated.
        self.assertIsNone(parts_of(thf)["14"]["outcomes"][0]["stated_at"])
        self.assertEqual(parts_of(tempo)["14"]["outcomes"][0]["stated_at"], SI)
        self.assertEqual(parts_of(tempo)["14"]["outcomes"][0]["yield"]["value"], 4)
        # Compounds drawn on another page point at their drawing; a class has no box.
        self.assertEqual((parts_of(thf)["12"]["source"], parts_of(thf)["12"]["page"]), ("drawn", 1))
        self.assertEqual((parts_of(failure)["alkyl-class"]["source"], parts_of(failure)["alkyl-class"]["bbox"]),
                         ("text", None))
        # A value on the recovered starting material stays with it.
        self.assertEqual([o.get("participant_key") for o in chloride["other_outcomes"]], ["12"])
        self.assertFalse(any("gives no conditions" in i for r in self.records for i in r["issues"]))

    def test_a_run_without_any_condition_says_so(self):
        data = passage_answer()
        data["experiments"][2]["conditions"] = []
        inv = read_passage(data)
        _, records, _ = assemble(inv, passage_handles(), passage_answers())
        self.assertIn("the passage gives no conditions for this run, and none were found in the main text or the SI",
                      records[4]["issues"])

    def test_view(self):
        self.assertEqual([x["label"] for x in self.view["experiments"]], ["14", "experiment 2", "experiment 3"])
        self.assertIn("based_on", self.view["experiments"][0]["template"])
        self.assertEqual(self.view["set_aside"][0]["reason"], "result of other work")
        data = block_view(self.view)
        self.assertEqual(len(data["experiments"]), 3)
        self.assertEqual(data["experiments"][0]["template"]["participants"][0]["crop"], "c/_template__12.png")
        self.assertEqual(data["set_aside"], self.view["set_aside"])
        self.assertNotIn("equations", data)
        self.assertTrue(data["entries"][0]["expansion"]["printed"].startswith("Under the standard conditions"))


class Driver(unittest.TestCase):
    SPEC = dataclasses.replace(s2_prose.SPEC, stage1_task=lambda job, region, block: {
        "text_layer": None, "block_text": "Under the standard conditions …", "passages": [], "other_blocks": []},
        extra_images=None)

    def test_read_table_and_an_empty_passage(self):
        with tempfile.TemporaryDirectory() as tmp, no_pdf():
            job = StubJob(Path(tmp), passage_answer())
            inv = s2_table.read_table(self.SPEC, job, REGION, BLOCK)
            self.assertEqual((inv["_meta"]["status"], inv["_meta"]["errors"]), ("ok", []))
            self.assertFalse(job.coverage)  # the rest of the paragraph is text: no uncovered-ink check
            self.assertIn("block_text", job.prompts[0])
            self.assertIn("every experiment it reports", job.prompts[0])
            task, _ = s2_table.entries_task(self.SPEC, job, REGION, BLOCK)
            self.assertEqual((task["block_text"], task["text_layer"]), ("Under the standard conditions …", None))
            # A passage that reports no experiment: turn 2 has nothing to list and runs no session.
            empty = {**passage_answer(), "compounds": [], "experiments": []}
            job = StubJob(Path(tmp), empty)
            inv = s2_table.read_table(self.SPEC, job, REGION, BLOCK, fresh=True)
            handles = s2_table.list_reactions(self.SPEC, job, REGION, BLOCK, inv)
        self.assertEqual(len(job.prompts), 1)
        self.assertEqual((handles["_meta"]["status"], handles["reactions"]), ("ok", []))
        view, records, counts = assemble_view(REGION, BLOCK, "s", inv, "ok", handles, "ok", {}, {}, {}, {}, ops=OPS)
        self.assertEqual((records, view["experiments"], len(view["set_aside"])), ([], [], 1))
        data = block_view({**view, "template_crops": {}, "structure_crops": {}})
        self.assertEqual((data["experiments"], len(data["set_aside"])), ([], 1))  # the viewer knows it is a passage

    def test_stage2_task(self):
        inv = read_passage()
        reactions = number_reactions(inv, passage_handles())
        with tempfile.TemporaryDirectory() as tmp, no_pdf():
            job = StubJob(Path(tmp))
            handles = {"reactions": reactions, "notes": [], "issues": []}
            task, _ = s2_table.reaction_task(self.SPEC, job, REGION, BLOCK, inv, handles, reactions[1])
        self.assertEqual(task["template"], template_of(inv, reactions[1]))
        self.assertEqual(task["entry"]["based_on"]["printed"], "under the standard conditions")
        self.assertTrue(task["entry"]["statement"].startswith("Under the standard conditions"))
        self.assertEqual(task["reaction"]["variant_title"], "in dioxane")
        solvent = next(c for c in task["protocol"]["conditions"] if c["key"] == "solvent")
        self.assertEqual(solvent["text"], "dioxane")

    def test_stage1_task_of_the_spec(self):
        words = [{"text": t, "bbox": [x, y, x + 20, y + 8], "block": b, "line": ln}
                 for t, x, y, b, ln in [("Under", 50, 310, 0, 0), ("the", 75, 310, 0, 0), ("standard", 50, 322, 0, 1),
                                        ("runs", 320, 50, 1, 0), ("on", 345, 50, 1, 0)]]
        job = StubJob(Path("."))
        job.manifests = {"main": {"pages": [{"page": 2, "tag": "p002"}]}}
        job.ws = SimpleNamespace(doc_dir=lambda doc: Path("."))
        table = {"region_id": "main:table1", "doc": "main", "label": "Table 1", "include": True,
                 "blocks": [{"block_id": "1", "title": "Optimization", "page": 1, "layout": "condition_table",
                             "include": True}]}
        job.regions = {"regions": [{**REGION, "include": True, "blocks": [{**BLOCK, "include": True}]}, table]}
        with mock.patch.object(s2_prose, "load_words", lambda d, tag: words):
            task = s2_prose.stage1_task(job, REGION, BLOCK)
        self.assertEqual(task["block_text"], "Under the\nstandard")
        self.assertEqual([(p["this_block"], p["text"]) for p in task["passages"]],
                         [(True, "Under the\nstandard"), (False, "runs on")])
        self.assertEqual(task["other_blocks"], [])
        self.assertEqual(task["blocks_of_paper"], [{"ref": "main:table1/1", "doc": "main", "label": "Table 1",
                                                    "title": "Optimization", "page": 1, "layout": "condition_table"}])


class Text(unittest.TestCase):
    def test_passage_text_follows_the_layer(self):
        words = [{"text": "a", "bbox": [0, 0, 5, 5], "block": 0, "line": 0},
                 {"text": "b", "bbox": [6, 0, 10, 5], "block": 0, "line": 0},
                 {"text": "c", "bbox": [0, 7, 5, 12], "block": 0, "line": 1},
                 {"text": "out", "bbox": [100, 100, 110, 105], "block": 1, "line": 0}]
        self.assertEqual(passage_text(words, [0, 0, 20, 20]), "a b\nc")


if __name__ == "__main__":
    unittest.main()
