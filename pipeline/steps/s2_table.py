"""Step 2 for blocks whose layout has skills of its own: condition tables (s2_ctable), reactant
tables (s2_rtable), product scopes (s2_pscope, a figure read as a table without a header: its
entries are the rows), equation blocks (s2_equation: every equation is an entry with a template
of its own, which `ops.template_of` builds) and prose passages (s2_prose: the same, with the
experiments a passage reports in words). All run the same two stages; a `TableSpec` names the
skills, the schemas and the pure functions of the layout.

Stage 1, skill <layout>-entries, one Codex session with two turns:
  turn 1 reads the table: template, columns, every printed row as cells   -> inventory.json
  turn 2 lists the reactions of the table, one handle each              -> handles.json
Stage 2, skill <layout>-reaction, one new session per reaction (run in parallel):
  checks the table reading for the reaction, writes what its row changes, reads its outcomes and
  looks the entry up in the main text and the SI                        -> reactions/<rid>.json

The pure logic (validation, assembly of records and views) is in pipeline/extract_ctable.py,
pipeline/extract_rtable.py, pipeline/extract_pscope.py, pipeline/extract_equation.py and
pipeline/extract_prose.py; the generic driver (s2_extract) runs these functions on its thread pool
and publishes their views.

Files in step2/blocks/<slug>/: inventory.json (shaped like a generic block reader's, so a block
that shares the scheme reads its participants as usual), handles.json, reactions/<rid>.json,
tasks/, crops/ (_template__*, _structure__*, _cell__<structure key>, eNNN__entry), overlay_pNNN.png.
Every answer stores the hash of its task (which embeds what the stage before it wrote), of the
skill files and of the Codex config: a re-run only redoes what is missing, failed or stale.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pymupdf

from ..config import REPO_ROOT, repo_rel
from ..extract_ctable import assemble_view, drawn_cells, entry_of, structure_key
from ..extract_records import block_ref, block_slug, resolve_protocol, safe, section_for
from ..pagetools.crop import render_clip
from ..pagetools.grid import render_grid
from ..pagetools.trim import edge_severity, ink_edges
from ..papers import write_json
from ..geometry_candidates import attach as candidate_images
from ..table_words import load_words, table_lines
from .s2_common import files_sha, grow, load_json, sha

SHARED_CORE = REPO_ROOT / ".agents" / "shared" / "extract-core.md"
SKILLS = REPO_ROOT / ".agents" / "skills"
SCHEMA_DIR = REPO_ROOT / "pipeline" / "schemas"


@dataclass(frozen=True)
class TableSpec:
    layout: str            # the Step 1 block layout this spec reads
    name: str              # how prompts and logs call the table ("condition table")
    prefix: str            # schema file prefix ("ctable" -> ctable_entries.schema.json, ...)
    entries_skill: str     # stage 1
    reaction_skill: str    # stage 2
    validate_table: Callable
    validate_handles: Callable
    number_reactions: Callable
    validate_reaction: Callable
    ops: object            # base_row / entry_unit / printed / synthesize for assemble_view
    stage2_task: Callable | None = None   # (task, inv, handles, reaction) -> extra keys for the stage 2 task
    stage2_instruction: str = ""          # what stage 2 does, for its prompt
    scheme_image: bool = False            # stage 2 also gets the general scheme when it is on another page
    name_unlabelled: bool = False         # stage 2's prompt names an entry without a printed label as its records do
    block_word: str = "table"             # what prompts call the block ("figure" for a product scope)
    zoom: bool = False                    # stage 1 also gets close-ups of the block (small print, many boxes)
    # A layout whose answer of turn 1 has a shape of its own: `prepare` turns it, in place and once it is
    # valid, into the inventory shape the driver works on (template, columns, entries, ignored, notes).
    prepare: Callable | None = None
    shares_scheme: bool = True            # takes the participants of a shared general scheme from its leader
    entry_word: str = "row"               # what prompts call one entry ("equation" for an equation block)
    # (old, new) replacements that put the messages of the shared geometry checks, which speak of the
    # inventory shape, in the words of the layout's own answer.
    rename: tuple = ()
    turn1_note: str = ("This turn writes the template, the columns and every row as cells. In the next turn you "
                       "will list the reactions the rows report.")
    # Ink inside the block that no box of the answer accounts for is sent back (not for a passage of text,
    # whose other sentences are ink too).
    coverage: bool = True
    # (job, region, block) -> more keys for the task of turn 1 (they go into its hash).
    stage1_task: Callable | None = None
    # (job, region, block, tasks dir) -> (more images for turn 1, what the prompt says about them).
    extra_images: Callable | None = None
    layer_note: str | None = None          # what the prompt of turn 1 says about the text of the block
    _schema_cache: dict = field(default_factory=dict, compare=False, repr=False)

    def schema_path(self, name: str) -> Path:
        return SCHEMA_DIR / f"{self.prefix}_{name}.schema.json"

    def schema(self, name: str) -> dict:
        if name not in self._schema_cache:
            self._schema_cache[name] = json.loads(self.schema_path(name).read_text(encoding="utf-8"))
        return self._schema_cache[name]

    def stage1_sha(self) -> str:
        return files_sha([SHARED_CORE, SKILLS / self.entries_skill / "SKILL.md", self.schema_path("entries"),
                          self.schema_path("handles")])

    def stage2_sha(self) -> str:
        return files_sha([SHARED_CORE, SKILLS / self.reaction_skill / "SKILL.md", self.schema_path("reaction")])


# ------------------------------------------------------------------ tasks and hashes

def _text_layer(job, region: dict, block: dict):
    """The text layer of the block area as lines (None for a drawn or scanned table)."""
    doc = region["doc"]
    page = next((p for p in job.manifests[doc]["pages"] if p["page"] == block["page"]), None)
    if page is None:
        return None
    return table_lines(load_words(job.ws.doc_dir(doc), page["tag"]), grow(block["bbox"], 4))


def entries_task(spec: TableSpec, job, region: dict, block: dict):
    task = job._base_task(spec.entries_skill, region, block)
    task["shared_participants"] = job._shared_participants(region, block) if spec.shares_scheme else None
    task["text_layer"] = _text_layer(job, region, block)
    if spec.stage1_task is not None:
        task.update(spec.stage1_task(job, region, block))
    task["geometry_contract"] = 3  # candidates + semantic/geometry-separated bounded repair
    task["locate_geometry_issues"] = block.get("locate_geometry_issues", [])
    if spec.layout in ("reactant_table", "product_scope"):
        task["variable_contract"] = ("Every printed row-specific assignment belongs in a variable column with "
                                     "explicit targets, not only in descriptor or participant text. Shared "
                                     "drawings use empty same_as cells; put changing values in separate cells.")
    return task, sha(task, spec.stage1_sha(), job.codex_cfg)


def template_for(spec: TableSpec, inv: dict, reaction: dict) -> dict:
    """The template one reaction runs: the table's, or what the layout builds for it (an equation's own)."""
    of = getattr(spec.ops, "template_of", None)
    return of(inv, reaction) if of else inv["template"]


def handles_hash(spec: TableSpec, job, inv: dict) -> str:
    reading = {k: inv[k] for k in ("template", "columns", "entries")}
    return sha(inv["_meta"].get("hash"), reading, spec.stage1_sha(), job.codex_cfg)


def reaction_task(spec: TableSpec, job, region: dict, block: dict, inv: dict, handles: dict, reaction: dict):
    t, en = template_for(spec, inv, reaction), entry_of(inv, reaction)
    row = spec.ops.base_row(inv, reaction)
    variant = next((v for v in t["variants"] if v["key"] == reaction["variant"]), None)
    footnotes = {f["marker"]: f["text"] for f in t["footnotes"]}
    task = job._base_task(spec.reaction_skill, region, block)
    task["template"] = t
    task["columns"] = inv["columns"]
    task["entry"] = {**{k: en[k] for k in ("eid", "label", "page", "bbox", "descriptor")},
                     "cells": [{**c, "structure_key": structure_key(en["eid"], c["column"])
                                if c["structure_bbox"] is not None else None} for c in en["cells"]]}
    task["reaction"] = {
        **{k: reaction[k] for k in ("rid", "results", "results_text", "variant", "footnote_markers", "distinguishing")},
        "variant_title": variant["title"] if variant else None,
        "footnotes": [{"marker": m, "text": footnotes.get(m)} for m in reaction["footnote_markers"]],
        "variables": row["variables"], "drawn_structures": row["drawn_structures"],
    }
    task["protocol"] = resolve_protocol(t, row)
    task["other_reactions_of_entry"] = [{k: r[k] for k in ("rid", "results_text", "variant", "distinguishing")}
                                        for r in handles["reactions"]
                                        if r["entry"] == reaction["entry"] and r["rid"] != reaction["rid"]]
    task["other_entries"] = [{k: e[k] for k in ("eid", "label", "page", "bbox", "descriptor")}
                             for e in inv["entries"] if e["eid"] != en["eid"]]
    if spec.stage2_task is not None:
        task.update(spec.stage2_task(task, inv, handles, reaction))
    return task, sha(task, spec.stage2_sha(), job.codex_cfg)


# Codex errors that mean the session of turn 1 can no longer be resumed: read the table again.
DEAD_THREAD = ("no rollout found", "thread not found", "session that read the table is unknown")
# Step 1 may have searched only the main text; Step 2 reads every document.
SCOPE_NOTE = ("`documents` lists every document of the paper, the SI included: read it as the skill says, whatever "
              "the notes of the locate step say about its own scope.")


def _failed(error: str) -> dict:
    return {"status": "failed", "errors": [error], "warnings": [], "repair_rounds": 0, "usage": {},
            "usage_total": {}, "seconds": 0.0, "thread_id": None}


# ------------------------------------------------------------------ stage 1

def run_block(spec: TableSpec, job, region: dict, block: dict, expand: bool = True) -> dict:
    """Stage 1 of one table (turn 1, then turn 2 when `expand`). The reactions it lists are
    reported on the job's event queue, so that their stage 2 sessions start right away."""
    inv = read_table(spec, job, region, block)
    job.events.put(("template", block_ref(region, block)))
    if not expand or inv["_meta"]["status"] != "ok":
        return inv
    handles = list_reactions(spec, job, region, block, inv)
    hmeta = handles["_meta"]
    if hmeta["status"] != "ok" and any(m in e for e in hmeta["errors"] for m in DEAD_THREAD):
        # The session that read the table is gone (pruned, another machine): read it again in a new one.
        job.log.warning("table %s: its session cannot be resumed; reading the table again", block_ref(region, block))
        inv = read_table(spec, job, region, block, fresh=True)
        if inv["_meta"]["status"] != "ok":
            return inv
        handles = list_reactions(spec, job, region, block, inv)
    if handles["_meta"]["status"] == "ok" and job.cfg.extract.entries:
        job.events.put(("table", (spec, region, block, inv, handles)))
    return inv


