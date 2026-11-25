"""Pure logic of the two equation skills (Step 2, block layout `equation`): the validators of the
three Codex answers, and the assembly of records and views. No PDF, no Codex.

An equation block draws whole reactions: every equation its own starting materials, arrows with the
conditions over and under them, products and results. Unlike a table, the equations share no
template. Stage 1 lists the compounds of the block once (a drawing that several equations use, such
as a starting material at the centre of a set of arrows, is one compound with one box) and gives
every equation the fields of a template (its participants with their roles, steps, conditions,
variants); turn 2 lists the reactions, one per experiment. Stage 2 reads the outcomes of one
reaction and looks its experiment up in the main text and the SI; it writes no changes of its own,
since stage 1 has written everything the equation prints.

The table driver (steps/s2_table.py) runs it like a table: `prepare` turns the answer of turn 1 into
the shape the driver works on (a block template whose participants are the compounds, for boxes,
crops and overlays; the equations as entries), and `template_of` builds the template of one
reaction's equation from the compounds and the equation's own fields, in the shape every merge and
record function takes.

Stage 1, skill equation-entries, and stage 2, skill equation-reaction, answer with the schemas
eqn_entries, eqn_handles and eqn_reaction.

Prose passages (extract_prose) are read the same way, with experiments in place of equations: a
`Form` says how a layout's answer names its entries and its reference, and what its messages call
an entry; `prepare` turns either answer into the same inventory shape, so everything after it is
shared.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from dataclasses import dataclass
from types import SimpleNamespace

from .extract_ctable import _participants, entry_of
from .extract_records import (_box_error, _check_ref, _check_structures, _open_decisions, _schema_errors, active_steps,
                              check_lookup, check_outcomes, merge_items, open_groups, protocol_groups, row_checks,
                              swapped, template_errors, template_groups)

LAYOUT = "equation"
CHECK_TARGETS = {"steps", "condition_pointer", "results", "default_yield_type", "general_reaction", "reading_guide"}


@dataclass(frozen=True)
class Form:
    """How the answer of turn 1 of a layout read with this logic is laid out and worded."""
    entries: str = "equations"           # the answer's list of entries
    pointer: str = "condition_pointer"   # an entry's reference to conditions given elsewhere
    entry: str = "equation"              # what messages call one entry
    source: str = "equation"             # what messages call what an entry prints
    drawn_here: bool = True              # a compound with a box is drawn in the block (and has no stated_at)
    may_be_empty: bool = False           # an answer without entries is valid when it says why (set_aside)
    runs_may_lack_results: bool = False  # one reaction of an entry may have no result while others have


EQUATION = Form()


# ------------------------------------------------------------------ the equations as a table

def prepare(data: dict, form: Form = EQUATION) -> dict:
    """Turn 1's answer, in place, in the shape the table driver works on: `template` holds what
    the block shares (its participants are the compounds, with their boxes), `entries` are the
    equations and `columns` is empty. The participants keep the role of their first equation;
    only `template_of` gives a compound its role in a reaction. Another `form` (prose) is brought
    into the same shape: its entries become `entries`, their reference `condition_pointer`."""
    roles: dict = {}
    for eq in data[form.entries]:
        for p in eq["participants"]:
            roles.setdefault(p["key"], p["role"])
    data["template"] = {
        "general_reaction": "; ".join(eq["general_reaction"] for eq in data[form.entries] if eq["general_reaction"].strip()),
        "reading_guide": data.pop("reading_guide"),
        "scheme": None,
        "participants": [{"key": c["key"], "role": roles.get(c["key"], "reactant"), "label": c["label"],
                          "text": c["text"], "amount": None, "generic": c["generic"], "isolated": None,
                          "page": c["page"], "bbox": c["bbox"], "alternatives": [], "stated_at": c["stated_at"]}
                         for c in data.pop("compounds")],
        "alternative_groups": [], "steps": [], "conditions": [],
        "structures": data.pop("structures"), "footnotes": data.pop("footnotes"), "preparations": [],
        "variable_defaults": [], "default_yield_type": None, "variants": [], "context": data.pop("context"),
    }
    data["columns"] = []
    data["entries"] = data.pop(form.entries)
    for eq in data["entries"]:
        eq["cells"] = []
        if form.pointer != "condition_pointer":
            eq["condition_pointer"] = eq.pop(form.pointer)
    data.setdefault("ignored", [])
    return data


def compose(inv: dict, entry: dict) -> dict:
    """The template of one equation, in the shape of any block template: the compounds it uses
    (with their boxes) in their roles here, its own steps, conditions and variants, the footnotes it
    prints, and what the block shares (structures, passages, reading guide)."""
    t = inv["template"]
    compounds = {p["key"]: p for p in t["participants"]}
    parts = []
    for p in entry["participants"]:
        c = compounds.get(p["key"], {})
        # Two sources: where the paper draws or names the compound, and where it states this equation's amount.
        parts.append({"key": p["key"], "role": p["role"], "label": c.get("label"), "text": c.get("text"),
                      "amount": p["amount"], "generic": bool(c.get("generic")), "isolated": p["isolated"],
                      "page": c.get("page"), "bbox": c.get("bbox"), "alternatives": p["alternatives"],
                      "stated_at": c.get("stated_at"), "amount_stated_at": p["stated_at"]})
    printed = set(entry["footnote_markers"])
    return {"general_reaction": entry["general_reaction"], "reading_guide": t["reading_guide"], "scheme": None,
            "participants": parts, "alternative_groups": entry["alternative_groups"], "steps": entry["steps"],
            "conditions": [{**c, "per_entry": False} for c in entry["conditions"]],
            "structures": t["structures"], "footnotes": [f for f in t["footnotes"] if f["marker"] in printed],
            "preparations": entry["preparations"], "variable_defaults": entry["variable_defaults"],
            "default_yield_type": entry["default_yield_type"], "variants": entry["variants"],
            "context": t["context"], "condition_pointer": entry["condition_pointer"]}


def template_of(inv: dict, reaction: dict) -> dict:
    return compose(inv, entry_of(inv, reaction))


# ------------------------------------------------------------------ stage 1, turn 1

def validate_table(data: dict, schema: dict, page_sizes: dict, n_est: int | None = None,
                   doc_pages: dict | None = None, form: Form = EQUATION):
    """The reading of the block: compounds listed once with their boxes, every equation a coherent
    template of its own (participants among the compounds, steps, conditions, variants, footnotes),
    a reference for the conditions resolved or said to lead nowhere."""
    errors, warnings = _schema_errors(data, schema), []
    if errors:
        return errors, warnings
    inv = prepare(copy.deepcopy(data), form)
    E, F = form.entry, form.entries  # 'equation', 'equations' in the messages
    t = inv["template"]
    compounds = {p["key"]: p for p in t["participants"]}
    keys = [p["key"] for p in t["participants"]]
    for k in sorted({k for k in keys if keys.count(k) > 1}):
        once = "one drawing is one compound, listed once" if form.drawn_here else "a compound is listed once"
        errors.append(f"compounds: key '{k}' is used more than once: {once} and used by every {E} it takes part in")
    # An intermediate of a sequence over one arrow may be neither drawn nor named.
    roles: dict = {}
    for eq in inv["entries"]:
        for p in eq["participants"]:
            roles.setdefault(p["key"], set()).add(p["role"])
    for p in t["participants"]:
        where = f"compound '{p['key']}'"
        if (p["page"] is None) != (p["bbox"] is None):
            errors.append(f"{where}: give both page and bbox, or neither")
        elif p["bbox"] is not None:
            err = _box_error(where, p["page"], p["bbox"], page_sizes)
            if err:
                errors.append(err)
        if p["bbox"] is None and not ((p["label"] or "").strip() or (p["text"] or "").strip()) \
                and roles.get(p["key"], set()) - {"intermediate"}:
            errors.append(f"{where}: a compound that is not drawn needs the number or the name printed for it")
        if form.drawn_here and p["bbox"] is not None and p["stated_at"] is not None:
            errors.append(f"{where}: the block draws it, so it has no stated_at: its name is looked up later for each "
                          "experiment; give it only the number and name the block prints")
        _check_ref(f"{where} stated_at", p["stated_at"], doc_pages, errors)
    skeys = _check_structures("block", t["structures"], page_sizes, errors)
    for k in sorted(skeys & set(keys)):
        errors.append(f"'{k}' is both a compound and a structure: a compound that reacts or forms is a compound; a "
                      "drawn catalyst, ligand or additive is a structure")
    for i, passage in enumerate(t["context"]):
        _check_ref(f"context[{i}]", passage, doc_pages, errors)
    markers = [f["marker"] for f in t["footnotes"]]
    for m in sorted({m for m in markers if markers.count(m) > 1}):
        errors.append(f"footnotes: marker '{m}' is listed more than once")

    used = {p["key"] for eq in inv["entries"] for p in eq["participants"]}
    leftover = ("a drawing that belongs to no reaction goes under ignored" if form.drawn_here else
                f"a compound that takes part in no {E} of this block is left out")
    for k in keys:
        if k not in used:
            errors.append(f"compound '{k}' takes part in no {E}: list it among the participants of every {E} "
                          f"it reacts or forms in; a drawn compound that does not react is a structure, and {leftover}")
    printed_anywhere = set()
    for i, eq in enumerate(inv["entries"]):
        name = f"{F}[{i}]"
        err = _box_error(f"{name} bbox", eq["page"], eq["bbox"], page_sizes)
        if err:
            errors.append(err)
        for p in eq["participants"]:
            if p["key"] not in compounds:
                errors.append(f"{name} participant '{p['key']}' is not one of the compounds ({sorted(compounds)})")
        for m in eq["footnote_markers"]:
            if m not in markers:
                errors.append(f"{name}: footnote marker '{m}' is not one of the footnotes ({sorted(markers)})")
        printed_anywhere.update(eq["footnote_markers"])
        for j, r in enumerate(eq["results"]):
            if not r.strip():
                errors.append(f"{name}.results[{j}] is empty")
        et = compose(inv, eq)
        # The compounds' own sources were checked once above; here the equation's sources of its amounts.
        own = {**et, "participants": [{**p, "stated_at": p["amount_stated_at"]} for p in et["participants"]]}
        errors += template_errors(own, page_sizes, doc_pages, name, boxes=False)
        ptr, P = eq["condition_pointer"], form.pointer
        if ptr is not None:
            _check_ref(f"{name} {P} stated_at", ptr["stated_at"], doc_pages, errors)
            if ptr["found"] and ptr["stated_at"] is None:
                errors.append(f"{name}: {P} has found true: say where the paper gives the conditions it "
                              "refers to (stated_at)")
            elif not ptr["found"] and ptr["stated_at"] is not None:
                errors.append(f"{name}: {P} has found false, so stated_at is null (when the paper gives "
                              "the conditions there, found is true)")
        if not any(p["role"] in ("product", "byproduct", "intermediate") for p in eq["participants"]):
            warnings.append(f"{name}: no product")
        errors += _emptied_steps(et, name)
        items, _ = merge_items(et, None, [], [])
        for group, _left in open_groups(et, items):
            errors.append(f"{name}: the alternatives {group} have no default: a reaction without a variant runs the "
                          f"{E} as it is, so give the group a `default` (with stated_at, or inferred and your "
                          "reasoning); a variant still picks its own member with `use`")
    for f in t["footnotes"]:
        if f["overrides"] and f["marker"] not in printed_anywhere:
            errors.append(f"footnote '{f['marker']}' has overrides, but no {E} prints its marker: " + (
                f"a footnote of the title or the caption concerns every {E}; write what it states into the {E}s and "
                "give it no overrides" if form.drawn_here else
                f"a note no {E} of the block prints changes none of them; give it no overrides"))
    for i, g in enumerate(inv["ignored"]):
        err = _box_error(f"ignored[{i}]", g["page"], g["bbox"], page_sizes)
        if err:
            errors.append(err)

    n = len(inv["entries"])
    if n == 0 and not (form.may_be_empty and inv.get("set_aside")):
        errors.append(f"no {E}s: list every {E} of the block" + (
            "; when it reports none of its own, say under set_aside what it says instead" if form.may_be_empty else ""))
    elif n_est and n > n_est + max(2, n_est):
        warnings.append(f"{n} {E}s listed, but Step 1 estimated about {n_est} entries")
    if not errors:
        for i, eq in enumerate(inv["entries"]):
            warnings += [f"{F}[{i}]: {w}" for w in _open_decisions(compose(inv, eq))]
    return list(dict.fromkeys(errors)), warnings


def _emptied_steps(t: dict, name: str) -> list[str]:
    """A variant or a footnote that removes every product of a step whose reactants stay: the step
    would drop out of the record (with what only it needs). A protocol that starts from an isolated
    intermediate removes the step's reactants as well, and that is fine."""
    errors = []
    layers = [(f"variant '{v['key']}'", v["key"], []) for v in t["variants"]]
    layers += [(f"footnote '{f['marker']}'", None, [f["marker"]]) for f in t["footnotes"] if f["overrides"]]
    for where, variant, markers in layers:
        items, _ = merge_items(t, variant, markers, [])
        gone = lambda k: bool(items.get(k, {}).get("removed"))
        for st in t["steps"]:
            if st["products"] and all(gone(k) for k in st["products"]) and not all(gone(k) for k in st["reactants"]):
                errors.append(f"{name} {where}: removes every product of step {st['n']} ({st['products']}) while its "
                              "reactants stay, so the step would drop out: replace the product with the one this "
                              "protocol gives (its name with stated_at, or a short description, inferred) instead of "
                              "removing it")
    return errors


