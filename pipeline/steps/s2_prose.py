"""Step 2 for blocks of layout `prose` (experiments reported in words: a paragraph of the main text,
a reference note or an endnote, a paragraph of the methods; nothing drawn in the block, conditions
mostly given by a reference to another reaction plus what was changed).

Stage 1, skill prose-entries, one Codex session with two turns:
  turn 1 reads the passage: the compounds once (boxed where the paper draws that very compound),
         every experiment with a template of its own (participants, steps, conditions, the reaction
         or conditions it is based on, its runs as variants, its results), and what the passage says
         that is no experiment of its own (set_aside)                    -> inventory.json
  turn 2 lists the reactions, one handle each (no turn when the passage reports no experiment)
                                                                         -> handles.json
Stage 2, skill prose-reaction, one new session per reaction (run in parallel):
  checks the reading for the reaction, reads its outcomes (the SI's measured values of the run where
  the passage states a result only in words) and looks the run up in the main text and the SI
                                                                         -> reactions/<rid>.json

The driver is shared with the tables (s2_table); the pure logic is in pipeline/extract_prose.py (the
equation logic, with experiments in place of equations). Prose blocks do not take part in sharing a
general scheme, and the check for ink no box accounts for does not apply: the rest of a paragraph is
text. The session gets the text of every box of the region (a passage often runs on into the next
column or page, and a region may hold several blocks) and images of the boxes that belong to no block.
"""

from __future__ import annotations

import pymupdf

from ..extract_prose import (LAYOUT, OPS, number_reactions, prepare, stage2_task, validate_handles, validate_reaction,
                             validate_table)
from ..extract_records import block_ref, select_blocks
from ..pagetools.grid import render_grid
from ..table_words import load_words, passage_text
from .s2_common import grow
from .s2_table import TableSpec


def _overlaps(a: dict, b: dict) -> bool:
    return a["page"] == b["page"] and pymupdf.Rect(a["bbox"]).intersects(pymupdf.Rect(b["bbox"]))


def _text(job, doc: str, page: int, bbox) -> str:
    tag = next((p["tag"] for p in job.manifests[doc]["pages"] if p["page"] == page), None)
    return passage_text(load_words(job.ws.doc_dir(doc), tag), grow(bbox, 2)) if tag else ""


def stage1_task(job, region: dict, block: dict) -> dict:
    """The block's text, the text of every box of its region (where the passage starts or runs on),
    the region's other blocks, whose sentences are not this block's, and the blocks the paper's
    experiments are read in (a passage that restates one of their entries leaves it to them). The
    text layer as lines is not given: a passage is read as running text."""
    doc = region["doc"]
    me = block_ref(region, block)
    return {
        "text_layer": None,
        "block_text": _text(job, doc, block["page"], block["bbox"]),
        "passages": [{"page": b["page"], "bbox": b["bbox"], "this_block": _overlaps(b, block),
                      "text": _text(job, doc, b["page"], b["bbox"])} for b in region["boxes"]],
        "other_blocks": [{k: b.get(k) for k in ("block_id", "title", "page", "bbox", "layout")}
                         for b in region["blocks"] if b["block_id"] != block["block_id"]],
        "blocks_of_paper": [{"ref": block_ref(r, b), "doc": r["doc"], "label": r.get("label"), "title": b.get("title"),
                             "page": b["page"], "layout": b.get("layout")}
                            for r, b in select_blocks(job.regions) if block_ref(r, b) != me],
    }


def extra_images(job, region: dict, block: dict, tasks_dir):
    """Images of the region's boxes that lie in no block box: where the passage runs on into another
    column or onto another page. Returns (paths, what the prompt says about them)."""
    rest = [b for b in region["boxes"] if not any(_overlaps(b, x) for x in region["blocks"])]
    paths = []
    with job.pdf_lock:
        for i, box in enumerate(rest, 1):
            paths.append(tasks_dir / f"table__more{i}.png")
            img, _, _ = render_grid(job._page(region["doc"], box["page"]), grow(box["bbox"], 6))
            img.save(paths[-1])
    if not paths:
        return [], ""
    pages = ", ".join(str(b["page"]) for b in rest)
    return paths, (f" The last {len(paths)} image(s) show the rest of the region (page {pages}): where the passage "
                   "starts or runs on.")


SPEC = TableSpec(
    layout=LAYOUT, name="prose passage", prefix="prose",
    entries_skill="prose-entries", reaction_skill="prose-reaction",
    validate_table=validate_table, validate_handles=validate_handles, number_reactions=number_reactions,
    validate_reaction=validate_reaction, ops=OPS, stage2_task=stage2_task,
    block_word="passage", entry_word="experiment", scheme_image=True, prepare=prepare, shares_scheme=False,
    coverage=False, stage1_task=stage1_task, extra_images=extra_images,
    layer_note=(" The task file gives the text of the block (block_text) and of every box of its region (passages), "
                "from the text layer: check numbers, superscripts, Greek letters and the middle dot against the image."),
    # The geometry checks speak of the prepared inventory; the answer has compounds and experiments.
    rename=(("template participant '", "compound '"), ("template structure '", "structure '"),
            ("entries[", "experiments["), (" (None)", "")),
    turn1_note=("This turn writes the compounds of the passage once, every experiment it reports with its own "
                "participants, steps, conditions, runs and results, and what it says that is no experiment of its "
                "own (set_aside). In the next turn you will list the reactions the experiments report."),
    stage2_instruction=("Check the reading of this experiment for your reaction, read its outcomes, then look the run "
                        "up in the main text and the SI: its amounts and scale, what the passage leaves open, and the "
                        "measured values of a result the passage states only in words."),
)


def stage1_sha() -> str:
    return SPEC.stage1_sha()


def stage2_sha() -> str:
    return SPEC.stage2_sha()