def _trim_cells(job, doc: str, inv: dict) -> list[str]:
    """Tighten the boxes of drawn values to their ink. Needs pdf_lock."""
    errors: list[str] = []
    for i, en in enumerate(inv["entries"]):
        for c in en["cells"]:
            if c["structure_bbox"] is not None:
                c["structure_bbox"] = job._trim(doc, en["page"], c["structure_bbox"],
                                                f"entries[{i}] cell '{c['column']}' structure_bbox", errors)
    return errors


def _cell_crops(job, doc: str, inv: dict, bdir) -> None:
    """Crops of the drawn values (a ligand or a reactant drawn in a row). Needs pdf_lock."""
    crops = bdir / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    for old in crops.glob("_cell__*.png"):
        old.unlink()
    for en in inv["entries"]:
        for key, c in drawn_cells(en).items():
            render_clip(job._page(doc, en["page"]), c["structure_bbox"], crops / f"_cell__{safe(key)}.png",
                        dpi=250, margin=2)


AUTO_PAD_MAX = 8.0  # pt: a box cut by less than this is settled by widening it to white paper
AUTO_PAD_STEP = 0.5


def _settle_page_box(page, bbox, max_pad: float = AUTO_PAD_MAX, step: float = AUTO_PAD_STEP):
    """Widen `bbox` along the sides that touch ink until those sides reach paper (at most `max_pad`
    points, never past the page edge). Returns (box, remaining sides).

    Trimming leaves a white margin with `trim_bbox`; this covers the other half of the same problem:
    a reader that gives a tight box on one side gets that side pushed out, while a real cut or a
    neighbouring structure keeps touching the ink and is returned for re-boxing."""
    rect = pymupdf.Rect(bbox) & page.rect
    sides = ink_edges(page, rect)
    if not sides:
        return rect, []
    limits = {"left": page.rect.x0, "top": page.rect.y0, "right": page.rect.x1, "bottom": page.rect.y1}
    for _ in range(4 * int(max_pad / step) + 4):
        if not sides:
            return rect, []
        side = sides[0]
        found = False
        for pad in (step * i for i in range(1, int(max_pad / step) + 1)):
            test = pymupdf.Rect(rect)
            if side == "left":
                test.x0 = max(limits["left"], rect.x0 - pad)
            elif side == "top":
                test.y0 = max(limits["top"], rect.y0 - pad)
            elif side == "right":
                test.x1 = min(limits["right"], rect.x1 + pad)
            else:
                test.y1 = min(limits["bottom"], rect.y1 + pad)
            if side not in ink_edges(page, test):
                rect, found = test, True
                break
        if not found:
            return rect, sides
        sides = ink_edges(page, rect)
    return rect, sides