# ------------------------------------------------------------------ stage 1, turn 2

def validate_handles(handles: dict, inv: dict, schema: dict, form: Form = EQUATION):
    """The reactions of the block: every printed result belongs to exactly one, every equation has
    at least one, and the reactions of one equation differ in their variant, footnotes or variable
    values."""
    errors, warnings = _schema_errors(handles, schema), []
    if errors:
        return errors, warnings
    E = form.entry
    entries = inv["entries"]
    used: dict = {}
    seen: dict = {}
    count: Counter = Counter()
    for i, h in enumerate(handles["reactions"], 1):
        if not 1 <= h["entry"] <= len(entries):
            errors.append(f"reactions[{i}]: there is no {E} {h['entry']} ({E}s are numbered 1..{len(entries)})")
            continue
        w = f"reactions[{i}] ({E} {h['entry']})"
        eq = entries[h["entry"] - 1]
        count[h["entry"]] += 1
        t = compose(inv, eq)
        for r in h["results"]:
            if 1 <= r <= len(eq["results"]):
                used.setdefault((h["entry"], r), []).append(i)
            else:
                errors.append(f"{w}: the {E} has no result {r} (its results are numbered 1..{len(eq['results'])})")
        if eq["results"] and not h["results"]:
            if form.runs_may_lack_results:
                warnings.append(f"{w}: no result: right only when the passage states none for this run")
            else:
                errors.append(f"{w}: give the numbers of its results in the {E}'s `results`")
        variants = {v["key"] for v in t["variants"]}
        if h["variant"] is not None and h["variant"] not in variants:
            errors.append(f"{w}: unknown variant '{h['variant']}' (the {E}'s variants: {sorted(variants)})")
        for m in h["footnote_markers"]:
            if m not in eq["footnote_markers"]:
                errors.append(f"{w}: footnote marker '{m}' is not printed in this {E} (its markers: "
                              f"{eq['footnote_markers']})")
        parts = {p["key"] for p in eq["participants"]}
        for v in h["variables"]:
            if not v["name"].strip() or not v["value"].strip():
                errors.append(f"{w}: a variable needs a name and a value")
            if not v["participant_keys"]:
                carries = "whose drawing carries it" if form.drawn_here else "that carry it"
                errors.append(f"{w}: variable {v['name']}: name the participants {carries}")
            for k in v["participant_keys"]:
                if k not in parts:
                    errors.append(f"{w}: variable {v['name']}: '{k}' is not a participant of the {E} ({sorted(parts)})")
        sig = json.dumps([h["entry"], h["variant"], sorted(h["footnote_markers"]),
                          sorted((v["name"], v["value"]) for v in h["variables"])])
        if sig in seen:
            errors.append(f"{w} and reactions[{seen[sig]}] run the same {E} with the same variant, footnotes and "
                          "variable values, so they are one reaction: give it one handle with all its results, or the "
                          "variant (or the variable values) that tells them apart")
        seen.setdefault(sig, i)
        if h["variant"] is None or h["variant"] in variants:
            items, _ = merge_items(t, h["variant"], [m for m in h["footnote_markers"] if m in eq["footnote_markers"]], [])
            for keys, left in open_groups(t, items):
                state = "none of them is left" if not left else f"{left} are all still in play"
                errors.append(f"{w}: {keys} are alternatives for one position, but {state}: the {E}'s default "
                              "or the variant has to choose")
            if t["steps"] and not active_steps(t, items):
                errors.append(f"{w}: under its variant and footnotes no step of the {E} is left (all reactants or "
                              "all products of every step are removed): a variant does not remove the only product of a "
                              "step; it replaces it with the name of the product this protocol gives, or a description")
    for n, eq in enumerate(entries, 1):
        if not count[n]:
            errors.append(f"{E} {n} ({eq['label'] or eq['descriptor'][:40]}) has no reaction: every {E} "
                          "reports at least one, also when it prints no result")
        for r, text in enumerate(eq["results"], 1):
            if (n, r) not in used:
                errors.append(f"{E} {n}: result {r} ('{text}') belongs to no reaction: every printed result is "
                              "the outcome of one reaction")
            elif len(used[(n, r)]) > 1:
                errors.append(f"{E} {n}: result {r} ('{text}') is given to reactions {used[(n, r)]}; a result "
                              "belongs to one reaction")
    for i, h in enumerate(handles["reactions"], 1):
        if 1 <= h["entry"] <= len(entries) and count[h["entry"]] > 1 and not (h["distinguishing"] or "").strip():
            warnings.append(f"reactions[{i}]: {E} {h['entry']} reports several reactions: say in distinguishing "
                            "what sets this one apart, as printed")
    return errors, warnings


