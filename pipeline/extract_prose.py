"""Pure logic of the two prose skills (Step 2, block layout `prose`): the validators of the three
Codex answers, and the assembly of records and views. No PDF, no Codex.

A prose block reports experiments in words: a paragraph of the main text, a reference note or an
endnote, a paragraph of the methods. Nothing is drawn in it: its compounds are numbers the paper
defines elsewhere, names, descriptions of a class, or a drawn compound changed in words; its
conditions are mostly a reference to another reaction ("standard conditions", "the model reaction
of Table 1") plus what was changed. Read like an equation block, with experiments in place of
equations (extract_equation, under the form PROSE): the compounds are listed once (boxed where the
paper draws that very compound, on any page), every experiment carries the fields of a template
(its runs that differ in a condition are variants), and turn 2 lists the reactions. What the
passage says that is no experiment of its own (other work, a restatement of an entry printed
elsewhere, an analytical measurement, a general procedure) is listed under `set_aside`; a passage
may report no experiment at all.

Stage 2 reads the outcomes of one reaction from the passage's results; where the passage states a
result only in words and the SI reports the measured value of that run, the value is the outcome,
with `stated_at`. It then looks the run up in the main text and the SI.

Stage 1, skill prose-entries, and stage 2, skill prose-reaction, answer with the schemas
prose_entries, prose_handles and prose_reaction.
"""

from __future__ import annotations

import re
from functools import partial
from types import SimpleNamespace

from . import extract_equation as eq
from .extract_ctable import entry_of
from .extract_records import _check_ref, _schema_errors, _squash, check_outcomes, merge_items

LAYOUT = "prose"
PROSE = eq.Form(entries="experiments", pointer="based_on", entry="experiment", source="passage", drawn_here=False,
                may_be_empty=True, runs_may_lack_results=True)
CHECK_TARGETS = {"steps", "based_on", "statement", "results", "default_yield_type", "general_reaction", "reading_guide"}
NUMBER = re.compile(r"\d\s*%")  # a result that prints a percentage

prepare = partial(eq.prepare, form=PROSE)
number_reactions = eq.number_reactions
base_row = eq.base_row


def template_of(inv: dict, reaction: dict) -> dict:
    """The template of one reaction's experiment, its reference under the name stage 1 gave it."""
    t = eq.compose(inv, entry_of(inv, reaction))
    t["based_on"] = t.pop("condition_pointer")
    return t


# ------------------------------------------------------------------ stage 1

def validate_table(data: dict, schema: dict, page_sizes: dict, n_est: int | None = None,
                   doc_pages: dict | None = None):
    """The reading of the passage: the equation checks under the form PROSE, plus every experiment
    quoted and every statement set aside quoted with its reason."""
    errors, warnings = _schema_errors(data, schema), []
    if errors:
        return errors, warnings
    errors, warnings = eq.validate_table(data, schema, page_sizes, n_est, doc_pages, form=PROSE)
    for i, ex in enumerate(data["experiments"]):
        if not ex["statement"].strip():
            errors.append(f"experiments[{i}]: quote the sentences that report the experiment (statement)")
        if not ex["descriptor"].strip():
            errors.append(f"experiments[{i}]: say in short what the experiment is (descriptor)")
    for c in data["compounds"]:
        for field in ("label", "text"):
            if c[field] is not None and not c[field].strip():
                errors.append(f"compound '{c['key']}': {field} is an empty string: give what the paper prints, or null")
    for i, s in enumerate(data["set_aside"]):
        if not s["text"].strip() or not s["reason"].strip():
            errors.append(f"set_aside[{i}]: quote the statement and say why it is no experiment of this passage")
    if not data["experiments"] and n_est:
        warnings.append(f"no experiments listed, but Step 1 estimated about {n_est} entries")
    return list(dict.fromkeys(errors)), warnings


validate_handles = partial(eq.validate_handles, form=PROSE)


# ------------------------------------------------------------------ stage 2

def _printed_in(value_text: str | None, result: str) -> bool:
    """Whether a value's text stands in a result as printed: whole, not as a part of a longer number
    ('4%' is not in '64%')."""
    if not (value_text or "").strip():
        return False
    pattern = r"\s*".join(re.escape(c) for c in re.sub(r"\s+", "", value_text))
    return re.search(rf"(?<![\w.]){pattern}(?![\w.])", result) is not None


def stage2_task(task: dict, inv: dict, handles: dict, reaction: dict) -> dict:
    """What the reaction's session gets beyond the driver's task: the experiment as quoted, with its
    results and reference, and the variable values with the participants that carry them."""
    en = entry_of(inv, reaction)
    return {"entry": {**{k: en[k] for k in ("eid", "label", "page", "bbox", "descriptor", "statement", "results",
                                            "footnote_markers")},
                      "based_on": en["condition_pointer"]},
            "reaction": {**task["reaction"], "variables": reaction["variables"]}}