def _settle_box_edges(job, doc: str, inv: dict) -> tuple[list[str], list[str]]:
    """Settle touching boxes by widening them (bounded) and report the ones that stay cut.
    Returns (errors, warnings); the widened boxes are written back in place. Needs pdf_lock."""
    t = inv["template"]
    items = [(f"template/participants/{i}", f"template participant '{p['key']}'", p["page"], p, "bbox", True)
             for i, p in enumerate(t["participants"]) if p["bbox"]]
    items += [(f"template/structures/{i}", f"template structure '{x['key']}'", x["page"], x, "bbox", True)
              for i, x in enumerate(t["structures"]) if x["bbox"]]
    items += [(f"entries/{i}/cells/{j}", f"entries[{i}] cell '{c['column']}'", en["page"], c, "structure_bbox", False)
              for i, en in enumerate(inv["entries"]) for j, c in enumerate(en["cells"]) if c["structure_bbox"]]
    errors, warnings = [], []
    for tid, where, page, target, field, blocking in items:
        if page not in job._page_sizes(doc):
            continue
        old = list(target[field])
        # A shared scheme structure may be wide; row cells sit in a dense grid, so they get the
        # smaller budget and a touching edge there is a warning anyway.
        box, sides = _settle_page_box(job._page(doc, page), old, max_pad=20 if blocking else AUTO_PAD_MAX)
        target[field] = [round(v, 1) for v in box]
        if sides:
            severity = edge_severity(job._page(doc, page), box)
            cut = [s for s in sides if severity.get(s, "cut") == "cut"]
            if cut:
                message = (f"box edge: {where}: ink still runs to the {'/'.join(cut)} edge of "
                           f"{[round(v, 1) for v in box]}; the box may cut the drawing. "
                           "Check the complete-page context and re-box the whole structure with a white margin, "
                           "excluding neighbours; do not accept a fragment.")
                (errors if blocking else warnings).append(message)
            else:
                warnings.append(f"box edge: {where}: ink touches the {'/'.join(sides)} edge of "
                                f"{[round(v, 1) for v in box]} but the drawing's body stays inside")
        elif target[field] != old:
            warnings.append(f"box edge: {where}: widened {old} -> {target[field]} to clear the ink")
    return errors, warnings


