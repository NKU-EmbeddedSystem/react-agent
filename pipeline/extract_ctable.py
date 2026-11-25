"""Pure logic of the two condition-table skills (Step 2, block layout `condition_table`): the
validators of the three Codex answers, and the assembly of records and views. No PDF, no Codex.

Stage 1, skill condition-table-entries, one session:
  turn 1 reads the table: the template (what every row shares), the columns and every printed row
         as cells (schema ctable_entries);
  turn 2 lists the reactions of the table, one handle each (schema ctable_handles).
Stage 2, skill condition-table-reaction, one session per handle: checks the table reading for this
  reaction, writes how its row differs from the template, reads its outcomes and looks the entry
  up in the main text and the SI (schema ctable_reaction).

A handle with its stage 2 answer becomes the same three things the generic path hands to
`build_record`: the printed entry, the reaction (a "row": variant, footnotes, printed changes) and
what the reaction's own session found (participants, outcomes, lookup). Participants are not
written by the model here: every row runs the model reaction of the header, so they follow from
the template as merged for the reaction.
"""

from __future__ import annotations

import re
from collections import Counter
from types import SimpleNamespace

from .extract_records import (_box_error, _check_ref, _schema_errors, _squash, active_steps, build_record,
                              alternative_groups, check_lookup, check_outcomes, merge_items, open_groups,
                              protocol_groups, resolve_protocol, row_checks, swapped, template_groups,
                              validate_inventory)

LAYOUT = "condition_table"
# A deviation cell that names no change: the row runs the standard conditions.
NO_CHANGE = {"", "–", "-", "—", "none", "standard", "standardconditions"}
# Cell texts that print no value.
BLANK = {"", "–", "-", "—", "none", "n/a"}
CHECK_TARGETS = {"steps", "scheme", "default_yield_type", "general_reaction", "reading_guide"}
SELECTIVITY = {"ee", "er", "dr"}


def _norm(text) -> str:
    return _squash(text or "").lower()


def structure_key(eid: str, column: str) -> str:
    """Key of the drawing in one cell (a ligand drawn for one row)."""
    return f"{eid}-{column}"


def columns_by_key(inv: dict) -> dict:
    return {c["key"]: c for c in inv["columns"]}


def cells_of(entry: dict) -> dict:
    return {c["column"]: c for c in entry["cells"]}


def drawn_cells(entry: dict) -> dict:
    """{structure key: cell} of the cells whose value is a drawing."""
    return {structure_key(entry["eid"], c["column"]): c for c in entry["cells"] if c["structure_bbox"] is not None}


def value_of(column: dict, text: str):
    """The item of `column["values"]` that says what the printed `text` stands for, or None."""
    want = _norm(text)
    return next((v for v in column["values"] if _norm(v["printed"]) == want), None) if want else None


# ------------------------------------------------------------------ stage 1, turn 1

