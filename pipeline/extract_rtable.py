"""Pure logic of the two reactant-table skills (Step 2, block layout `reactant_table`): the
validators of the three Codex answers, and the assembly of records and views. No PDF, no Codex.

A reactant table runs one general reaction, drawn once (often generically: R, X, Ar, a coloured
part), whose positions the rows fill in. A row gives the compounds of one or more positions: drawn
in a cell, named, as a compound number, or as the values of variable groups. A position the row
leaves open is fixed by the header (a specific compound), or follows from the others by the general
reaction: it is recorded as derived (unknown here, to be worked out later), and the template says
how it follows (`derivations`).

Stage 1, skill reactant-table-entries, one session:
  turn 1 reads the table: the template, the columns (each pointing at the positions it gives,
         `targets`) and every printed row as cells (schema rtable_entries); a cell that repeats an
         earlier row's value says so with `same_as`;
  turn 2 lists the reactions, one handle each (schema rtable_handles; a row split on one cell that
         prints two compounds gives each reaction its part of that cell in `cells`).
Stage 2, skill reactant-table-reaction, one session per handle: checks the reading for this
  reaction, writes what is left to read (condition cells, what sets a split reaction apart), its
  outcomes, and looks the entry up in the main text and the SI (schema rtable_reaction).

The pipeline applies a row's participant, variable and label cells itself: a participant cell
becomes an override of the row ("entry" layer) that puts the drawn or named compound in its
position, a variable cell a variable of the participants that carry it, a label cell the compound
number of its position. The records keep the generic path's format (`build_record`), so viewer and
evaluation are shared with the other layouts.
"""

from __future__ import annotations

import re
from collections import Counter
from types import SimpleNamespace

from .extract_ctable import (CHECK_TARGETS, _column_target, _footnote_conflicts, _norm,
                             _protocol_overrides, cells_of, check_cells, check_merged, check_outcome_cells,
                             columns_by_key, entry_of, stamp_outcome, structure_key, value_of)
from .extract_ctable import number_reactions as _number_reactions
from .extract_ctable import validate_handles as _validate_handles
from .extract_records import (_box_error, _check_ref, _schema_errors, _squash, active_steps, check_lookup,
                              merge_items, open_groups, protocol_groups, row_checks, swapped, template_groups,
                              validate_inventory)

LAYOUT = "reactant_table"
# Column kinds whose cells the pipeline applies to the participants itself.
GIVEN_BY_CELL = ("participant", "variable", "label")
# How many positions a column points at, by kind: exactly one, one or more, or none.
ONE_TARGET = ("participant", "label", "condition", "amount")
TEMPLATE_KEYS = {"derivations", "shared_results", "lookup_guide"}


def targets(column: dict) -> list[str]:
    return list(column.get("targets") or [])


def _eid(inv: dict, n: int) -> str:
    """The entry id of row n (1-based); rows of an answer not yet numbered get the id they will have."""
    return inv["entries"][n - 1].get("eid") or f"e{n:03d}"


def _row_number(inv: dict, entry: dict) -> int:
    return int(entry["eid"][1:]) if entry.get("eid") else inv["entries"].index(entry) + 1


def _empty(cell: dict | None) -> bool:
    return cell is None or (not cell["text"].strip() and cell["structure_bbox"] is None)


# ------------------------------------------------------------------ cells

def resolve_cells(inv: dict, n: int) -> dict:
    """{column key: cell} of row n (1-based). A cell that repeats an earlier row (`same_as`) takes
    the text and the drawing of the cell it repeats, with that cell's structure key (one drawing,
    one crop); it keeps its own footnote markers. `from_row` is the row whose cell prints the value
    (None: this row); `page` is the page the drawing is on."""
    entries = inv["entries"]
    entry = entries[n - 1]
    out = {}
    for cell in entry["cells"]:
        src, src_n, seen = cell, n, set()
        while src.get("same_as") is not None and _empty(src):
            k = src["same_as"]
            if k in seen or not 1 <= k < src_n:
                break
            seen.add(k)
            nxt = next((c for c in entries[k - 1]["cells"] if c["column"] == cell["column"]), None)
            if nxt is None:
                break
            src, src_n = nxt, k
        drawn = src["structure_bbox"] is not None
        out[cell["column"]] = {
            "column": cell["column"], "text": src["text"], "markers": cell["markers"],
            "structure_bbox": src["structure_bbox"],
            "structure_key": structure_key(_eid(inv, src_n), cell["column"]) if drawn else None,
            "page": entries[src_n - 1]["page"], "same_as": cell.get("same_as"),
            "from_row": src_n if src_n != n else None,
        }
    return out


def reaction_cells(inv: dict, reaction: dict) -> dict:
    """The row's cells as they apply to one reaction: repeats resolved, and a cell the row split
    between its reactions (`reaction["cells"]`) cut down to this reaction's part."""
    cells = resolve_cells(inv, reaction["entry"])
    for part in reaction.get("cells", []):
        c = cells.get(part["column"])
        if c is not None:
            cells[part["column"]] = {**c, "text": part["part"], "split": True}
    return cells


def _variable_value(name: str | None, text: str) -> str:
    """'X = OMe' under a column of X gives 'OMe'."""
    value = text.strip()
    if name and name.strip():
        value = re.sub(rf"^\s*{re.escape(name.strip())}\s*[=:]\s*", "", value)
    return value.strip()