def _box_edge_issues(job, doc: str, inv: dict) -> list[tuple[str, str]]:
    """(target id, message) for structure boxes whose ink runs to an edge: the box may cut the
    drawing. The id matches `geometry_repair.targets`, so only these boxes are re-located.
    Needs pdf_lock."""
    t, out = inv["template"], []
    boxes = [(f"template/participants/{i}", f"template participant '{p['key']}'", p["page"], p["bbox"])
             for i, p in enumerate(t["participants"]) if p["bbox"]]
    boxes += [(f"template/structures/{i}", f"template structure '{x['key']}'", x["page"], x["bbox"])
              for i, x in enumerate(t["structures"])]
    for tid, where, page, bbox in boxes:
        if page in job._page_sizes(doc):
            sides = ink_edges(job._page(doc, page), bbox)
            cut = [s for s in sides if edge_severity(job._page(doc, page), bbox).get(s, "cut") == "cut"]
            if cut:
                out.append((tid, f"box edge: {where}: ink runs to the {'/'.join(cut)} edge of {bbox}; the box may "
                                 "cut the drawing (or touch a neighbour). Check the complete-page context and re-box "
                                 "the whole structure with a white margin, excluding neighbours; do not accept a "
                                 "fragment."))
    return out


def _box_edges(job, doc: str, inv: dict) -> list[str]:
    """Messages of `_box_edge_issues`. Needs pdf_lock."""
    return [message for _, message in _box_edge_issues(job, doc, inv)]