def validate_table(inv: dict, schema: dict, page_sizes: dict, n_est: int | None = None,
                   doc_pages: dict | None = None):
    """The table reading: template (as for any block), columns that point into it, rows of cells."""
    errors, warnings = validate_inventory(inv, schema, page_sizes, n_est, doc_pages, entries_required=True)
    if any(e.startswith("schema at") for e in errors):
        return errors, warnings
    t = inv["template"]
    conds = {c["key"]: c for c in t["conditions"]}
    parts = {p["key"]: p for p in t["participants"]}
    markers = {f["marker"] for f in t["footnotes"]}
    skeys = {x["key"] for x in t["structures"]}
    columns = inv["columns"]
    keys = [c["key"] for c in columns]
    for k in sorted({k for k in keys if keys.count(k) > 1}):
        errors.append(f"columns: key '{k}' is used more than once")
    if not any(c["kind"] == "outcome" for c in columns):
        errors.append("columns: no outcome column; the column(s) with the results have kind outcome")
    if sum(c["kind"] == "entry_number" for c in columns) > 1:
        errors.append("columns: more than one entry_number column (a table printed in two halves side by side "
                      "lists its columns once; the rows of both halves use them)")

    targeted = set()
    for c in columns:
        w = f"column '{c['key']}'"
        kind, target = c["kind"], c["target"]
        if kind == "condition":
            if target not in conds:
                errors.append(f"{w}: target '{target}' is not a template condition (conditions: {sorted(conds)})")
            elif not conds[target]["per_entry"]:
                errors.append(f"{w}: gives template condition '{target}' row by row, so that condition needs "
                              "per_entry true, with the header or placeholder as printed as its text")
            targeted.add(target)
        elif kind == "amount":
            if target not in conds and target not in parts:
                errors.append(f"{w}: target '{target}' is neither a template condition nor a participant (an amount "
                              f"column gives the amount of one of them; keys: {sorted(conds) + sorted(parts)})")
        elif kind in ("participant", "variable"):
            if target not in parts:
                hint = (" A variable column gives a group (X, R) of a reactant or product; a column that selects a "
                        "drawn catalyst or ligand by its R group is a condition column whose `values` say which "
                        "compound each printed value stands for." if kind == "variable" else "")
                errors.append(f"{w}: target '{target}' is not a template participant (participants: {sorted(parts)}).{hint}")
            if kind == "variable" and not (c["variable_name"] or "").strip():
                errors.append(f"{w}: a variable column needs variable_name (the symbol, e.g. 'X')")
        elif target is not None:
            errors.append(f"{w}: only condition, amount, participant and variable columns have a target")
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
            printed = [_norm(v["printed"]) for v in c["values"]]
            for p in sorted({p for p in printed if printed.count(p) > 1}):
                errors.append(f"{w}: the printed value '{p}' is listed twice under values")
            cell_texts = {_norm(cell["text"]) for en in inv["entries"] for cell in en["cells"] if cell["column"] == c["key"]}
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
    carried = {m for en in inv["entries"] for cell in en["cells"] for m in cell["markers"]}
    for f in t["footnotes"]:
        if f["overrides"] and f["marker"] not in carried:
            errors.append(f"footnote '{f['marker']}' has overrides, but no row prints its marker: a footnote of the "
                          "title, a column header or the header reaction concerns every row; put what it states "
                          "into the template's participants and conditions and give it no overrides")

    col = {c["key"]: c for c in columns}
    for i, en in enumerate(inv["entries"]):
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
            for m in cell["markers"]:
                if m not in markers:
                    errors.append(f"{cw}: footnote marker '{m}' is not defined in the template (markers: {sorted(markers)})")
            if cell["structure_bbox"] is not None:
                if col.get(cell["column"], {}).get("kind") not in ("condition", "participant"):
                    errors.append(f"{cw}: only a condition or participant cell can be a drawing (structure_bbox)")
                err = _box_error(f"{cw} structure_bbox", en["page"], cell["structure_bbox"], page_sizes)
                if err:
                    errors.append(err)
        if not any(cell["text"].strip() for cell in en["cells"] if col.get(cell["column"], {}).get("kind") == "outcome"):
            warnings.append(f"{w}: prints no result")
    return errors, warnings


# ------------------------------------------------------------------ stage 1, turn 2

def _row_text(entry: dict, col: dict, reaction: dict) -> str:
    """What the row prints for one reaction: its non-result cells and its own results."""
    cells = cells_of(entry)
    texts = [c["text"] for c in entry["cells"] if col.get(c["column"], {}).get("kind") != "outcome"]
    for res in reaction["results"]:
        cell = cells.get(res["column"])
        if cell is not None:
            texts.append(res["part"] if res["part"] is not None else cell["text"])
    return _norm(" ".join(texts))