# A cell that prints only a compound number ("3a", "12b′"), not a name.
COMPOUND_NUMBER = re.compile(r"^[0-9]{1,3}[a-z]{0,3}[′'″]*$")


def _cell_label(column: dict, cell: dict) -> str | None:
    """The compound number a participant cell prints: the label under a drawing, a number the
    column's `values` resolve, or a bare compound number."""
    text = cell["text"].strip()
    if not text:
        return None
    if cell["structure_bbox"] is not None or value_of(column, text) is not None or COMPOUND_NUMBER.match(text):
        return text
    return None


def row_layout(inv: dict, reaction: dict, cells: dict) -> SimpleNamespace:
    """What the reaction's row gives, position by position, once its variant and footnotes apply:
    `protocol` (the merged items before the row), `given` ({position: (column key, cell)} of the
    participant cells the pipeline applies), `labels` and `variables` by position. A column whose
    target the protocol swapped for another member of its alternative group applies to that member;
    a position the protocol removes, swaps or picks is left to it."""
    t, col = inv["template"], columns_by_key(inv)
    protocol, _ = merge_items(t, reaction["variant"], reaction["footnote_markers"], [])
    fixed = _protocol_overrides(t, {"variant": reaction["variant"], "footnote_markers": reaction["footnote_markers"]})
    given, labels, variables = {}, {}, {}
    for key, c in col.items():
        cell = cells.get(key)
        if _empty(cell) or not targets(c):
            continue
        tks = [_column_target(t, protocol, tk) for tk in targets(c)]
        if c["kind"] == "participant":
            target = tks[0]
            # A `use` only picks the member of its group; a removal or a named or drawn compound replaces it.
            if target not in protocol or protocol[target].get("removed") or any(
                    o["action"] == "remove" or o["text"] is not None or o["structure_key"] is not None
                    for o in fixed.get(target, [])):
                continue
            given[target] = (key, cell)
            label = _cell_label(c, cell)
            if label:
                labels.setdefault(target, label)
        elif c["kind"] == "label":
            labels[tks[0]] = cell["text"].strip()
        elif c["kind"] == "variable":
            for tk in tks:
                variables.setdefault(tk, []).append(
                    {"name": c["variable_name"], "value": _variable_value(c["variable_name"], cell["text"])})
    return SimpleNamespace(protocol=protocol, given=given, labels=labels, variables=variables)


def cell_overrides(inv: dict, reaction: dict, cells: dict | None = None) -> list[dict]:
    """What the row's participant cells print, as overrides of the reaction's entry layer: the
    drawn compound (its structure key) or the named one in the place of the position the column
    gives. A position the reaction's variant or footnotes already set is left to them."""
    col = columns_by_key(inv)
    cells = cells if cells is not None else reaction_cells(inv, reaction)
    out = []
    for target, (key, cell) in row_layout(inv, reaction, cells).given.items():
        c = col[key]
        where = f"cell '{c['header'] or key}'" + (f" (as in row {cell['from_row']})" if cell["from_row"] else "")
        o = {"key": target, "action": "replace", "role": None, "text": None, "amount": None, "structure_key": None,
             "step": None, "alternatives": [], "basis": where, "stated_at": None, "inferred": False}
        v = value_of(c, cell["text"]) if cell["structure_bbox"] is None else None
        if cell["structure_bbox"] is not None:
            # A drawing: its printed label is the participant's label, not its name.
            o.update(text="", structure_key=cell["structure_key"])
        elif v is not None:
            # A compound number the column resolves: the compound it stands for.
            o.update(text=v["text"] if v["text"] is not None else "", amount=v["amount"],
                     structure_key=v["structure_key"], stated_at=v["stated_at"], basis=f"{where}: {v['basis']}")
        elif COMPOUND_NUMBER.match(cell["text"].strip()):
            o["text"] = ""  # only a number: it becomes the label, the name stays open
        else:
            o["text"] = cell["text"]
        out.append(o)
    return out


def base_row(inv: dict, reaction: dict, overrides=()) -> dict:
    """The reaction in the shape of a row of the generic path: the row's participant cells as its
    first overrides, then `overrides` (what stage 2 wrote)."""
    col, cells = columns_by_key(inv), reaction_cells(inv, reaction)
    variables = [{"name": c["variable_name"], "value": _variable_value(c["variable_name"], cells[k]["text"])}
                 for k, c in col.items() if c["kind"] == "variable" and k in cells and cells[k]["text"].strip()]
    applied = cell_overrides(inv, reaction, cells)
    # The drawings a row's overrides may point at: those the pipeline applies, and drawn condition values.
    used = {o["structure_key"] for o in applied if o["structure_key"]}
    drawn: dict = {}
    for k, cell in cells.items():
        skey = cell["structure_key"]
        if skey and (skey in used or col.get(k, {}).get("kind") == "condition"):
            drawn.setdefault(skey, {"key": skey, "label": cell["text"] or None, "text": None})
    # An unnumbered row split on its label cell: each reaction is called by its part.
    entry = inv["entries"][reaction["entry"] - 1]
    label = None
    if not entry["label"]:
        products = {p["key"] for p in inv["template"]["participants"] if p["role"] == "product"}
        split = [k for k, c in col.items() if c["kind"] == "label" and cells.get(k, {}).get("split")]
        split.sort(key=lambda k: not products.intersection(targets(col[k])))  # the product's number first
        label = cells[split[0]]["text"].strip() if split else None
    return {"rid": reaction["rid"], "label": label, "results": list(range(1, len(reaction["results_text"]) + 1)),
            "results_text": reaction["results_text"], "variant": reaction["variant"],
            "footnote_markers": list(reaction["footnote_markers"]), "variables": variables,
            "drawn_structures": list(drawn.values()), "overrides": applied + list(overrides)}


