"""Pure helpers for Step 2: block selection, validation of the Codex outputs (inventory,
expansion of one entry, extraction of one reaction), condition merging and assembly of
the final reaction records.

Nothing here touches PDFs or Codex, so everything is unit-testable.
"""

from __future__ import annotations

import copy
import json
import re

from jsonschema import Draft202012Validator

from .schemas.build_extract import COND_ROLES, PART_ROLES

BBOX_FIELDS = ("bbox", "structure_bbox")
PAGE_TOLERANCE = 2.0  # pt a box may stick out of the page


# ------------------------------------------------------------------ selection

def safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")


def block_ref(region: dict, block: dict) -> str:
    return f"{region['region_id']}/{block['block_id']}"


def block_slug(region: dict, block: dict) -> str:
    return f"{safe(region['region_id'])}__{safe(block['block_id'])}"


def select_blocks(regions: dict, blocks=None, kinds=None) -> list[tuple[dict, dict]]:
    """Included blocks of included regions, optionally filtered by ref/region id and kind."""
    selected, known = [], set()
    for region in regions["regions"]:
        for block in region["blocks"]:
            if not (region["include"] and block["include"]):
                continue
            ref = block_ref(region, block)
            known.update((ref, region["region_id"]))
            if blocks and ref not in blocks and region["region_id"] not in blocks:
                continue
            if kinds and block["kind"] not in kinds:
                continue
            selected.append((region, block))
    unknown = [b for b in (blocks or ()) if b not in known]
    if unknown:
        raise ValueError(f"unknown blocks {unknown}; available: {sorted(k for k in known if '/' in k)}")
    return selected


def section_for(regions: dict, doc: str, page: int) -> str | None:
    """Title of the narrowest SI section containing `page` (None for the main text)."""
    if doc != "si":
        return None
    hits = [s for s in regions.get("si_sections", []) if s["first_page"] <= page <= s["last_page"]]
    return min(hits, key=lambda s: s["last_page"] - s["first_page"])["title"] if hits else None


# ----------------------------------------------------------------- validation

def full_schema(schema: dict) -> dict:
    """The strict Codex schema plus what it cannot express: boxes have exactly 4 numbers."""
    full = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, dict):
            for name, sub in node.get("properties", {}).items():
                if name in BBOX_FIELDS:
                    sub.update(minItems=4, maxItems=4)
            for sub in node.values():
                walk(sub)
        elif isinstance(node, list):
            for sub in node:
                walk(sub)

    walk(full)
    return full


def _schema_errors(data, schema) -> list[str]:
    return [f"schema at /{'/'.join(map(str, e.absolute_path))}: {e.message}"
            for e in Draft202012Validator(full_schema(schema)).iter_errors(data)]


def _box_error(where: str, page, bbox, page_sizes: dict) -> str | None:
    if page not in page_sizes:
        return f"{where}: page {page} is not a page of this document (1..{max(page_sizes)})"
    x0, y0, x1, y1 = bbox
    w, h = page_sizes[page]
    t = PAGE_TOLERANCE
    if not (x0 < x1 and y0 < y1):
        return f"{where}: bbox {bbox} needs x0<x1 and y0<y1"
    if x0 < -t or y0 < -t or x1 > w + t or y1 > h + t:
        return f"{where}: bbox {bbox} exceeds page size {w}x{h} pt"
    return None


def _check_step(where: str, step, errors: list) -> None:
    if step is not None and step < 1:
        errors.append(f"{where}: step must be 1 or greater (or null)")


def _check_alternatives(where: str, alternatives: list, structure_keys: set, errors: list) -> None:
    if len(alternatives) == 1:
        errors.append(f"{where}: alternatives needs at least two options (leave it empty for a definite item)")
    for a in alternatives:
        if not a["text"].strip():
            errors.append(f"{where}: an alternative has no text")
        if a["structure_key"] is not None and a["structure_key"] not in structure_keys:
            errors.append(f"{where}: alternative '{a['text']}' refers to unknown structure "
                          f"'{a['structure_key']}' (structures: {sorted(structure_keys)})")


def _check_ref(where: str, ref, doc_pages, errors: list) -> None:
    """A {doc, page} pointer into the paper (stated_at, or a quoted passage)."""
    if ref is None or doc_pages is None:
        return
    if ref["doc"] not in doc_pages:
        errors.append(f"{where}: this paper has no '{ref['doc']}' document")
    elif not 1 <= ref["page"] <= doc_pages[ref["doc"]]:
        errors.append(f"{where}: page {ref['page']} is not a page of '{ref['doc']}' (1..{doc_pages[ref['doc']]}; "
                      "use PDF page indices, not printed page labels)")


def _check_overrides(where: str, overrides: list, groups: dict, structure_keys: set,
                     errors: list, alt_keys=frozenset(), doc_pages=None) -> None:
    """`groups` maps every known key to 'participant' or 'condition'; `alt_keys` are the
    participants that belong to an alternative group."""
    for o in overrides:
        w = f"{where}: override {o['action']} '{o['key']}'"
        if o["structure_key"] is not None and o["structure_key"] not in structure_keys:
            errors.append(f"{w} refers to unknown structure '{o['structure_key']}' "
                          f"(structures: {sorted(structure_keys)})")
        _check_step(w, o["step"], errors)
        _check_alternatives(w, o["alternatives"], structure_keys, errors)
        _check_ref(f"{w} stated_at", o["stated_at"], doc_pages, errors)
        if o["inferred"] and o["stated_at"] is not None:
            errors.append(f"{w}: inferred=true and stated_at contradict each other (either the paper "
                          "states it there, or it is your conclusion)")
        if o["action"] == "use" and o["key"] in groups and o["key"] not in alt_keys:
            errors.append(f"{w}: 'use' picks one of the alternatives listed in template.alternative_groups "
                          f"({sorted(alt_keys)}); '{o['key']}' is not one of them")
        if o["action"] == "add":
            if o["role"] not in COND_ROLES:
                errors.append(f"{w} needs a condition role ({', '.join(COND_ROLES)}); compounds that "
                              "react or form belong in participants")
            if not (o["text"] or "").strip():
                errors.append(f"{w} needs text")
        elif o["key"] not in groups:
            errors.append(f"{w} targets an unknown key (known keys: {sorted(groups)})")
        else:
            allowed = PART_ROLES if groups[o["key"]] == "participant" else COND_ROLES
            if o["role"] is not None and o["role"] not in allowed:
                errors.append(f"{w}: role '{o['role']}' does not fit a {groups[o['key']]} "
                              f"({', '.join(allowed)})")
            if o["action"] == "replace" and not o["alternatives"] and all(
                    o[k] is None for k in ("text", "amount", "structure_key", "role", "step")):
                errors.append(f"{w} changes nothing")