def _renamed(spec: TableSpec, messages: list[str]) -> list[str]:
    out = []
    for m in messages:
        for old, new in spec.rename:
            m = m.replace(old, new)
        out.append(m)
    return out


def read_table(spec: TableSpec, job, region: dict, block: dict, fresh: bool = False) -> dict:
    """Turn 1: the template, the columns and every row as cells. `fresh`: ignore a cached answer."""
    ref, bdir, slug, doc = block_ref(region, block), job._block_dir(region, block), block_slug(region, block), region["doc"]
    task, task_hash = entries_task(spec, job, region, block)
    cached = None if fresh else load_json(bdir / "inventory.json")
    if cached and cached["_meta"].get("hash") == task_hash and cached["_meta"]["status"] == "ok":
        job.log.info("table %s: cached (%d rows)", ref, len(cached["entries"]))
        return cached

    scratch = job.out / "scratch" / f"{slug}__table"
    scratch.mkdir(parents=True, exist_ok=True)
    (bdir / "tasks").mkdir(parents=True, exist_ok=True)
    task_path = bdir / "tasks" / "table.json"
    write_json(task_path, {**task, "scratch": repo_rel(scratch)})
    shared = task["shared_participants"]
    # Candidate overlays have no coordinate grid, so they go before the whole-page context; the
    # page image stays last and the prompt can call it "the last image".
    appendix_images, appendix_note = [], ""
    if spec.layout in ("condition_table", "reactant_table", "product_scope"):
        more, note = candidate_images(job, doc, block, task["block"]["scheme"], bdir / "tasks" / "geometry")
        appendix_images, appendix_note = more, note
    if spec.extra_images is not None:
        more, note = spec.extra_images(job, region, block, bdir / "tasks")
        appendix_images, appendix_note = appendix_images + more, appendix_note + note
    images, scheme_note = job._block_images(doc, block, task["block"]["scheme"], bdir / "tasks", "table",
                                            zoom=spec.zoom, appendix=(appendix_images, appendix_note))
    layer = (spec.layer_note if spec.layer_note is not None
             else " The task file gives the text layer of the block area (text_layer)." if task["text_layer"]
             else f" The {spec.block_word}'s text is not in the text layer: read it from the image.")
    prompt = (
        f"Use the ${spec.entries_skill} skill.\n\n"
        f"Task file: {repo_rel(task_path)} ({spec.name}, turn 1)\n"
        f"Attached image: the block on page {block['page']} of '{doc}', with a point grid.{scheme_note}{layer}\n"
        f"Read what the main text and the SI say about this {spec.block_word} before you fix the template. "
        f"{SCOPE_NOTE}\n"
        f"{spec.turn1_note}\n\n"
        "Your final message must be only the JSON object required by the output schema."
    )
    sizes = job._page_sizes(doc)

    def check(data):
        errors, warnings = spec.validate_table(data, spec.schema("entries"), sizes, block["n_entries_est"],
                                               job.doc_pages)
        if errors:
            return errors, warnings
        if spec.prepare is not None:
            spec.prepare(data)
        own = copy.deepcopy(data["template"]["participants"])
        errors += job._apply_shared(data, shared)
        # (A layout that prepares its answer does not share a scheme: its prepared data would not validate again.)
        if shared and not errors and spec.prepare is None:
            # The leader's participants replaced this template's. Where they contradict this block's rows (a position
            # the leader holds fixed that these rows vary), this block keeps its own reading: it validated on its own,
            # and failing would not help, since the leader's participants come back in every repair round.
            clash = spec.validate_table(data, spec.schema("entries"), sizes, block["n_entries_est"], job.doc_pages)[0]
            if clash:
                data["template"]["participants"] = own
                warnings += [f"the participants of the shared scheme were not taken over from the block that leads it, "
                             f"since they contradict this block: {e}" for e in clash]
        if errors:
            return errors, warnings
        with job.pdf_lock:
            errors += _renamed(spec, job._inventory_geometry(doc, block, data, coverage=spec.coverage))
            errors += _trim_cells(job, doc, data)
            # A tight box is settled here by widening it to white paper. Only boxes that stay in
            # ink (a real cut or a neighbour) reach the bounded re-location repair below.
            edge_errors, edge_warnings = _settle_box_edges(job, doc, data)
            errors += _renamed(spec, edge_errors)
            warnings += _renamed(spec, edge_warnings)
        return errors, warnings

    def repair_geometry(data, round_no, errors):
        from ..geometry_repair import repair
        directory = bdir / "geometry-repair" / f"round-{round_no}"
        write_json(directory / "source.json", data)
        write_json(directory / "validation-errors.json", errors)
        # Only the boxes that failed the edge check are re-located; the rest of the answer is
        # kept, so a bad reader call cannot re-draw boxes that were already right.
        with job.pdf_lock:
            bad_ids = [tid for tid, _ in _box_edge_issues(job, doc, data)]
        repaired = repair(data, job, doc, directory, only_ids=bad_ids)
        audit = load_json(directory / "audit.json") or {}
        write_json(directory / "repaired.json", repaired)
        return repaired, {"audit": str(directory / "audit.json"), "thread_id": audit.get("thread_id"),
                          "usage": audit.get("usage", {}), "method": "automatic-bbox-only",
                          "targets": bad_ids}

    job.log.info("table %s: start", ref)
    repair_options = {"geometry_repair": repair_geometry} if spec.prepare is None else {}
    data, meta = job._codex(spec.schema_path("entries"), prompt, images, bdir / "inventory_raw.json",
                            job.ws.log_dir / "step2" / f"{slug}__table.jsonl", job.cfg.extract.inventory_timeout_s, check,
                            **repair_options)
    if block.get("locate_geometry_issues"):
        meta["warnings"] += block["locate_geometry_issues"]
    meta["hash"], meta["layout"] = task_hash, spec.layout
    job._soften_coverage(meta)

    inv = {"template": None, "columns": [], "entries": [], "ignored": [], "notes": ""}
    if data is not None and meta["status"] == "ok":
        inv = data
        for i, r in enumerate(inv["entries"], 1):
            r["eid"] = f"e{i:03d}"
        extra = [("structure", key, en["page"], c["structure_bbox"])
                 for en in inv["entries"] for key, c in drawn_cells(en).items()]
        with job.pdf_lock:
            meta["overlays"] = job._overlays(doc, block, inv, bdir, extra)
            job._template_crops(doc, inv, bdir)
            _cell_crops(job, doc, inv, bdir)
    inv["_meta"] = meta
    write_json(bdir / "inventory.json", inv)
    job.log.info("table %s: %s, %d rows, %.0fs%s", ref, meta["status"], len(inv["entries"]), meta["seconds"],
                 f", errors: {meta['errors'][:3]}" if meta["errors"] else "")
    return inv