def number_reactions(inv: dict, handles: dict) -> list[dict]:
    """As for condition tables; a result printed once for the whole table belongs to every reaction."""
    shared = [x for x in inv["template"].get("shared_results") or [] if x.strip()]
    return [{**r, "results_text": r["results_text"] + shared} for r in _number_reactions(inv, handles)]


# ------------------------------------------------------------------ positions

def positions(inv: dict, reaction: dict, items: dict, cells: dict) -> dict:
    """How the reaction has each of its participants: {key: state} with state
    'cell' (the row prints it), 'swapped' (a variant, footnote or the row's changes put another
    compound in its place), 'fixed' (a specific compound of the header), 'variables' (the generic
    drawing, completed by the variable values the row or the defaults give) or 'unknown' (to be
    worked out from the others: a generic position with a derivation, or one the row leaves open).

    A position the template derives stays unknown when the row gives it some variable values (they
    may define only part of it) and when a footnote puts only a name in its place (a class name
    such as "ArZnCl" still leaves its groups to the derivation)."""
    t = inv["template"]
    tparts = {p["key"]: p for p in t["participants"]}
    lay = row_layout(inv, reaction, cells)
    derived = {d["key"] for d in t.get("derivations", [])}
    defaults = {d["participant_key"] for d in t["variable_defaults"] if d["participant_key"]}
    out = {}
    for _, reactants, products in active_steps(t, items):
        for key in reactants + products:
            tp, item = tparts.get(key), items[key]
            if tp is None:
                continue
            if key in lay.given:
                out[key] = "cell"
            elif swapped(item, tp):
                named_only = item.get("structure_key") is None
                out[key] = "unknown" if tp["generic"] and key in derived and named_only else "swapped"
            elif not tp["generic"]:
                out[key] = "fixed"
            elif key in derived:
                out[key] = "unknown"
            elif key in lay.variables or key in defaults:
                out[key] = "variables"
            else:
                out[key] = "unknown"
    return out


def row_prints(inv: dict, cells: dict) -> set:
    """The positions the row's participant cells print, whatever the reaction's protocol does with
    them (a product the row draws stays known to a reaction that stops one step before it)."""
    return {targets(c)[0] for k, c in columns_by_key(inv).items()
            if c["kind"] == "participant" and targets(c) and not _empty(cells.get(k))}


def underivable(t: dict, state: dict, printed=()) -> list[str]:
    """The unknown participants of a reaction that its row does not let one work out: no
    derivation, or one that needs a participant that is neither given nor derivable itself.
    `printed`: positions the row prints although they take no part in this reaction (`row_prints`)."""
    groups = [g["keys"] for g in t.get("alternative_groups", [])]

    def present(k):
        """The participant that takes k's place in this reaction (k, or the member of its group in use)."""
        if k in state:
            return k
        return next((m for g in groups if k in g for m in g if m in state), k)

    derivations = {d["key"]: {**d, "from": [present(k) for k in d["from"]]} for d in t.get("derivations", [])}
    known = {k for k, st in state.items() if st != "unknown"} | {k for k in printed if k not in state}
    grew = True
    while grew:  # what follows from what is known is known too
        grew = False
        for key in state:
            d = derivations.get(key)
            if key not in known and d and all(k in known for k in d["from"]):
                known.add(key)
                grew = True
    issues = []
    for key, st in state.items():
        if st != "unknown" or key in known:
            continue
        d = derivations.get(key)
        if d is None:
            issues.append(f"'{key}' is unknown in this row and the template does not say how it follows")
        else:
            missing = [k for k in d["from"] if k not in known]
            issues.append(f"'{key}' cannot be derived from this row: {', '.join(missing)} not given")
    return issues