def _check_structures(where: str, structures: list, page_sizes: dict, errors: list) -> set:
    keys = [x["key"] for x in structures]
    for k in sorted({k for k in keys if keys.count(k) > 1}):
        errors.append(f"{where}: structure key '{k}' is used more than once")
    for x in structures:
        err = _box_error(f"{where} structure '{x['key']}'", x["page"], x["bbox"], page_sizes)
        if err:
            errors.append(err)
    return set(keys)


def _check_steps(t: dict, name: str = "template") -> list[str]:
    """The template's steps must be a coherent picture of the reaction. `name`: how messages call
    the template."""
    errors = []
    parts = {p["key"]: p for p in t["participants"]}
    steps = t["steps"]
    if parts and not steps:
        return [f"{name}.steps is empty: describe the reaction as one or more steps "
                "(which participants react, which are formed)"]
    numbers = [st["n"] for st in steps]
    if sorted(numbers) != list(range(1, len(steps) + 1)):
        errors.append(f"{name}.steps: step numbers must be 1..{len(steps)} without gaps, got {numbers}")
    made, used = {}, {}
    for st in steps:
        for side, seen in (("reactants", used), ("products", made)):
            for key in st[side]:
                if key not in parts:
                    errors.append(f"{name}.steps[{st['n']}].{side}: '{key}' is not a participant key "
                                  f"({sorted(parts)})")
                seen.setdefault(key, []).append(st["n"])
    for key, p in parts.items():
        if key not in made and key not in used:
            errors.append(f"{name} participant '{key}' does not appear in any step")
        elif p["role"] == "intermediate" and not (key in made and key in used and min(made[key]) < max(used[key])):
            errors.append(f"{name} participant '{key}' has role intermediate, so it must be a product of one "
                          "step and a reactant of a later one (otherwise it is a reactant or a product)")
    return errors


def template_groups(template: dict) -> dict:
    groups = {p["key"]: "participant" for p in template["participants"]}
    groups.update({c["key"]: "condition" for c in template["conditions"]})
    return groups


def protocol_groups(template: dict, variant: str | None, markers) -> dict:
    """The keys one reaction's own changes can refer to: the template's, and the conditions its
    variant and footnotes add."""
    groups = template_groups(template)
    v = next((v for v in template["variants"] if v["key"] == variant), None)
    footnotes = {f["marker"]: f for f in template["footnotes"]}
    for layer in ([v["overrides"]] if v else []) + [footnotes[m]["overrides"] for m in markers if m in footnotes]:
        for o in layer:
            if o["action"] == "add":
                groups.setdefault(o["key"], "condition")
    return groups


def validate_inventory(inv: dict, schema: dict, page_sizes: dict, n_est: int | None = None,
                       doc_pages: dict | None = None, entries_required: bool = False):
    """`page_sizes`: pages of the block's own document; `doc_pages`: {doc: page count} of the paper.
    `entries_required`: a block that lists no entry is an error (a table or a scope figure always
    prints some), not a warning."""
    errors, warnings = _schema_errors(inv, schema), []
    if errors:
        return errors, warnings
    t = inv["template"]
    errors += template_errors(t, page_sizes, doc_pages)

    for i, r in enumerate(inv["entries"]):
        err = _box_error(f"entries[{i}] ({r['label'] or r['descriptor'][:30]})", r["page"], r["bbox"], page_sizes)
        if err:
            errors.append(err)
    for i, g in enumerate(inv["ignored"]):
        err = _box_error(f"ignored[{i}]", g["page"], g["bbox"], page_sizes)
        if err:
            errors.append(err)

    if not errors:
        warnings += _open_decisions(t)

    n = len(inv["entries"])
    if n == 0 and entries_required:
        errors.append("no entries listed: list every entry the block prints, each with its cells")
    elif n == 0:
        warnings.append("no entries listed for this block")
    elif n_est and abs(n - n_est) > max(2, 0.25 * n_est):
        warnings.append(f"{n} entries listed, but Step 1 estimated about {n_est}")
    return errors, warnings