def validate_handles(handles: dict, inv: dict, schema: dict):
    """The reactions of the table: every row has one or more, every printed result belongs to one."""
    errors, warnings = _schema_errors(handles, schema), []
    if errors:
        return errors, warnings
    t, entries, col = inv["template"], inv["entries"], columns_by_key(inv)
    variants = {v["key"] for v in t["variants"]}
    titles = {v["key"]: _norm(v["title"]) for v in t["variants"] if len(_norm(v["title"])) >= 3}
    markers = {f["marker"] for f in t["footnotes"]}
    refs: dict = {}
    per_row = Counter()
    seen: dict = {}
    for i, r in enumerate(handles["reactions"], 1):
        w = f"reactions[{i}] (row {r['entry']})"
        if not 1 <= r["entry"] <= len(entries):
            errors.append(f"{w}: there is no row {r['entry']} (rows are numbered 1..{len(entries)})")
            continue
        en = entries[r["entry"] - 1]
        cells = cells_of(en)
        per_row[r["entry"]] += 1
        for res in r["results"]:
            c = col.get(res["column"])
            if c is None or c["kind"] != "outcome":
                errors.append(f"{w}: '{res['column']}' is not an outcome column")
                continue
            cell = cells.get(res["column"])
            if cell is None or not cell["text"].strip():
                errors.append(f"{w}: the row prints nothing in column '{res['column']}'")
                continue
            if res["part"] is not None and _squash(res["part"]) not in _squash(cell["text"]):
                errors.append(f"{w}: part '{res['part']}' is not in the text '{cell['text']}' of column '{res['column']}'")
            refs.setdefault((r["entry"], res["column"]), []).append((i, res["part"]))
        if r["variant"] is not None and r["variant"] not in variants:
            errors.append(f"{w}: unknown variant '{r['variant']}' (template variants: {sorted(variants)})")
        else:
            # The protocol label printed for this reaction, if any (the most specific of the titles found).
            text = _row_text(en, col, r)
            found = [k for k, title in titles.items() if title in text]
            found = [k for k in found if not any(k2 != k and titles[k] in titles[k2] for k2 in found)]
            if found and r["variant"] not in found:
                errors.append(f"{w}: the row prints the label of variant {found} for this reaction, but its variant "
                              f"is {r['variant']!r}")
            elif r["variant"] is not None and r["variant"] in titles and r["variant"] not in found:
                warnings.append(f"{w}: the label of variant '{r['variant']}' is not printed in this row")
        printed = {m for cell in en["cells"] for m in cell["markers"]}
        for m in r["footnote_markers"]:
            if m not in markers:
                errors.append(f"{w}: footnote marker '{m}' is not defined in the template (markers: {sorted(markers)})")
            elif m not in printed:
                warnings.append(f"{w}: footnote marker '{m}' is not printed in this row")
        # Results do not set reactions apart: one experiment measured twice is one reaction.
        sig = (r["entry"], r["variant"], tuple(sorted(r["footnote_markers"])), _norm(r["distinguishing"]))
        if sig in seen:
            errors.append(f"{w} and reactions[{seen[sig]}] are the same reaction: same row, protocol and footnotes, "
                          "and nothing that sets them apart. Give one experiment's results to one reaction; when "
                          "the row reports several experiments, say in `distinguishing` what sets each apart")
        seen.setdefault(sig, i)

    for n, en in enumerate(entries, 1):
        w = f"row {n}" + (f" ({en['label']})" if en["label"] else "")
        if not per_row[n]:
            errors.append(f"{w} has no reaction: every printed row reports at least one")
            continue
        for key, cell in cells_of(en).items():
            if col.get(key, {}).get("kind") != "outcome" or not cell["text"].strip():
                continue
            used = refs.get((n, key), [])
            if not used:
                errors.append(f"{w}: result cell '{key}' ('{cell['text']}') belongs to no reaction")
            elif len(used) > 1:
                if any(p is None for _, p in used):
                    errors.append(f"{w}: result cell '{key}' is shared by reactions {[i for i, _ in used]}; each "
                                  "gives the part of the cell that is its own")
                count = Counter(_squash(p) for _, p in used if p)
                if any(k > _squash(cell["text"]).count(p) for p, k in count.items()):
                    errors.append(f"{w}: reactions give the same part of result cell '{key}' more often than the "
                                  "cell prints it")
    for x in handles["notes"]:
        if not 1 <= x["entry"] <= len(entries):
            warnings.append(f"notes: there is no row {x['entry']}")
    return errors, warnings


def number_reactions(inv: dict, handles: dict) -> list[dict]:
    """The handles with what the pipeline adds: `eid`, `rid` (e003-1, e003-2 for a split row) and
    `results_text` (the printed result each one has)."""
    out, count = [], Counter()
    for h in handles["reactions"]:
        en = inv["entries"][h["entry"] - 1]
        count[en["eid"]] += 1
        cells = cells_of(en)
        texts = [res["part"] if res["part"] is not None else cells[res["column"]]["text"] for res in h["results"]]
        out.append({**h, "eid": en["eid"], "rid": f"{en['eid']}-{count[en['eid']]}", "results_text": texts})
    return out


# ------------------------------------------------------------------ the reaction

def entry_of(inv: dict, reaction: dict) -> dict:
    return inv["entries"][reaction["entry"] - 1]


def entry_label(entry: dict) -> str:
    """The row's entry number; for a table without numbers, the label of the row's drawing, else 'row N'."""
    if entry["label"]:
        return entry["label"]
    drawn = [c["text"] for c in entry["cells"] if c["structure_bbox"] is not None and c["text"].strip()]
    return drawn[0] if drawn else f"row {int(entry['eid'][1:])}"


def entry_unit(entry: dict) -> dict:
    return {**{k: entry[k] for k in ("eid", "page", "bbox", "descriptor")}, "label": entry_label(entry)}


def base_row(inv: dict, reaction: dict, overrides=()) -> dict:
    """The reaction in the shape of a row of the generic path. Its label is left to the entry
    (the row's label), so that a product keeps the template's label."""
    en, col = entry_of(inv, reaction), columns_by_key(inv)
    cells = cells_of(en)
    variables = [{"name": col[k]["variable_name"], "value": cells[k]["text"]}
                 for k in col if col[k]["kind"] == "variable" and k in cells and cells[k]["text"].strip()]
    drawn = [{"key": key, "label": cell["text"] or None, "text": None} for key, cell in drawn_cells(en).items()]
    return {"rid": reaction["rid"], "label": None, "results": list(range(1, len(reaction["results_text"]) + 1)),
            "results_text": reaction["results_text"], "variant": reaction["variant"],
            "footnote_markers": list(reaction["footnote_markers"]), "variables": variables,
            "drawn_structures": drawn, "overrides": list(overrides)}


