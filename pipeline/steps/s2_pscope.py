"""Step 2 for blocks of layout `product_scope` (a figure of one general reaction and, below it,
entries that each draw one product with its compound number and results; the reactants are not
drawn and are recorded as unknown).

Stage 1, skill product-scope-entries, one Codex session with two turns:
  turn 1 reads the figure: template (with how the unknown reactants follow from the product),
         the fields of an entry as columns, every entry as cells       -> inventory.json
  turn 2 lists the reactions of the figure, one handle each             -> handles.json
Stage 2, skill product-scope-reaction, one new session per reaction (run in parallel):
  checks the reading of the entry, writes what is left to read in it, reads its outcomes and
  looks the product up in the main text and the SI (its name, the starting materials its
  paragraph names)                                                     -> reactions/<rid>.json

The driver is shared with the condition and reactant tables (s2_table); the pure logic is in
pipeline/extract_pscope.py, which reads the reactant-table engine in the other direction.
"""

from __future__ import annotations

from ..extract_pscope import LAYOUT, OPS, number_reactions, validate_handles, validate_reaction, validate_table
from .s2_rtable import stage2_task
from .s2_table import TableSpec

SPEC = TableSpec(
    layout=LAYOUT, name="product scope", prefix="pscope",
    entries_skill="product-scope-entries", reaction_skill="product-scope-reaction",
    validate_table=validate_table, validate_handles=validate_handles, number_reactions=number_reactions,
    validate_reaction=validate_reaction, ops=OPS, stage2_task=stage2_task, scheme_image=True,
    block_word="figure", zoom=True, name_unlabelled=True,
    stage2_instruction=("Check the reading of this entry, write what is left to read in it, read its outcomes, "
                        "then look the product up in the main text and the SI: its name, and the starting "
                        "materials its paragraph names with their amounts."),
)


def stage1_sha() -> str:
    return SPEC.stage1_sha()


def stage2_sha() -> str:
    return SPEC.stage2_sha()