def template_errors(t: dict, page_sizes: dict, doc_pages: dict | None = None, name: str = "template",
                    boxes: bool = True) -> list[str]:
    """What is wrong with one template on its own: keys, steps, boxes, alternative groups,
    conditions, footnotes, variants, defaults, preparations. `name`: how messages call it.
    `boxes`: also check the boxes of its participants, scheme and structures and its quoted
    passages (a layout whose templates share their compounds checks those once for the block)."""
    errors: list[str] = []
    pre = "" if name == "template" else f"{name}."  # for the parts messages name without the template
    keys = [p["key"] for p in t["participants"]] + [c["key"] for c in t["conditions"]]
    for k in sorted({k for k in keys if keys.count(k) > 1}):
        errors.append(f"{name}: key '{k}' is used more than once (participants and conditions share one key space)")
    groups = template_groups(t)

    errors += _check_steps(t, name)
    if boxes:
        for p in t["participants"]:
            where = f"{name} participant '{p['key']}'"
            if (p["page"] is None) != (p["bbox"] is None):
                errors.append(f"{where}: give both page and bbox, or neither")
            elif p["bbox"] is not None:
                err = _box_error(where, p["page"], p["bbox"], page_sizes)
                if err:
                    errors.append(err)
        if t["scheme"] is not None:
            err = _box_error(f"{name} scheme", t["scheme"]["page"], t["scheme"]["bbox"], page_sizes)
            if err:
                errors.append(err)
        skeys = _check_structures(name, t["structures"], page_sizes, errors)
    else:
        skeys = {x["key"] for x in t["structures"]}
    for p in t["participants"]:
        _check_alternatives(f"{name} participant '{p['key']}'", p["alternatives"], skeys, errors)
        _check_ref(f"{name} participant '{p['key']}' stated_at", p["stated_at"], doc_pages, errors)
    if boxes:
        for i, passage in enumerate(t["context"]):
            _check_ref(f"{name}.context[{i}]", passage, doc_pages, errors)

    alt_keys: set = set()
    for i, g in enumerate(t["alternative_groups"]):
        where = f"{pre}alternative_groups[{i}] {g['keys']}"
        if len(set(g["keys"])) < 2:
            errors.append(f"{where}: a group has at least two different participants")
        for key in g["keys"]:
            if groups.get(key) != "participant":
                errors.append(f"{where}: '{key}' is not a participant key")
            if key in alt_keys:
                errors.append(f"{where}: '{key}' is already in another group")
        alt_keys.update(g["keys"])
        if g["default"] is not None and g["default"] not in g["keys"]:
            errors.append(f"{where}: default '{g['default']}' is not one of the group")
        if g["inferred"] and g["stated_at"] is not None:
            errors.append(f"{where}: inferred=true and stated_at contradict each other")
        _check_ref(f"{where} stated_at", g["stated_at"], doc_pages, errors)

    for c in t["conditions"]:
        where = f"{name} condition '{c['key']}'"
        _check_ref(f"{where} stated_at", c["stated_at"], doc_pages, errors)
        if c["structure_key"] is not None and c["structure_key"] not in skeys:
            errors.append(f"{where}: unknown structure_key '{c['structure_key']}' (structures: {sorted(skeys)})")
        _check_step(where, c["step"], errors)
        if c["step"] is not None and c["step"] not in {st["n"] for st in t["steps"]}:
            errors.append(f"{where}: step {c['step']} is not one of {name}.steps")
        _check_alternatives(where, c["alternatives"], skeys, errors)

    markers = [f["marker"] for f in t["footnotes"]]
    for m in sorted({m for m in markers if markers.count(m) > 1}):
        errors.append(f"{name}: footnote marker '{m}' is listed more than once")
    for f in t["footnotes"]:
        _check_overrides(f"{pre}footnote '{f['marker']}'", f["overrides"], groups, skeys, errors, alt_keys, doc_pages)
    vkeys = [v["key"] for v in t["variants"]]
    for k in sorted({k for k in vkeys if vkeys.count(k) > 1}):
        errors.append(f"{name}: variant key '{k}' is used more than once")
    for v in t["variants"]:
        _check_overrides(f"{pre}variant '{v['key']}'", v["overrides"], groups, skeys, errors, alt_keys, doc_pages)
    for d in t["variable_defaults"]:
        if d["participant_key"] is not None and groups.get(d["participant_key"]) != "participant":
            errors.append(f"{pre}variable default '{d['name']}': unknown participant_key '{d['participant_key']}'")
    part_keys = sorted(k for k, g in groups.items() if g == "participant")
    for i, prep in enumerate(t["preparations"]):
        where = f"{pre}preparations[{i}] ('{prep['participant_key']}')"
        for key in [prep["participant_key"], *prep["from_participants"]]:
            if groups.get(key) != "participant":
                errors.append(f"{where}: '{key}' is not a participant key ({part_keys})")
        if prep["participant_key"] in prep["from_participants"]:
            errors.append(f"{where}: a compound is not made from itself")
        if not prep["from_participants"] and not prep["items"]:
            errors.append(f"{where}: says nothing about the preparation (no from_participants, no items)")
        for item in prep["items"]:
            if item["structure_key"] is not None and item["structure_key"] not in skeys:
                errors.append(f"{where}: item refers to unknown structure '{item['structure_key']}' "
                              f"(structures: {sorted(skeys)})")
            if not (item["text"] or "").strip() and item["structure_key"] is None:
                errors.append(f"{where}: an item needs its printed text or the structure_key of its drawing")
    return errors


def _open_decisions(t: dict) -> list[str]:
    """"A or B" positions that a protocol leaves open: every row under it will have to choose."""
    notes = []
    protocols = [(v["key"], f"variant '{v['key']}'") for v in t["variants"]] or [(None, "the template")]
    for key, name in protocols:
        items, _ = merge_items(t, key, [], [])
        for keys, left in open_groups(t, items):
            notes.append(f"{name} leaves the alternatives {keys} open: every reaction under it has to pick one "
                         "with a `use` override")
    return notes


def _signature(row: dict) -> str:
    """What sets a reaction apart from the others of its entry (its results do not)."""
    overrides = sorted(json.dumps({k: o[k] for k in ("key", "action", "role", "text", "amount", "structure_key",
                                                      "step", "alternatives")}, sort_keys=True)
                       for o in row["overrides"])
    variables = sorted((v["name"], v["value"]) for v in row["variables"])
    return json.dumps([row["label"], row["variant"], sorted(row["footnote_markers"]), overrides, variables])


def validate_expansion(exp: dict, schema: dict, template: dict, doc_pages: dict | None = None):
    """One entry spelled out as reactions (rows): every printed result belongs to exactly one
    row, and every row settles what the template leaves open."""
    errors, warnings = _schema_errors(exp, schema), []
    if errors:
        return errors, warnings
    results = exp["results"]

    if not exp["rows"]:
        warnings.append("no reaction in this entry")
    used: dict = {}
    seen: dict = {}
    for i, row in enumerate(exp["rows"], 1):
        where = f"rows[{i}]" + (f" ({row['label']})" if row["label"] else "")
        for r in row["results"]:
            if 1 <= r <= len(results):
                used.setdefault(r, []).append(i)
            else:
                errors.append(f"{where}: there is no result {r} (results are numbered 1..{len(results)})")
        if results and not row["results"]:
            errors.append(f"{where}: give the numbers of its results in `results`")
        e, w = row_checks(template, row, where, doc_pages)
        errors += e
        warnings += w
        sig = _signature(row)
        if sig in seen:
            errors.append(f"{where} and rows[{seen[sig]}] have the same label, protocol, footnotes, changes and "
                          "variables, so they are one reaction: give it one row with all its results, or state "
                          "what differs between them")
        seen.setdefault(sig, i)
    for r, text in enumerate(results, 1):
        if r not in used:
            errors.append(f"result {r} ('{text}') belongs to no row: every printed result is the outcome of one reaction")
        elif len(used[r]) > 1:
            errors.append(f"result {r} ('{text}') is given to rows {used[r]}; a result belongs to one reaction")
    if not errors:
        for i, row in enumerate(exp["rows"], 1):
            e, w = _check_row(template, row, f"rows[{i}]" + (f" ({row['label']})" if row["label"] else ""))
            errors += e
            warnings += w
    return errors, warnings