def participants(inv: dict, reaction: dict, items: dict, cells: dict, template_crops: dict, cell_crops: dict,
                 structure_crops: dict, found_labels=()):
    """The participants of the reaction as `build_record` takes them. A compound the row draws has
    the cell's box; one it names has no box; a specific header compound keeps the header drawing;
    a generic one the row does not print is derived: the generic drawing completed by variable
    values, or unknown. Returns (participants, crops by key, {key: state})."""
    t = inv["template"]
    tparts = {p["key"]: p for p in t["participants"]}
    legend = {x["key"]: x for x in t["structures"]}
    derivations = {d["key"]: d for d in t.get("derivations", [])}
    lay = row_layout(inv, reaction, cells)
    drawn = {c["structure_key"]: c for c in cells.values() if c["structure_key"]}
    found = {x["key"]: x for x in found_labels}
    state = positions(inv, reaction, items, cells)
    out, crops, seen = [], {}, set()
    for _, reactants, products in active_steps(t, items):
        for key in reactants + products:
            if key not in tparts or key in seen:
                continue
            seen.add(key)
            tp, item, st = tparts[key], items[key], state.get(key)
            # A name the text or the SI gives for it (the lookup layer) keeps where it says so.
            named_at = item.get("stated_at") if item.get("origin") == "lookup" else None
            p = {"key": key, "role": item["role"], "label": lay.labels.get(key), "text": None, "amount": None,
                 "isolated": None, "variables": lay.variables.get(key, []), "basis": None, "stated_at": named_at,
                 "source": "text", "page": None, "bbox": None}
            skey = item.get("structure_key")
            if st == "unknown":
                p["source"], p["unknown"] = "derived", True
                if key in derivations:
                    d = derivations[key]
                    p["basis"] = f"unknown, to be derived: {d['how']} (from {', '.join(d['from'])})"
                else:
                    p["basis"] = "unknown: the row does not print it and the general reaction draws it only generically"
            elif skey in drawn:
                cell = drawn[skey]
                p.update(source="drawn", page=cell["page"], bbox=cell["structure_bbox"])
                crops[key] = cell_crops.get(skey)
            elif skey in legend:
                x = legend[skey]
                p.update(source="drawn", page=x["page"], bbox=x["bbox"], label=p["label"] or x["label"])
                crops[key] = structure_crops.get(skey)
            elif st in ("cell", "swapped"):
                pass  # named only: no box
            elif st == "fixed":
                if tp["bbox"] is not None:
                    p.update(source="drawn", page=tp["page"], bbox=tp["bbox"])
                    crops[key] = template_crops.get(key)
            else:  # variables: the generic drawing with the row's (or the default) groups
                p["source"] = "derived"
                shown = ", ".join(f"{v['name']} = {v['value']}" for v in p["variables"]) or "the default groups"
                p["basis"] = f"the general reaction's generic drawing with {shown}"
            if p["label"] is None and key in found:
                # A number the text or the SI gives it, where the row prints none.
                p["label"] = found[key]["label"]
                p["stated_at"] = p["stated_at"] or found[key]["stated_at"]
            out.append(p)
    return out, crops, state


# ------------------------------------------------------------------ record and view

def entry_label(inv: dict, entry: dict) -> str:
    """The row's entry number; for a table without numbers, the compound number a label column
    prints, else the label of the row's drawing, else 'row N'."""
    if entry["label"]:
        return entry["label"]
    n = _row_number(inv, entry)
    cells = resolve_cells(inv, n)
    for k, c in columns_by_key(inv).items():
        if c["kind"] == "label" and not _empty(cells.get(k)):
            return cells[k]["text"].strip()
    drawn = [c["text"] for c in entry["cells"] if c["structure_bbox"] is not None and c["text"].strip()]
    return drawn[0] if drawn else f"row {n}"


def entry_unit(inv: dict, entry: dict) -> dict:
    return {**{k: entry[k] for k in ("eid", "page", "bbox", "descriptor")}, "label": entry_label(inv, entry)}


def printed(inv: dict, entry: dict) -> str:
    """The row as printed, one line per cell; a repeated value says which row prints it."""
    col = columns_by_key(inv)
    cells = resolve_cells(inv, _row_number(inv, entry))
    out = []
    for cell in entry["cells"]:
        name = col.get(cell["column"], {}).get("header") or cell["column"]
        r = cells[cell["column"]]
        marks = f" [{', '.join(cell['markers'])}]" if cell["markers"] else ""
        drawn = " (drawn)" if r["structure_bbox"] is not None else ""
        if r["from_row"]:
            out.append(f"{name}: as in row {r['from_row']}: {r['text'] or 'the drawing'}{drawn}{marks}")
        else:
            out.append(f"{name}: {r['text'] or '—'}{drawn}{marks}")
    return "\n".join(out)


def synthesize(inv: dict, reaction: dict, answer: dict, template_crops: dict, cell_crops: dict,
               structure_crops: dict | None = None):
    """Stage 1 + stage 2 of one reaction as `build_record` takes them:
    (entry unit, row, the reaction session's result, crops by participant key and 's:<structure key>')."""
    t, en, col = inv["template"], entry_of(inv, reaction), columns_by_key(inv)
    cells = reaction_cells(inv, reaction)
    row = base_row(inv, reaction, answer["overrides"])
    items, _ = merge_items(t, row["variant"], row["footnote_markers"], row["overrides"], answer["lookup"])
    parts, crops, state = participants(inv, reaction, items, cells, template_crops, cell_crops, structure_crops or {},
                                       answer.get("labels", []))
    structures, seen = [], set()
    for cell in cells.values():
        if cell["structure_key"] and cell["structure_key"] not in seen:
            seen.add(cell["structure_key"])
            structures.append({"key": cell["structure_key"], "label": cell["text"] or None, "text": None,
                               "page": cell["page"], "bbox": cell["structure_bbox"]})
    crops.update({f"s:{x['key']}": cell_crops.get(x["key"]) for x in structures})
    checks = [f"table reading questioned for {x['target']}: it says {x['stage1']!r}, the page shows {x['seen']!r} "
              f"({x['evidence']})" for x in answer["template_check"]]
    child = {"participants": parts, "structures": structures,
             "outcomes": [stamp_outcome(o, col) for o in answer["outcomes"]],
             "overrides": answer["lookup"], "related": answer["related"], "notes": answer["notes"],
             "issues": checks + underivable(t, state, row_prints(inv, cells)) + answer["issues"]}
    return entry_unit(inv, en), row, child, crops


# What extract_ctable.assemble_view needs from this layout.
OPS = SimpleNamespace(base_row=base_row, entry_unit=entry_unit, printed=printed, synthesize=synthesize)


