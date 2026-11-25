"""Step 2 for blocks of layout `condition_table` (an optimization or screening table).

Stage 1, skill condition-table-entries, one Codex session with two turns:
  turn 1 reads the table: template, columns, every printed row as cells   -> inventory.json
  turn 2 lists the reactions of the table, one handle each              -> handles.json
Stage 2, skill condition-table-reaction, one new session per reaction (run in parallel):
  checks the table reading for the reaction, writes how its row changes the model reaction,
  reads its outcomes and looks the entry up in the main text and the SI -> reactions/<rid>.json

The driver is shared with the reactant tables and product scopes (s2_table); the pure logic is in
pipeline/extract_ctable.py.
"""

from __future__ import annotations

from ..extract_ctable import (CTABLE_OPS, LAYOUT, number_reactions, validate_handles, validate_reaction,
                              validate_table)
from .s2_table import TableSpec

SPEC = TableSpec(
    layout=LAYOUT, name="condition table", prefix="ctable",
    entries_skill="condition-table-entries", reaction_skill="condition-table-reaction",
    validate_table=validate_table, validate_handles=validate_handles, number_reactions=number_reactions,
    validate_reaction=validate_reaction, ops=CTABLE_OPS, scheme_image=True,
    stage2_instruction=("Check the table reading for this reaction, write how its row changes the model reaction, "
                        "read its outcomes, then look the entry up in the main text and the SI."),
)


def stage1_sha() -> str:
    return SPEC.stage1_sha()


def stage2_sha() -> str:
    return SPEC.stage2_sha()
