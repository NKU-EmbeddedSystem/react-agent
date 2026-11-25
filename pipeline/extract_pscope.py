"""Pure logic of the two product-scope skills (Step 2, block layout `product_scope`): the
validators of the three Codex answers, and the assembly of records and views. No PDF, no Codex.

A product scope runs one general reaction, drawn once (often generically), and below it one entry
per product: its drawing, its compound number, its results and sometimes a remark. The reactants
are not drawn: they follow from the product by the general reaction and are recorded as derived
(unknown here, to be worked out later); the template says how they follow (`derivations`).

The logic is the reactant-table engine (pipeline/extract_rtable.py) read in the other direction.
The figure is taken as a table without a printed header: an entry is a row, and each kind of thing
the entries print is a column (the drawing: a participant column that points at the product; the
compound number: a label column; then variables, outcomes, remarks). Entries that share one drawing
repeat it with `same_as`. What differs from a reactant table:

- every generic position the entries do not draw needs a derivation, also one whose variable groups
  have values (a leaving group with its default names one part of the reactant, not the reactant),
  and an entry with the box of an earlier one shares its drawing by `same_as` (`validate_table`);
- a remark an entry prints about a reactant ("from the branched bromide") may be written onto that
  unknown reactant as its text (`validate_reaction`); it keeps the reactant's number, and every
  remark the entry prints reaches the record's notes (`synthesize`);
- an entry without a label is called by the compound number of its product, also when the number of
  a byproduct comes first among its cells (`entry_label`).

Stage 1, skill product-scope-entries, and stage 2, skill product-scope-reaction, answer with the
schemas pscope_entries, pscope_handles and pscope_reaction, which have the shape of the reactant
table's.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from . import extract_rtable as _rtable
from .extract_ctable import columns_by_key, entry_of
# The engine, as the driver (steps/s2_pscope.py) and the tests take it from this layout.
from .extract_rtable import (_empty, _row_number, base_row, cell_overrides, number_reactions, participants,
                             positions, printed, reaction_cells, resolve_cells, targets, underivable,
                             validate_handles)

LAYOUT = "product_scope"
# What a generic position the entries do not draw needs, in this layout.
NEEDS_DERIVATION = ("add it to derivations (which participants it follows from and how), also when a variable group "
                    "of it has a value or a default: a group names one part of it, not the compound")


def validate_table(inv: dict, schema: dict, page_sizes: dict, n_est: int | None = None,
                   doc_pages: dict | None = None):
    """As for a reactant table, and: every generic position the entries do not all draw has a
    derivation (in a reactant table a position with variable values is complete; here a value names
    a group of a reactant, not the reactant), and an entry with the box of an earlier entry that
    draws a field repeats that drawing with `same_as`."""
    errors, warnings = _rtable.validate_table(inv, schema, page_sizes, n_est, doc_pages)
    if any(e.startswith("schema at") for e in errors):
        return errors, warnings
    # The reactant table's message also offers variable values as a way out, which this layout does not take.
    errors = [re.sub(r"^(participant '.+?' is generic and rows .+? do not print it): .*$", rf"\1: {NEEDS_DERIVATION}", e)
              for e in errors]
    t, col, entries = inv["template"], columns_by_key(inv), inv["entries"]
    derived = {d["key"] for d in t["derivations"]}
    drawn_everywhere = {targets(c)[0] for k, c in col.items() if c["kind"] == "participant" and targets(c)
                        and all(not _empty(resolve_cells(inv, n).get(k)) for n in range(1, len(entries) + 1))}
    for p in t["participants"]:
        reported = any(e.startswith(f"participant '{p['key']}' is generic") for e in errors)
        if p["generic"] and p["key"] not in derived and p["key"] not in drawn_everywhere and not reported:
            errors.append(f"participant '{p['key']}' is generic and not every entry draws it: {NEEDS_DERIVATION}")
    drawing = {k for k, c in col.items() if c["kind"] == "participant"}
    for i, en in enumerate(entries):
        for j in range(i):
            if entries[j]["page"] != en["page"] or entries[j]["bbox"] != en["bbox"]:
                continue
            for cell in en["cells"]:
                if cell["column"] not in drawing or not _empty(cell) or cell.get("same_as") is not None:
                    continue
                earlier = next((c for c in entries[j]["cells"] if c["column"] == cell["column"]), None)
                if earlier is not None and (earlier["structure_bbox"] is not None or earlier.get("same_as")):
                    errors.append(f"entries[{i}] cell '{cell['column']}': the entry has the box of row {j + 1}, which "
                                  f"draws this field: repeat its drawing with same_as {j + 1}")
            break
    return errors, warnings


def validate_reaction(answer: dict, schema: dict, inv: dict, reaction: dict, doc_pages: dict | None = None):
    """As for a reactant table, but a remark the entry prints about an unknown reactant may be
    written onto it."""
    return _rtable.validate_reaction(answer, schema, inv, reaction, doc_pages, printed_text_ok=True)


def entry_label(inv: dict, entry: dict) -> str:
    """The entry's label; for an entry without one, the compound number its cells print for a
    product (a byproduct's number may come first), else as for a reactant table."""
    if entry["label"]:
        return entry["label"]
    products = {p["key"] for p in inv["template"]["participants"] if p["role"] == "product"}
    cells = resolve_cells(inv, _row_number(inv, entry))
    for k, c in columns_by_key(inv).items():
        text = cells[k]["text"].strip() if k in cells else ""
        if c["kind"] == "label" and text and products.intersection(targets(c)):
            return text
    label = _rtable.entry_label(inv, entry)
    return f"entry {label[4:]}" if label.startswith("row ") else label


def entry_unit(inv: dict, entry: dict) -> dict:
    return {**{k: entry[k] for k in ("eid", "page", "bbox", "descriptor")}, "label": entry_label(inv, entry)}


def synthesize(inv: dict, reaction: dict, answer: dict, template_crops: dict, cell_crops: dict,
               structure_crops: dict | None = None):
    """As for a reactant table, with the entry called as this layout calls it. An unknown reactant
    that a remark of the entry names keeps the number of its position, and the remarks the entry
    prints are kept in the notes."""
    _, row, child, crops = _rtable.synthesize(inv, reaction, answer, template_crops, cell_crops, structure_crops)
    words = lambda text: " ".join((text or "").split())
    # A text on an unknown reactant passes validate_reaction only as a remark of the entry; a footnote or a
    # variant that names another compound there takes the number away, as in any record.
    remarked = {o["key"] for o in answer["overrides"] if o["action"] == "replace" and words(o["text"])}
    tparts = {p["key"]: p for p in inv["template"]["participants"]}
    for p in child["participants"]:
        if p.get("unknown") and p["label"] is None and p["key"] in tparts and p["key"] in remarked:
            p["label"] = tparts[p["key"]]["label"]
    col, notes = columns_by_key(inv), child["notes"] or ""
    # An override's words survive only where no name from the text or the SI replaces them (the lookup layer).
    looked = {o["key"] for o in answer["lookup"] if words(o["text"])}
    written = [words(o["text"]) for o in answer["overrides"]
               if o["action"] == "replace" and words(o["text"]) and o["key"] not in looked]
    said = words(" ".join([notes] + written))
    # A part is said when the notes or an override carry it, or when an override quotes whole words of it.
    is_said = lambda part: words(part) in said or any(
        re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", words(part)) for w in written)
    missing = []
    for k, c in reaction_cells(inv, reaction).items():
        if col.get(k, {}).get("kind") != "other" or not c["text"].strip():
            continue
        # Remarks that tell the results of the entry apart stand together, "A / B": each reaction says its own.
        parts = [x.strip() for x in c["text"].split(" / ") if x.strip()]
        left = [x for x in parts if not is_said(x)]
        if len(left) == len(parts):
            missing.append(c["text"].strip())  # nothing of it said: which part is ours is unknown
        elif not reaction["distinguishing"]:
            missing += left  # the entry reports one reaction: every part is ours
    if missing:
        child["notes"] = "; ".join([notes] * bool(notes) + [f"printed: {r}" for r in missing])
    return entry_unit(inv, entry_of(inv, reaction)), row, child, crops


# What extract_ctable.assemble_view needs from this layout.
OPS = SimpleNamespace(base_row=base_row, entry_unit=entry_unit, printed=printed, synthesize=synthesize)