def number_reactions(inv: dict, handles: dict) -> list[dict]:
    """The handles with what the pipeline adds: `eid`, `rid` (e002-1, e002-2 for an equation that
    reports two reactions) and `results_text` (the printed results each one has)."""
    out, count = [], Counter()
    for h in handles["reactions"]:
        en = inv["entries"][h["entry"] - 1]
        count[en["eid"]] += 1
        out.append({**h, "eid": en["eid"], "rid": f"{en['eid']}-{count[en['eid']]}",
                    "results_text": [en["results"][r - 1] for r in h["results"]]})
    return out


# ------------------------------------------------------------------ the reaction

def base_row(inv: dict, reaction: dict, overrides=()) -> dict:
    """The reaction in the shape of a row of the generic path: everything the equation prints is in
    its template, so the row only says which protocol, footnotes and variable values it runs."""
    return {"rid": reaction["rid"], "label": None, "results": list(range(1, len(reaction["results_text"]) + 1)),
            "results_text": reaction["results_text"], "variant": reaction["variant"],
            "footnote_markers": list(reaction["footnote_markers"]),
            "variables": [{"name": v["name"], "value": v["value"]} for v in reaction["variables"]],
            "drawn_structures": [], "overrides": list(overrides)}


def stage2_task(task: dict, inv: dict, handles: dict, reaction: dict) -> dict:
    """What the reaction's session gets beyond the driver's task: the equation with its printed
    results, and the variable values with the participants that carry them."""
    en = entry_of(inv, reaction)
    return {"entry": {k: en[k] for k in ("eid", "label", "page", "bbox", "descriptor", "results", "footnote_markers")},
            "reaction": {**task["reaction"], "variables": reaction["variables"]}}