# ------------------------------------------------------------------ stage 1, turn 1

def validate_table(inv: dict, schema: dict, page_sizes: dict, n_est: int | None = None,
                   doc_pages: dict | None = None):
    """The table reading: the template (as for any block, plus how its unknowns follow), columns
    that point at its positions, rows of cells whose repeats point upwards."""
    errors, warnings = validate_inventory(inv, schema, page_sizes, n_est, doc_pages, entries_required=True)
    if any(e.startswith("schema at") for e in errors):
        return errors, warnings
    t = inv["template"]
    conds = {c["key"]: c for c in t["conditions"]}
    parts = {p["key"]: p for p in t["participants"]}
    markers = {f["marker"] for f in t["footnotes"]}
    skeys = {x["key"] for x in t["structures"]}
    columns, entries = inv["columns"], inv["entries"]
    keys = [c["key"] for c in columns]
    shared = [x for x in t["shared_results"] if x.strip()]
    for k in sorted({k for k in keys if keys.count(k) > 1}):
        errors.append(f"columns: key '{k}' is used more than once")
    if not any(c["kind"] == "outcome" for c in columns) and not shared:
        errors.append("columns: no outcome column; the column(s) with the results have kind outcome (a result "
                      "printed once for every row goes into template.shared_results)")
    if sum(c["kind"] == "entry_number" for c in columns) > 1:
        errors.append("columns: more than one entry_number column (a table printed in two halves side by side "
                      "lists its columns once; the rows of both halves use them)")

    targeted = set()
    for c in columns:
        w = f"column '{c['key']}'"
        kind, tks = c["kind"], targets(c)
        if kind in ONE_TARGET and len(tks) != 1:
            errors.append(f"{w}: a {kind} column has exactly one target ({len(tks)} given)")
        elif kind == "variable" and not tks:
            errors.append(f"{w}: a variable column targets every participant whose drawing carries "
                          f"'{c['variable_name'] or '?'}' (at least one)")
        elif kind not in ONE_TARGET and kind != "variable" and tks:
            errors.append(f"{w}: only participant, label, variable, condition and amount columns have targets")
        for tk in tks:
            if kind == "condition":
                if tk not in conds:
                    errors.append(f"{w}: target '{tk}' is not a template condition (conditions: {sorted(conds)})")
                elif not conds[tk]["per_entry"]:
                    errors.append(f"{w}: gives template condition '{tk}' row by row, so that condition needs "
                                  "per_entry true, with the header or placeholder as printed as its text")
                targeted.add(tk)
            elif kind == "amount":
                if tk not in conds and tk not in parts:
                    errors.append(f"{w}: target '{tk}' is neither a template condition nor a participant")
            elif kind in GIVEN_BY_CELL:
                if tk not in parts:
                    hint = (" A column that selects a drawn catalyst or ligand is a condition column."
                            if kind == "variable" else "")
                    errors.append(f"{w}: target '{tk}' is not a template participant (participants: "
                                  f"{sorted(parts)}).{hint}")
                elif kind == "variable" and not parts[tk]["generic"]:
                    errors.append(f"{w}: '{tk}' carries the variable '{c['variable_name']}', so its template drawing "
                                  "is generic (generic true)")
                elif kind == "participant" and not parts[tk]["generic"]:
                    errors.append(f"{w}: the rows put different compounds in position '{tk}', so the template "
                                  "participant is generic (generic true); a compound the scheme draws for it (a "
                                  "model reaction) is one instance, not the position")
        if kind == "variable" and not (c["variable_name"] or "").strip():
            errors.append(f"{w}: a variable column needs variable_name (the symbol, e.g. 'X')")
        elif kind == "variable":
            # A printed column that gives different groups in different rows ("X = OMe", "R3Si = SiMe3")
            # is one column item per group.
            others = sorted({m.group(1).strip() for en in entries for cell in en["cells"] if cell["column"] == c["key"]
                             for m in [re.match(r"^\s*([A-Za-z(\[][^=:\s]{0,23}?)(?:\s+[=:]|[=:]\s+|:)", cell["text"])]
                             if m and _norm(m.group(1)) != _norm(c["variable_name"])})
            if others:
                errors.append(f"{w}: its cells also give {others}, not only '{c['variable_name']}': write one variable "
                              "column per group (same header), each with its own targets, and leave its cell '' in "
                              "the rows that give the other group")
        if kind == "outcome":
            if not c["measures"]:
                errors.append(f"{w}: list under measures what one cell holds, in printed order")
            for m in c["measures"]:
                pk = m["participant_key"]
                if pk is not None and pk not in parts:
                    errors.append(f"{w}: measure on unknown participant '{pk}' (participants: {sorted(parts)})")
                elif pk is not None and m["measure"] != "conversion" and parts[pk]["role"] == "reactant":
                    pass  # a value measured on a recovered starting material is recorded as such, not a product yield
                elif pk is not None and m["measure"] != "conversion" and parts[pk]["role"] not in ("product", "byproduct"):
                    warnings.append(f"{w}: a {m['measure']} measured on '{pk}', which is not a product or byproduct")
        elif c["measures"]:
            errors.append(f"{w}: measures are only for outcome columns")
        if c["values"]:
            if kind not in ("condition", "participant", "amount"):
                errors.append(f"{w}: values are only for condition, amount and participant columns")
            printed_values = [_norm(v["printed"]) for v in c["values"]]
            for pv in sorted({pv for pv in printed_values if printed_values.count(pv) > 1}):
                errors.append(f"{w}: the printed value '{pv}' is listed twice under values")
            cell_texts = {_norm(cell["text"]) for en in entries for cell in en["cells"] if cell["column"] == c["key"]}
            for v in c["values"]:
                vw = f"{w} value '{v['printed']}'"
                if v["text"] is None and v["amount"] is None and v["structure_key"] is None:
                    errors.append(f"{vw}: says nothing (give its text, amount or structure_key)")
                if v["structure_key"] is not None and v["structure_key"] not in skeys:
                    errors.append(f"{vw}: unknown structure_key '{v['structure_key']}' (structures: {sorted(skeys)})")
                _check_ref(f"{vw} stated_at", v["stated_at"], doc_pages, errors)
                if _norm(v["printed"]) not in cell_texts:
                    warnings.append(f"{vw}: no cell of the column prints it")
    for key, cond in conds.items():
        if cond["per_entry"] and key not in targeted:
            errors.append(f"template condition '{key}' has per_entry true, but no condition column gives it; "
                          "per_entry marks a condition the table gives row by row in a column")

    items, _ = merge_items(t, None, [], [])
    for group, _left in open_groups(t, items):
        errors.append(f"the alternatives {group} have no default: rows without a protocol label run the template, "
                      "so give the group a `default` (with stated_at, or inferred and your reasoning); a variant "
                      "still picks its own member with `use`")
    carried = {m for en in entries for cell in en["cells"] for m in cell["markers"]}
    for f in t["footnotes"]:
        if f["overrides"] and f["marker"] not in carried:
            errors.append(f"footnote '{f['marker']}' has overrides, but no row prints its marker: a footnote of the "
                          "title, a column header or the header reaction concerns every row; put what it states "
                          "into the template's participants and conditions and give it no overrides")

    # How the unknowns follow from the rest.
    dkeys = [d["key"] for d in t["derivations"]]
    for k in sorted({k for k in dkeys if dkeys.count(k) > 1}):
        errors.append(f"derivations: '{k}' is listed more than once")
    for d in t["derivations"]:
        w = f"derivations '{d['key']}'"
        if d["key"] not in parts:
            errors.append(f"{w}: not a template participant (participants: {sorted(parts)})")
            continue
        if not parts[d["key"]]["generic"]:
            errors.append(f"{w}: a participant that follows from the others is drawn (if at all) only generically: "
                          "its template participant has generic true")
        if not d["from"]:
            errors.append(f"{w}: say which participants it follows from")
        for k in d["from"]:
            if k not in parts:
                errors.append(f"{w}: '{k}' in from is not a template participant")
            elif k == d["key"]:
                errors.append(f"{w}: a participant does not follow from itself")
        if not d["how"].strip():
            errors.append(f"{w}: say how it follows (how)")

    col = {c["key"]: c for c in columns}
    for i, en in enumerate(entries):
        n = i + 1
        w = f"entries[{i}]" + (f" ({en['label']})" if en["label"] else "")
        seen = [c["column"] for c in en["cells"]]
        for k in sorted({k for k in seen if k not in col}):
            errors.append(f"{w}: cell of unknown column '{k}' (columns: {keys})")
        for k in sorted({k for k in seen if seen.count(k) > 1}):
            errors.append(f"{w}: two cells for column '{k}'")
        missing = [k for k in keys if k not in seen]
        if missing:
            errors.append(f"{w}: no cell for column(s) {missing}; every column gets a cell, text '' when it is empty")
        for cell in en["cells"]:
            cw = f"{w} cell '{cell['column']}'"
            kind = col.get(cell["column"], {}).get("kind")
            for m in cell["markers"]:
                if m not in markers:
                    errors.append(f"{cw}: footnote marker '{m}' is not defined in the template (markers: {sorted(markers)})")
            if cell["structure_bbox"] is not None:
                if kind not in ("condition", "participant"):
                    errors.append(f"{cw}: only a condition or participant cell can be a drawing (structure_bbox)")
                err = _box_error(f"{cw} structure_bbox", en["page"], cell["structure_bbox"], page_sizes)
                if err:
                    errors.append(err)
            k = cell["same_as"]
            if k is not None:
                if kind in ("outcome", "entry_number"):
                    errors.append(f"{cw}: same_as is for a compound, variable or condition that repeats the row "
                                  "above, not for results or entry numbers")
                elif not _empty(cell):
                    errors.append(f"{cw}: a cell with same_as prints nothing of its own (text '' and no "
                                  f"structure_bbox); it repeats the cell of row {k}")
                elif not 1 <= k < n:
                    errors.append(f"{cw}: same_as {k} must be the number of an earlier row (1..{n - 1})")
                else:
                    src = resolve_cells(inv, n).get(cell["column"])
                    if src is None or (not src["text"].strip() and src["structure_bbox"] is None):
                        errors.append(f"{cw}: same_as {k}, but row {k} prints nothing in column '{cell['column']}' "
                                      "either (point at the row that prints the value)")
        if en["lookup_hint"] is not None:
            _check_ref(f"{w} lookup_hint", en["lookup_hint"], doc_pages, errors)
        if not shared and not any(cell["text"].strip() for cell in en["cells"]
                                  if col.get(cell["column"], {}).get("kind") == "outcome"):
            warnings.append(f"{w}: prints no result")
    if errors:
        return errors, warnings

    from .variable_contract import check as check_variable_contract
    errors.extend(check_variable_contract(inv, resolve_cells))
    if errors:
        return errors, warnings

    # Every row needs each of its participants: printed, fixed by the header, generic with values,
    # or unknown with a derivation.
    derivations = {d["key"] for d in t["derivations"]}
    unknown_rows: dict = {}
    for i, en in enumerate(entries):
        n = i + 1
        cells = resolve_cells(inv, n)
        printed = sorted({m for cell in en["cells"] for m in cell["markers"]} & markers)
        reaction = {"entry": n, "variant": None, "footnote_markers": printed}
        row_items, _ = merge_items(t, None, printed, cell_overrides(inv, reaction, cells))
        state = positions(inv, reaction, row_items, cells)
        for key, st in state.items():
            if st == "unknown" and key not in derivations:
                unknown_rows.setdefault(key, []).append(en["label"] or str(n))
        for issue in underivable(t, state, row_prints(inv, cells)):
            if "cannot be derived" in issue:
                warnings.append(f"entries[{i}]: {issue}")
    for key, rows in unknown_rows.items():
        errors.append(f"participant '{key}' is generic and rows {rows} do not print it: add it to derivations "
                      "(which participants it follows from and how), give its variables (a variable column or "
                      "variable_defaults), or point a column at it")
    return errors, warnings