def _measure(outcome: dict, column: dict | None):
    """The item of the column's `measures` this outcome is, or None."""
    if not column or column["kind"] != "outcome" or not column["measures"]:
        return None
    i = outcome.get("measure")
    if i is not None:
        return column["measures"][i - 1] if 1 <= i <= len(column["measures"]) else None
    return column["measures"][0] if len(column["measures"]) == 1 else None


def stamp_outcome(outcome: dict, col: dict) -> dict:
    """An outcome as `build_record` takes it: the measure of its column decides what the model left
    open (a conversion has type conversion and no product; a yield takes the measure's product and
    yield type)."""
    o = {k: v for k, v in outcome.items() if k not in ("column", "measure")}
    c = col.get(outcome.get("column"))
    m = _measure(outcome, c)
    if m is not None:
        o["measure_target"] = m["participant_key"]  # who the value is measured on; build_record reads it
        if m["measure"] == "conversion":
            o["yield_type"] = "conversion"
        elif m["measure"] == "yield":
            if o["yield_type"] is None:
                o["yield_type"] = m["yield_type"]
            if o["product_key"] is None:
                o["product_key"] = m["participant_key"]
    elif c and c["kind"] == "outcome" and o["yield_type"] is None:
        types = {x["yield_type"] for x in c["measures"] if x["measure"] == "yield" and x["yield_type"]}
        if len(types) == 1 and all(x["measure"] == "yield" for x in c["measures"]):
            o["yield_type"] = types.pop()
    if o["yield_type"] == "conversion":
        o["product_key"] = None
    return o


def _participants(inv: dict, entry: dict, items: dict, template_crops: dict, cell_crops: dict,
                  structure_crops: dict):
    """The participants of the reaction, from the template as merged for it: an unchanged compound
    (or one a lookup only names) keeps the header drawing; one the row replaced by a drawn value or a
    legend compound gets that drawing; one replaced by a name has no box.
    Returns (participants, crops by key)."""
    t = inv["template"]
    tparts = {p["key"]: p for p in t["participants"]}
    legend = {x["key"]: x for x in t["structures"]}
    col = columns_by_key(inv)
    cells = cells_of(entry)
    variables: dict = {}
    for k, c in col.items():
        if c["kind"] == "variable" and k in cells and cells[k]["text"].strip():
            variables.setdefault(c["target"], []).append({"name": c["variable_name"], "value": cells[k]["text"]})
    drawn = drawn_cells(entry)
    out, crops, seen = [], {}, set()
    for _, reactants, products in active_steps(t, items):
        for key in reactants + products:
            if key in seen or key not in tparts:
                continue
            seen.add(key)
            tp, item = tparts[key], items[key]
            p = {"key": key, "role": item["role"], "label": None, "text": None, "amount": None, "isolated": None,
                 "variables": variables.get(key, []), "basis": None, "stated_at": None}
            skey = item.get("structure_key")
            if skey in drawn:
                p.update(source="drawn", page=entry["page"], bbox=drawn[skey]["structure_bbox"],
                         label=drawn[skey]["text"] or None)
                crops[key] = cell_crops.get(skey)
            elif skey in legend:
                x = legend[skey]
                p.update(source="drawn", page=x["page"], bbox=x["bbox"], label=x["label"])
                crops[key] = structure_crops.get(skey)
            elif not swapped(item, tp) and tp["bbox"] is not None:
                p.update(source="drawn", page=tp["page"], bbox=tp["bbox"])
                crops[key] = template_crops.get(key)
            else:
                p.update(source="text", page=None, bbox=None)
            out.append(p)
    return out, crops


def synthesize(inv: dict, reaction: dict, answer: dict, template_crops: dict, cell_crops: dict,
               structure_crops: dict | None = None):
    """Stage 1 + stage 2 of one reaction as `build_record` takes them:
    (entry unit, row, the reaction session's result, crops by participant key and 's:<structure key>')."""
    t, en, col = inv["template"], entry_of(inv, reaction), columns_by_key(inv)
    row = base_row(inv, reaction, answer["overrides"])
    items, _ = merge_items(t, row["variant"], row["footnote_markers"], row["overrides"], answer["lookup"])
    participants, crops = _participants(inv, en, items, template_crops, cell_crops, structure_crops or {})
    structures = [{"key": key, "label": cell["text"] or None, "text": None, "page": en["page"],
                   "bbox": cell["structure_bbox"]} for key, cell in drawn_cells(en).items()]
    crops.update({f"s:{x['key']}": cell_crops.get(x["key"]) for x in structures})
    checks = [f"table reading questioned for {x['target']}: it says {x['stage1']!r}, the page shows {x['seen']!r} "
              f"({x['evidence']})" for x in answer["template_check"]]
    child = {"participants": participants, "structures": structures,
             "outcomes": [stamp_outcome(o, col) for o in answer["outcomes"]],
             "overrides": answer["lookup"], "related": answer["related"], "notes": answer["notes"],
             "issues": checks + answer["issues"]}
    return entry_unit(en), row, child, crops


