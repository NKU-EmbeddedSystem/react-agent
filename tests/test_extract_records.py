import json
import unittest

from pipeline.extract_records import (build_record, merge_items, resolve_protocol, select_blocks,
                                      validate_entry, validate_expansion, validate_inventory)
from pipeline.extract_view import block_head, block_view
from pipeline.steps.s2_extract import SCHEMAS

INV_SCHEMA = json.loads(SCHEMAS["inventory"].read_text())
ENTRY_SCHEMA = json.loads(SCHEMAS["entry"].read_text())
EXPAND_SCHEMA = json.loads(SCHEMAS["expand"].read_text())
SIZES = {1: (600.0, 800.0), 2: (600.0, 800.0)}


SI5 = {"doc": "si", "page": 5}
DOC_PAGES = {"main": 2, "si": 40}


def ov(key, action, text=None, amount=None, role=None, basis="test", structure_key=None, step=None,
       alternatives=(), inferred=False, stated_at=None):
    return {"key": key, "action": action, "role": role, "text": text, "amount": amount,
            "structure_key": structure_key, "step": step, "alternatives": list(alternatives), "basis": basis,
            "stated_at": stated_at, "inferred": inferred}


def cond(key, role, text, amount=None, structure_key=None, step=None, alternatives=(), per_entry=False,
         stated_at=None):
    return {"key": key, "role": role, "text": text, "amount": amount, "structure_key": structure_key,
            "step": step, "alternatives": list(alternatives), "stated_at": stated_at, "per_entry": per_entry}


def variant(key, title, overrides=(), notes="", conditions_given=True):
    return {"key": key, "title": title, "conditions_given": conditions_given, "overrides": list(overrides),
            "notes": notes}


def tpart(key, role, label=None, text=None, amount=None, generic=True, bbox=None, isolated=None,
          alternatives=(), stated_at=None):
    return {"key": key, "role": role, "label": label, "text": text, "amount": amount, "generic": generic,
            "isolated": isolated, "page": 1 if bbox else None, "bbox": bbox,
            "alternatives": list(alternatives), "stated_at": stated_at}


def epart(key, role, source, label=None, bbox=None, basis=None, variables=(), isolated=None, text=None,
          stated_at=None):
    return {"key": key, "role": role, "label": label, "text": text, "amount": None, "source": source,
            "isolated": isolated, "page": 1 if bbox else None, "bbox": bbox,
            "variables": list(variables), "basis": basis, "stated_at": stated_at}


def group(keys, default=None, basis="test", stated_at=None, inferred=False):
    return {"keys": list(keys), "default": default, "basis": basis, "stated_at": stated_at, "inferred": inferred}


def step(n, reactants, products, description=""):
    return {"n": n, "description": description, "reactants": list(reactants), "products": list(products)}


def template():
    return {
        "general_reaction": "1 + 2 -> 3",
        "reading_guide": "Each drawing is a product; the bold label is followed by the isolated yield.",
        "scheme": {"page": 1, "bbox": [50, 50, 300, 90]},
        "participants": [
            tpart("1", "reactant", "1", amount="0.2 mmol", bbox=[50, 55, 100, 85]),
            tpart("2", "reactant", "2", "RMgBr", "0.4 mmol, 2.0 equiv", bbox=[120, 55, 160, 85]),
            tpart("3", "product", "3", bbox=[240, 55, 300, 85]),
        ],
        "alternative_groups": [],
        "steps": [step(1, ["1", "2"], ["3"])],
        "conditions": [
            cond("cat", "catalyst", "Fe(BF-Phos)Cl2", "0.5 mol%", "C1"),
            cond("licl", "additive", "LiCl", "1.0 equiv"),
            cond("solvent", "solvent", "THF"),
            cond("temp", "temperature", "22-25 °C"),
            cond("time", "time", "2 h"),
        ],
        "structures": [
            {"key": "C1", "label": "C1", "text": "Fe(BF-Phos)Cl2", "page": 1, "bbox": [50, 600, 110, 660]},
            {"key": "C2", "label": "C2", "text": "Fe(dppe)Cl2", "page": 1, "bbox": [120, 600, 180, 660]},
        ],
        "footnotes": [
            {"marker": "a", "text": "Reaction conditions: ...", "overrides": [], "notes": "X = Br unless noted"},
            {"marker": "b", "text": "Reaction time: 24 h.", "overrides": [ov("time", "replace", "24 h")], "notes": ""},
            {"marker": "c", "text": "2 (3.0 equiv), 60 °C",
             "overrides": [ov("2", "replace", amount="0.6 mmol, 3.0 equiv"), ov("temp", "replace", "60 °C")],
             "notes": ""},
        ],
        "preparations": [],
        "variable_defaults": [{"name": "X", "value": "Br", "participant_key": "1", "basis": "footnote a"}],
        "default_yield_type": "isolated",
        "variants": [variant("ni", "[Ni]", [ov("cat", "replace", "NiCl2·glyme", "20 mol%", stated_at=SI5,
                                               basis="General Procedure E")],
                             "Ni conditions are in the SI")],
        "context": [{"doc": "main", "page": 1, "text": "With optimized conditions in hand …",
                     "about": "the scope uses the conditions of the scheme"}],
    }


def sequence_template():
    """acid + HATU -> (activation) -> ester -> (coupling) -> product. The "isolated" protocol starts from
    the ester, which the scheme shows being made from the acid with a drawn N-hydroxy compound and DIC;
    the document gives no conditions for the Ni protocol."""
    t = template()
    t["participants"] = [
        tpart("acid", "reactant", amount="1 equiv", bbox=[50, 55, 80, 85]),
        tpart("hatu", "reactant", text="HATU", amount="1 equiv", generic=False),  # reacts, only named
        tpart("ester", "intermediate", bbox=[90, 55, 130, 85], isolated=False),
        tpart("zn", "reactant", text="R-M-R", amount="1.5 equiv", bbox=[140, 55, 170, 85]),
        tpart("product", "product", bbox=[240, 55, 300, 85]),
    ]
    t["steps"] = [step(1, ["acid", "hatu"], ["ester"], "activation"),
                  step(2, ["ester", "zn"], ["product"], "coupling")]
    t["conditions"] = [cond("base", "base", "Et3N", "1 equiv", step=1), cond("act-time", "time", "2 h", step=1),
                       cond("cat", "catalyst", "Fe(acac)3", "10 mol%", step=2), cond("time", "time", "1 h", step=2)]
    t["structures"] = [{"key": "nhpi", "label": None, "text": None, "page": 1, "bbox": [60, 20, 90, 50]}]
    t["preparations"] = [{"participant_key": "ester", "description": "esterification of the acid",
                          "from_participants": ["acid"],
                          "items": [{"role": "reactant", "text": None, "amount": None, "structure_key": "nhpi"},
                                    {"role": "reagent", "text": "DIC", "amount": None, "structure_key": None}],
                          "basis": "first arrow of the general scheme"}]
    t["footnotes"] = [{"marker": "e", "text": "Reaction at 0 °C.", "notes": "",
                       "overrides": [ov("temp", "add", "0 °C", role="temperature", step=2)]},
                      {"marker": "g", "text": "20 mol% catalyst.", "notes": "",
                       "overrides": [ov("cat", "replace", amount="20 mol%")]}]
    t["variable_defaults"] = [{"name": "M", "value": "Zn", "participant_key": "zn", "basis": "panel title: [M = Zn]"}]
    t["variants"] = [
        variant("in-situ", "[in situ]"),
        variant("isolated", "[isolated]", [ov("acid", "remove"), ov("hatu", "remove")]),
        variant("ni", "[Ni]", [ov("acid", "remove", basis="no prefix: read like the unprefixed [Fe] results", inferred=True),
                               ov("hatu", "remove", basis="no prefix: read like the unprefixed [Fe] results", inferred=True)],
                notes="For the Ni couplings, see SI.", conditions_given=False),
    ]
    return t