def row_checks(template: dict, row: dict, where: str, doc_pages: dict | None = None):
    """What one reaction (a row: variant, footnote markers, variables, drawn structures and the
    printed changes as overrides) refers to exists in the template. Returns (errors, warnings)."""
    errors, warnings = [], []
    variants = {v["key"] for v in template["variants"]}
    footnotes = {f["marker"] for f in template["footnotes"]}
    tskeys = {x["key"] for x in template["structures"]}
    alt_keys = {k for g in alternative_groups(template) for k in g}
    if row["variant"] is not None and row["variant"] not in variants:
        errors.append(f"{where}: unknown variant '{row['variant']}' (template variants: {sorted(variants)})")
    for m in row["footnote_markers"]:
        if m not in footnotes:
            errors.append(f"{where}: footnote marker '{m}' is not defined in the template (markers: {sorted(footnotes)})")
    dkeys = [x["key"] for x in row["drawn_structures"]]
    for k in sorted({k for k in dkeys if dkeys.count(k) > 1 or k in tskeys}):
        errors.append(f"{where}: drawn structure key '{k}' is used twice or is already a template structure")
    _check_overrides(where, row["overrides"], protocol_groups(template, row["variant"], row["footnote_markers"]),
                     tskeys | set(dkeys), errors, alt_keys,
                     doc_pages)
    for k in sorted(set(dkeys) - {o["structure_key"] for o in row["overrides"]}):
        warnings.append(f"{where}: drawn structure '{k}' is not used by any override")
    for v in row["variables"]:
        if not v["name"].strip() or not v["value"].strip():
            errors.append(f"{where}: a variable needs a name and a value")
    return errors, warnings


def _check_row(template: dict, row: dict, where: str):
    """After template, variant, footnotes and the row's own changes, one participant is left of
    every "A or B" position and every per-entry condition has this row's value."""
    items, problems = merge_items(template, row["variant"], row["footnote_markers"], row["overrides"])
    errors = []
    for keys, left in open_groups(template, items):
        state = "none of them is left" if not left else f"{left} are all still in play"
        errors.append(f"{where}: {keys} are alternatives for one position, but {state}; add a `use` override "
                      "for the one this reaction uses (with stated_at when the paper says which, or "
                      "inferred=true and your reasoning when it does not)")
    for item in items.values():
        if item.get("per_entry") and not item.get("removed") and not item.get("not_given"):
            errors.append(f"{where}: condition '{item['key']}' ('{item['text']}') is given entry by entry: state this "
                          "reaction's value with a replace (the printed text), or remove it if the entry has none")
    return errors, [f"{where}: {p}" for p in problems]


def validate_entry(entry: dict, schema: dict, template: dict, row: dict, page_sizes: dict,
                   doc_pages: dict | None = None):
    """One reaction (`row` of an expanded entry) with its boxes, outcomes and what the text and the SI add."""
    errors, warnings = _schema_errors(entry, schema), []
    if errors:
        return errors, warnings

    tparts = {p["key"]: p for p in template["participants"]}
    keys = [p["key"] for p in entry["participants"]]
    for k in sorted({k for k in keys if keys.count(k) > 1}):
        errors.append(f"participant key '{k}' is used more than once")
    if not entry["participants"]:
        errors.append("no participants: list every reactant and product of this reaction")
    for p in entry["participants"]:
        where = f"participant '{p['key']}'"
        tp = tparts.get(p["key"])
        if p["source"] == "drawn":
            if p["page"] is None or p["bbox"] is None:
                errors.append(f"{where}: source=drawn needs page and bbox of the structure")
            else:
                err = _box_error(where, p["page"], p["bbox"], page_sizes)
                if err:
                    errors.append(err)
        elif p["source"] == "derived":
            if tp is None:
                errors.append(f"{where}: source=derived must use the key of a template participant "
                              f"({sorted(tparts)})")
            if not (p["basis"] or "").strip():
                errors.append(f"{where}: source=derived needs a basis")
        elif not ((p["text"] or "").strip() or (p["label"] or "").strip()):
            errors.append(f"{where}: source=text needs text or a label")
        _check_ref(f"{where} stated_at", p["stated_at"], doc_pages, errors)
    for i, passage in enumerate(entry["related"]):
        _check_ref(f"related[{i}]", passage, doc_pages, errors)

    # Variables: the row says which are printed for this reaction, the entry where they sit.
    printed = {(v["name"], v["value"]) for v in row["variables"]}
    placed = {(v["name"], v["value"]) for p in entry["participants"] for v in p["variables"]}
    for name, value in sorted(placed - printed):
        errors.append(f"variable {name} = {value} is not one of this reaction's variables {sorted(printed)}; "
                      "a variable printed for it that the reaction misses goes under issues")
    for name, value in sorted(printed - placed):
        errors.append(f"variable {name} = {value} of this reaction is on no participant: attach it to every "
                      "participant whose drawing carries that symbol")

    declared = {x["key"] for x in row["drawn_structures"]}
    skeys = _check_structures("entry", entry["structures"], page_sizes, errors)
    for k in sorted(skeys - declared):
        errors.append(f"structure '{k}' is not one of reaction.drawn_structures {sorted(declared)}; a drawn compound "
                      "the reaction does not mention goes under issues")
    for k in sorted(declared - skeys):
        errors.append(f"reaction.drawn_structures lists '{k}': give its box under structures")
    skeys = declared | {x["key"] for x in template["structures"]}

    groups = {**protocol_groups(template, row["variant"], row["footnote_markers"]), **{k: "participant" for k in keys}}
    check_lookup(entry["overrides"], groups, skeys, template, errors, doc_pages)
    check_outcomes(entry["outcomes"], keys, template, row, errors, warnings)
    if not errors:
        errors += _check_completeness(entry, template, row)
    return errors, warnings


def check_lookup(overrides: list, groups: dict, structure_keys: set, template: dict, errors: list,
                 doc_pages: dict | None = None) -> None:
    """Overrides found in the main text or the SI: each states where (stated_at) or is a conclusion."""
    alt_keys = {k for g in alternative_groups(template) for k in g}
    _check_overrides("lookup", overrides, groups, structure_keys, errors, alt_keys, doc_pages)
    for o in overrides:
        if o["stated_at"] is None and not o["inferred"]:
            errors.append(f"lookup: override {o['action']} '{o['key']}' has neither stated_at nor inferred. Your "
                          "overrides record what the main text or the SI states (stated_at) or what you conclude "
                          "(inferred); what the entry prints was settled with the reaction. Put a disagreement "
                          "with it under issues")