# ------------------------------------------------------------------ stage 2

def _footnote_conflicts(t: dict, row: dict, overrides: list) -> list[str]:
    """A cell override that sets again what one of the row's footnotes already sets for it."""
    footnotes = {f["marker"]: f for f in t["footnotes"]}
    errors = []
    for m in row["footnote_markers"]:
        for fo in footnotes.get(m, {}).get("overrides", []):
            for o in overrides:
                if o["key"] != fo["key"]:
                    continue
                what = []
                if fo["action"] == "remove" and o["action"] in ("replace", "use"):
                    what.append("removes it")
                if fo["text"] is not None and o["text"] is not None and _norm(o["text"]) != _norm(fo["text"]):
                    what.append(f"text '{fo['text']}'")
                if fo["amount"] is not None and o["amount"] is not None and _norm(o["amount"]) != _norm(fo["amount"]):
                    what.append(f"amount '{fo['amount']}'")
                if what:
                    errors.append(f"footnote {m} already sets '{o['key']}' for this reaction ({', '.join(what)}): a cell "
                                  "under the footnote is read through it; leave out what the footnote sets, or "
                                  "explain the conflict under issues")
    return errors


def _protocol_overrides(t: dict, row: dict) -> dict:
    """What the reaction's variant and footnotes change, by key."""
    out: dict = {}
    v = next((v for v in t["variants"] if v["key"] == row["variant"]), None)
    footnotes = {f["marker"]: f for f in t["footnotes"]}
    layers = ([v["overrides"]] if v else []) + [footnotes[m]["overrides"] for m in row["footnote_markers"] if m in footnotes]
    for o in (o for layer in layers for o in layer):
        out.setdefault(o["key"], []).append(o)
    return out


def _column_target(t: dict, protocol: dict, target):
    """The item a column's cells apply to for this reaction: its target or, when the variant or a
    footnote swapped the target for another member of its alternative group, that member."""
    if target in protocol and protocol[target].get("removed"):
        for keys in alternative_groups(t):
            left = [k for k in keys if k in protocol and not protocol[k].get("removed")]
            if target in keys and len(left) == 1:
                return left[0]
    return target


def _deviation_names_change(t: dict, reaction: dict, text: str) -> bool:
    """Whether a deviation cell names a change beyond the protocol label printed in it."""
    v = next((v for v in t["variants"] if v["key"] == reaction["variant"]), None)
    rest = text
    if v is not None:
        tparts = {p["key"]: p for p in t["participants"]}
        names = [v["title"]] + [o["text"] for o in v["overrides"] if o["text"]]
        names += [tparts[o["key"]]["text"] or "" for o in v["overrides"] if o["action"] == "use" and o["key"] in tparts]
        names += [tparts[o["key"]]["label"] or "" for o in v["overrides"] if o["action"] == "use" and o["key"] in tparts]
        for name in sorted((n for n in names if n), key=len, reverse=True):
            rest = re.sub(re.escape(name), " ", rest, flags=re.IGNORECASE)
    return _norm(rest).rstrip(".") not in NO_CHANGE