def list_reactions(spec: TableSpec, job, region: dict, block: dict, inv: dict) -> dict:
    """Turn 2, in the same session: the reactions of the table, one handle each."""
    ref, bdir, slug = block_ref(region, block), job._block_dir(region, block), block_slug(region, block)
    h_hash = handles_hash(spec, job, inv)
    path = bdir / "handles.json"
    cached = load_json(path)
    if cached and cached["_meta"].get("hash") == h_hash and cached["_meta"]["status"] == "ok":
        job.log.info("reactions %s: cached (%d)", ref, len(cached["reactions"]))
        return cached

    prompt = (
        f"Turn 2. Go through the {spec.entry_word}s you wrote and list the reactions the {spec.block_word} reports, "
        f"one handle each, in {spec.entry_word} order, following the section 'Turn 2: the reactions' of the skill.\n\n"
        f"Use the validated inventory at {repo_rel(bdir / 'inventory.json')} as the authoritative table reading; "
        "its structure boxes may have been corrected independently after your last turn.\n\n"
        "Your final message must be only the JSON object required by the output schema."
    )
    thread = inv["_meta"].get("thread_id")
    if not inv["entries"]:
        # Nothing to list (a passage that reports no experiment of its own): no turn needed.
        data = {"reactions": [], "notes": [], "issues": []}
        meta = {**_failed(""), "status": "ok", "errors": [], "thread_id": thread}
    elif not thread:
        data, meta = None, _failed("codex: the session that read the table is unknown")
    else:
        data, meta = job._codex(spec.schema_path("handles"), prompt, [], bdir / "handles_raw.json",
                                job.ws.log_dir / "step2" / f"{slug}__table.jsonl", job.cfg.extract.expand_timeout_s,
                                lambda d: spec.validate_handles(d, inv, spec.schema("handles")),
                                thread_id=thread, prior=inv["_meta"].get("usage_total"))
    meta["hash"] = h_hash
    handles = {"reactions": [], "notes": [], "issues": []}
    if data is not None and meta["status"] == "ok":
        handles = {**data, "reactions": spec.number_reactions(inv, data)}
    handles["_meta"] = meta
    write_json(path, handles)
    job.log.info("reactions %s: %s, %d reactions, %.0fs%s", ref, meta["status"], len(handles["reactions"]),
                 meta["seconds"], f", errors: {meta['errors'][:3]}" if meta["errors"] else "")
    return handles


