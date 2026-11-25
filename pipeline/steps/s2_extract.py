"""Step 2: turn every included reaction block into reaction records.

Per block (skill `extract-reactions`):
  A. one Codex session, the block reader:
     turn 1 (inventory) reads the block together with what the main text and the SI say about
     it, writes the template the entries share and lists the entries (what is printed as one
     unit: a drawing with its results, a table row, a paragraph);
     then one turn per entry (expand), in the same session: Python shows it that entry alone, and
     it transcribes what is printed, reasons about how many reactions the entry reports, and
     writes one row per reaction (protocol, alternative used, footnotes, printed changes);
  B. one Codex session per row (entry mode, several at once): boxes of the compounds, the
     outcomes, and what the main text and the SI say about that reaction;
  C. Python merges template + variant + footnotes + row + lookup, crops the boxes and writes
     one record per row.

Blocks of a layout with skills of their own (condition_table, reactant_table, product_scope,
equation, prose; `TABLES`) take the two-stage path of steps/s2_table.py instead. Step 1 gives every
included block one of those layouts, so the generic skill only reads blocks of a layout it does not
know (`other`, which Step 1 excludes, or a regions.json written before layouts existed). It is kept
in .agents/backup/, outside the skills Codex lists, and the prompt names its file.

Structures are not recognised here: participants carry boxes (crops), labels and
printed text only.

Outputs in work/<paper_id>/step2/:
  blocks/<region>__<block>/  inventory.json, expand/<eid>.json, entries/<rid>.json, tasks/,
                             crops/, overlay_pNNN.png
  blocks/<region>__<block>/view.json  the block as a viewer reads it (pipeline/extract_view.py)
  index.json      one line per block, for a viewer
  reactions.json  summary.json
Every result is cached with a hash of its inputs, so a re-run only does what is missing,
failed or outdated.
"""

from __future__ import annotations

import json
import math
import queue
import shutil
import threading
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from ..codex import CodexError, resume_codex, run_codex
from ..config import REPO_ROOT, repo_rel
from ..extract_records import (block_ref, block_slug, build_record, resolve_protocol, safe, section_for,
                               select_blocks, validate_entry, validate_expansion, validate_inventory)
from ..extract_view import block_head, block_view, index as view_index
from ..pagetools.crop import render_clip
from ..pagetools.grid import render_grid
from ..pagetools.trim import trim_bbox, uncovered_blobs
from ..papers import write_json
from . import s2_ctable, s2_equation, s2_prose, s2_pscope, s2_rtable, s2_table
from .s2_common import grow as _grow
from .s2_common import load_json as _load
from .s2_common import numbers as _numbers
from .s2_common import outlined as _outlined
from .s2_common import repair_prompt as _repair_prompt
from .s2_common import sha as _sha
from .s2_common import thread_usage, usage_delta

NAME = "extract"
VERSION = 8

SKILL_NAME = "extract-reactions"
# Not under .agents/skills (no layout of Step 1 uses it): the prompt points at its file.
SKILL_DIR = REPO_ROOT / ".agents" / "backup" / SKILL_NAME
USE_SKILL = f"Read the skill {repo_rel(SKILL_DIR / 'SKILL.md')} ({SKILL_NAME}) and follow it.\n\n"
SCHEMAS = {
    "inventory": REPO_ROOT / "pipeline" / "schemas" / "extract_inventory.schema.json",
    "expand": REPO_ROOT / "pipeline" / "schemas" / "extract_expand.schema.json",
    "entry": REPO_ROOT / "pipeline" / "schemas" / "extract_entry.schema.json",
}
PUBLISH_EVERY_S = 20
# Warnings that belong to the whole block (its geometry and derivations): shown once in the block
# view, not repeated in every record of the block.
BLOCK_ONLY_WARNINGS = ("box edge:", "cannot be derived", "scheme ", "uncovered area", "table ")


def _record_warnings(warnings):
    """The block reader also reports block-wide geometry and derivation problems; a record keeps
    only what concerns itself."""
    return [w for w in warnings if not w.startswith(BLOCK_ONLY_WARNINGS)]

# Block layouts with skills of their own (driven by s2_table), and which of them leads a shared scheme.
TABLES = {spec.layout: spec for spec in (s2_ctable.SPEC, s2_rtable.SPEC, s2_pscope.SPEC, s2_equation.SPEC,
                                         s2_prose.SPEC)}
LEADER_RANK = {s2_ctable.SPEC.layout: 0, s2_rtable.SPEC.layout: 1, s2_pscope.SPEC.layout: 2}
# The layouts that read a general scheme as generic positions their rows or entries fill in.
POSITION_LAYOUTS = (s2_rtable.SPEC.layout, s2_pscope.SPEC.layout)
# The block reader gives up on its remaining entries after this many Codex failures in a row.
MAX_CODEX_FAILURES = 2


def mode_sha(mode: str) -> str:
    files = [SKILL_DIR / "SKILL.md", SKILL_DIR / "references" / f"{mode}.md", SCHEMAS[mode]]
    return _sha([f.read_text(encoding="utf-8") for f in files])


def params(cfg) -> dict:
    ex = cfg.extract
    return {
        "codex": cfg.codex.identity(),
        "blocks": list(ex.blocks) if ex.blocks else None,
        "kinds": list(ex.kinds) if ex.kinds else None,
        "limit": ex.limit,
        "entries": ex.entries,
        "inventory_sha": mode_sha("inventory"),
        "expand_sha": mode_sha("expand"),
        "entry_sha": mode_sha("entry"),
        # blocks of layout condition_table (s2_ctable), reactant_table (s2_rtable) and product_scope (s2_pscope)
        "ctable_entries_sha": s2_ctable.stage1_sha(),
        "ctable_reaction_sha": s2_ctable.stage2_sha(),
        "rtable_entries_sha": s2_rtable.stage1_sha(),
        "rtable_reaction_sha": s2_rtable.stage2_sha(),
        "pscope_entries_sha": s2_pscope.stage1_sha(),
        "pscope_reaction_sha": s2_pscope.stage2_sha(),
        # blocks of layout equation (s2_equation)
        "eqn_entries_sha": s2_equation.stage1_sha(),
        "eqn_reaction_sha": s2_equation.stage2_sha(),
        # blocks of layout prose (s2_prose)
        "prose_entries_sha": s2_prose.stage1_sha(),
        "prose_reaction_sha": s2_prose.stage2_sha(),
    }