def validate_reaction(answer: dict, schema: dict, inv: dict, reaction: dict, doc_pages: dict | None = None):
    """One reaction: its printed changes point into the template, follow the columns and settle
    every open point; its outcomes are read from its own result cells; its lookup says where the
    paper states it."""
    errors, warnings = _schema_errors(answer, schema), []
    if errors:
        return errors, warnings
    t, en, col = inv["template"], entry_of(inv, reaction), columns_by_key(inv)
    parts = {p["key"]: p for p in t["participants"]}
    row = base_row(inv, reaction, answer["overrides"])
    e, w = row_checks(t, row, "overrides", doc_pages)
    errors += e
    warnings += w
    known = (set(template_groups(t)) | set(col) | {f["marker"] for f in t["footnotes"]}
             | {x["key"] for x in t["structures"]} | CHECK_TARGETS)
    for x in answer["template_check"]:
        if x["target"] not in known:
            warnings.append(f"template_check: unknown target '{x['target']}'")
    skeys = {x["key"] for x in t["structures"]} | {x["key"] for x in row["drawn_structures"]}
    check_lookup(answer["lookup"], protocol_groups(t, row["variant"], row["footnote_markers"]), skeys, t, errors,
                 doc_pages)
    for i, passage in enumerate(answer["related"]):
        _check_ref(f"related[{i}]", passage, doc_pages, errors)
    used_cols = {r["column"] for r in reaction["results"]}
    errors += check_outcome_cells(list(enumerate(answer["outcomes"])), col, used_cols)
    cells = cells_of(en)
    errors += check_cells(t, col, en, cells, row, answer["overrides"])
    errors += _footnote_conflicts(t, row, answer["overrides"])
    if reaction["distinguishing"] and reaction["variant"] is None:
        d = _norm(reaction["distinguishing"])
        values = [_norm(x) for o in answer["overrides"] for x in (o["text"], o["amount"]) if x]
        if not any(x and (x in d or d in x) for x in values):
            errors.append(f"your row reports several reactions and yours is set apart by '{reaction['distinguishing']}': "
                          "write that as an override (the condition it names, e.g. replace temp text '60 °C')")
    if errors:
        return errors, warnings
    e, w = check_merged(t, col, cells, row, answer, reaction)
    return errors + e, warnings + w


def check_outcome_cells(outcomes: list, col: dict, used_cols: set) -> list[str]:
    """`outcomes`: (index, outcome) pairs. Each is read from one of the reaction's result cells, and
    from the right measure of its column."""
    errors = []
    for i, o in outcomes:
        c = col.get(o["column"])
        if o["column"] not in used_cols:
            errors.append(f"outcomes[{i}]: column '{o['column']}' is not one of this reaction's result cells "
                          f"{sorted(used_cols)}")
            continue
        n = len(c["measures"])
        m = _measure(o, c)
        if o["measure"] is None and n > 1:
            names = [x["participant_key"] or x["measure"] for x in c["measures"]]
            errors.append(f"outcomes[{i}]: column '{o['column']}' holds several measures {names}: say with `measure` "
                          "which one this value is (1 = first)")
        elif o["measure"] is not None and not 1 <= o["measure"] <= n:
            errors.append(f"outcomes[{i}]: measure {o['measure']} is not one of the column's measures (1..{n})")
        elif m is not None and m["measure"] in SELECTIVITY:
            errors.append(f"outcomes[{i}]: an {m['measure']} is not an outcome of its own: put it into `selectivity` "
                          "of the yield outcome of its product")
    return errors


def check_cells(t: dict, col: dict, entry: dict, cells: dict, row: dict, overrides: list) -> list[str]:
    """The condition, amount and variable columns of the row against the reaction's `overrides`:
    an amount cell has its replace, a printed value the column's `values` explain is written as they
    say, a variable value does not replace its participant. `cells`: {column key: cell}; a cell may
    carry the `structure_key` of its drawing (else the key of the row's own cell is used)."""
    errors = []
    parts = {p["key"]: p for p in t["participants"]}
    # The variant and the footnotes come first: a cell under a footnote is read through it, and a
    # column whose target they swapped for another compound of its group applies to that compound.
    protocol, _ = merge_items(t, row["variant"], row["footnote_markers"], [])
    fixed = _protocol_overrides(t, row)
    for key, c in col.items():
        cell = cells.get(key)
        printed = cell["text"] if cell else ""
        target = _column_target(t, protocol, c["target"])
        gone = target in protocol and protocol[target].get("removed")
        mine = [o for o in overrides if o["key"] == target]
        if c["kind"] == "variable" and any(o["action"] == "replace" and o["text"] is not None for o in mine):
            errors.append(f"column '{key}' gives a variable group of '{c['target']}' ({c['variable_name']} = {printed}); "
                          "the pipeline attaches it to the participant (reaction.variables): do not replace the participant")
        if c["kind"] == "amount" and _norm(printed) not in BLANK and not gone \
                and not any(o["amount"] is not None for o in fixed.get(target, [])):
            via = f" (the column's '{c['target']}' is '{target}' in this reaction)" if target != c["target"] else ""
            if not any(o["action"] in ("replace", "use") and o["amount"] is not None for o in mine) \
                    and not any(o["action"] == "remove" for o in mine):
                errors.append(f"column '{key}' gives the amount of '{target}' for this row ('{printed}'){via}: write a "
                              f"replace of '{target}' with that `amount`" + (f" (unit: {c['unit']})" if c["unit"] else ""))
            if target in parts and any(o["action"] == "replace" and o["text"] is not None
                                       and _norm(o["text"]) != _norm(parts[target]["text"]) for o in mine):
                errors.append(f"column '{key}' gives only the amount of '{target}': its replace sets `amount`, "
                              "not `text`")
        footnote_names = any(o["action"] in ("remove", "use") or o["text"] is not None for o in fixed.get(target, []))
        if c["values"] and cell is not None and not gone and not footnote_names:
            v = value_of(c, printed)
            if v is not None:
                # A drawn cell and the legend drawing the values name show the same compound.
                own = cell.get("structure_key") or (structure_key(entry["eid"], key)
                                                    if cell["structure_bbox"] is not None else None)
                drawings = [k for k in (own, v["structure_key"]) if k]
                ok = any(o["action"] in ("replace", "use")
                         and (v["text"] is None or _norm(o["text"]) == _norm(v["text"]))
                         and (v["amount"] is None or _norm(o["amount"]) == _norm(v["amount"]))
                         and (not drawings or o["structure_key"] in drawings) for o in mine)
                if not ok:
                    say = ", ".join([f"{k} '{x}'" for k, x in (("text", v["text"]), ("amount", v["amount"])) if x]
                                    + (["structure_key " + " or ".join(f"'{k}'" for k in drawings)] if drawings else []))
                    errors.append(f"column '{key}' says the printed '{v['printed']}' stands for {say}: write the "
                                  f"override of '{c['target']}' with those values")
    return errors