def two_ester_template():
    """The scheme draws "ester A or ester B": the isolated ester is a starting material, the other one is
    made in situ from the acid (step 1). Each protocol uses one of them."""
    t = sequence_template()
    t["participants"] = [
        tpart("acid", "reactant", amount="1 equiv", bbox=[50, 55, 80, 85]),
        tpart("hatu", "reactant", text="HATU", amount="1 equiv", generic=False),
        tpart("ester-a", "reactant", text="NHPI or TCNHPI ester", amount="0.1 mmol", bbox=[90, 55, 130, 85],
              alternatives=[{"text": "NHPI ester", "structure_key": None}, {"text": "TCNHPI ester", "structure_key": None}]),
        tpart("ester-b", "intermediate", bbox=[135, 55, 165, 85], isolated=False),
        tpart("zn", "reactant", text="Ar2Zn or dialkylzinc", amount="1.5 equiv", bbox=[170, 55, 200, 85]),
        tpart("product", "product", bbox=[240, 55, 300, 85]),
    ]
    t["alternative_groups"] = [group(["ester-a", "ester-b"])]
    t["steps"] = [step(1, ["acid", "hatu"], ["ester-b"], "activation"),
                  step(2, ["ester-a", "ester-b", "zn"], ["product"], "coupling")]
    t["preparations"][0]["participant_key"] = "ester-a"
    t["variants"] = [
        variant("isolated", "[isolated] [Fe]", [ov("ester-a", "use", basis="footnote a")]),
        variant("in-situ", "[in situ] [Fe]", [ov("ester-b", "use", basis="footnote b"),
                                              ov("zn", "replace", "diarylzinc", "2.5 equiv", basis="footnote b")]),
        variant("fe", "[Fe]", [ov("ester-a", "use", basis="no prefix: the usual protocol of the panel", inferred=True)]),
        variant("ni", "[Ni]", [ov("ester-a", "use", basis="General Procedure E starts from the isolated ester",
                                  stated_at=SI5)], notes="see SI", conditions_given=False),
    ]
    return t


def outcome(**kw):
    o = {"product_key": None, "yield_text": "42%", "yield_value": 42, "yield_qualifier": None,
         "yield_type": None, "selectivity": [], "footnote_markers": [], "notes": None}
    o.update(kw)
    return o


def entry(*outcomes):
    """What the session of one reaction returns."""
    return {
        "participants": [
            epart("1", "reactant", "derived", basis="only the product is drawn"),
            epart("2", "reactant", "derived", basis="only the product is drawn"),
            epart("3", "product", "drawn", label="3fa", bbox=[55, 102, 145, 140]),
        ],
        "structures": [],
        "outcomes": list(outcomes) or [outcome(footnote_markers=["b"])],
        "overrides": [], "related": [], "notes": "", "issues": [],
    }


def two_ester_entry(*outcomes):
    en = entry(*outcomes)
    en["participants"] = [epart("acid", "reactant", "derived", basis="b"), epart("hatu", "reactant", "text", label="HATU"),
                          epart("ester-a", "reactant", "derived", basis="b"),
                          epart("ester-b", "intermediate", "derived", basis="b"),
                          # the agent copied the template text: that is not a statement of this reaction
                          epart("zn", "reactant", "derived", basis="b", text="Ar2Zn or dialkylzinc"),
                          epart("product", "product", "drawn", label="3", bbox=[55, 102, 145, 140])]
    return en


def sequence_entry(*outcomes):
    en = entry(*outcomes)
    en["participants"] = [epart("acid", "reactant", "derived", basis="b"), epart("hatu", "reactant", "text", label="HATU"),
                          epart("ester", "intermediate", "derived", basis="b"), epart("zn", "reactant", "derived", basis="b"),
                          epart("product", "product", "drawn", label="3", bbox=[55, 102, 145, 140])]
    return en


def reaction(rid="e001-1", label="3fa", variant=None, markers=("b",), overrides=(), variables=(), drawn=(),
             results=("42% b",)):
    """One row of an expanded entry, as the pipeline hands it on (with rid and results_text)."""
    return {"rid": rid, "label": label, "results": list(range(1, len(results) + 1)), "results_text": list(results),
            "variant": variant, "footnote_markers": list(markers), "variables": list(variables),
            "drawn_structures": list(drawn), "overrides": list(overrides)}


def row(**kw):
    """A row as the block reader writes it (no rid, no results_text)."""
    r = reaction(**kw)
    del r["rid"], r["results_text"]
    return r


def expansion(*rows, results=("42% b",)):
    return {"printed": "3fa 42% b", "results": list(results), "reasoning": "one result, one reaction",
            "rows": list(rows) or [row()], "issues": []}


def inventory():
    return {"template": template(),
            "entries": [{"label": "3fa", "page": 1, "bbox": [50, 100, 150, 160], "descriptor": "3fa, 42%, b"}],
            "ignored": [], "notes": ""}


CTX = {"region": {"region_id": "main:scheme2", "doc": "main", "label": "Scheme 2", "caption": "Scheme 2. Scope"},
       "block": {"block_id": "1", "kind": "substrate_scope"}, "section": None,
       "crops": {"3": "c/e001-1__3.png"}, "entry_crop": "c/e001__entry.png",
       "template_crops": {"1": "c/_template__1.png", "2": "c/_template__2.png"},
       "structure_crops": {"C1": "c/_structure__C1.png", "C2": "c/_structure__C2.png"}}
UNIT = {"eid": "e001", "label": "3fa", "page": 1, "bbox": [50, 100, 150, 160], "descriptor": "3fa, 42%, b"}
SEQ_CTX = {**CTX, "template_crops": {"acid": "a.png", "ester": "e.png", "zn": "z.png"},
           "structure_crops": {"nhpi": "c/_structure__nhpi.png"}}


def record(t=None, en=None, ctx=CTX, **kw):
    return build_record(ctx, t or template(), UNIT, reaction(**kw), en or entry())


