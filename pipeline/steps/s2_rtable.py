"""Step 2 for blocks of layout `reactant_table` (a table whose rows give the reactants of one
general reaction; what a row does not print, usually the product, is recorded as unknown).

Stage 1, skill reactant-table-entries, one Codex session with two turns:
  turn 1 reads the table: template (with how the unknowns follow), columns, every row as cells
                                                                       -> inventory.json
  turn 2 lists the reactions of the table, one handle each              -> handles.json
Stage 2, skill reactant-table-reaction, one new session per reaction (run in parallel):
  checks the reading for the reaction, writes what is left to read in its row, reads its
  outcomes and looks the entry up in the main text and the SI (the product's name and number)
                                                                       -> reactions/<rid>.json

The driver is shared with the condition tables and product scopes (s2_table); the pure logic is in
pipeline/extract_rtable.py.
"""

from __future__ import annotations

from ..extract_records import merge_items
from ..extract_rtable import (LAYOUT, OPS, base_row, number_reactions, participants, reaction_cells, row_prints,
                              underivable, validate_handles, validate_reaction, validate_table)
from .s2_table import TableSpec


def stage2_task(task: dict, inv: dict, handles: dict, reaction: dict) -> dict:
    """What the reaction's session gets beyond a condition table's task: its row with repeats
    resolved and split cells cut, and the participants as the pipeline builds them from the row."""
    t = inv["template"]
    cells = reaction_cells(inv, reaction)
    row = base_row(inv, reaction)
    items, _ = merge_items(t, row["variant"], row["footnote_markers"], row["overrides"])
    parts, _, state = participants(inv, reaction, items, cells, {}, {}, {})
    entry = inv["entries"][reaction["entry"] - 1]
    return {
        "entry": {**task["entry"], "lookup_hint": entry.get("lookup_hint")},
        "row_cells": [{k: c[k] for k in ("column", "text", "markers", "structure_key", "from_row")}
                      for c in cells.values()],
        "reaction_cells": reaction.get("cells", []),
        "participants": [{k: p[k] for k in ("key", "role", "source", "label", "page", "bbox", "variables", "basis")}
                         | {"state": state.get(p["key"])} for p in parts],
        "cannot_derive": underivable(t, state, row_prints(inv, cells)),
    }


SPEC = TableSpec(
    layout=LAYOUT, name="reactant table", prefix="rtable",
    entries_skill="reactant-table-entries", reaction_skill="reactant-table-reaction",
    validate_table=validate_table, validate_handles=validate_handles, number_reactions=number_reactions,
    validate_reaction=validate_reaction, ops=OPS, stage2_task=stage2_task, scheme_image=True,
    stage2_instruction=("Check the table reading for this reaction, write what is left to read in its row, read its "
                        "outcomes, then look the entry up in the main text and the SI: the product's name and "
                        "number in particular."),
)


def stage1_sha() -> str:
    return SPEC.stage1_sha()


def stage2_sha() -> str:
    return SPEC.stage2_sha()