def reaction_scope(answer: dict, inv: dict, reaction: dict, doc_pages: dict | None, targets: set,
                   form: Form = EQUATION):
    """What every stage 2 answer of a block of composed templates is checked for apart from its
    outcomes (the reaction's own checks, the targets of template_check, the lookup, the passages, the
    labels, alternatives left open), and what its outcomes are checked against.
    Returns (errors, warnings, scope) with scope: t, row, items, active, formed, products."""
    errors: list[str] = []
    t, row = compose(inv, entry_of(inv, reaction)), base_row(inv, reaction)
    e, warnings = row_checks(t, row, "reaction", doc_pages)
    errors += e
    known = (set(template_groups(t)) | {p["key"] for p in inv["template"]["participants"]}
             | {f["marker"] for f in t["footnotes"]} | {x["key"] for x in t["structures"]}
             | {v["key"] for v in t["variants"]} | targets)
    for x in answer["template_check"]:
        if x["target"] not in known:
            warnings.append(f"template_check: unknown target '{x['target']}'")
    check_lookup(answer["lookup"], protocol_groups(t, row["variant"], row["footnote_markers"]),
                 {x["key"] for x in t["structures"]}, t, errors, doc_pages)
    for i, passage in enumerate(answer["related"]):
        _check_ref(f"related[{i}]", passage, doc_pages, errors)

    items, problems = merge_items(t, row["variant"], row["footnote_markers"], [], answer["lookup"])
    warnings += [f"merge: {p}" for p in problems]
    steps = active_steps(t, items)
    active = [k for _, r, p in steps for k in r + p]
    formed = {k for _, _, p in steps for k in p}
    for i, x in enumerate(answer["labels"]):
        if x["key"] not in active:
            errors.append(f"labels[{i}]: '{x['key']}' is not a participant of this reaction ({active})")
        if x["stated_at"] is None:
            where = "passage" if form.drawn_here else "paper"
            errors.append(f"labels[{i}]: say where the {where} gives the number (stated_at)")
        _check_ref(f"labels[{i}] stated_at", x["stated_at"], doc_pages, errors)
    for keys, left in open_groups(t, items):
        state = "none of them is left" if not left else f"{left} are all still in play"
        errors.append(f"{keys} are alternatives for one position, but {state}")
    products = [k for k in active if k in formed and items[k]["role"] in ("product", "byproduct")]
    return errors, warnings, SimpleNamespace(t=t, row=row, items=items, active=active, formed=formed, products=products)