def validate_reaction(answer: dict, schema: dict, inv: dict, reaction: dict, doc_pages: dict | None = None):
    """One reaction: every outcome belongs to one of the reaction's results and is measured on a
    product (or on a starting material recovered at the end); a value the passage does not print is
    the SI's measured value of the same run, with where it is stated."""
    errors, warnings = _schema_errors(answer, schema), []
    if errors:
        return errors, warnings
    errors, warnings, scope = eq.reaction_scope(answer, inv, reaction, doc_pages, CHECK_TARGETS, PROSE)
    mine = dict(zip(reaction["results"], reaction["results_text"]))  # the experiment's numbers of its results
    for i, o in enumerate(answer["outcomes"]):
        w = f"outcomes[{i}]"
        if not mine:
            errors.append(f"{w}: the passage states no result for this reaction; a value only the SI or another "
                          "passage gives goes into notes and related")
            continue
        if o["result"] not in mine:
            errors.append(f"{w}: result {o['result']} is not one of this reaction's results ({mine})")
        _check_ref(f"{w} stated_at", o["stated_at"], doc_pages, errors)
        text = mine.get(o["result"], "")
        if o["stated_at"] is not None:
            if NUMBER.search(text):
                warnings.append(f"{w}: result {o['result']} ('{text}') prints a value, which is the outcome; a value the "
                                "SI gives for it goes into notes, a different one into issues")
            if not (o["notes"] or "").strip():
                warnings.append(f"{w}: say in notes what the passage states for this result")
        elif o["yield_value"] is not None and text and not _printed_in(o["yield_text"], text):
            errors.append(f"{w}: result {o['result']} ('{text}') does not print '{o['yield_text']}': a value the SI or "
                          "another place of the paper gives needs stated_at, with the passage's words in notes; a value "
                          "the passage prints is copied as printed (yield_text)")
        eq.check_measured_on(o, w, scope, answer, errors, warnings, entry="experiment")
    plain = lambda o: {k: v for k, v in o.items() if k not in ("result", "stated_at")}
    printed = [i for i, o in enumerate(answer["outcomes"]) if o["stated_at"] is None]
    found = [i for i, o in enumerate(answer["outcomes"]) if o["stated_at"] is not None]
    # A value found in the SI is not part of the passage's wording: no check against the printed results.
    unprinted = {**scope.row, "results_text": []}
    for idx, row in ((printed, scope.row if printed or not found else unprinted), (found, unprinted)):
        check_outcomes([plain(answer["outcomes"][i]) for i in idx], scope.active, scope.t, row, errors, warnings, idx)
    read = {o["result"] for o in answer["outcomes"]}
    for r, text in mine.items():
        if r not in read:
            warnings.append(f"no outcome read from result {r} ('{text}')")
    return list(dict.fromkeys(errors)), warnings


# ------------------------------------------------------------------ record and view

entry_unit = partial(eq.entry_unit, form=PROSE)


def printed(inv: dict, entry: dict) -> str:
    """The experiment as the passage reports it, with its results and the reference it is based on."""
    lines = [entry["statement"]] + [f"result {i}: {r}" for i, r in enumerate(entry["results"], 1)]
    ptr = entry["condition_pointer"]
    if ptr is not None:
        lines.append(f"based on: {ptr['printed']} ({ptr['refers_to']})")
    return "\n".join(lines)


def synthesize(inv: dict, reaction: dict, answer: dict, template_crops: dict, cell_crops: dict,
               structure_crops: dict | None = None):
    """As for an equation; an outcome keeps where the paper states a value the passage does not print,
    and a run for which neither the passage nor what it refers to nor the run's report gives any
    condition says so."""
    unit, row, child, crops = eq.synthesize(inv, reaction, answer, template_crops, cell_crops, structure_crops,
                                            form=PROSE)
    t = eq.compose(inv, entry_of(inv, reaction))
    items, _ = merge_items(t, row["variant"], row["footnote_markers"], [], answer["lookup"])
    if t["condition_pointer"] is None and not any(i["group"] == "condition" and not i.get("removed")
                                                  for i in items.values()):
        child["issues"].append("the passage gives no conditions for this run, and none were found in the main text or "
                               "the SI")
    return unit, row, child, crops


def view_extra(inv: dict) -> dict:
    """What the viewer shows of the passage beyond its compounds: every experiment's own template,
    and what the passage says that is no experiment of its own."""
    return {"experiments": [{"eid": en["eid"], "label": eq.entry_label(inv, en, PROSE),
                             "template": template_of(inv, {"entry": n})}
                            for n, en in enumerate(inv["entries"], 1)],
            "set_aside": inv.get("set_aside", [])}


# What extract_ctable.assemble_view and the driver need from this layout.
OPS = SimpleNamespace(base_row=base_row, entry_unit=entry_unit, printed=printed, synthesize=synthesize,
                      template_of=template_of, view_extra=view_extra)