# ------------------------------------------------------------------ stage 2

def collect_reaction(spec: TableSpec, job, region: dict, block: dict, inv: dict, handles: dict,
                     reaction: dict) -> dict:
    """Stage 2: one reaction of the table, in a session of its own."""
    rid, bdir, slug, doc = reaction["rid"], job._block_dir(region, block), block_slug(region, block), region["doc"]
    ref = f"{block_ref(region, block)}/{rid}"
    task, task_hash = reaction_task(spec, job, region, block, inv, handles, reaction)
    path = bdir / "reactions" / f"{rid}.json"
    cached = load_json(path)
    if cached and cached["_meta"].get("hash") == task_hash and cached["_meta"]["status"] == "ok":
        return cached

    scratch = job.out / "scratch" / f"{slug}__{rid}"
    scratch.mkdir(parents=True, exist_ok=True)
    task_path = bdir / "tasks" / f"{rid}.json"
    write_json(task_path, {**task, "scratch": repo_rel(scratch)})
    en = entry_of(inv, reaction)
    context, closeup = bdir / "tasks" / f"{rid}__context.png", bdir / "tasks" / f"{rid}__row.png"
    images = [context, closeup]
    # The general reaction: what the locate step linked, else where stage 1 found it (a pointer in the caption).
    scheme = task["block"]["scheme"] or inv["template"]["scheme"]
    with job.pdf_lock:
        page = job._page(doc, en["page"])
        if en["page"] == block["page"]:
            area = pymupdf.Rect(block["bbox"]) | pymupdf.Rect(en["bbox"])
            if scheme and scheme["page"] == en["page"]:
                area |= pymupdf.Rect(scheme["bbox"])  # the header reaction the row modifies
            clip = grow(area, 6)
        else:
            b = en["bbox"]
            clip = [b[0] - 20, b[1] - 60, b[2] + 20, b[3] + 60]
        img, _, _ = render_grid(page, clip, outline=[en["bbox"]])
        img.save(context)
        img, _, _ = render_grid(page, grow(en["bbox"], 10), max_px=1400)
        img.save(closeup)
        scheme_elsewhere = bool(spec.scheme_image and scheme and scheme["page"] != en["page"])
        if scheme_elsewhere:
            images.append(bdir / "tasks" / f"{rid}__scheme.png")
            img, _, _ = render_grid(job._page(doc, scheme["page"]), grow(scheme["bbox"], 6))
            img.save(images[-1])

    results = "; ".join(reaction["results_text"]) or "none printed"
    # An entry may have no label of its own (those of a figure): it is then called as its records are, where the
    # layout's records call it by a compound number; a table row is named only by what it prints.
    name = en["label"] or (spec.ops.entry_unit(inv, en)["label"] if spec.name_unlabelled else "")
    label = "" if not name else f", {name}" if name.startswith(("row ", "entry ")) else f", entry {name}"
    scheme_note = f"; (3) the general scheme on page {scheme['page']}" if scheme_elsewhere else ""
    prompt = (
        f"Use the ${spec.reaction_skill} skill.\n\n"
        f"Task file: {repo_rel(task_path)} ({spec.name}, reaction {rid}{label}; results: {results})\n"
        f"Attached images: (1) page {en['page']} of '{doc}' around the {spec.block_word}, with a point grid and "
        f"the {spec.entry_word} outlined in red; (2) a close-up of the {spec.entry_word} with a finer grid{scheme_note}.\n"
        f"{spec.stage2_instruction} {SCOPE_NOTE}\n\n"
        "Your final message must be only the JSON object required by the output schema."
    )
    data, meta = job._codex(spec.schema_path("reaction"), prompt, images, bdir / "reactions" / f"{rid}_raw.json",
                            job.ws.log_dir / "step2" / f"{slug}__{rid}.jsonl", job.cfg.extract.entry_timeout_s,
                            lambda d: spec.validate_reaction(d, spec.schema("reaction"), inv, reaction, job.doc_pages))
    meta["hash"] = task_hash
    result = dict(data) if data is not None else {}
    result["_meta"] = meta
    write_json(path, result)
    job.log.info("reaction %s: %s, %.0fs%s", ref, meta["status"], meta["seconds"],
                 f", errors: {meta['errors'][:2]}" if meta["errors"] else "")
    return result