# ------------------------------------------------------------------ stage 1, turn 2

def validate_handles(handles: dict, inv: dict, schema: dict):
    """As for condition tables, plus the cells a row is split on: a participant, variable or label
    cell, and each reaction's part copied from it."""
    errors, warnings = _validate_handles(handles, inv, schema)
    if any(e.startswith("schema at") for e in errors):
        return errors, warnings
    col, entries = columns_by_key(inv), inv["entries"]
    split: dict = {}
    for i, r in enumerate(handles["reactions"], 1):
        if not 1 <= r["entry"] <= len(entries):
            continue
        w = f"reactions[{i}] (row {r['entry']})"
        cells = cells_of(entries[r["entry"] - 1])
        for part in r["cells"]:
            c = col.get(part["column"])
            if c is None or c["kind"] not in GIVEN_BY_CELL:
                errors.append(f"{w}: cells: '{part['column']}' is not a participant, variable or label column")
                continue
            text = cells.get(part["column"], {}).get("text", "")
            if not part["part"].strip() or _squash(part["part"]) not in _squash(text):
                errors.append(f"{w}: cells: part '{part['part']}' is not in the text '{text}' of column "
                              f"'{part['column']}'")
            split.setdefault((r["entry"], part["column"]), []).append(i)
        if r["cells"] and not (r["distinguishing"] or "").strip():
            errors.append(f"{w}: a reaction split on a cell says in `distinguishing` what sets it apart")
    per_row = Counter(r["entry"] for r in handles["reactions"])
    for (n, column), rids in split.items():
        if len(rids) < per_row[n]:
            errors.append(f"row {n}: reactions split on cell '{column}' must each give their part of it "
                          f"(only reactions {rids} of {per_row[n]} do)")
    return errors, warnings