def check_outcomes(outcomes: list, keys: list, template: dict, row: dict, errors: list, warnings: list,
                   indices: list | None = None) -> None:
    """The measured values of one reaction: known markers, a product of this reaction, a sane value,
    and printed among the reaction's own results (`row["results_text"]`). `indices`: the positions of
    `outcomes` in the answer, when they are a part of its outcomes."""
    footnotes = {f["marker"] for f in template["footnotes"]}
    texts = [_squash(t) for t in row.get("results_text", [])]
    for i, o in enumerate(outcomes):
        where = f"outcomes[{indices[i] if indices else i}]"
        for m in o["footnote_markers"]:
            if m not in footnotes:
                errors.append(f"{where}: footnote marker '{m}' is not defined in the template (markers: {sorted(footnotes)})")
            elif m not in row["footnote_markers"]:
                warnings.append(f"{where}: footnote marker '{m}' is not one of the reaction's markers {row['footnote_markers']}")
        if o["product_key"] is not None and o["product_key"] not in keys:
            errors.append(f"{where}: product_key '{o['product_key']}' is not one of the participants {keys}")
        v = o["yield_value"]
        if v is not None and not 0 <= v <= 100:
            errors.append(f"{where}: yield_value {v} is outside 0..100")
        if v is None and o["yield_qualifier"] is None and not (o["yield_text"] or o["notes"] or o["selectivity"]):
            errors.append(f"{where}: empty outcome")
        if o["yield_text"] and texts and not any(_squash(o["yield_text"]) in t for t in texts):
            warnings.append(f"{where}: '{o['yield_text']}' is not part of this reaction's results {row.get('results_text')}")
    if not outcomes and row.get("results_text"):
        warnings.append("no outcome reported")


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _check_completeness(entry: dict, template: dict, row: dict) -> list[str]:
    """Each template participant that takes part in this reaction is listed, and each condition the
    block gives entry by entry has a value."""
    listed = {p["key"] for p in entry["participants"]}
    items, _ = merge_items(template, row["variant"], row["footnote_markers"], row["overrides"], entry["overrides"])
    errors = []
    for _, reactants, products in active_steps(template, items):
        for key in reactants + products:
            if key not in listed:
                errors.append(f"template participant '{key}' takes part in this reaction but is not listed under "
                              "participants: list it (drawn, text or derived as it applies)")
    for item in items.values():
        if item.get("per_entry") and not item.get("removed") and not item.get("not_given"):
            errors.append(f"condition '{item['key']}' ('{item['text']}') has no value for this reaction")
    return errors


# -------------------------------------------------------------------- merging

def _base_items(template: dict) -> dict:
    """The template as items. `stated_at` is where the paper states the item (its name);
    `amount_stated_at` where it states the amount (a participant's own `amount_stated_at` when the
    template gives one, else its `stated_at`), which a later layer may change on its own."""
    items = {}
    for p in template["participants"]:
        items[p["key"]] = {"key": p["key"], "group": "participant", "role": p["role"], "text": p["text"],
                           "amount": p["amount"], "structure_key": None, "step": None,
                           "alternatives": p.get("alternatives", []), "stated_at": p.get("stated_at"),
                           # A template may say apart where the amount is stated (an equation's participant).
                           "amount_stated_at": p.get("amount_stated_at", p.get("stated_at")) if p["amount"] is not None else None,
                           "origin": "base", "amount_origin": "base"}
    for c in template["conditions"]:
        items[c["key"]] = {"key": c["key"], "group": "condition", "role": c["role"], "text": c["text"],
                           "amount": c["amount"], "structure_key": c["structure_key"], "step": c["step"],
                           "alternatives": c["alternatives"], "stated_at": c.get("stated_at"),
                           "amount_stated_at": c.get("stated_at") if c["amount"] is not None else None,
                           "origin": "base"}
        if c.get("per_entry"):
            items[c["key"]]["per_entry"] = True  # a placeholder until an entry states its value
    return items


def swapped(item: dict | None, tp: dict | None) -> bool:
    """A variant, footnote or the reaction's own entry put another compound in the place of the
    template participant `tp`: the template's label and drawing name the compound it replaced.
    A name found in the text or the SI identifies the compound; it does not swap it."""
    if item is None or tp is None or not item.get("swap_origin"):
        return False
    return item["text"] != tp["text"] or item.get("structure_key") is not None


def alternative_groups(template: dict) -> list[list[str]]:
    return [g["keys"] for g in template.get("alternative_groups", [])]


def _choose(items: dict, group: list, key: str, origin: str, basis: str, stated_at, inferred: bool) -> None:
    """Of the alternatives the source offers for one position, `key` applies; the others drop out."""
    for k in group:
        if k not in items:
            continue
        item = dict(items[k])
        if k == key:
            item.pop("removed", None)
            item["choice"] = {"origin": origin, "basis": basis, "stated_at": stated_at, "inferred": inferred}
            if not inferred and item.get("inferred", {}).get("action") == "use":
                del item["inferred"]  # an earlier guess, now stated
        else:
            item.update(removed=True, origin=origin)
            item.pop("choice", None)
            item.pop("inferred", None)
        items[k] = item


def _change(items: dict, o: dict, origin: str, problems: list) -> None:
    """Apply the non-null fields of a replace (or of a `use` that also changes something)."""
    key = o["key"]
    if not o["alternatives"] and all(o[k] is None for k in ("text", "amount", "structure_key", "role", "step")):
        return
    if items[key].get("not_given") and o["text"] is None:
        problems.append(f"{origin}: changes '{key}', but the paper does not give the conditions of this protocol")
        return
    item = dict(items[key])
    item.pop("not_given", None)
    if o["text"] is not None or o["alternatives"]:
        item.pop("per_entry", None)
    if o["text"] is not None:
        # Another compound: its drawing and alternatives are whatever the override names. A name
        # found in the text or the SI identifies what the block shows: it keeps the drawing.
        item["text"] = o["text"]
        if origin != "lookup" or o["structure_key"] is not None:
            item["structure_key"] = o["structure_key"]
        item["alternatives"] = o["alternatives"]
        item["stated_at"] = o.get("stated_at")
        if not o.get("inferred"):
            item.pop("inferred", None)
    else:
        if o["structure_key"] is not None:
            item["structure_key"] = o["structure_key"]
        if o["alternatives"]:
            item["alternatives"] = o["alternatives"]
    if origin != "lookup" and (o["text"] is not None or o["structure_key"] is not None):
        item["swap_origin"] = origin  # see swapped()
    if o["amount"] is not None:
        item["amount"] = o["amount"]
        item["amount_stated_at"] = o.get("stated_at")
        item["amount_origin"] = origin  # the layer that set the amount, which may differ from the name's
    if o["step"] is not None:
        item["step"] = o["step"]
    if o["role"] is not None:
        item["role"] = o["role"]
        item["role_origin"] = origin
    item["origin"] = origin
    items[key] = item