def demo_views():
    """Two blocks as publish() gathers them: one with every kind of reaction, one stale."""
    def rv(reaction_, record_=None, status="ok", errors=()):
        return {"reaction": reaction_, "status": status, "errors": list(errors), "warnings": [], "record": record_,
                "protocol": resolve_protocol(two_ester_template(), {**reaction_, "variant": reaction_["variant"]}),
                "seconds": 1}

    t2 = template()
    t2["conditions"][0] = cond("cat", "catalyst", "A or B",
                               alternatives=[{"text": "A", "structure_key": "C1"}, {"text": "B", "structure_key": None}])
    seq = record(sequence_template(), sequence_entry(outcome()), SEQ_CTX, variant="ni", markers=())
    en = two_ester_entry(outcome())
    en["related"] = [{"doc": "si", "page": 31, "text": "3 was prepared following …", "about": "procedure"}]
    fe = record(two_ester_template(), en, SEQ_CTX, variant="fe", markers=())
    open_rec = record({**two_ester_template(), "variants": []}, two_ester_entry(outcome()), SEQ_CTX, markers=())
    exp = {**expansion(results=("[Fe] 62%", "[Ni] 66%")), "printed": "5\n[Fe] 62%  [Ni] 66%",
           "reasoning": "two protocols: two reactions", "issues": ["label hard to read"]}
    r_fe = reaction(variant="fe", markers=(), results=("[Fe] 62%",))
    r_ni = reaction(rid="e001-2", variant="ni", markers=(), results=("[Ni] 66%",),
                    overrides=[ov("ester-a", "use", basis="GP E", stated_at=SI5)])
    entries = [
        {"entry": UNIT, "crop": "c/e001__entry.png", "status": "ok", "errors": [], "warnings": [], "expansion": exp,
         "reactions": [rv(r_fe, fe), rv(r_ni, None, "failed", ["boom"]), rv(reaction(rid="e001-3"), record()),
                       rv(reaction(rid="e001-4"), record(t2)), rv(reaction(rid="e001-5"), seq),
                       rv(reaction(rid="e001-6"), open_rec)]},
        {"entry": {**UNIT, "eid": "e002"}, "crop": "c/e002__entry.png", "status": "failed", "errors": ["no rows"],
         "warnings": [], "expansion": None, "reactions": []},
    ]
    view = {"region": {**CTX["region"], "first_page": 1}, "block": {**CTX["block"], "page": 1, "title": None},
            "slug": "main-scheme2__1", "status": "ok",
            "meta": {"errors": [], "warnings": ["w"], "overlays": ["overlay_p001.png"]},
            "template": two_ester_template(), "entries": entries,
            "template_crops": SEQ_CTX["template_crops"], "structure_crops": SEQ_CTX["structure_crops"],
            "ignored": [{"page": 1, "bbox": [50, 20, 300, 40], "reason": "title"}], "notes": "n"}
    stale = {**view, "slug": "main-scheme2__2", "status": "stale", "template": None, "entries": [],
             "meta": {"errors": [], "warnings": [], "overlays": ["overlay_p001.png"]}}
    return [view, stale]


def keys(participants):
    return [p["key"] for p in participants]


def conds(rec):
    return {c["key"]: c for st in rec["steps"] for c in st["conditions"]}


class Merge(unittest.TestCase):
    def test_layers_and_origins(self):
        items, problems = merge_items(template(), "ni", ["b", "c"], [ov("licl", "remove"),
                                                                    ov("tempo", "add", "TEMPO", "2.0 equiv", "additive")])
        self.assertEqual(problems, [])
        self.assertEqual((items["cat"]["text"], items["cat"]["origin"]), ("NiCl2·glyme", "variant:ni"))
        self.assertEqual((items["time"]["text"], items["time"]["origin"]), ("24 h", "footnote:b"))
        self.assertEqual((items["temp"]["text"], items["temp"]["origin"]), ("60 °C", "footnote:c"))
        self.assertEqual((items["2"]["amount"], items["2"]["origin"]), ("0.6 mmol, 3.0 equiv", "footnote:c"))
        self.assertEqual(items["2"]["text"], "RMgBr")  # replace with text=None keeps the text
        self.assertTrue(items["licl"]["removed"])
        self.assertEqual(items["tempo"]["origin"], "entry")
        self.assertEqual(items["solvent"]["origin"], "base")

    def test_entry_wins_over_footnote_and_lookup_comes_last(self):
        items, _ = merge_items(template(), None, ["b"], [ov("time", "replace", "36 h")])
        self.assertEqual((items["time"]["text"], items["time"]["origin"]), ("36 h", "entry"))
        items, _ = merge_items(template(), None, ["b"], [ov("time", "replace", "36 h")],
                               [ov("temp", "replace", "23 °C", stated_at=SI5)])
        self.assertEqual((items["temp"]["text"], items["temp"]["origin"], items["temp"]["stated_at"]),
                         ("23 °C", "lookup", SI5))

    def test_unknown_marker_and_key_are_reported(self):
        _, problems = merge_items(template(), None, ["z"], [ov("nope", "remove")])
        self.assertEqual(len(problems), 2)