# ------------------------------------------------------------------ stage 2

def validate_reaction(answer: dict, schema: dict, inv: dict, reaction: dict, doc_pages: dict | None = None,
                      printed_text_ok: bool = False):
    """One reaction: what it writes points into the template and leaves the row's own compounds to
    the pipeline; its outcomes are its own results (or the results printed for the whole table);
    its lookup says where the paper states it.

    `printed_text_ok`: a remark the row prints about an unknown position (an `other` cell: "from
    the branched bromide") may be written onto that position as its text; it stays unknown."""
    errors, warnings = _schema_errors(answer, schema), []
    if errors:
        return errors, warnings
    t, en, col = inv["template"], entry_of(inv, reaction), columns_by_key(inv)
    cells = reaction_cells(inv, reaction)
    row = base_row(inv, reaction, answer["overrides"])
    e, w = row_checks(t, row, "overrides", doc_pages)
    errors += e
    warnings += w
    known = (set(template_groups(t)) | set(col) | {f["marker"] for f in t["footnotes"]}
             | {x["key"] for x in t["structures"]} | {v["key"] for v in t["variants"]} | CHECK_TARGETS | TEMPLATE_KEYS)
    for x in answer["template_check"]:
        if x["target"] not in known:
            warnings.append(f"template_check: unknown target '{x['target']}'")
    skeys = {x["key"] for x in t["structures"]} | {x["key"] for x in row["drawn_structures"]}
    check_lookup(answer["lookup"], protocol_groups(t, row["variant"], row["footnote_markers"]), skeys, t, errors,
                 doc_pages)
    for i, passage in enumerate(answer["related"]):
        _check_ref(f"related[{i}]", passage, doc_pages, errors)
    active = {k for _, r, p in active_steps(t, merge_items(t, row["variant"], row["footnote_markers"],
                                                           row["overrides"])[0]) for k in r + p}
    for i, x in enumerate(answer["labels"]):
        if x["key"] not in active:
            errors.append(f"labels[{i}]: '{x['key']}' is not a participant of this reaction ({sorted(active)})")
        if x["stated_at"] is None:
            errors.append(f"labels[{i}]: say where the passage gives the number (stated_at)")
        _check_ref(f"labels[{i}] stated_at", x["stated_at"], doc_pages, errors)

    # The row's own compounds, variables and numbers are the pipeline's to apply; an amount for one
    # of them (an amount column) is the reaction's to write.
    by_cell = {}
    for k, c in col.items():
        if c["kind"] in GIVEN_BY_CELL and not _empty(cells.get(k)):
            for tk in targets(c):
                by_cell.setdefault(tk, k)
    amount_only = lambda o: o["action"] == "replace" and all(o[f] is None for f in ("text", "structure_key", "role")) \
        and not o["alternatives"]
    before, _ = merge_items(t, row["variant"], row["footnote_markers"], cell_overrides(inv, reaction, cells))
    state = positions(inv, reaction, before, cells)
    # With `printed_text_ok`, one kind of override passes both checks below: the words of a remark the row prints,
    # as the text of an unknown position that has a derivation (a name only, so `positions` keeps it unknown).
    derived = {d["key"] for d in t.get("derivations", [])}
    words = lambda text: " ".join((text or "").split())
    remarks = [words(c["text"]) for k, c in cells.items() if col.get(k, {}).get("kind") == "other"]
    # Whole words of the remark: a fragment cut inside a word ("propyl bromide" of "isopropyl bromide") is another name.
    quoted = lambda text: any(re.search(rf"(?<![\w-]){re.escape(words(text))}(?![\w-])", r) for r in remarks)
    printed_remark = lambda o: printed_text_ok and o["action"] == "replace" and bool(words(o["text"])) \
        and all(o[f] is None for f in ("structure_key", "role", "step", "stated_at")) and not o["alternatives"] \
        and not o["inferred"] and state.get(o["key"]) == "unknown" and o["key"] in derived and quoted(o["text"])
    for o in answer["overrides"]:
        if o["key"] in by_cell and o["action"] in ("replace", "remove", "use") and not amount_only(o) \
                and not printed_remark(o):
            errors.append(f"overrides: {o['action']} '{o['key']}': the row's cell '{by_cell[o['key']]}' gives this "
                          "participant and the pipeline applies it; leave it out (a name found in the text or the "
                          "SI goes into lookup; a disagreement with the cell into template_check or issues)")
    # An unknown position (or a generic one the row's values complete) is worked out later, never here:
    # only a name the text or the SI prints, with where it does, may be added to it.
    open_keys = {k for k, st in state.items() if st in ("unknown", "variables")}
    remark_hint = ("; a remark the row prints about it (a cell of an `other` column) may be its `text`, in the "
                   "printed words and with nothing else set" if printed_text_ok else "")
    for o in answer["overrides"]:
        if o["key"] in open_keys and not amount_only(o) and not printed_remark(o):
            errors.append(f"overrides: {o['action']} '{o['key']}': this participant is not printed in the row and is "
                          "worked out later from the others; do not fill it in. A name the text or the SI prints for "
                          f"it goes into lookup with stated_at{remark_hint}")
    for o in answer["lookup"]:
        if o["key"] in open_keys and (o["text"] or o["structure_key"]) and (o["stated_at"] is None or o["inferred"]):
            errors.append(f"lookup: '{o['key']}' is not printed in the row: only a name a passage prints may be added "
                          "to it, with stated_at (never a name you work out)")

    used_cols = {r["column"] for r in reaction["results"]}
    shared = [_squash(x) for x in t["shared_results"] if x.strip()]
    by_column = []
    for i, o in enumerate(answer["outcomes"]):
        if o["column"] is not None:
            by_column.append((i, o))
        elif not shared:
            errors.append(f"outcomes[{i}]: column null is only for a result printed once for the whole table "
                          "(template.shared_results), and this table has none")
        elif o["yield_text"] and not any(_squash(o["yield_text"]) in s for s in shared):
            errors.append(f"outcomes[{i}]: '{o['yield_text']}' is not one of the results printed for the whole table "
                          f"{t['shared_results']}")
    errors += check_outcome_cells(by_column, col, used_cols)
    # Condition and amount cells: as in a condition table.
    ccol = {k: {**c, "target": targets(c)[0] if targets(c) else None} for k, c in col.items()
            if c["kind"] in ("condition", "amount")}
    # The words of a remark describe the unknown compound; they are not a name an amount column would contradict.
    errors += check_cells(t, ccol, en, cells, row,
                          [{**o, "text": None} if printed_remark(o) else o for o in answer["overrides"]])
    errors += _footnote_conflicts(t, row, answer["overrides"])
    # A split row: what sets this reaction apart is a protocol (variant, its own footnotes), a cell part,
    # or a condition it writes. The reaction of the row that runs the template has nothing to write.
    footnotes = {f["marker"]: f for f in t["footnotes"]}
    by_protocol = reaction["variant"] is not None or reaction.get("cells") or any(
        footnotes.get(m, {}).get("overrides") for m in reaction["footnote_markers"])
    if reaction["distinguishing"] and not by_protocol:
        d = _norm(reaction["distinguishing"])
        values = [_norm(x) for o in answer["overrides"] for x in (o["text"], o["amount"]) if x]
        if not any(x and (x in d or d in x) for x in values):
            warnings.append(f"your row reports several reactions and yours is set apart by "
                            f"'{reaction['distinguishing']}': when that is a condition, write it as an override")
    if errors:
        return errors, warnings
    e, w = check_merged(t, col, cells, row, answer, reaction)
    return errors + e, warnings + w