def _apply(items: dict, overrides: list, origin: str, problems: list, groups=()) -> None:
    for o in overrides:
        key, action = o["key"], o["action"]
        # A change the paper does not state stays marked as such on whatever it touches.
        inferred = {"origin": origin, "action": action, "basis": o["basis"]} if o.get("inferred") else None
        if action == "add":
            items[key] = {"key": key, "group": "condition", "role": o["role"] or "other",
                          "text": o["text"] or "", "amount": o["amount"],
                          "structure_key": o["structure_key"], "step": o["step"],
                          "alternatives": o["alternatives"], "stated_at": o.get("stated_at"),
                          "amount_stated_at": o.get("stated_at") if o["amount"] is not None else None,
                          "origin": origin}
        elif key not in items:
            problems.append(f"{origin}: override targets unknown key '{key}'")
            continue
        elif action == "remove":
            items[key] = {**items[key], "removed": True, "origin": origin}
        elif action == "use":
            group = next((g for g in groups if key in g), None)
            if group is None:
                problems.append(f"{origin}: 'use {key}', but '{key}' is not one of the alternatives of a group")
                continue
            _choose(items, group, key, origin, o["basis"], o.get("stated_at"), inferred is not None)
            _change(items, o, origin, problems)
        elif items[key].get("removed"):
            # Removed by an earlier layer (e.g. the variant): a later amount change, such as a
            # scale footnote that names every compound, must not bring it back. A change the
            # reaction's own entry prints for it is worth a look, though.
            if origin == "entry":
                problems.append(f"entry: {action} '{key}' has no effect: '{key}' was removed by "
                                f"{items[key].get('origin')}")
            continue
        else:
            _change(items, o, origin, problems)
        if inferred:
            items[key]["inferred"] = inferred


def merge_items(template: dict, variant: str | None, markers: list[str], entry_overrides: list,
                lookup_overrides=()):
    """Base conditions -> variant -> footnotes (in marker order) -> what the entry prints for this
    reaction ("entry") -> what the main text or the SI states about it ("lookup").

    Returns ({key: item}, problems); every item records the last layer that set it in `origin`.
    A variant whose conditions the paper does not give starts from nothing: its conditions
    are `not_given` and its participants have no amount until a later layer states one."""
    items, problems = _base_items(template), []
    groups = alternative_groups(template)
    for g in template.get("alternative_groups", []):
        if g["default"] in items:
            _choose(items, g["keys"], g["default"], "base", g["basis"], g.get("stated_at"), bool(g.get("inferred")))
            if g.get("inferred"):
                items[g["default"]]["inferred"] = {"origin": "base", "action": "use", "basis": g["basis"]}
    if variant is not None:
        v = next((v for v in template["variants"] if v["key"] == variant), None)
        if v is None:
            problems.append(f"unknown variant '{variant}'")
        else:
            if not v.get("conditions_given", True):
                for item in items.values():
                    if item["group"] == "condition":
                        item["not_given"] = True
                    else:
                        item["amount"] = None
            _apply(items, v["overrides"], f"variant:{variant}", problems, groups)
    footnotes = {f["marker"]: f for f in template["footnotes"]}
    for m in markers:
        if m in footnotes:
            _apply(items, footnotes[m]["overrides"], f"footnote:{m}", problems, groups)
        else:
            problems.append(f"footnote marker '{m}' is not defined in the template")
    _apply(items, entry_overrides, "entry", problems, groups)
    _apply(items, list(lookup_overrides), "lookup", problems, groups)
    return items, problems


def active_steps(template: dict, items: dict) -> list[tuple[dict, list, list]]:
    """The template steps that take place under the merged items: (step, reactant keys, product keys).

    A step drops out when all of its reactants or all of its products were removed: the activation
    step of a protocol that starts from the isolated intermediate, or the step that would have
    made an alternative this reaction does not use."""
    gone = lambda k: bool(items.get(k, {}).get("removed"))
    steps = []
    for st in sorted(template["steps"], key=lambda st: st["n"]):
        reactants = [k for k in st["reactants"] if not gone(k)]
        products = [k for k in st["products"] if not gone(k)]
        if (st["reactants"] and not reactants) or (st["products"] and not products):
            continue
        steps.append((st, reactants, products))
    return steps


def open_groups(template: dict, items: dict) -> list[tuple[list, list]]:
    """Alternative groups of which not exactly one participant is left: (group keys, keys left)."""
    left = [[k for k in keys if k in items and not items[k].get("removed")] for keys in alternative_groups(template)]
    return [(keys, rest) for keys, rest in zip(alternative_groups(template), left) if len(rest) != 1]