def check_measured_on(o: dict, w: str, scope, answer: dict, errors: list, warnings: list, entry: str = "equation") -> None:
    """The compound one outcome is measured on: a product of the reaction, a starting material
    recovered at the end (said so in notes), or an intermediate (a result of its own, which makes its
    steps separate entries)."""
    k = o["product_key"]
    if k is None:
        if o["yield_value"] is not None and len(scope.products) > 1:
            warnings.append(f"{w}: '{o['yield_text']}' has no product_key, but the reaction has several products "
                            f"{scope.products}")
    elif k not in scope.active:
        errors.append(f"{w}: product_key '{k}' is not a participant of this reaction ({scope.active})")
    elif k in scope.products:
        pass
    elif k not in scope.formed:
        if not (o["notes"] or "").strip():
            errors.append(f"{w}: '{k}' is a starting material of this reaction: a value measured on it is a "
                          "starting material recovered at the end, so say so in notes; a yield of a product has the "
                          "product's key")
    elif not any(x["target"] == "steps" for x in answer["template_check"]):
        # An intermediate: the value stays on it, and its steps should have been separate equations.
        warnings.append(f"{w}: '{k}' is an intermediate of this reaction; a result printed for it means it was "
                        f"isolated, which makes its steps separate {entry}s: say so in template_check (target "
                        "'steps')")