# ------------------------------------------------------------------ publish

def block_view(spec: TableSpec, job, region: dict, block: dict):
    """The block as publish() gathers it, from what is on disk.
    Returns (view, records, counts, metas, seconds), or None before turn 1 ever ran."""
    bdir, slug = job._block_dir(region, block), block_slug(region, block)
    inv = load_json(bdir / "inventory.json")
    if inv is None or not isinstance(inv.get("_meta"), dict):
        return None
    _, task_hash = entries_task(spec, job, region, block)
    meta = inv["_meta"]
    # An inventory of another kind (written by the generic path, another layout, or an older version) is only stale.
    current = meta.get("hash") == task_hash and meta.get("layout") == spec.layout
    inv_status = meta.get("status", "failed") if current else "stale"
    if inv_status != "ok":
        view, records, counts = assemble_view(region, block, slug, inv, inv_status, None, None, {}, {}, {}, {},
                                              ops=spec.ops)
        return view, records, counts, [meta], meta.get("seconds", 0)
    metas, seconds = [meta], meta.get("seconds", 0)
    handles, h_status, answers = None, None, {}
    handles = load_json(bdir / "handles.json")
    if handles is not None:
        hmeta = handles["_meta"]
        metas.append(hmeta)
        seconds += hmeta.get("seconds", 0)
        h_status = hmeta["status"] if hmeta.get("hash") == handles_hash(spec, job, inv) else "stale"
    if handles is not None and h_status == "ok":
        limit = job.cfg.extract.limit
        for i, r in enumerate(handles["reactions"]):
            answer = load_json(bdir / "reactions" / f"{r['rid']}.json")
            if answer is None:
                answers[r["rid"]] = (None, "skipped" if limit and i >= limit else "pending")
                continue
            ameta = answer["_meta"]
            metas.append(ameta)
            seconds += ameta.get("seconds", 0)
            _, a_hash = reaction_task(spec, job, region, block, inv, handles, r)
            answers[r["rid"]] = (answer, ameta["status"] if ameta.get("hash") == a_hash else "stale")

    template = inv["template"] or {"participants": [], "structures": []}
    template_crops = {p["key"]: f"blocks/{slug}/crops/_template__{safe(p['key'])}.png"
                      for p in template["participants"] if p["bbox"] is not None}
    structure_crops = {x["key"]: f"blocks/{slug}/crops/_structure__{safe(x['key'])}.png" for x in template["structures"]}
    cell_crops = {key: f"blocks/{slug}/crops/_cell__{safe(key)}.png"
                  for en in inv["entries"] for key in drawn_cells(en)}
    view, records, counts = assemble_view(region, block, slug, inv, inv_status, handles, h_status, answers,
                                          template_crops, structure_crops, cell_crops,
                                          section_for(job.regions, region["doc"], block["page"]), ops=spec.ops)
    return view, records, counts, metas, seconds