def _unique(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def resolve_protocol(template: dict, reaction: dict, view: bool = False) -> dict:
    """The template as it applies to one reaction (variant, footnotes and the row's changes merged):
    its steps with their participants, and its conditions with where each comes from. `view`: also
    where each participant's amount comes from (for the viewer; tasks keep their shape, and hash)."""
    items, problems = merge_items(template, reaction["variant"], reaction["footnote_markers"], reaction["overrides"])
    tparts = {p["key"]: p for p in template["participants"]}

    def part(key):
        tp, item = tparts[key], items[key]
        gone = swapped(item, tp)  # another compound in its place: the template's label and drawing do not apply
        return {"key": key, "role": item["role"], "label": None if gone else tp["label"], "text": item["text"],
                "amount": item["amount"], "generic": tp["generic"],
                "drawn_at": {"page": tp["page"], "bbox": tp["bbox"]} if tp["bbox"] and not gone else None,
                "origin": item["origin"],
                **({"amount_origin": item.get("amount_origin", item["origin"])} if view else {})}

    steps = [{"n": st["n"], "description": st["description"], "reactants": [part(k) for k in reactants],
              "products": [part(k) for k in products]} for st, reactants, products in active_steps(template, items)]
    kept = {st["n"] for st in steps}
    conditions, removed = [], []
    for item in items.values():
        if item["group"] != "condition":
            continue
        if item.get("removed") or (item["step"] is not None and len(template["steps"]) > 1 and item["step"] not in kept):
            removed.append(item["key"])  # dropped, or belongs to a step that does not take place
        elif not item.get("not_given"):
            conditions.append({k: item.get(k) for k in ("key", "role", "text", "amount", "step", "structure_key",
                                                        "alternatives", "origin", "stated_at", "amount_stated_at",
                                                        "inferred")})
    return {"steps": steps, "conditions": conditions, "removed": removed, "problems": problems,
            "removed_participants": [k for k, item in items.items() if item["group"] == "participant" and item.get("removed")]}


def build_record(ctx: dict, template: dict, entry_unit: dict, reaction: dict, entry: dict) -> dict:
    """The record of one reaction: one row of an expanded entry, with what its own session found.

    ctx: {region, block, section, entry_crop, crops: {participant key | 's:<structure key>': path},
          template_crops: {participant key: path}, structure_crops: {structure key: path}}.
    reaction: the row plus `rid` and `results_text`; entry_unit: the printed entry it comes from
    (eid, label, page, bbox, descriptor)."""
    region, block = ctx["region"], ctx["block"]
    tparts = {p["key"]: p for p in template["participants"]}
    in_template_steps = {k for st in template["steps"] for k in st["reactants"] + st["products"]}
    footnote_text = {f["marker"]: f["text"] for f in template["footnotes"]}
    # Drawn catalysts/ligands/...: the template's, plus those drawn only in this entry.
    structures = {x["key"]: {**x, "crop": ctx.get("structure_crops", {}).get(x["key"])}
                  for x in template["structures"]}
    for x in reaction["drawn_structures"]:
        structures[x["key"]] = {**x, "page": None, "bbox": None, "crop": None}
    for x in entry["structures"]:
        structures[x["key"]] = {**structures.get(x["key"], {}), **x, "crop": ctx["crops"].get(f"s:{x['key']}")}
    variants = {v["key"]: v for v in template["variants"]}
    preparations = {p["participant_key"]: p for p in template.get("preparations", [])}
    options = lambda alternatives: [{"text": a["text"], "structure": structures.get(a["structure_key"])}
                                    for a in alternatives]

    variant = reaction["variant"]
    markers = list(reaction["footnote_markers"])
    items, problems = merge_items(template, variant, markers, reaction["overrides"], entry["overrides"])

    # Participants: a variant or footnote may drop one or change its role.
    parts = []
    for p in entry["participants"]:
        item = items.get(p["key"])
        if item is not None and item.get("removed"):
            continue
        role = item["role"] if item is not None and "role_origin" in item else p["role"]
        parts.append((p, item, role))
    product_keys = [p["key"] for p, _, role in parts if role == "product"]

    by_product, other = {}, []
    roles_by_key = {p["key"]: role for p, _, role in parts}
    for o in entry["outcomes"]:
        out = {"yield": {"text": o["yield_text"], "value": o["yield_value"],
                         "qualifier": o["yield_qualifier"],
                         "type": o["yield_type"] or template["default_yield_type"],
                         "type_origin": "stated" if o["yield_type"] else "default"},
               "selectivity": o["selectivity"], "footnote_markers": o["footnote_markers"],
               "notes": o["notes"],
               # Where the paper states a value the block prints only in words (a prose passage); else null.
               "stated_at": o.get("stated_at")}
        target = o.get("measure_target")
        if target is not None and roles_by_key.get(target) == "reactant":
            # A value printed for a starting material (recovered starting material, remaining 1):
            # not a product yield, and not read as one.
            out.update(participant_key=target, measurement_kind="recovered_starting_material")
            other.append(out)
            continue
        key = o["product_key"]
        if key is None and len(product_keys) == 1 and o["yield_type"] != "conversion":
            key = product_keys[0]
        if key is None:
            other.append(out)
        else:
            by_product.setdefault(key, []).append(out)

    recs, unresolved = {}, []
    for p, item, role in parts:
        tp = tparts.get(p["key"])
        amount, amount_origin = p["amount"], "entry"
        if amount is None and item is not None:
            amount, amount_origin = item["amount"], item.get("amount_origin", item["origin"])
        variables = [{**v, "origin": "stated"} for v in p["variables"]]
        named = {v["name"] for v in p["variables"]}
        for d in template["variable_defaults"]:
            if d["participant_key"] == p["key"] and d["name"] not in named:
                variables.append({"name": d["name"], "value": d["value"], "origin": "default",
                                  "basis": d["basis"]})
        # What the session for this reaction found wins; a copy of the template text is not that,
        # and gives way to what a variant, footnote or the row says.
        own = p["text"] if p["text"] and (tp is None or p["text"] != tp["text"]) else None
        alternatives = options(item["alternatives"]) if item is not None and own is None else []
        if alternatives:
            unresolved.append(p["key"])
        # A derived participant has no drawing of its own: point at the generic one.
        derived = p["source"] == "derived"
        loc = tp if derived and tp else p
        recs[p["key"]] = {
            "key": p["key"], "role": role,
            # A variant, footnote or row that puts another compound in this place: the template's
            # label names the compound it replaced.
            "label": p["label"] or (tp["label"] if tp and not swapped(item, tp) else None),
            "text": own or (item["text"] if item is not None else None),
            "amount": amount, "amount_origin": amount_origin if amount is not None else None,
            # Where the paper states an amount the block does not print (set for an amount that
            # came from the template or a later layer, not for one this reaction's session read).
            "amount_stated_at": (item or {}).get("amount_stated_at") if p["amount"] is None and amount is not None else None,
            "source": p["source"],
            # Derived and not printed in any form: the compound is to be worked out later (reactant tables).
            "unknown": bool(derived and p.get("unknown")),
            "generic": bool(derived and tp and tp["generic"]),
            "isolated": p["isolated"] if p["isolated"] is not None else (tp["isolated"] if tp else None),
            "page": loc["page"], "bbox": loc["bbox"],
            "crop": ctx["template_crops"].get(p["key"]) if derived else ctx["crops"].get(p["key"]),
            "variables": variables, "basis": p["basis"],
            "alternatives": alternatives,
            # Where the paper states the name or amount when the block does not print it: the session's own
            # text keeps its own source; otherwise the text is the merged item's, and so is its source (a
            # number the row prints does not change where the name comes from).
            "stated_at": p.get("stated_at") if own else (p.get("stated_at") or (item or {}).get("stated_at")),
            # Which of the source's alternatives ("A or B") this is, and what decided it.
            "choice": item.get("choice") if item is not None else None,
            # Set when taking part (or the role) in this reaction is a conclusion, not stated.
            "inferred": item.get("inferred") if item is not None else None,
        }

    # Alternatives nobody decided between: flag them instead of presenting both as reactants.
    for keys, _ in open_groups(template, items):
        both = [k for k in keys if k in recs]
        if len(both) > 1:
            for k in both:
                recs[k]["undecided_with"] = [x for x in both if x != k]
            problems.append(f"{' / '.join(both)} are alternatives, but nothing decides which one this "
                            "reaction uses")

    # Lay the participants out step by step, following the template's picture of the reaction.
    steps, placed = [], set()
    for st, reactants, products in active_steps(template, items):
        steps.append({"n": st["n"], "description": st["description"],
                      "reactants": [k for k in reactants if k in recs],
                      "products": [k for k in products if k in recs]})
        placed.update(steps[-1]["reactants"] + steps[-1]["products"])
    if not steps:
        steps = [{"n": 1, "description": "", "reactants": [], "products": []}]
    for key, rec in recs.items():  # compounds only this reaction has
        if key in placed or key in in_template_steps:
            continue  # a template participant outside the active steps takes no part here
        (steps[0]["reactants"] if rec["role"] == "reactant" else steps[-1]["products"]).append(key)
    kept_numbers = {st["n"] for st in steps}
    formed = {k for st in steps for k in st["products"]}
    # A value measured on a compound of the reaction that it does not form (a starting material recovered at
    # the end) stays with that compound's key, among the outcomes that belong to no product. When that
    # compound is a reactant the result is a recovered starting material, not a product yield.
    for key in [k for k in by_product if k in recs and k not in formed]:
        kind = "recovered_starting_material" if recs[key]["role"] == "reactant" else None
        other += [{**o, "participant_key": key, **({"measurement_kind": kind} if kind else {})}
                  for o in by_product.pop(key)]

    def participant(key: str, as_product: bool) -> dict:
        rec = dict(recs[key])
        if rec["role"] == "intermediate" and key not in formed:
            rec["role"] = "reactant"  # nothing in this reaction makes it: it is a starting material
        if rec["role"] != "intermediate":
            rec["isolated"] = None
        if as_product:
            rec["outcomes"] = by_product.get(key, [])
        elif key not in formed and key in preparations:
            # A starting material the block shows being made beforehand; the yield does not cover that.
            prep = preparations[key]
            rec["preparation"] = {
                "description": prep["description"], "basis": prep["basis"], "in_yield": False,
                "from": [{"key": k, "label": tparts[k]["label"], "text": tparts[k]["text"],
                          "page": tparts[k]["page"], "bbox": tparts[k]["bbox"],
                          "crop": ctx["template_crops"].get(k)}
                         for k in prep["from_participants"] if k in tparts],
                "items": [{"role": x["role"], "text": x["text"], "amount": x["amount"],
                           "structure": structures.get(x["structure_key"])} for x in prep["items"]],
            }
        return rec

    loose, removed = [], []
    by_step: dict = {n: [] for n in kept_numbers}
    for item in items.values():
        if item["group"] != "condition" or item.get("not_given"):
            continue
        if item.get("removed"):
            removed.append({k: item[k] for k in ("key", "role", "text", "origin")})
            continue
        cond = {
            **{k: item[k] for k in ("key", "role", "text", "amount", "origin")},
            "structure": structures.get(item["structure_key"]),
            "alternatives": options(item["alternatives"]),
            "stated_at": item.get("stated_at"),
            # Where the paper states the amount, when that is not where it names the condition.
            "amount_stated_at": item.get("amount_stated_at"),
            "inferred": item.get("inferred"),
            # Still the placeholder of the block ("cat."): nothing stated its value for this reaction.
            "value_missing": bool(item.get("per_entry")),
        }
        if cond["value_missing"]:
            problems.append(f"condition '{item['key']}' ('{item['text']}') is given entry by entry, "
                            "but nothing states it for this reaction")
        n = item["step"] if item["step"] is not None else (steps[0]["n"] if len(steps) == 1 else None)
        if n is None:
            loose.append(cond)
        elif n in by_step:
            by_step[n].append(cond)
        else:  # belongs to a step that did not happen in this reaction
            removed.append({**{k: item[k] for k in ("key", "role", "text")}, "origin": "step not part of this protocol"})
            continue
        if cond["alternatives"]:
            unresolved.append(cond["key"])

    record_steps = [{
        "step": i, "description": st["description"],
        "reactants": [participant(k, False) for k in st["reactants"]],
        "products": [participant(k, True) for k in st["products"]],
        "conditions": by_step[st["n"]],
    } for i, st in enumerate(steps, 1)]
    v = variants.get(variant)
    return {
        "reaction_id": f"{region['region_id']}/{block['block_id']}/{reaction['rid']}",
        "label": reaction["label"] or entry_unit["label"],
        "kind": block["kind"],
        "variant": {"key": variant, "title": v["title"] if v else None,
                    "notes": v["notes"] if v else ""} if variant else None,
        # False: the paper does not give the conditions of this protocol, so none are listed.
        "conditions_given": v.get("conditions_given", True) if v else True,
        # The results printed for this reaction, as the block reader assigned them.
        "results": reaction["results_text"],
        # Everything in this record that is a conclusion rather than stated in the paper.
        "inferences": [{"key": item["key"], "group": item["group"], "text": item["text"], **item["inferred"]}
                       for item in items.values() if item.get("inferred")],
        "source": {
            "doc": region["doc"], "page": entry_unit["page"], "figure": region["label"],
            "section": ctx.get("section"), "caption": region["caption"],
            "region_id": region["region_id"], "block_id": block["block_id"],
            "entry_id": entry_unit["eid"], "reaction_id": reaction["rid"], "entry_bbox": entry_unit["bbox"],
            "crop": ctx.get("entry_crop"),
        },
        # One item per reaction step, each with its own reactants, products and conditions.
        "steps": record_steps,
        "conditions": loose,  # conditions of a sequence that are not tied to one step
        "removed_conditions": removed,
        # What the source leaves open ("A or B"); a later step has to settle it.
        "unresolved": unresolved,
        "other_outcomes": other,
        "footnotes": [{"marker": m, "text": footnote_text.get(m)} for m in markers],
        # What the main text and the SI say about this reaction outside the block.
        "related": entry.get("related", []),
        "notes": entry["notes"],
        "issues": entry["issues"] + problems,
    }