def validate_reaction(answer: dict, schema: dict, inv: dict, reaction: dict, doc_pages: dict | None = None):
    """One reaction: its outcomes are read from its own printed results and measured on its products
    (or on a starting material recovered at the end); its lookup says where the paper states it."""
    errors, warnings = _schema_errors(answer, schema), []
    if errors:
        return errors, warnings
    errors, warnings, scope = reaction_scope(answer, inv, reaction, doc_pages, CHECK_TARGETS)
    mine = dict(zip(reaction["results"], reaction["results_text"]))  # the equation's numbers of its results
    for i, o in enumerate(answer["outcomes"]):
        w = f"outcomes[{i}]"
        if not mine:
            errors.append(f"{w}: the equation prints no result for this reaction; a value only the text or the SI gives "
                          "goes into notes and related")
            continue
        if o["result"] not in mine:
            errors.append(f"{w}: result {o['result']} is not one of this reaction's results ({mine})")
        check_measured_on(o, w, scope, answer, errors, warnings)
    outcomes = [{k: v for k, v in o.items() if k != "result"} for o in answer["outcomes"]]
    check_outcomes(outcomes, scope.active, scope.t, scope.row, errors, warnings)
    read = {o["result"] for o in answer["outcomes"]}
    for r, text in mine.items():
        if r not in read:
            warnings.append(f"no outcome read from result {r} ('{text}')")
    return list(dict.fromkeys(errors)), warnings


# ------------------------------------------------------------------ record and view