class Records(unittest.TestCase):
    def test_single_step_record(self):
        rec = record()
        self.assertEqual(rec["reaction_id"], "main:scheme2/1/e001-1")
        self.assertEqual((rec["source"]["figure"], rec["source"]["page"], rec["source"]["entry_id"]),
                         ("Scheme 2", 1, "e001"))
        self.assertEqual((rec["source"]["crop"], rec["results"]), ("c/e001__entry.png", ["42% b"]))
        (st,) = rec["steps"]
        self.assertEqual((keys(st["reactants"]), keys(st["products"])), (["1", "2"], ["3"]))
        r1 = st["reactants"][0]
        self.assertEqual((r1["source"], r1["generic"], r1["bbox"], r1["crop"]),
                         ("derived", True, [50, 55, 100, 85], "c/_template__1.png"))
        self.assertEqual(r1["variables"], [{"name": "X", "value": "Br", "origin": "default", "basis": "footnote a"}])
        self.assertEqual(r1["amount"], "0.2 mmol")
        p = st["products"][0]
        self.assertEqual((p["source"], p["crop"], p["bbox"]), ("drawn", "c/e001-1__3.png", [55, 102, 145, 140]))
        self.assertEqual(p["outcomes"][0]["yield"],
                         {"text": "42%", "value": 42, "qualifier": None, "type": "isolated", "type_origin": "default"})
        self.assertEqual((conds(rec)["time"]["text"], conds(rec)["time"]["origin"]), ("24 h", "footnote:b"))
        self.assertEqual(rec["footnotes"], [{"marker": "b", "text": "Reaction time: 24 h."}])
        self.assertEqual((rec["conditions"], rec["variant"]), ([], None))

    def test_sequence_is_laid_out_step_by_step(self):
        t = sequence_template()
        in_situ = record(t, sequence_entry(outcome(yield_text="71%", yield_value=71)), SEQ_CTX, variant="in-situ", markers=())
        isolated = record(t, sequence_entry(outcome(yield_text="81%", yield_value=81)), SEQ_CTX, variant="isolated",
                          markers=(), rid="e001-2")

        # in situ: acid + HATU -> ester (not isolated), then ester + zinc reagent -> product
        s1, s2 = in_situ["steps"]
        self.assertEqual((keys(s1["reactants"]), keys(s1["products"])), (["acid", "hatu"], ["ester"]))
        self.assertEqual((keys(s2["reactants"]), keys(s2["products"])), (["ester", "zn"], ["product"]))
        self.assertEqual((s1["reactants"][1]["source"], s1["reactants"][1]["text"], s1["reactants"][1]["amount"]),
                         ("text", "HATU", "1 equiv"))
        self.assertEqual((s1["products"][0]["role"], s1["products"][0]["isolated"]), ("intermediate", False))
        self.assertEqual(keys(s1["conditions"]), ["base", "act-time"])
        self.assertEqual(keys(s2["conditions"]), ["cat", "time"])
        self.assertEqual(s2["products"][0]["outcomes"][0]["yield"]["value"], 71)
        self.assertEqual(s2["reactants"][1]["variables"][0]["value"], "Zn")  # block-level [M = Zn]
        self.assertNotIn("preparation", s2["reactants"][0])               # made in step 1 of this record
        self.assertEqual((in_situ["conditions_given"], in_situ["inferences"]), (True, []))
        self.assertEqual(in_situ["variant"]["title"], "[in situ]")

        # isolated: the activation step did not happen; the ester is the starting material
        (only,) = isolated["steps"]
        self.assertEqual((keys(only["reactants"]), keys(only["products"])), (["ester", "zn"], ["product"]))
        self.assertEqual((only["reactants"][0]["role"], only["reactants"][0]["isolated"]), ("reactant", None))
        self.assertEqual(keys(only["conditions"]), ["cat", "time"])
        self.assertEqual([c["key"] for c in isolated["removed_conditions"]], ["base", "act-time"])
        self.assertEqual(only["products"][0]["outcomes"][0]["yield"]["value"], 81)
        self.assertEqual(isolated["reaction_id"], "main:scheme2/1/e001-2")

    def test_preparation_of_a_starting_material(self):
        rec = record(sequence_template(), sequence_entry(outcome()), SEQ_CTX, variant="isolated", markers=())
        prep = rec["steps"][0]["reactants"][0]["preparation"]
        self.assertFalse(prep["in_yield"])
        self.assertEqual([(s["key"], s["crop"]) for s in prep["from"]], [("acid", "a.png")])
        self.assertEqual([(x["role"], x["text"], x["structure"] and x["structure"]["crop"]) for x in prep["items"]],
                         [("reactant", None, "c/_structure__nhpi.png"), ("reagent", "DIC", None)])

    def test_protocol_without_conditions_takes_nothing_over(self):
        rec = record(sequence_template(), sequence_entry(outcome()), SEQ_CTX, variant="ni", markers=("e", "g"))
        (only,) = rec["steps"]
        self.assertFalse(rec["conditions_given"])
        self.assertEqual(keys(only["reactants"]), ["ester", "zn"])
        self.assertEqual([p["amount"] for p in only["reactants"]], [None, None])   # no Fe amounts
        # Only what a footnote states outright is listed; "20 mol% catalyst" names no catalyst here.
        self.assertEqual([(c["key"], c["text"], c["origin"]) for c in only["conditions"]], [("temp", "0 °C", "footnote:e")])
        self.assertEqual(rec["removed_conditions"], [])
        self.assertTrue(any("does not give the conditions" in i for i in rec["issues"]))
        # Starting from the ester is a conclusion, and the record says so.
        self.assertEqual([(i["key"], i["action"], i["origin"]) for i in rec["inferences"]],
                         [("acid", "remove", "variant:ni"), ("hatu", "remove", "variant:ni")])
        self.assertIn("no prefix", rec["inferences"][0]["basis"])

    def test_each_record_uses_one_of_the_alternatives(self):
        ctx = {**SEQ_CTX, "template_crops": {"acid": "a.png", "ester-a": "ea.png", "ester-b": "eb.png", "zn": "z.png"}}
        isolated, in_situ, fe, ni = (record(two_ester_template(), two_ester_entry(outcome()), ctx, variant=v, markers=())
                                     for v in ("isolated", "in-situ", "fe", "ni"))

        # isolated ester: the activation step and its compounds drop out without being named
        (only,) = isolated["steps"]
        self.assertEqual((keys(only["reactants"]), keys(only["products"])), (["ester-a", "zn"], ["product"]))
        ester = only["reactants"][0]
        self.assertEqual((ester["choice"]["origin"], ester["choice"]["basis"], ester["inferred"]),
                         ("variant:isolated", "footnote a", None))
        self.assertEqual([a["text"] for a in ester["alternatives"]], ["NHPI ester", "TCNHPI ester"])
        self.assertEqual(isolated["unresolved"], ["ester-a"])
        self.assertIn("preparation", ester)
        self.assertEqual([c["key"] for c in isolated["removed_conditions"]], ["base", "act-time"])
        self.assertEqual(isolated["issues"], [])

        # in situ: both steps, the other ester; what the variant says about the zinc reagent wins
        s1, s2 = in_situ["steps"]
        self.assertEqual((keys(s1["reactants"]), keys(s1["products"])), (["acid", "hatu"], ["ester-b"]))
        self.assertEqual(keys(s2["reactants"]), ["ester-b", "zn"])
        self.assertEqual((s2["reactants"][1]["text"], s2["reactants"][1]["amount"]), ("diarylzinc", "2.5 equiv"))

        # no prefix: read as the isolated protocol, and the record says that this is a conclusion
        self.assertEqual(keys(fe["steps"][0]["reactants"]), ["ester-a", "zn"])
        self.assertEqual([(i["key"], i["action"], i["origin"]) for i in fe["inferences"]], [("ester-a", "use", "variant:fe")])
        self.assertEqual(fe["steps"][0]["reactants"][0]["inferred"]["basis"], "no prefix: the usual protocol of the panel")

        # Ni: the SI says where it starts; nothing of the Fe conditions is taken over
        self.assertEqual((ni["conditions_given"], ni["inferences"]), (False, []))
        self.assertEqual(ni["steps"][0]["reactants"][0]["choice"]["stated_at"], SI5)
        self.assertEqual([p["amount"] for p in ni["steps"][0]["reactants"]], [None, None])

    def test_default_alternative_and_row_choice(self):
        t = two_ester_template()
        t["variants"] = []
        t["alternative_groups"] = [group(["ester-a", "ester-b"], default="ester-a",
                                         basis="'optimization … using NHPI ester 1'", stated_at={"doc": "main", "page": 1})]
        rec = record(t, two_ester_entry(outcome()), SEQ_CTX, markers=())
        self.assertEqual(keys(rec["steps"][0]["reactants"]), ["ester-a", "zn"])
        self.assertEqual(rec["steps"][0]["reactants"][0]["choice"]["origin"], "base")

        rec = record(t, two_ester_entry(outcome()), SEQ_CTX, markers=(),       # this row says otherwise
                     overrides=[ov("ester-b", "use", basis="row: 'HOAt ester [in situ]'")])
        self.assertEqual([keys(st["reactants"]) for st in rec["steps"]], [["acid", "hatu"], ["ester-b", "zn"]])
        self.assertEqual(rec["steps"][1]["reactants"][0]["choice"]["origin"], "entry")

    def test_undecided_alternatives_are_flagged(self):
        t = two_ester_template()
        t["variants"] = []                                # no default, nothing chooses
        rec = record(t, two_ester_entry(outcome()), SEQ_CTX, markers=())
        esters = [p for p in rec["steps"][1]["reactants"] if p["key"].startswith("ester")]
        self.assertEqual([p["undecided_with"] for p in esters], [["ester-b"], ["ester-a"]])
        self.assertTrue(any("are alternatives" in i for i in rec["issues"]))

    def test_what_the_paper_states_elsewhere_keeps_its_location(self):
        en = entry()
        en["participants"][0] = epart("1", "reactant", "derived", basis="only the product is drawn", text="SI-26",
                                      stated_at={"doc": "si", "page": 31})
        en["overrides"] = [ov("time", "replace", "3 h", basis="procedure for 3fa", stated_at={"doc": "si", "page": 31})]
        en["related"] = [{"doc": "si", "page": 31, "text": "3fa was prepared following General Procedure B using SI-26 …",
                          "about": "names the starting ester and the reaction time"}]
        rec = record(en=en)
        r1 = rec["steps"][0]["reactants"][0]
        self.assertEqual((r1["text"], r1["source"], r1["stated_at"]), ("SI-26", "derived", {"doc": "si", "page": 31}))
        self.assertEqual((conds(rec)["time"]["stated_at"], conds(rec)["time"]["origin"]), ({"doc": "si", "page": 31}, "lookup"))
        self.assertIsNone(conds(rec)["solvent"]["stated_at"])
        self.assertEqual(rec["related"][0]["page"], 31)
        ni = record(variant="ni")
        self.assertEqual(conds(ni)["cat"]["stated_at"], SI5)       # from the variant, found in the SI

    def test_inferred_change_marks_the_item(self):
        rec = record(overrides=[ov("time", "replace", "12 h", basis="as for the neighbouring entry", inferred=True)])
        self.assertEqual(conds(rec)["time"]["inferred"],
                         {"origin": "entry", "action": "replace", "basis": "as for the neighbouring entry"})
        self.assertIsNone(conds(rec)["cat"]["inferred"])
        self.assertEqual([i["key"] for i in rec["inferences"]], ["time"])

    def test_condition_given_entry_by_entry(self):
        t = template()
        t["conditions"][0] = cond("cat", "catalyst", "cat.", "0.5 mol%", per_entry=True)
        rec = record(t, overrides=[ov("cat", "replace", "C2", structure_key="C2", basis="row cell: cat.")])
        c = conds(rec)["cat"]
        self.assertEqual((c["text"], c["amount"], c["value_missing"], c["structure"]["key"]), ("C2", "0.5 mol%", False, "C2"))
        rec = record(t)                                          # nothing states it
        self.assertTrue(conds(rec)["cat"]["value_missing"])
        self.assertTrue(any("entry by entry" in i for i in rec["issues"]))

    def test_entry_only_participants_are_placed(self):
        en = entry()
        en["participants"] += [epart("tempo-adduct", "byproduct", "drawn", bbox=[150, 102, 190, 140]),
                               epart("extra", "reactant", "text", label="TEMPO")]
        rec = record(en=en, ctx={**CTX, "crops": {**CTX["crops"], "tempo-adduct": "t.png"}})
        (st,) = rec["steps"]
        self.assertEqual((keys(st["reactants"]), keys(st["products"])), (["1", "2", "extra"], ["3", "tempo-adduct"]))

    def test_condition_structures(self):
        cat = lambda rec: conds(rec)["cat"]
        rec = record()
        self.assertEqual(cat(rec)["structure"]["crop"], "c/_structure__C1.png")
        self.assertIsNone(conds(rec)["solvent"]["structure"])

        rec = record(overrides=[ov("cat", "replace", "C2", structure_key="C2")])
        self.assertEqual((cat(rec)["text"], cat(rec)["structure"]["key"]), ("C2", "C2"))

        rec = record(overrides=[ov("cat", "replace", "FeCl2")])           # not drawn: structure cleared
        self.assertIsNone(cat(rec)["structure"])

        rec = record(overrides=[ov("cat", "replace", amount="1 mol%")])   # same compound, new amount
        self.assertEqual((cat(rec)["amount"], cat(rec)["structure"]["key"]), ("1 mol%", "C1"))

        # drawn inside the entry: the row names it, the reaction's session boxes it
        en = entry()
        en["structures"] = [{"key": "L9", "label": "L9", "text": None, "page": 1, "bbox": [60, 110, 90, 130]}]
        ctx = {**CTX, "crops": {**CTX["crops"], "s:L9": "c/e001-1__s-L9.png"}}
        rec = record(en=en, ctx=ctx, drawn=[{"key": "L9", "label": "L9", "text": "dppBz"}],
                     overrides=[ov("lig", "add", "L9", role="ligand", structure_key="L9")])
        lig = conds(rec)["lig"]["structure"]
        self.assertEqual((lig["crop"], lig["text"], lig["bbox"]), ("c/e001-1__s-L9.png", None, [60, 110, 90, 130]))

    def test_removed_item_is_not_revived_by_a_later_replace(self):
        t = template()
        t["variants"] = [variant("v", "V", [ov("1", "remove"), ov("licl", "remove")])]
        t["footnotes"].append({"marker": "s", "text": "1.0 mmol scale.", "notes": "",
                               "overrides": [ov("1", "replace", amount="1.0 mmol"), ov("licl", "replace", amount="2 equiv")]})
        rec = record(t, variant="v", markers=("s",))
        self.assertEqual(keys(rec["steps"][0]["reactants"]), ["2"])
        self.assertNotIn("licl", conds(rec))

    def test_alternatives_stay_unresolved_until_stated(self):
        t = template()
        t["conditions"][0] = cond("cat", "catalyst", "Fe(acac)3 or FeCl3", "10 mol%",
                                  alternatives=[{"text": "Fe(acac)3", "structure_key": None},
                                                {"text": "FeCl3", "structure_key": None}])
        t["footnotes"].append({"marker": "d", "text": "Using FeCl3 (5 mol%).", "notes": "",
                               "overrides": [ov("cat", "replace", "FeCl3", "5 mol%")]})
        rec = record(t)
        self.assertEqual(rec["unresolved"], ["cat"])
        self.assertEqual([a["text"] for a in conds(rec)["cat"]["alternatives"]], ["Fe(acac)3", "FeCl3"])

        rec = record(t, markers=("d",))
        self.assertEqual(rec["unresolved"], [])
        self.assertEqual((conds(rec)["cat"]["text"], conds(rec)["cat"]["alternatives"]), ("FeCl3", []))

    def test_stated_variable_beats_default(self):
        en = entry()
        en["participants"][0]["variables"] = [{"name": "X", "value": "Cl"}]
        rec = record(en=en, variables=[{"name": "X", "value": "Cl"}])
        self.assertEqual(rec["steps"][0]["reactants"][0]["variables"], [{"name": "X", "value": "Cl", "origin": "stated"}])

    def test_reactions_of_one_entry_are_records_of_their_own(self):
        fe = record(results=("[Fe] 81%",), markers=())
        ni = record(rid="e001-2", variant="ni", results=("[Ni] 85%",), markers=(),
                    en=entry(outcome(yield_text="85%", yield_value=85)))
        self.assertEqual([r["reaction_id"] for r in (fe, ni)], ["main:scheme2/1/e001-1", "main:scheme2/1/e001-2"])
        self.assertEqual([conds(r)["cat"]["text"] for r in (fe, ni)], ["Fe(BF-Phos)Cl2", "NiCl2·glyme"])
        self.assertEqual(ni["variant"]["notes"], "Ni conditions are in the SI")
        self.assertEqual(ni["results"], ["[Ni] 85%"])

    def test_conversion_and_multi_product(self):
        en = entry(outcome(product_key="3", yield_text="90", yield_value=90, yield_type="NMR"),
                   outcome(product_key="3x", yield_text="5", yield_value=5, yield_type="NMR"),
                   outcome(yield_text=">98", yield_value=98, yield_qualifier=">", yield_type="conversion"))
        en["participants"].append(epart("3x", "byproduct", "text", label="3a'"))
        rec = record(en=en)
        self.assertEqual([len(p["outcomes"]) for p in rec["steps"][0]["products"]], [1, 1])
        self.assertEqual(rec["other_outcomes"][0]["yield"]["type"], "conversion")

    def test_protocol_handed_to_the_reaction_session(self):
        p = resolve_protocol(sequence_template(), reaction(variant="isolated", markers=("g",)))
        (st,) = p["steps"]
        self.assertEqual(([x["key"] for x in st["reactants"]], [x["key"] for x in st["products"]]),
                         (["ester", "zn"], ["product"]))
        self.assertEqual(st["reactants"][0]["drawn_at"], {"page": 1, "bbox": [90, 55, 130, 85]})
        self.assertEqual({c["key"]: (c["amount"], c["origin"]) for c in p["conditions"]}["cat"], ("20 mol%", "footnote:g"))
        self.assertEqual((p["removed"], p["removed_participants"]), (["base", "act-time"], ["acid", "hatu"]))

    def test_view_for_a_viewer(self):
        view, stale = demo_views()
        data = block_view(view)
        json.dumps(data)  # plain data, nothing else
        self.assertEqual((data["ref"], data["status"], data["warnings"], data["ignored"][0]["reason"]),
                         ("main:scheme2/1", "ok", ["w"], "title"))
        # Crop paths are spelled out: a viewer does not rebuild file names.
        self.assertEqual({p["key"]: p["crop"] for p in data["template"]["participants"]},
                         {"acid": "a.png", "hatu": None, "ester-a": None, "ester-b": None, "zn": "z.png", "product": None})
        self.assertEqual(data["template"]["structures"][0]["crop"], "c/_structure__nhpi.png")
        split, unsplit = data["entries"]
        self.assertEqual((split["eid"], split["crop"], split["expansion"]["reasoning"]),
                         ("e001", "c/e001__entry.png", "two protocols: two reactions"))
        self.assertEqual((unsplit["status"], unsplit["errors"], unsplit["expansion"], unsplit["reactions"]),
                         ("failed", ["no rows"], None, []))
        done, failed = split["reactions"][:2]
        self.assertEqual((done["record"]["reaction_id"], done["draft"], done["flags"]),
                         ("main:scheme2/1/e001-1", None, ["inferred", "unresolved"]))
        # Without a record, the reaction is laid out from the template as merged for it.
        draft = failed["draft"]
        self.assertEqual((failed["status"], failed["errors"], failed["record"], failed["flags"]),
                         ("failed", ["boom"], None, ["issues"]))
        self.assertEqual((draft["variant"]["title"], draft["conditions_given"]), ("[Ni]", False))
        (st,) = draft["steps"]
        self.assertEqual(([x["key"] for x in st["reactants"]], [(x["key"], x["label"]) for x in st["products"]]),
                         (["ester-a", "zn"], [("product", "3fa")]))
        self.assertEqual((st["step"], st["reactants"][1]["crop"], st["conditions"]), (1, "z.png", []))

        head = block_head(data)
        self.assertEqual((head["slug"], head["figure"], head["status"]), ("main-scheme2__1", "Scheme 2", "ok"))
        self.assertEqual(head["entries"], {"listed": 2, "ok": 1, "failed": 1, "skipped": 0})
        self.assertEqual(head["reactions"], {"listed": 6, "ok": 5, "failed": 1, "inferred": 2, "unresolved": 3, "issues": 2})
        old = block_head(block_view(stale))
        self.assertEqual((old["status"], old["entries"]["listed"]), ("stale", 0))
        self.assertNotEqual(head["rev"], old["rev"])
        self.assertEqual(head["rev"], block_head(block_view(demo_views()[0]))["rev"])