def run(ws, cfg, log, force: bool = False) -> dict:
    regions_path = ws.root / "step1" / "regions.json"
    if not regions_path.exists():
        raise RuntimeError("step1/regions.json not found; run the locate step first")
    regions = json.loads(regions_path.read_text(encoding="utf-8"))
    selected = select_blocks(regions, cfg.extract.blocks, cfg.extract.kinds)

    out = ws.root / "step2"
    if force and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    events: queue.Queue = queue.Queue()
    job = _Job(ws, cfg, log, regions, out, events)
    log.info("extract: %d blocks, concurrency %d", len(selected), cfg.extract.concurrency)

    # Blocks that follow the same general scheme share its participants: the leader of each
    # scheme writes its template first and the others reuse what it found.
    selected_refs = {block_ref(r, b) for r, b in selected}
    followers: dict[str, list] = {}
    first = []
    for region, block in selected:
        leader = job.leader_of(block)
        if leader is None or block_ref(*leader) == block_ref(region, block):
            first.append((region, block))
        else:
            followers.setdefault(block_ref(*leader), []).append((region, block))
            if block_ref(*leader) not in selected_refs and leader not in first:
                first.append(leader)  # needed for its participants only; its entries are not read

    def keep_failed_attempt(bdir, attempt, ref):
        """Keep the answer and errors of a failed attempt; the next attempt is a fresh session."""
        keep = Path(bdir) / "attempts" / f"try-{attempt}"
        keep.mkdir(parents=True, exist_ok=True)
        for name in ("inventory.json", "inventory_raw.json", "handles.json", "handles_raw.json"):
            path = Path(bdir) / name
            if path.exists():
                shutil.copy2(path, keep / name)
        errors = []
        path = Path(bdir) / "inventory.json"
        if path.exists():
            try:
                errors = json.loads(path.read_text(encoding="utf-8")).get("_meta", {}).get("errors") or []
            except (OSError, ValueError):
                errors = []
        log.warning("block %s: attempt %d failed (%s); retrying in a fresh session",
                    ref, attempt, errors[0] if errors else "no details")

    def run_block_with_retries(region, block, expand):
        """Bounded automatic retry of a failed block reader (which entry attempts share)."""
        ref, bdir = block_ref(region, block), job._block_dir(region, block)
        attempts, inv = 0, None
        while attempts <= cfg.extract.retries:
            attempts += 1
            try:
                inv = job.block(region, block, expand)
            except Exception:
                log.exception("block %s: attempt %d crashed", ref, attempts)
                inv = {"_meta": {"status": "failed", "errors": ["crashed"], "entries": []}}
            if inv.get("_meta", {}).get("status") == "ok":
                break
            if attempts <= cfg.extract.retries:
                keep_failed_attempt(bdir, attempts, ref)
        if inv is not None:
            inv.setdefault("_meta", {})["attempts"] = attempts
            path = Path(bdir) / "inventory.json"
            if path.exists():
                write_json(path, inv)  # keep the attempt count with the answer it produced
        return inv

    last_publish, crashed = 0.0, 0  # crashed: sessions that died on an unexpected error
    with ThreadPoolExecutor(max_workers=cfg.extract.concurrency) as pool:
        pending = {}

        def start_block(region, block):
            ref = block_ref(region, block)
            pending[pool.submit(run_block_with_retries, region, block, ref in selected_refs)] = ("block", ref)

        def release(ref):
            for r, b in followers.pop(ref, []):
                start_block(r, b)

        for region, block in first:
            start_block(region, block)
        while pending or not events.empty():
            # The block reader reports while it works: its template is ready (followers may
            # start), an entry is spelled out (its reactions may start).
            while not events.empty():
                kind, payload = events.get()
                if kind == "template":
                    release(payload)
                elif kind == "rows" and cfg.extract.entries:
                    region, block, inv, entry, exp = payload
                    for reaction in exp["rows"]:
                        fut = pool.submit(job.entry, region, block, inv, entry, exp, reaction)
                        pending[fut] = ("entry", reaction["rid"])
                elif kind == "table" and cfg.extract.entries:
                    # A table has listed its reactions: one stage-2 session each.
                    spec, region, block, inv, handles = payload
                    limit = cfg.extract.limit
                    for reaction in handles["reactions"][:limit] if limit else handles["reactions"]:
                        fut = pool.submit(s2_table.collect_reaction, spec, job, region, block, inv, handles,
                                          reaction)
                        pending[fut] = ("entry", reaction["rid"])
            if not pending:
                continue
            done, _ = wait(pending, timeout=2, return_when=FIRST_COMPLETED)
            for fut in done:
                kind, ref = pending.pop(fut)
                try:
                    fut.result()
                except Exception:
                    log.exception("%s session %s crashed", kind, ref)
                    crashed += 1
                if kind == "block":
                    release(ref)  # in case its template failed: followers then work without it
            if time.time() - last_publish > PUBLISH_EVERY_S or not pending:
                job.publish_progress()
                last_publish = time.time()
    summary = job.publish()
    if crashed:
        summary["crashed_sessions"] = crashed
    log.info("  -> %s", summary)
    return summary


def sharing_class(block: dict) -> str | None:
    """Blocks share a scheme's participants only when they read it the same way: a reactant table
    and a product scope read it as generic positions that their rows or entries fill in, every
    other layout as specific compounds. An equation block draws its own reactions, a prose passage
    names its own compounds, and neither shares anything (None)."""
    if not TABLES.get(block.get("layout"), s2_ctable.SPEC).shares_scheme:
        return None
    return "positions" if block.get("layout") in POSITION_LAYOUTS else "compounds"


def scheme_leaders(blocks, schemes: dict) -> dict:
    """(scheme_id, sharing class) -> the (region, block) whose template describes the scheme for the
    other blocks of its class that follow it. The block the scheme is drawn in describes it;
    otherwise a condition table (it runs the model reaction the others refer to), then a reactant
    table, then a product scope; otherwise the cheapest one to read that has entries."""
    groups: dict = {}
    for region, block in blocks:
        if block.get("scheme_id") in schemes and sharing_class(block) is not None:
            groups.setdefault((block["scheme_id"], sharing_class(block)), []).append((region, block))
    leaders = {}
    for (sid, cls), members in groups.items():
        if len(members) < 2:
            continue
        sc = schemes[sid]
        outside = lambda rb: not (rb[0]["doc"] == sc["doc"] and rb[1]["page"] == sc["page"] and
                                   pymupdf.Rect(_grow(rb[1]["bbox"], 6)).contains(pymupdf.Rect(sc["bbox"])))
        leaders[(sid, cls)] = min(members, key=lambda rb: (outside(rb), LEADER_RANK.get(rb[1].get("layout"), 2),
                                                          rb[1]["n_entries_est"] == 0, rb[1]["n_entries_est"],
                                                          block_ref(*rb)))
    return leaders