def check_merged(t: dict, col: dict, cells: dict, row: dict, answer: dict, reaction: dict):
    """The reaction with all its layers merged: every open point settled, its outcomes on its own
    products, every result cell read. Returns (errors, warnings)."""
    errors, warnings = [], []
    used_cols = {r["column"] for r in reaction["results"]}
    items, problems = merge_items(t, row["variant"], row["footnote_markers"], row["overrides"], answer["lookup"])
    errors += [p for p in problems if p.startswith("entry:")]
    warnings += [f"merge: {p}" for p in problems if not p.startswith("entry:")]
    for keys, left in open_groups(t, items):
        state = "none of them is left" if not left else f"{left} are all still in play"
        errors.append(f"{keys} are alternatives for one position, but {state}: add a `use` override for the one this "
                      "reaction uses (with stated_at, or inferred and your reasoning)")
    for item in items.values():
        if item.get("per_entry") and not item.get("removed") and not item.get("not_given"):
            errors.append(f"condition '{item['key']}' ('{item['text']}') is given row by row and still open: a replace "
                          "fills it only when it gives `text` (the value with its unit, or the compound's name), or "
                          "remove it when the cell is empty")
    keys = [k for _, r, p in active_steps(t, items) for k in r + p]
    products = [k for k in keys if items[k]["role"] in ("product", "byproduct")]
    outcomes = [stamp_outcome(o, col) for o in answer["outcomes"]]
    check_outcomes(outcomes, keys, t, row, errors, warnings)
    for i, o in enumerate(outcomes):
        if o["product_key"] is not None and o["product_key"] not in products:
            errors.append(f"outcomes[{i}]: product_key '{o['product_key']}' is not a product or byproduct of this "
                          f"reaction ({products}); a conversion has product_key null")
        elif (o["product_key"] is None and o["yield_type"] != "conversion" and o["yield_value"] is not None
              and len(products) > 1):
            warnings.append(f"outcomes[{i}]: '{o['yield_text']}' has no product_key, but the reaction has "
                            f"several products {products}")
    # An ee, er or dr printed in a column of its own goes into the selectivity of its product's outcome.
    selectivity_cols = {k for k in used_cols if col[k]["measures"]
                        and all(m["measure"] in SELECTIVITY for m in col[k]["measures"])}
    for key in sorted(used_cols):
        read = any(o["column"] == key for o in answer["outcomes"])
        if not read and not (key in selectivity_cols and any(o["selectivity"] for o in answer["outcomes"])):
            warnings.append(f"no outcome read from result cell '{key}'")
    for key, c in col.items():
        if c["kind"] == "deviation" and key in cells and not answer["overrides"] \
                and _deviation_names_change(t, reaction, cells[key]["text"]):
            warnings.append(f"the deviation '{cells[key]['text']}' names a change, but there are no overrides")
    return errors, warnings


# ------------------------------------------------------------------ view

def _printed(inv: dict, entry: dict) -> str:
    col = columns_by_key(inv)
    out = []
    for cell in entry["cells"]:
        c = col.get(cell["column"], {})
        name = c.get("header") or cell["column"]
        marks = f" [{', '.join(cell['markers'])}]" if cell["markers"] else ""
        drawn = " (drawn)" if cell["structure_bbox"] is not None else ""
        out.append(f"{name}: {cell['text'] or '—'}{drawn}{marks}")
    return "\n".join(out)


