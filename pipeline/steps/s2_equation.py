"""Step 2 for blocks of layout `equation` (whole reactions drawn as equations: starting materials, an
arrow with the conditions over and under it, products and results; one or a few per block, often
one arrow of a figure whose arrows start from one compound, or a sequence over several arrows).

Stage 1, skill equation-entries, one Codex session with two turns:
  turn 1 reads the block: the compounds once (with their boxes), every equation with a template of
         its own (participants, steps, conditions, variants, results)  -> inventory.json
  turn 2 lists the reactions of the block, one handle each               -> handles.json
Stage 2, skill equation-reaction, one new session per reaction (run in parallel):
  checks the reading for the reaction, reads its outcomes and looks the experiment up in the main
  text and the SI (amounts, scale, conditions a reference leaves open)   -> reactions/<rid>.json

The driver is shared with the tables (s2_table); the pure logic is in pipeline/extract_equation.py.
Equation blocks do not take part in sharing a general scheme: every equation draws its own.
"""

from __future__ import annotations

from ..extract_equation import (LAYOUT, OPS, number_reactions, prepare, stage2_task, validate_handles,
                                validate_reaction, validate_table)
from .s2_table import TableSpec

SPEC = TableSpec(
    layout=LAYOUT, name="equation block", prefix="eqn",
    entries_skill="equation-entries", reaction_skill="equation-reaction",
    validate_table=validate_table, validate_handles=validate_handles, number_reactions=number_reactions,
    validate_reaction=validate_reaction, ops=OPS, stage2_task=stage2_task,
    block_word="block", entry_word="equation", zoom=True, prepare=prepare, shares_scheme=False,
    # The geometry checks speak of the prepared inventory; the answer has compounds and equations.
    rename=(("template participant '", "compound '"), ("template structure '", "structure '"),
            ("entries[", "equations["), (" (None)", ""),
            ("in no entry, scheme, participant, structure or ignored box; add what is printed there (entries, drawn "
             "catalysts/ligands)", "in no equation, compound, structure or ignored box; add what is printed there (an "
             "equation, a compound, a drawn catalyst or ligand)")),
    turn1_note=("This turn writes the compounds of the block once and every equation with its own participants, "
                "steps, conditions and results. In the next turn you will list the reactions the equations report."),
    stage2_instruction=("Check the reading of this equation for your reaction, read its outcomes, then look the "
                        "experiment up in the main text and the SI: its amounts and scale, and what the equation "
                        "leaves open."),
)


def stage1_sha() -> str:
    return SPEC.stage1_sha()


def stage2_sha() -> str:
    return SPEC.stage2_sha()