def zoom_pieces(area, overlap: float = 10) -> list[list[float]]:
    """`area` cut into close-ups of about 260 x 200 pt (at most six), in reading order: left to
    right, top to bottom. Neighbours overlap by `overlap` pt, so that a number or a superscript on
    a cut is whole in one of them. Empty when one piece would be the whole area."""
    area = pymupdf.Rect(area)
    cols = max(1, min(3, math.ceil(area.width / 260)))
    rows = max(1, min(math.ceil(area.height / 200), 6 // cols))
    if cols * rows == 1:
        return []
    w, h, d = area.width / cols, area.height / rows, overlap / 2
    return [[max(area.x0, area.x0 + c * w - d), max(area.y0, area.y0 + r * h - d),
             min(area.x1, area.x0 + (c + 1) * w + d), min(area.y1, area.y0 + (r + 1) * h + d)]
            for r in range(rows) for c in range(cols)]


def eid_ranges(eids: list[str]) -> str:
    """One tag for several entry ids: consecutive ones as a range ('e001-e007'), the others listed.
    A plain hyphen: the overlay's font has no en dash."""
    runs: list[list[str]] = []
    for eid in eids:
        if runs and int(eid[1:]) == int(runs[-1][-1][1:]) + 1:
            runs[-1].append(eid)
        else:
            runs.append([eid])
    return ", ".join(run[0] if len(run) == 1 else f"{run[0]}-{run[-1]}" for run in runs)


class _Job:
    def __init__(self, ws, cfg, log, regions, out: Path, events: queue.Queue | None = None):
        self.ws, self.cfg, self.log, self.regions, self.out = ws, cfg, log, regions, out
        self.events = events if events is not None else queue.Queue()
        self.manifests = {doc: json.loads((ws.doc_dir(doc) / "manifest.json").read_text(encoding="utf-8"))
                          for doc in ws.paper.documents()}
        self.schemas = {m: json.loads(p.read_text(encoding="utf-8")) for m, p in SCHEMAS.items()}
        self.shas = {m: mode_sha(m) for m in SCHEMAS}
        self.codex_cfg = cfg.codex.identity()
        self.doc_pages = {doc: m["page_count"] for doc, m in self.manifests.items()}
        self.schemes = {sc["scheme_id"]: sc for sc in regions.get("schemes", [])}
        # (scheme_id, sharing class) -> the included block that describes the scheme for the others
        self.leaders = scheme_leaders(select_blocks(regions), self.schemes)
        # PyMuPDF is not thread-safe: every use of a document happens under this lock.
        self.pdf_lock = threading.Lock()
        self._pdfs: dict = {}

    # ------------------------------------------------------------ helpers

    def _page(self, doc: str, page: int) -> pymupdf.Page:
        if doc not in self._pdfs:
            self._pdfs[doc] = pymupdf.open(self.manifests[doc]["pdf"])
        return self._pdfs[doc][page - 1]

    def _page_sizes(self, doc: str) -> dict:
        return {p["page"]: tuple(p["size_pt"]) for p in self.manifests[doc]["pages"]}

    def _block_dir(self, region, block) -> Path:
        return self.out / "blocks" / block_slug(region, block)

    def leader_of(self, block: dict):
        """The (region, block) whose inventory defines the scheme participants, if shared."""
        return self.leaders.get((block.get("scheme_id"), sharing_class(block)))

    def _shared_participants(self, region: dict, block: dict):
        """Scheme participants already described by the leader block (None for the leader itself)."""
        leader = self.leader_of(block)
        if leader is None or block_ref(*leader) == block_ref(region, block):
            return None
        inv = _load(self._block_dir(*leader) / "inventory.json")
        if inv is None or inv["_meta"]["status"] != "ok":
            return None
        scheme = self.schemes[block["scheme_id"]]
        area = pymupdf.Rect(_grow(scheme["bbox"], 6))
        return [p for p in inv["template"]["participants"]
                if p["bbox"] is not None and p["page"] == scheme["page"] and area.contains(pymupdf.Rect(p["bbox"]))]

    def _base_task(self, mode: str, region: dict, block: dict) -> dict:
        scheme = self.schemes.get(block.get("scheme_id"))
        return {
            "mode": mode,
            "workspace": repo_rel(self.ws.root),
            "doc": region["doc"],
            # Everything the paper consists of: the block is read together with its text and SI.
            "documents": {doc: {"dir": repo_rel(self.ws.doc_dir(doc)), "pages": n}
                          for doc, n in self.doc_pages.items()},
            "paper": {"paper_id": self.ws.paper.paper_id, **self.regions["paper"]},
            "region": {k: region[k] for k in ("region_id", "label", "caption", "kind", "presentation",
                                              "footnotes", "first_page", "last_page", "notes")},
            "block": {**{k: block[k] for k in ("block_id", "title", "kind", "page", "bbox",
                                               "general_reaction", "conditions_text", "n_entries_est",
                                               "labels_seen", "entries_first_page", "entries_last_page",
                                               "notes")},
                      "layout": block.get("layout"),  # absent in regions.json written before it existed
                      "scheme": ({k: scheme[k] for k in ("scheme_id", "page", "bbox", "description")}
                                 if scheme else None)},
        }

    def _inventory_task(self, region, block):
        task = self._base_task("inventory", region, block)
        task["shared_participants"] = self._shared_participants(region, block)
        return task, _sha(task, self.shas["inventory"], self.codex_cfg)

    def _expand_hash(self, inv: dict, entry: dict) -> str:
        return _sha(inv["_meta"].get("hash"), entry, self.shas["expand"], self.codex_cfg)

    def _entry_task(self, region, block, inv, entry, exp, reaction):
        task = self._base_task("entry", region, block)
        task["template"] = inv["template"]
        task["entry"] = {**{k: entry[k] for k in ("eid", "label", "page", "bbox", "descriptor")},
                         "printed": exp["printed"], "results": exp["results"]}
        variant = next((v for v in inv["template"]["variants"] if v["key"] == reaction["variant"]), None)
        footnotes = {f["marker"]: f["text"] for f in inv["template"]["footnotes"]}
        task["reaction"] = {
            **{k: reaction[k] for k in ("rid", "label", "results_text", "variant", "footnote_markers",
                                        "variables", "drawn_structures", "overrides")},
            "variant_title": variant["title"] if variant else None,
            "footnotes": [{"marker": m, "text": footnotes.get(m)} for m in reaction["footnote_markers"]],
        }
        task["protocol"] = resolve_protocol(inv["template"], reaction)
        task["other_reactions_of_entry"] = [{k: r[k] for k in ("rid", "label", "results_text", "variant")}
                                            for r in exp["rows"] if r["rid"] != reaction["rid"]]
        task["other_entries"] = [{k: e[k] for k in ("eid", "label", "page", "bbox")}
                                 for e in inv["entries"] if e["eid"] != entry["eid"]]
        return task, _sha(task, self.shas["entry"], self.codex_cfg)

    def _trim(self, doc: str, page: int, bbox, where: str, errors: list):
        """Tightened box, or the original plus an error when the box is blank."""
        tight = trim_bbox(self._page(doc, page), bbox)
        if tight is None:
            errors.append(f"{where}: bbox {bbox} on page {page} contains no ink")
            return bbox
        return [round(v, 1) for v in tight]

    def _codex(self, schema, prompt, images, raw_path, events, timeout, check, thread_id=None, prior=None,
               geometry_repair=None):
        """Run Codex (a new session, or one more turn of `thread_id`) with the output schema at
        path `schema`, validate with `check(data) -> (errors, warnings)`, repair in the same
        session if needed.

        Codex reports tokens as a running total of the thread. `usage_total` keeps the last total,
        `usage` what this call added to `prior` (the thread's total before it).
        Returns (data | None, meta)."""
        meta = {"status": "failed", "errors": [], "warnings": [], "repair_rounds": 0,
                "usage": {}, "usage_total": dict(_numbers(prior)), "seconds": 0.0, "thread_id": thread_id}
        t0 = time.time()
        data = None
        # Sessions write only to scratch (their own directories under step2/scratch, the page tools'
        # images under the workspace's scratch/), never into the tasks and results of step2.
        writable = (self.out / "scratch", self.ws.root / "scratch")
        try:
            if thread_id:
                res = resume_codex(thread_id, prompt, schema=schema, out_json=raw_path, events_log=events,
                                   cfg=self.cfg.codex, images=images, timeout=timeout, writable=writable)
            else:
                res = run_codex(prompt, schema=schema, out_json=raw_path, events_log=events,
                                cfg=self.cfg.codex, images=images, timeout=timeout, writable=writable)
            data, meta["thread_id"] = res.data, res.thread_id or thread_id
            meta["usage_total"] = _numbers(res.usage) or meta["usage_total"]
            salvaged = res.salvaged
            errors, warnings = check(data)
            while errors and meta["repair_rounds"] < self.cfg.codex.max_repair_rounds and meta["thread_id"]:
                meta["repair_rounds"] += 1
                # Preserve measurements/conditions once only geometry errors remain.
                if geometry_repair and all(e.startswith(("box edge:", "geometry:")) for e in errors):
                    data, metric = geometry_repair(data, meta["repair_rounds"], errors)
                    meta.setdefault("geometry_repairs", []).append(metric)
                    errors, warnings = check(data)
                else:
                    res = resume_codex(meta["thread_id"], _repair_prompt(errors), schema=schema,
                                       out_json=raw_path, events_log=events, cfg=self.cfg.codex,
                                       timeout=timeout, writable=writable)
                    data, salvaged = res.data, res.salvaged
                    meta["usage_total"] = _numbers(res.usage) or meta["usage_total"]
                    errors, warnings = check(data)
            if salvaged:
                warnings = [*warnings, "codex: the final message was not one JSON object (prose around it, or the object repeated); the last complete object in it was taken"]
            meta["errors"], meta["warnings"] = errors, warnings
            meta["status"] = "failed" if errors else "ok"
        except (CodexError, ValueError) as exc:
            meta["errors"] = [f"codex: {exc}"]
        meta["usage"] = usage_delta(meta["usage_total"], prior)
        for repair in meta.get("geometry_repairs", []):
            for key, value in _numbers(repair.get("usage")).items():
                meta["usage"][key] = meta["usage"].get(key, 0) + value
        meta["seconds"] = round(time.time() - t0, 1)
        return data, meta

    def _block_images(self, doc: str, block: dict, scheme, tasks_dir: Path, prefix: str, zoom: bool = False,
                      appendix=None):
        """The block with a point grid, plus its general scheme when that lies outside the block;
        with `zoom`, close-ups of the block after them. `appendix` is optional extra (images, note).
        The continuation pages of a block whose entries run on and the whole source page come last.
        Returns (image paths, what the prompt says about the images after the first)."""
        images = [tasks_dir / f"{prefix}__block.png"]
        appendix_images, appendix_note = appendix if appendix else ([], "")
        block_area = pymupdf.Rect(_grow(block["bbox"], 6))
        note = ""
        with self.pdf_lock:
            page = self._page(doc, block["page"])
            page_rect = page.rect
            img, _, _ = render_grid(page, block_area)
            img.save(images[0])
            if scheme and not (scheme["page"] == block["page"] and block_area.contains(pymupdf.Rect(scheme["bbox"]))):
                images.append(tasks_dir / f"{prefix}__scheme.png")
                img, _, _ = render_grid(self._page(doc, scheme["page"]), _grow(scheme["bbox"], 6))
                img.save(images[-1])
                note = f" A second image shows its general scheme on page {scheme['page']}."
            pieces = zoom_pieces(block_area & page_rect) if zoom else []
            for i, piece in enumerate(pieces, 1):
                # The grid is labelled in PDF points of the page, so all pieces share the overview's coordinates.
                images.append(tasks_dir / f"{prefix}__zoom{i}.png")
                img, _, _ = render_grid(page, piece)
                img.save(images[-1])
            if pieces:
                note += (f" The next {len(pieces)} images are close-ups of the block, left to right and top to bottom, "
                         "with the same point coordinates: read small print and box coordinates from them.")
        if appendix_images:
            images.extend(appendix_images)
            note += appendix_note
        # A block whose entries continue on later pages has no other view of those pages: render
        # them here, before the complete first page, so the reader can box them too.
        first, last = block.get("entries_first_page"), block.get("entries_last_page")
        cont_pages = list(range(block["page"] + 1, last + 1)) if first is not None and last is not None else []
        for page_no in cont_pages:
            path = tasks_dir / f"{prefix}__continued-{page_no}.png"
            with self.pdf_lock:
                continued = self._page(doc, page_no)
                img, _, _ = render_grid(continued, continued.rect, max_px=1800)
                img.save(path)
            images.append(path)
            note += (f" A whole-page image of page {page_no} follows with the same PDF-point coordinates: "
                     "the entries continue there; read boxes on that page too.")
        # A locate crop can cut a reactant off before extraction starts. Full-page context lets
        # the reader detect that error and use page coordinates outside the proposed crop.
        images.append(tasks_dir / f"{prefix}__page.png")
        with self.pdf_lock:
            img, _, _ = render_grid(page, page_rect, max_px=1800)
            img.save(images[-1])
        note += (" The last image is the complete source page with the same PDF-point coordinates. "
                 "Check it for structures cut off by the block crop; use the full page for missing parts, "
                 "never guess a box from a clipped fragment.")
        return images, note

    @staticmethod
    def _apply_shared(data: dict, shared) -> list[str]:
        """Blocks that follow one general scheme share its participants: copy what the leader
        block wrote over this template's participants of the same keys."""
        if not shared:
            return []
        have = {p["key"]: p for p in data["template"]["participants"]}
        missing = [p["key"] for p in shared if p["key"] not in have]
        if missing:
            return [f"template.participants must contain the shared scheme participants "
                    f"unchanged (same keys); missing: {missing}"]
        for sp in shared:  # one description of the scheme for all blocks that follow it
            have[sp["key"]].update({k: sp[k] for k in ("label", "text", "generic", "page", "bbox")})
        return []

    @staticmethod
    def _soften_coverage(meta: dict) -> None:
        """Leftover coverage problems after the repair round are kept as warnings, not failures."""
        leftovers = [e for e in meta["errors"] if e.startswith("uncovered area")]
        if leftovers and len(leftovers) == len(meta["errors"]):
            meta["warnings"] += leftovers
            meta["errors"], meta["status"] = [], "ok"

    # ---------------------------------------------------------- inventory

    def inventory(self, region: dict, block: dict) -> dict:
        ref, bdir = block_ref(region, block), self._block_dir(region, block)
        task, task_hash = self._inventory_task(region, block)
        cached = _load(bdir / "inventory.json")
        if cached and cached["_meta"].get("hash") == task_hash and cached["_meta"]["status"] == "ok":
            self.log.info("inventory %s: cached (%d entries)", ref, len(cached["entries"]))
            return cached

        doc, slug = region["doc"], block_slug(region, block)
        scratch = self.out / "scratch" / f"{slug}__inventory"
        scratch.mkdir(parents=True, exist_ok=True)
        (bdir / "tasks").mkdir(parents=True, exist_ok=True)
        task_path = bdir / "tasks" / "inventory.json"
        write_json(task_path, {**task, "scratch": repo_rel(scratch)})
        shared = task["shared_participants"]
        images, scheme_note = self._block_images(doc, block, task["block"]["scheme"], bdir / "tasks", "inventory")

        prompt = (
            USE_SKILL +
            f"Task file: {repo_rel(task_path)} (mode: inventory)\n"
            f"Attached image: the block on page {block['page']} of '{doc}', with a point grid."
            f"{scheme_note}\n"
            "Read what the main text and the SI say about this block before you fix the template.\n"
            "This turn writes the template and lists the entries. In the turns that follow you will be "
            "shown one entry at a time and spell out the reactions it reports.\n\n"
            "Your final message must be only the JSON object required by the output schema."
        )
        sizes = self._page_sizes(doc)

        def check(data):
            errors, warnings = validate_inventory(data, self.schemas["inventory"], sizes,
                                                  block["n_entries_est"], self.doc_pages)
            if errors:
                return errors, warnings
            errors += self._apply_shared(data, shared)
            if errors:
                return errors, warnings
            with self.pdf_lock:
                errors += self._inventory_geometry(doc, block, data)
            return errors, warnings

        self.log.info("inventory %s: start", ref)
        data, meta = self._codex(SCHEMAS["inventory"], prompt, images, bdir / "inventory_raw.json",
                                 self.ws.log_dir / "step2" / f"{slug}__inventory.jsonl",
                                 self.cfg.extract.inventory_timeout_s, check)
        meta["hash"] = task_hash
        self._soften_coverage(meta)

        inv = {"template": None, "entries": [], "ignored": [], "notes": ""}
        if data is not None and meta["status"] == "ok":
            inv = data
            for i, r in enumerate(inv["entries"], 1):
                r["eid"] = f"e{i:03d}"
            with self.pdf_lock:
                meta["overlays"] = self._overlays(doc, block, inv, bdir)
                self._template_crops(doc, inv, bdir)
        inv["_meta"] = meta
        write_json(bdir / "inventory.json", inv)
        self.log.info("inventory %s: %s, %d entries, %.0fs%s", ref, meta["status"],
                      len(inv["entries"]), meta["seconds"],
                      f", errors: {meta['errors'][:3]}" if meta["errors"] else "")
        return inv

    def _inventory_geometry(self, doc: str, block: dict, inv: dict, coverage: bool = True) -> list[str]:
        """Tighten every box in place and report ink no box accounts for (unless not `coverage`).
        Needs pdf_lock."""
        errors: list[str] = []
        t = inv["template"]
        for p in t["participants"]:
            if p["bbox"] is not None:
                p["bbox"] = self._trim(doc, p["page"], p["bbox"], f"template participant '{p['key']}'", errors)
        if t["scheme"] is not None:
            t["scheme"]["bbox"] = self._trim(doc, t["scheme"]["page"], t["scheme"]["bbox"], "template scheme", errors)
        for x in t["structures"]:
            x["bbox"] = self._trim(doc, x["page"], x["bbox"], f"template structure '{x['key']}'", errors)
        for i, r in enumerate(inv["entries"]):
            r["bbox"] = self._trim(doc, r["page"], r["bbox"], f"entries[{i}] ({r['label']})", errors)

        if coverage and block["entries_first_page"] is None and inv["entries"]:
            page = block["page"]
            covered = [r["bbox"] for r in inv["entries"] if r["page"] == page]
            covered += [g["bbox"] for g in inv["ignored"] if g["page"] == page]
            covered += [p["bbox"] for p in t["participants"] if p["bbox"] is not None and p["page"] == page]
            covered += [x["bbox"] for x in t["structures"] if x["page"] == page]
            if t["scheme"] is not None and t["scheme"]["page"] == page:
                covered.append(t["scheme"]["bbox"])
            for blob in uncovered_blobs(self._page(doc, page), block["bbox"], covered):
                box = [round(v) for v in blob]
                errors.append(f"uncovered area on page {page}: {box} is inside the block but in no "
                              "entry, scheme, participant, structure or ignored box; add what is "
                              "printed there (entries, drawn catalysts/ligands) or list the area "
                              "under ignored with a reason")
        return errors

    def _overlays(self, doc: str, block: dict, inv: dict, bdir: Path, extra=()) -> list[str]:
        """One annotated image per page that carries boxes; `extra`: more (kind, tag, page, bbox).
        Needs pdf_lock."""
        t = inv["template"]
        boxes: dict[int, list] = {block["page"]: [("block", None, block["bbox"])]}
        # Labelled with the entry ids the viewer uses; entries with one and the same box (they share a
        # drawing) are outlined once, under one tag.
        same_box: dict = {}
        for r in inv["entries"]:
            same_box.setdefault((r["page"], tuple(r["bbox"])), []).append(r)
        for (page_no, _), group in same_box.items():
            boxes.setdefault(page_no, []).append(("reaction", eid_ranges([r["eid"] for r in group]), group[0]["bbox"]))
        for p in t["participants"]:
            if p["bbox"] is not None:
                boxes.setdefault(p["page"], []).append(("participant", p["key"], p["bbox"]))
        if t["scheme"] is not None:
            boxes.setdefault(t["scheme"]["page"], []).append(("scheme", None, t["scheme"]["bbox"]))
        for x in t["structures"]:
            boxes.setdefault(x["page"], []).append(("structure", x["key"], x["bbox"]))
        for g in inv["ignored"]:
            boxes.setdefault(g["page"], []).append(("ignored", None, g["bbox"]))
        for kind, tag, page_no, b in extra:
            boxes.setdefault(page_no, []).append((kind, tag, b))

        colors = {"block": (120, 120, 120), "reaction": (0, 150, 0), "participant": (0, 90, 220),
                  "scheme": (150, 0, 200), "structure": (220, 120, 0), "ignored": (160, 160, 160)}
        font = ImageFont.load_default(size=15)
        names = []
        for page_no, items in sorted(boxes.items()):
            page = self._page(doc, page_no)
            clip = pymupdf.Rect(items[0][2])
            for _, _, b in items[1:]:
                clip |= pymupdf.Rect(b)
            clip = pymupdf.Rect(_grow(clip, 14)) & page.rect
            dpi = max(72, min(200, int(1800 / max(clip.width, clip.height) * 72)))
            pix = page.get_pixmap(dpi=dpi, clip=clip)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            draw = ImageDraw.Draw(img)
            s = dpi / 72
            for kind, tag, b in items:
                xy = [(b[0] - clip.x0) * s, (b[1] - clip.y0) * s, (b[2] - clip.x0) * s, (b[3] - clip.y0) * s]
                draw.rectangle(xy, outline=colors[kind], width=3 if kind == "reaction" else 2)
                if tag and kind in ("reaction", "structure"):
                    # Outside the box's left edge, so that it does not cover the number printed there.
                    w = draw.textlength(str(tag), font=font) + 4
                    x = xy[0] - w - 2 if xy[0] - w - 2 >= 0 else xy[0] + 3
                    draw.rectangle([x, xy[1], x + w, xy[1] + 17], fill=(255, 255, 255))
                    draw.text((x + 2, xy[1] + 1), str(tag), fill=colors[kind], font=font)
            name = f"overlay_p{page_no:03d}.png"
            img.save(bdir / name)
            names.append(name)
        return names

    def _template_crops(self, doc: str, inv: dict, bdir: Path) -> None:
        (bdir / "crops").mkdir(parents=True, exist_ok=True)
        for pattern in ("_template__*.png", "_structure__*.png", "e[0-9][0-9][0-9]__entry.png"):
            for old in (bdir / "crops").glob(pattern):
                old.unlink()  # keys and entries may have changed since the previous inventory
        template = inv["template"]
        for entry in inv["entries"]:
            render_clip(self._page(doc, entry["page"]), entry["bbox"],
                        bdir / "crops" / f"{entry['eid']}__entry.png", dpi=200, margin=3)
        for p in template["participants"]:
            if p["bbox"] is not None:
                render_clip(self._page(doc, p["page"]), p["bbox"],
                            bdir / "crops" / f"_template__{safe(p['key'])}.png", dpi=250, margin=2)
        for x in template["structures"]:
            render_clip(self._page(doc, x["page"]), x["bbox"],
                        bdir / "crops" / f"_structure__{safe(x['key'])}.png", dpi=250, margin=2)

    # -------------------------------------------------------------- block

    def block(self, region: dict, block: dict, expand: bool = True) -> dict:
        """The block reader: the template (turn 1), then one turn per entry in the same session.
        Each entry spelled out is reported on `events`, so its reactions can start right away.
        A block of a layout with skills of its own goes to its driver."""
        spec = TABLES.get(block.get("layout"))
        if spec is not None:
            return s2_table.run_block(spec, self, region, block, expand)
        ref = block_ref(region, block)
        inv = self.inventory(region, block)
        self.events.put(("template", ref))
        if not expand or inv["_meta"]["status"] != "ok":
            return inv
        limit = self.cfg.extract.limit
        entries = inv["entries"][:limit] if limit else inv["entries"]
        thread, told, failures = inv["_meta"].get("thread_id"), False, 0
        prior = dict(inv["_meta"].get("usage_total") or {})  # the thread's token total so far
        for n, entry in enumerate(entries, 1):
            exp, ran = self.expand(region, block, inv, entry, n, thread, told, prior)
            if exp["_meta"].get("thread_id") == thread:
                for k, v in (exp["_meta"].get("usage_total") or {}).items():
                    prior[k] = max(prior.get(k, 0), v)
            if ran:
                told = True
                thread = exp["_meta"].get("thread_id") or thread
                failures = failures + 1 if any(e.startswith("codex:") for e in exp["_meta"]["errors"]) else 0
            if exp["_meta"]["status"] == "ok":
                self.events.put(("rows", (region, block, inv, entry, exp)))
            if failures >= MAX_CODEX_FAILURES:
                self.log.warning("block %s: the block reader failed %d times in a row; its remaining entries "
                                 "are left for a later run", ref, failures)
                break
        return inv

    def expand(self, region, block, inv, entry, n, thread, told, prior=None):
        """One turn of the block reader: this entry alone, spelled out as reactions (rows).
        `prior`: the token total of the block reader's thread before this turn.

        Returns (expansion, whether Codex was called)."""
        bdir, eid = self._block_dir(region, block), entry["eid"]
        path = bdir / "expand" / f"{eid}.json"
        exp_hash = self._expand_hash(inv, entry)
        cached = _load(path)
        if cached and cached["_meta"].get("hash") == exp_hash and cached["_meta"]["status"] == "ok":
            return cached, False

        doc, slug = region["doc"], block_slug(region, block)
        closeup = bdir / "tasks" / f"{eid}__expand.png"
        closeup.parent.mkdir(parents=True, exist_ok=True)
        with self.pdf_lock:
            _outlined(self._page(doc, entry["page"]), _grow(entry["bbox"], 25), entry["bbox"]).save(closeup)
        total = len(inv["entries"])
        read_first = ("" if told else
                      f"Read {repo_rel(SKILL_DIR / 'references' / 'expand.md')} now; it applies to this and every "
                      "following entry turn.\n")
        prompt = (
            f"Entry {eid} ({n} of {total})" + (f", label {entry['label']}" if entry["label"] else "")
            + f": page {entry['page']}, box {entry['bbox']}. You listed it as: {entry['descriptor']}\n"
            "Attached: a close-up of this entry, outlined in red, with a little of its surroundings.\n"
            + read_first +
            "Look at this entry only. Transcribe what is printed for it, reason about how many reactions it "
            "reports, and give one row per reaction.\n\n"
            "Your final message must be only the JSON object required by the output schema."
        )

        def check(data):
            return validate_expansion(data, self.schemas["expand"], inv["template"], self.doc_pages)

        if not thread:
            data, meta = None, {"status": "failed", "errors": ["codex: the block reader's session is unknown"],
                                "warnings": [], "repair_rounds": 0, "usage": {}, "seconds": 0.0, "thread_id": None}
        else:
            data, meta = self._codex(SCHEMAS["expand"], prompt, [closeup], bdir / "expand" / f"{eid}_raw.json",
                                     self.ws.log_dir / "step2" / f"{slug}__inventory.jsonl",
                                     self.cfg.extract.expand_timeout_s, check, thread_id=thread, prior=prior)
        meta["hash"] = exp_hash
        exp = dict(data) if data is not None and meta["status"] == "ok" else {"printed": "", "results": [],
                                                                               "reasoning": "", "rows": [], "issues": []}
        for i, row in enumerate(exp["rows"], 1):
            row["rid"] = f"{eid}-{i}"
            row["results_text"] = [exp["results"][r - 1] for r in row["results"]]
        exp["_meta"] = meta
        write_json(path, exp)
        self.log.info("expand %s/%s: %s, %d reactions, %.0fs%s", block_ref(region, block), eid, meta["status"],
                      len(exp["rows"]), meta["seconds"], f", errors: {meta['errors'][:2]}" if meta["errors"] else "")
        return exp, True

    # -------------------------------------------------------------- entry

    def entry(self, region: dict, block: dict, inv: dict, entry: dict, exp: dict, reaction: dict) -> dict:
        """One reaction (a row of an expanded entry): boxes, outcomes, and what the text and SI add."""
        rid, bdir = reaction["rid"], self._block_dir(region, block)
        ref = f"{block_ref(region, block)}/{rid}"
        task, task_hash = self._entry_task(region, block, inv, entry, exp, reaction)
        path = bdir / "entries" / f"{rid}.json"
        cached = _load(path)
        if cached and cached["_meta"].get("hash") == task_hash and cached["_meta"]["status"] == "ok":
            return cached

        doc, slug = region["doc"], block_slug(region, block)
        scratch = self.out / "scratch" / f"{slug}__{rid}"
        scratch.mkdir(parents=True, exist_ok=True)
        task_path = bdir / "tasks" / f"{rid}.json"
        write_json(task_path, {**task, "scratch": repo_rel(scratch)})
        context, closeup = bdir / "tasks" / f"{rid}__context.png", bdir / "tasks" / f"{rid}__target.png"
        with self.pdf_lock:
            page = self._page(doc, entry["page"])
            if entry["page"] == block["page"]:
                clip = _grow(pymupdf.Rect(block["bbox"]) | pymupdf.Rect(entry["bbox"]), 6)
            else:
                b = entry["bbox"]
                clip = [b[0] - 20, b[1] - 60, b[2] + 20, b[3] + 60]
            img, _, _ = render_grid(page, clip, outline=[entry["bbox"]])
            img.save(context)
            img, _, _ = render_grid(page, _grow(entry["bbox"], 10), max_px=1400)
            img.save(closeup)

        results = "; ".join(reaction["results_text"]) or "none printed"
        prompt = (
            USE_SKILL +
            f"Task file: {repo_rel(task_path)} (mode: entry, reaction {rid}"
            + (f", label {reaction['label']}" if reaction["label"] else "") + f"; results: {results})\n"
            f"Attached images: (1) page {entry['page']} of '{doc}' around the block, with a point "
            "grid and the entry outlined in red; (2) a close-up of the entry with a finer grid.\n"
            "The block reader has decided what this reaction is (task: reaction, protocol). Take its boxes "
            "and outcomes from the entry, then look this reaction up in the main text and the SI.\n\n"
            "Your final message must be only the JSON object required by the output schema."
        )
        sizes = self._page_sizes(doc)

        def check(data):
            errors, warnings = validate_entry(data, self.schemas["entry"], inv["template"], reaction, sizes,
                                              self.doc_pages)
            if errors:
                return errors, warnings
            with self.pdf_lock:
                for p in data["participants"]:
                    if p["bbox"] is not None and p["page"] is not None:
                        p["bbox"] = self._trim(doc, p["page"], p["bbox"], f"participant '{p['key']}'", errors)
                for x in data["structures"]:
                    x["bbox"] = self._trim(doc, x["page"], x["bbox"], f"structure '{x['key']}'", errors)
            return errors, warnings

        data, meta = self._codex(SCHEMAS["entry"], prompt, [context, closeup], bdir / "entries" / f"{rid}_raw.json",
                                 self.ws.log_dir / "step2" / f"{slug}__{rid}.jsonl",
                                 self.cfg.extract.entry_timeout_s, check)
        meta["hash"] = task_hash
        result = dict(data) if data is not None else {}
        if meta["status"] == "ok":
            with self.pdf_lock:
                self._entry_crops(doc, rid, result, bdir)
        result["_meta"] = meta
        write_json(path, result)
        self.log.info("entry %s: %s, %.0fs%s", ref, meta["status"], meta["seconds"],
                      f", errors: {meta['errors'][:2]}" if meta["errors"] else "")
        return result

    def _entry_crops(self, doc: str, rid: str, entry: dict, bdir: Path) -> None:
        crops = bdir / "crops"
        crops.mkdir(parents=True, exist_ok=True)
        for p in entry["participants"]:
            if p["source"] != "derived" and p["bbox"] is not None and p["page"] is not None:
                render_clip(self._page(doc, p["page"]), p["bbox"],
                            crops / f"{rid}__{safe(p['key'])}.png", dpi=250, margin=2)
        for x in entry["structures"]:
            render_clip(self._page(doc, x["page"]), x["bbox"],
                        crops / f"{rid}__s-{safe(x['key'])}.png", dpi=250, margin=2)

    # ------------------------------------------------------------ publish

    def publish_progress(self) -> None:
        """Publish while sessions are still running; a failure here must not stop them."""
        try:
            self.publish()
        except Exception:
            self.log.exception("could not update step2 outputs (will retry)")

    def publish(self) -> dict:
        """Assemble records and the viewer's files from everything valid on disk."""
        records, views = [], []
        metas, seconds = [], 0.0  # metas of every Codex call behind the outputs: tokens are counted per thread
        counts = Counter()
        limit = self.cfg.extract.limit
        for region, block in select_blocks(self.regions):
            spec = TABLES.get(block.get("layout"))
            if spec is not None:
                got = s2_table.block_view(spec, self, region, block)
                if got is not None:
                    view, recs, block_counts, block_metas, block_seconds = got
                    views.append(view)
                    records += recs
                    counts.update(block_counts)
                    metas += block_metas
                    seconds += block_seconds
                continue
            bdir = self._block_dir(region, block)
            inv = _load(bdir / "inventory.json")
            if inv is None:
                continue
            slug = block_slug(region, block)
            meta = inv["_meta"]
            _, inv_hash = self._inventory_task(region, block)
            status = meta["status"] if meta.get("hash") == inv_hash else "stale"
            metas.append(meta)
            seconds += meta.get("seconds", 0)
            counts[f"inventories_{status}"] += 1
            view = {"region": region, "block": block, "slug": slug, "status": status, "meta": meta,
                    "template": inv["template"] if status == "ok" else None, "entries": [],
                    "template_crops": {}, "structure_crops": {}, "ignored": [], "notes": ""}
            views.append(view)
            if status != "ok":
                continue

            template = inv["template"]
            template_crops = {p["key"]: f"blocks/{slug}/crops/_template__{safe(p['key'])}.png"
                              for p in template["participants"] if p["bbox"] is not None}
            structure_crops = {x["key"]: f"blocks/{slug}/crops/_structure__{safe(x['key'])}.png"
                               for x in template["structures"]}
            view.update(template_crops=template_crops, structure_crops=structure_crops,
                        ignored=inv["ignored"], notes=inv["notes"])
            for i, entry in enumerate(inv["entries"]):
                counts["entries_listed"] += 1
                ev = {"entry": entry, "crop": f"blocks/{slug}/crops/{entry['eid']}__entry.png",
                      "status": "pending", "errors": [], "warnings": [], "expansion": None, "reactions": []}
                view["entries"].append(ev)
                exp = _load(bdir / "expand" / f"{entry['eid']}.json")
                if exp is None:
                    if limit and i >= limit:
                        ev["status"] = "skipped"
                        counts["entries_skipped"] += 1
                    continue
                emeta = exp["_meta"]
                metas.append(emeta)
                seconds += emeta.get("seconds", 0)
                ev.update(status=emeta["status"] if emeta.get("hash") == self._expand_hash(inv, entry) else "stale",
                          errors=emeta["errors"], warnings=emeta["warnings"])
                counts[f"entries_{ev['status']}"] += 1
                if ev["status"] != "ok":
                    continue
                ev["expansion"] = exp
                for reaction in exp["rows"]:
                    counts["reactions_listed"] += 1
                    rv = {"reaction": reaction, "status": "pending", "errors": [], "warnings": [], "record": None,
                          "protocol": resolve_protocol(template, reaction, view=True), "seconds": None}
                    ev["reactions"].append(rv)
                    child = _load(bdir / "entries" / f"{reaction['rid']}.json")
                    if child is None:
                        continue
                    cmeta = child["_meta"]
                    _, child_hash = self._entry_task(region, block, inv, entry, exp, reaction)
                    metas.append(cmeta)
                    seconds += cmeta.get("seconds", 0)
                    rv.update(status=cmeta["status"] if cmeta.get("hash") == child_hash else "stale",
                              errors=cmeta["errors"], warnings=_record_warnings(cmeta["warnings"]),
                              seconds=cmeta["seconds"])
                    counts[f"reactions_{rv['status']}"] += 1
                    if rv["status"] != "ok":
                        continue
                    crop_dir = f"blocks/{slug}/crops"
                    rid = reaction["rid"]
                    crops = {p["key"]: f"{crop_dir}/{rid}__{safe(p['key'])}.png"
                             for p in child["participants"] if p["source"] != "derived" and p["bbox"] is not None}
                    crops.update({f"s:{x['key']}": f"{crop_dir}/{rid}__s-{safe(x['key'])}.png"
                                  for x in child["structures"]})
                    ctx = {"region": region, "block": block, "crops": crops, "template_crops": template_crops,
                           "structure_crops": structure_crops, "entry_crop": ev["crop"],
                           "section": section_for(self.regions, region["doc"], entry["page"])}
                    rec = build_record(ctx, template, entry, reaction, child)
                    rec["issues"] = exp["issues"] + rec["issues"]
                    rv["record"] = rec
                    records.append(rec)

        paper_id = self.ws.paper.paper_id
        write_json(self.out / "reactions.json", {"paper_id": paper_id, "records": records})
        attempts = [int(m.get("attempts") or 1) for m in metas if isinstance(m, dict) and "attempts" in m]
        summary = {"blocks": len(views), **dict(sorted(counts.items())), "records": len(records),
                   "block_attempts": sum(attempts) if attempts else len(views),
                   "blocks_retried": sum(1 for a in attempts if a > 1),
                   "codex_seconds": round(seconds), "tokens": thread_usage(metas)}
        write_json(self.out / "summary.json", summary)
        # The same state for the viewer; a block's file is rewritten only when it changed.
        known = {b["slug"]: b["rev"] for b in (_load(self.out / "index.json") or {}).get("blocks", [])}
        heads = []
        for view in views:
            data = block_view(view)
            heads.append(block_head(data))
            path = self.out / "blocks" / view["slug"] / "view.json"
            if known.get(view["slug"]) != heads[-1]["rev"] or not path.exists():
                write_json(path, data)
        write_json(self.out / "index.json", view_index(paper_id, self.regions["paper"], summary, heads))
        return summary


def republish(ws, cfg, log) -> dict:
    """Assemble the step's outputs again from what is on disk, without running Codex."""
    regions = _load(ws.root / "step1" / "regions.json")
    if regions is None or not (ws.root / "step2").is_dir():
        raise RuntimeError("nothing to publish: step1/regions.json or step2/ is missing")
    return _Job(ws, cfg, log, regions, ws.root / "step2").publish()