def entry_label(inv: dict, entry: dict, form: Form = EQUATION) -> str:
    """What the records of an equation are called: the compound number of its first numbered
    product, else the label printed for the equation, else 'equation N'."""
    compounds = {p["key"]: p for p in inv["template"]["participants"]}
    for p in entry["participants"]:
        label = compounds.get(p["key"], {}).get("label")
        if p["role"] == "product" and label:
            return label
    return entry["label"] or f"{form.entry} {int(entry['eid'][1:])}"


def entry_unit(inv: dict, entry: dict, form: Form = EQUATION) -> dict:
    return {**{k: entry[k] for k in ("eid", "page", "bbox", "descriptor")}, "label": entry_label(inv, entry, form)}


def printed(inv: dict, entry: dict) -> str:
    """The equation in short, with its results and the reference its conditions are given by."""
    lines = [entry["descriptor"]] + [f"result {i}: {r}" for i, r in enumerate(entry["results"], 1)]
    ptr = entry["condition_pointer"]
    if ptr is not None:
        lines.append(f"conditions by reference: {ptr['printed']} ({ptr['refers_to']})")
    return "\n".join(lines)


def synthesize(inv: dict, reaction: dict, answer: dict, template_crops: dict, cell_crops: dict,
               structure_crops: dict | None = None, form: Form = EQUATION):
    """Stage 1 + stage 2 of one reaction as `build_record` takes them:
    (entry unit, row, the reaction session's result, crops by participant key)."""
    t, en = template_of(inv, reaction), entry_of(inv, reaction)
    row = base_row(inv, reaction)
    items, _ = merge_items(t, row["variant"], row["footnote_markers"], [], answer["lookup"])
    parts, crops = _participants({"template": t, "columns": []}, en, items, template_crops, cell_crops,
                                 structure_crops or {})
    carried: dict = {}
    for v in reaction["variables"]:
        for k in v["participant_keys"]:
            carried.setdefault(k, []).append({"name": v["name"], "value": v["value"]})
    tparts = {p["key"]: p for p in t["participants"]}
    # A product another compound took the place of (a protocol's own product) has lost the drawn one's number.
    labelled = {k for k, tp in tparts.items() if tp["label"] and not swapped(items.get(k), tp)}
    found = {x["key"]: x for x in answer["labels"]}
    for p in parts:
        p["variables"] = carried.get(p["key"], [])
        if p["key"] not in labelled and p["key"] in found:
            # A number the text or the SI gives it, where the equation prints none. The passage is the source of
            # the compound's name only when no other passage names it.
            p["label"] = found[p["key"]]["label"]
            if not items.get(p["key"], {}).get("stated_at"):
                p["stated_at"] = p["stated_at"] or found[p["key"]]["stated_at"]
    checks = [f"reading questioned for {x['target']}: it says {x['stage1']!r}, the page shows {x['seen']!r} "
              f"({x['evidence']})" for x in answer["template_check"]]
    ptr = en["condition_pointer"]
    if ptr is not None and not ptr["found"]:
        checks.append(f"the conditions are given by a reference the paper does not resolve: '{ptr['printed']}' "
                      f"({ptr['refers_to']}); only what the {form.source} prints is listed")
    child = {"participants": parts, "structures": [],
             "outcomes": [{k: v for k, v in o.items() if k != "result"} for o in answer["outcomes"]],
             "overrides": answer["lookup"], "related": answer["related"], "notes": answer["notes"],
             "issues": checks + answer["issues"]}
    # The records are called by this reaction's own first numbered product (not one its protocol replaced).
    label = None
    for _, _, products in active_steps(t, items):
        label = label or next((tparts[k]["label"] for k in products if k in labelled and items[k]["role"] == "product"),
                              None)
    row["label"] = label or en["label"] or f"{form.entry} {int(en['eid'][1:])}"
    return entry_unit(inv, en, form), row, child, crops


def view_extra(inv: dict) -> dict:
    """What the viewer shows of the block beyond its compounds: every equation's own template."""
    return {"equations": [{"eid": en["eid"], "label": entry_label(inv, en), "template": compose(inv, en)}
                          for en in inv["entries"]]}


# What extract_ctable.assemble_view and the driver need from this layout.
OPS = SimpleNamespace(base_row=base_row, entry_unit=entry_unit, printed=printed, synthesize=synthesize,
                      template_of=template_of, view_extra=view_extra)