def assemble_view(region: dict, block: dict, slug: str, inv, inv_status: str, handles, handles_status,
                  answers: dict, template_crops: dict, structure_crops: dict, cell_crops: dict,
                  section=None, ops=None):
    """The block as publish() gathers it for the viewer, with its records.

    inv / handles: the stage 1 answers as stored (with `_meta`), or None. answers: {rid: (stored
    stage 2 answer or None, status)} with status ok / failed / stale / pending / skipped.
    ops: how a table of this layout turns a row into the generic path's shapes (`base_row`,
    `entry_unit`, `printed`, `synthesize`); the condition table's by default. A layout whose entries
    each run a template of their own (equation blocks) adds `template_of` (the template of one
    reaction) and `view_extra` (more for the viewer).
    Returns (view, records, counts)."""
    ops = ops or CTABLE_OPS
    template_of = getattr(ops, "template_of", None)
    counts = Counter({f"inventories_{inv_status}": 1})
    meta = dict(inv["_meta"]) if inv else {"errors": [], "warnings": []}
    view = {"region": region, "block": block, "slug": slug, "status": inv_status, "meta": meta,
            "template": None, "entries": [], "template_crops": {}, "structure_crops": {}, "ignored": [], "notes": ""}
    records = []
    if inv is None or inv_status != "ok":
        return view, records, counts

    t = inv["template"]
    hmeta = handles["_meta"] if handles else None
    meta["errors"] = list(meta.get("errors", [])) + ([f"reactions: {e}" for e in hmeta["errors"]] if hmeta else [])
    meta["warnings"] = list(meta.get("warnings", [])) + ([f"reactions: {w}" for w in hmeta["warnings"]] if hmeta else [])
    view.update(template=t, template_crops=template_crops, structure_crops=structure_crops,
                ignored=inv["ignored"], notes=inv["notes"])
    if getattr(ops, "view_extra", None):
        view.update(ops.view_extra(inv))
    current = handles is not None and handles_status == "ok"
    reactions = handles["reactions"] if current else []
    notes = {x["entry"]: x["text"] for x in handles["notes"]} if current else {}
    questioned: dict = {}
    for n, en in enumerate(inv["entries"], 1):
        counts["entries_listed"] += 1
        mine = [r for r in reactions if r["entry"] == n]
        status = handles_status if handles_status else "pending"
        ev = {"entry": ops.entry_unit(inv, en), "crop": f"blocks/{slug}/crops/{en['eid']}__entry.png", "status": status,
              "errors": [], "warnings": [], "expansion": None, "reactions": []}
        counts[f"entries_{status}"] += 1
        view["entries"].append(ev)
        if not current:
            continue
        ev["expansion"] = {"printed": ops.printed(inv, en), "results": [x for r in mine for x in r["results_text"]],
                           "reasoning": notes.get(n, ""), "issues": handles["issues"] if n == 1 else [],
                           "rows": [ops.base_row(inv, r) for r in mine]}
        for r in mine:
            counts["reactions_listed"] += 1
            answer, rstatus = answers.get(r["rid"], (None, "pending"))
            row = ops.base_row(inv, r, answer.get("overrides", []) if answer and rstatus == "ok" else ())
            rt = template_of(inv, r) if template_of else t
            rmeta = (answer or {}).get("_meta", {})
            rv = {"reaction": row, "status": rstatus, "errors": rmeta.get("errors", []),
                  "warnings": rmeta.get("warnings", []), "record": None, "protocol": resolve_protocol(rt, row, view=True),
                  "seconds": rmeta.get("seconds")}
            if template_of:
                rv["template"] = rt  # what a draft of the reaction is laid out from
            counts[f"reactions_{rstatus}"] += 1
            ev["reactions"].append(rv)
            if rstatus != "ok":
                continue
            for x in answer["template_check"]:
                questioned.setdefault(f"{en['eid']}: {x['target']}" if template_of else x["target"], []).append(r["rid"])
            unit, row, child, crops = ops.synthesize(inv, r, answer, template_crops, cell_crops, structure_crops)
            ctx = {"region": region, "block": block, "crops": crops, "template_crops": template_crops,
                   "structure_crops": structure_crops, "entry_crop": ev["crop"], "section": section}
            rec = build_record(ctx, rt, unit, row, child)
            rv["record"] = rec
            records.append(rec)
    for target, rids in sorted(questioned.items()):
        meta["warnings"].append(f"the table reading is questioned for '{target}' by {len(rids)} reaction(s): "
                                f"{', '.join(rids)}")
    return view, records, counts


# What assemble_view needs from a table layout; reactant tables and product scopes have their own
# (extract_rtable, extract_pscope).
CTABLE_OPS = SimpleNamespace(base_row=base_row, entry_unit=lambda inv, entry: entry_unit(entry), printed=_printed,
                             synthesize=synthesize)