class Validation(unittest.TestCase):
    def errors_inv(self, inv, n_est=1):
        return validate_inventory(inv, INV_SCHEMA, SIZES, n_est, DOC_PAGES)[0]

    def errors_exp(self, exp, t=None):
        return validate_expansion(exp, EXPAND_SCHEMA, t or template(), DOC_PAGES)[0]

    def errors_entry(self, en, t=None, **kw):
        return validate_entry(en, ENTRY_SCHEMA, t or template(), reaction(**kw), SIZES, DOC_PAGES)[0]

    def assertHas(self, errors, fragment):
        self.assertTrue(any(fragment in e for e in errors), f"no error containing {fragment!r}: {errors}")

    def test_valid(self):
        self.assertEqual(validate_inventory(inventory(), INV_SCHEMA, SIZES, 1), ([], []))
        self.assertEqual(validate_expansion(expansion(), EXPAND_SCHEMA, template()), ([], []))
        self.assertEqual(validate_entry(entry(), ENTRY_SCHEMA, template(), reaction(), SIZES), ([], []))
        inv = inventory(); inv["template"] = sequence_template()
        self.assertEqual(self.errors_inv(inv), [])

    def test_inventory_errors(self):
        inv = inventory(); inv["entries"][0]["bbox"] = [50, 100, 150]
        self.assertHas(self.errors_inv(inv), "schema at /entries/0/bbox")
        inv = inventory(); inv["entries"][0]["page"] = 9
        self.assertHas(self.errors_inv(inv), "page 9 is not a page")
        inv = inventory(); inv["template"]["conditions"][0]["key"] = "1"
        self.assertHas(self.errors_inv(inv), "key '1' is used more than once")
        inv = inventory(); inv["template"]["footnotes"][1]["overrides"] = [ov("nope", "replace", "x")]
        self.assertHas(self.errors_inv(inv), "targets an unknown key")
        inv = inventory(); inv["template"]["variants"][0]["overrides"] = [ov("x", "add", "X")]
        self.assertHas(self.errors_inv(inv), "needs a condition role")
        inv = inventory(); inv["template"]["variable_defaults"][0]["participant_key"] = "9"
        self.assertHas(self.errors_inv(inv), "unknown participant_key")
        inv = inventory(); inv["template"]["conditions"][0]["alternatives"] = [{"text": "only one", "structure_key": None}]
        self.assertHas(self.errors_inv(inv), "at least two options")
        inv = inventory(); inv["template"]["variants"][0]["overrides"] = [ov("1", "replace", role="catalyst")]
        self.assertHas(self.errors_inv(inv), "does not fit a participant")
        inv = inventory(); inv["template"]["variants"][0]["overrides"] = [ov("x", "add", "X", role="reactant")]
        self.assertHas(self.errors_inv(inv), "needs a condition role")
        inv = inventory(); inv["template"]["variants"][0]["overrides"] = [ov("1", "remove"), ov("3", "replace", role="byproduct")]
        self.assertEqual(self.errors_inv(inv), [])
        inv = inventory(); inv["template"]["conditions"][0]["structure_key"] = "C9"
        self.assertHas(self.errors_inv(inv), "unknown structure_key 'C9'")
        inv = inventory(); inv["template"]["structures"][1]["key"] = "C1"
        self.assertHas(self.errors_inv(inv), "structure key 'C1' is used more than once")
        inv = inventory(); inv["template"]["footnotes"][1]["overrides"] = [ov("cat", "replace", "C7", structure_key="C7")]
        self.assertHas(self.errors_inv(inv), "refers to unknown structure 'C7'")

    def test_inventory_alternative_groups(self):
        def check(change):
            inv = inventory(); inv["template"] = two_ester_template(); change(inv["template"])
            return validate_inventory(inv, INV_SCHEMA, SIZES, 1, DOC_PAGES)
        self.assertEqual(check(lambda t: None), ([], []))
        # a protocol that leaves the choice open is allowed: its rows must choose, and the reader is told
        errors, warnings = check(lambda t: t["variants"][3].update(overrides=[]))
        self.assertEqual(errors, [])
        self.assertTrue(any("variant 'ni' leaves the alternatives" in w for w in warnings))
        self.assertHas(check(lambda t: t["alternative_groups"][0].update(default="zn"))[0], "is not one of the group")
        self.assertHas(check(lambda t: t["alternative_groups"][0].update(keys=["ester-a", "nope"]))[0],
                       "'nope' is not a participant key")
        self.assertHas(check(lambda t: t["alternative_groups"].append(group(["ester-a", "zn"], "zn")))[0],
                       "'ester-a' is already in another group")
        self.assertHas(check(lambda t: t["variants"][0]["overrides"].append(ov("zn", "use")))[0],
                       "'zn' is not one of them")
        self.assertHas(check(lambda t: t["variants"][0]["overrides"].append(
            ov("cat", "replace", "FeCl3", inferred=True, stated_at=SI5)))[0], "contradict each other")
        self.assertHas(check(lambda t: t["variants"][3]["overrides"][0].update(stated_at={"doc": "si", "page": 99}))[0],
                       "page 99 is not a page of 'si'")
        self.assertHas(check(lambda t: t["context"].append({"doc": "si", "page": 0, "text": "x", "about": "y"}))[0],
                       "template.context[1]: page 0")

    def test_inventory_preparations(self):
        def with_prep(**kw):
            inv = inventory(); inv["template"] = sequence_template()
            inv["template"]["preparations"][0].update(kw)
            return self.errors_inv(inv)
        self.assertEqual(with_prep(), [])
        self.assertHas(with_prep(participant_key="nope"), "'nope' is not a participant key")
        self.assertHas(with_prep(from_participants=["ester"]), "not made from itself")
        self.assertHas(with_prep(from_participants=[], items=[]), "says nothing about the preparation")
        self.assertHas(with_prep(items=[{"role": "reactant", "text": None, "amount": None, "structure_key": "zz"}]),
                       "unknown structure 'zz'")
        self.assertHas(with_prep(items=[{"role": "reagent", "text": None, "amount": None, "structure_key": None}]),
                       "needs its printed text or the structure_key")

    def test_inventory_steps(self):
        inv = inventory(); inv["template"]["steps"] = []
        self.assertHas(self.errors_inv(inv), "template.steps is empty")
        inv = inventory(); inv["template"]["steps"] = [step(2, ["1", "2"], ["3"])]
        self.assertHas(self.errors_inv(inv), "step numbers must be 1..1")
        inv = inventory(); inv["template"]["steps"] = [step(1, ["1", "zz"], ["3"])]
        self.assertHas(self.errors_inv(inv), "'zz' is not a participant key")
        inv = inventory(); inv["template"]["steps"] = [step(1, ["1"], ["3"])]
        self.assertHas(self.errors_inv(inv), "participant '2' does not appear in any step")
        inv = inventory(); inv["template"]["conditions"][0]["step"] = 3
        self.assertHas(self.errors_inv(inv), "step 3 is not one of template.steps")
        inv = inventory(); inv["template"] = sequence_template()
        inv["template"]["steps"] = [step(1, ["acid", "zn"], ["ester", "product"])]   # ester never used later
        self.assertHas(self.errors_inv(inv), "has role intermediate")

    def test_inventory_count_warning(self):
        _, warnings = validate_inventory(inventory(), INV_SCHEMA, SIZES, 20)
        self.assertTrue(any("1 entries listed, but Step 1 estimated about 20" in w for w in warnings))

    def test_expansion_results_belong_to_one_row_each(self):
        three = ("[isolated] [Fe] 81% c", "[in situ] [Fe] 71%", "[Ni] 85%")
        rows = [row(label="3", results=three[:1], variant="isolated", markers=()),
                row(label="3", results=three[:2], variant="in-situ", markers=()),
                row(label="3", results=three, variant="ni", markers=())]
        rows[1]["results"], rows[2]["results"] = [2], [3]
        t = two_ester_template()
        self.assertEqual(self.errors_exp(expansion(*rows, results=three), t), [])
        rows[2]["results"] = [2]
        errors = self.errors_exp(expansion(*rows, results=three), t)
        self.assertHas(errors, "result 3 ('[Ni] 85%') belongs to no row")
        self.assertHas(errors, "result 2 ('[in situ] [Fe] 71%') is given to rows [2, 3]")
        rows[2]["results"] = [4]
        self.assertHas(self.errors_exp(expansion(*rows, results=three), t), "there is no result 4")
        rows[2]["results"] = []
        self.assertHas(self.errors_exp(expansion(*rows, results=three), t), "give the numbers of its results")

    def test_expansion_rows(self):
        self.assertHas(self.errors_exp(expansion(row(variant="pd"))), "unknown variant 'pd'")
        self.assertHas(self.errors_exp(expansion(row(markers=("q",)))), "footnote marker 'q' is not defined")
        self.assertHas(self.errors_exp(expansion(row(overrides=[ov("ghost", "remove")]))), "targets an unknown key")
        self.assertHas(self.errors_exp(expansion(row(overrides=[ov("cat", "replace", "L9", structure_key="L9")]))),
                       "refers to unknown structure 'L9'")
        drawn = row(drawn=[{"key": "L9", "label": "L9", "text": None}],
                    overrides=[ov("cat", "replace", "L9", structure_key="L9")])
        self.assertEqual(self.errors_exp(expansion(drawn)), [])
        self.assertHas(self.errors_exp(expansion(row(drawn=[{"key": "C1", "label": None, "text": None}]))),
                       "drawn structure key 'C1' is used twice or is already a template structure")
        # two rows that describe the same experiment
        twice = expansion(row(), row(), results=("42%", "40%"))
        twice["rows"][1]["results"] = [2]
        self.assertHas(self.errors_exp(twice), "rows[2] (3fa) and rows[1] have the same label")
        twice["rows"][1]["variables"] = [{"name": "X", "value": "Cl"}]          # another substrate: fine
        self.assertEqual(self.errors_exp(twice), [])
        self.assertEqual(validate_expansion(expansion(row(results=()), results=()), EXPAND_SCHEMA, template()), ([], []))
        _, warnings = validate_expansion({**expansion(), "rows": []}, EXPAND_SCHEMA, template())
        self.assertIn("no reaction in this entry", warnings)

    def test_expansion_rows_settle_open_points(self):
        t = two_ester_template()
        t["variants"] = []
        self.assertHas(self.errors_exp(expansion(row(markers=())), t),
                       "['ester-a', 'ester-b'] are alternatives for one position, but ['ester-a', 'ester-b'] are all "
                       "still in play; add a `use` override")
        self.assertEqual(self.errors_exp(expansion(row(markers=(), overrides=[ov("ester-b", "use", inferred=True)])), t), [])
        t = template(); t["conditions"][0] = cond("cat", "catalyst", "cat.", per_entry=True)
        self.assertHas(self.errors_exp(expansion(row()), t), "condition 'cat' ('cat.') is given entry by entry")
        self.assertEqual(self.errors_exp(expansion(row(overrides=[ov("cat", "remove", basis="empty cell")])), t), [])

    def test_entry_errors(self):
        en = entry(); en["participants"][2]["bbox"] = None
        self.assertHas(self.errors_entry(en), "source=drawn needs page and bbox")
        en = entry(); en["participants"][0]["key"] = "zz"
        self.assertHas(self.errors_entry(en), "must use the key of a template participant")
        en = entry(); en["participants"][0]["basis"] = ""
        self.assertHas(self.errors_entry(en), "needs a basis")
        en = entry(outcome(footnote_markers=["q"]))
        self.assertHas(self.errors_entry(en), "footnote marker 'q' is not defined")
        en = entry(outcome(product_key="7"))
        self.assertHas(self.errors_entry(en), "product_key '7'")
        en = entry(outcome(yield_value=420))
        self.assertHas(self.errors_entry(en), "outside 0..100")
        en = entry(); en["overrides"] = [ov("ghost", "remove", stated_at=SI5)]
        self.assertHas(self.errors_entry(en), "targets an unknown key")
        en = entry(); en["overrides"] = [ov("cat", "replace", "C7", structure_key="C7", stated_at=SI5)]
        self.assertHas(self.errors_entry(en), "refers to unknown structure 'C7'")
        en = entry(); en["participants"][2]["bbox"] = [50, 100, 950, 160]
        self.assertHas(self.errors_entry(en), "exceeds page size")

    def test_entry_keeps_to_its_reaction(self):
        en = entry(); en["overrides"] = [ov("time", "replace", "3 h")]           # read from the figure: not its job
        self.assertHas(self.errors_entry(en), "has neither stated_at nor inferred")
        en["overrides"][0]["stated_at"] = {"doc": "si", "page": 31}
        self.assertEqual(self.errors_entry(en), [])
        # variables: those of the row, on the participants that carry them
        en = entry(); en["participants"][0]["variables"] = [{"name": "R", "value": "Me"}]
        self.assertHas(self.errors_entry(en), "variable R = Me is not one of this reaction's variables")
        self.assertEqual(self.errors_entry(en, variables=[{"name": "R", "value": "Me"}]), [])
        self.assertHas(self.errors_entry(entry(), variables=[{"name": "R", "value": "Me"}]), "is on no participant")
        # drawn structures: the row names them, the entry boxes them
        en = entry(); en["structures"] = [{"key": "L9", "label": "L9", "text": None, "page": 1, "bbox": [60, 110, 90, 130]}]
        self.assertHas(self.errors_entry(en), "structure 'L9' is not one of reaction.drawn_structures")
        drawn = [{"key": "L9", "label": "L9", "text": None}]
        self.assertEqual(self.errors_entry(en, drawn=drawn), [])
        self.assertHas(self.errors_entry(entry(), drawn=drawn), "lists 'L9': give its box")
        # a result that is not this reaction's is only a warning
        _, warnings = validate_entry(entry(outcome(yield_text="85%", yield_value=85)), ENTRY_SCHEMA, template(),
                                     reaction(), SIZES)
        self.assertTrue(any("is not part of this reaction's results" in w for w in warnings))

    def test_entry_must_be_complete(self):
        seq = lambda en, **kw: self.errors_entry(en, sequence_template(), markers=(), **kw)
        self.assertEqual(seq(sequence_entry(outcome()), variant="in-situ"), [])
        en = sequence_entry(outcome()); del en["participants"][1]                 # HATU forgotten
        self.assertHas(seq(en, variant="in-situ"), "template participant 'hatu' takes part in this reaction")
        en = sequence_entry(outcome()); del en["participants"][:2]                # not part of that protocol
        self.assertEqual(seq(en, variant="isolated"), [])
        en = sequence_entry(outcome()); del en["participants"][1]
        self.assertEqual(seq(en, variant="in-situ", overrides=[ov("hatu", "remove", basis="'without HATU'")]), [])

        # compounds of a step this protocol leaves out need not be listed
        two = lambda en, **kw: self.errors_entry(en, two_ester_template(), markers=(), **kw)
        en = two_ester_entry(outcome()); en["participants"] = en["participants"][2:3] + en["participants"][4:]
        self.assertEqual(two(en, variant="isolated"), [])
        self.assertHas(two(en, variant="in-situ"), "template participant 'acid' takes part in this reaction")
        en = two_ester_entry(outcome()); en["related"] = [{"doc": "si", "page": 77, "text": "x", "about": "y"}]
        self.assertHas(two(en, variant="isolated"), "related[0]: page 77 is not a page of 'si'")


class Selection(unittest.TestCase):
    REGIONS = {"regions": [
        {"region_id": "main:scheme2", "include": True, "blocks": [
            {"block_id": "A", "include": True, "kind": "substrate_scope"},
            {"block_id": "B", "include": False, "kind": "substrate_scope"}]},
        {"region_id": "main:scheme1", "include": False, "blocks": [
            {"block_id": "1", "include": True, "kind": "background"}]},
        {"region_id": "main:table1", "include": True, "blocks": [
            {"block_id": "1", "include": True, "kind": "optimization"}]},
    ]}

    def refs(self, **kw):
        return [f"{r['region_id']}/{b['block_id']}" for r, b in select_blocks(self.REGIONS, **kw)]

    def test_filters(self):
        self.assertEqual(self.refs(), ["main:scheme2/A", "main:table1/1"])
        self.assertEqual(self.refs(blocks=("main:table1",)), ["main:table1/1"])
        self.assertEqual(self.refs(blocks=("main:scheme2/A",)), ["main:scheme2/A"])
        self.assertEqual(self.refs(kinds=("optimization",)), ["main:table1/1"])
        with self.assertRaises(ValueError):
            self.refs(blocks=("main:scheme2/B",))


if __name__ == "__main__":
    unittest.main()
