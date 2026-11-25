"""Bounded geometry-only repair. The model may replace boxes, never chemistry or measurements."""
from __future__ import annotations

import copy
import json
import pymupdf
from pathlib import Path

from .codex import run_codex
from .papers import write_json


def targets(inv):
    result = {}
    for name in ("participants", "structures"):
        for i, part in enumerate(inv["template"][name]):
            if part.get("bbox"):
                result[f"template/{name}/{i}"] = (part, "bbox", part["page"])
    for i, entry in enumerate(inv["entries"]):
        if entry.get("bbox"):
            result[f"entries/{i}"] = (entry, "bbox", entry["page"])
        for j, cell in enumerate(entry["cells"]):
            if cell.get("structure_bbox"):
                result[f"entries/{i}/cells/{j}"] = (cell, "structure_bbox", entry["page"])
    return result


def apply(inv, answer, sizes, only_ids=None):
    result = copy.deepcopy(inv)
    refs = targets(result)
    if only_ids is not None:
        refs = {key: value for key, value in refs.items() if key in only_ids}
    if set(answer) - {"boxes", "reason"}:
        raise ValueError("geometry repair cannot modify non-geometry fields")
    rows = answer.get("boxes", [])
    if any(set(row) not in ({"id", "bbox"}, {"id", "bbox", "page"}) for row in rows):
        raise ValueError("geometry repair rows accept only id, bbox and page")
    if len(rows) != len(refs) or {r["id"] for r in rows} != set(refs):
        raise ValueError("geometry repair must cover every requested target exactly once")
    for row in rows:
        target, field, page = refs[row["id"]]
        if "page" in row:
            if isinstance(row["page"], bool) or not isinstance(row["page"], int) or row["page"] not in sizes:
                raise ValueError("invalid geometry page")
            if "/cells/" in row["id"] and row["page"] != page:
                raise ValueError("a cell box stays on its entry page")
            page = row["page"]
            if "/cells/" not in row["id"]:
                target["page"] = page
        box = row["bbox"]
        width, height = sizes[page]
        if len(box) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in box):
            raise ValueError("invalid geometry bbox")
        if not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
            raise ValueError("geometry bbox is outside the page")
        target[field] = box
    return result


def repair(inv, job, doc, directory, only_ids=None):
    refs = targets(inv)
    if only_ids is not None:
        refs = {key: value for key, value in refs.items() if key in only_ids}
    if not refs:
        return inv
    directory.mkdir(parents=True, exist_ok=True)
    images = []
    from .pagetools.grid import render_grid
    from .geometry_candidates import attach
    candidate_notes = []
    for page_no in sorted({page for _, _, page in refs.values()}):
        source_boxes = [target[field] for target, field, page in refs.values() if page == page_no]
        with job.pdf_lock:
            area = pymupdf.Rect(source_boxes[0])
            for box in source_boxes[1:]:
                area |= pymupdf.Rect(box)
        extra, note = attach(job, doc, {"page": page_no, "bbox": list(area)}, None,
                             directory / f"candidates-p{page_no}")
        images.extend(extra)
        candidate_notes.append(note)
    with job.pdf_lock:
        for page in sorted({page for _, _, page in refs.values()}):
            source = job._page(doc, page)
            path = directory / f"page-{page}.png"
            image, _, _ = render_grid(source, source.rect, max_px=2600)
            image.save(path)
            images.append(path)
    task = [{"id": key, "page": page, "previous_bbox": target[field],
             "label": target.get("label", target.get("text", "")),
             "key": target.get("key", target.get("column", ""))} for key, (target, field, page) in refs.items()]
    for target in task:
        if target["id"].startswith("entries/"):
            entry = inv["entries"][int(target["id"].split("/")[1])]
            target["row_label"] = entry.get("label")
            target["row_descriptor"] = entry.get("descriptor", "")
    write_json(directory / "targets.json", task)
    schema = {"type": "object", "properties": {"boxes": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "string"},
        "bbox": {"type": "array", "items": {"type": "number"}},
        "page": {"type": "integer"}},
        "required": ["id", "bbox", "page"], "additionalProperties": False}}},
        "required": ["boxes"], "additionalProperties": False}
    write_json(directory / "schema.json", schema)
    scratch = directory / "scratch"
    scratch.mkdir(exist_ok=True)
    result = run_codex(
        f"Correct only the molecular structure crop boxes that failed the edge check. "
        f"Targets: {directory / 'targets.json'}. Only these targets are re-located; every other box "
        "of the answer stays as it is. "
        "Attached images include candidate overlays followed by whole-page labelled grids in PDF POINTS "
        "(top-left origin). Use candidate JSON for exact coordinates and inspect crops; candidate boxes "
        "are proposals, not recognised molecules. " + " ".join(candidate_notes) + " " +
        "Locate each target visually on the page given in targets.json. "
        "Targets whose id is entries/N alone are row evidence boxes, not molecular crops: include only "
        "that row's own parameter/result text; a shared drawing may be separate from that row. "
        "Targets under entries/N/cells/J and template are molecular structures. For these, "
        "Include every atom label, bond, bracket, subscript and substituent belonging to that structure; "
        "leave 2 PDF points of white margin. Exclude neighbouring structures, arrows, plus signs, "
        "table rules and unrelated numbers. Participants are the numbered molecules in the general "
        "reaction above the screening table; ligand targets are drawings in the corresponding table rows. "
        "Use page tools for accurate vector/text coordinates. Do not modify any reaction data. "
        "Return the 1-based PDF page of each target as well: correct a previous page when the target "
        "is printed on another page. "
        f"Scratch: {scratch}. Return one box for every target id, no extra ids.",
        schema=directory / "schema.json", out_json=directory / "answer.json",
        events_log=directory / "events.jsonl", cfg=job.cfg.codex, images=images,
        writable=(scratch, job.ws.root / "scratch"), timeout=360)
    repaired = apply(inv, result.data, job._page_sizes(doc), only_ids=only_ids)
    write_json(directory / "audit.json", {"before": task, "answer": result.data,
                                          "thread_id": result.thread_id, "usage": result.usage})
    return repaired


def main():
    """Explicit opt-in recovery, restricted to a single saved condition-table inventory."""
    import argparse, logging, time
    from .config import PipelineConfig
    from .papers import PaperWorkspace, discover_papers, sha256_file
    from .steps.s2_extract import _Job
    from .steps.s2_ctable import SPEC
    from .steps.s2_table import _box_edges, _trim_cells, _cell_crops
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--paper", required=True)
    parser.add_argument("--block", required=True, help="region_id/block_id")
    parser.add_argument("--boxes", type=Path, help="optional visually reviewed bbox patch; no model call")
    args = parser.parse_args()
    cfg = PipelineConfig(work_dir=args.work.resolve())
    paper = next(p for p in discover_papers(cfg.data_dir) if p.paper_id == args.paper)
    ws = PaperWorkspace(paper, cfg.work_dir)
    regions = json.loads((ws.root / "step1/regions.json").read_text())
    job = _Job(ws, cfg, logging.getLogger(__name__), regions, ws.root / "step2")
    region, block = next((r, b) for r in regions["regions"] for b in r["blocks"]
                         if f"{r['region_id']}/{b['block_id']}" == args.block)
    if block["layout"] != "condition_table":
        raise ValueError("geometry-only recovery currently supports condition tables")
    bdir = job._block_dir(region, block)
    previous = json.loads((bdir / "inventory.json").read_text())
    doc = region["doc"]
    candidates = []
    # Retain model-emitted answers only. Never repair chemical fields deterministically.
    events = ws.log_dir / "step2" / f"{bdir.name}__table.jsonl"
    for line in events.read_text().splitlines():
        try:
            event = json.loads(line)
            item = event.get("item", {})
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                candidate = json.loads(item.get("text", ""))
                if not SPEC.validate_table(candidate, SPEC.schema("entries"), job._page_sizes(doc),
                                           block["n_entries_est"], job.doc_pages)[0]:
                    candidates.append(candidate)
        except (ValueError, KeyError, TypeError):
            continue
    if not candidates:
        raise ValueError("no schema-valid retained model answer; rerun extraction")
    base = bdir / f"geometry-repair-{time.time_ns()}"
    base.mkdir()
    write_json(base / "source.json", candidates[-1])
    write_json(base / "previous-meta.json", previous["_meta"])
    if args.boxes:
        patch = json.loads(args.boxes.read_text())
        if not patch.get("reason"):
            raise ValueError("reviewed bbox patch requires a reason")
        repaired = apply(candidates[-1], patch, job._page_sizes(doc))
        write_json(base / "audit.json", {"before": candidates[-1], "answer": patch,
                                          "method": "visual-review", "thread_id": None, "usage": {}})
    else:
        repaired = repair(candidates[-1], job, doc, base)
    errors, warnings = SPEC.validate_table(repaired, SPEC.schema("entries"), job._page_sizes(doc),
                                           block["n_entries_est"], job.doc_pages)
    if not errors:
        with job.pdf_lock:
            errors += job._inventory_geometry(doc, block, repaired)
            errors += _trim_cells(job, doc, repaired)
            errors += _box_edges(job, doc, repaired)
    write_json(base / "validation.json", {"errors": errors, "warnings": warnings})
    write_json(base / "repaired.json", repaired)
    if errors:
        raise ValueError(f"geometry repair rejected: {errors}")
    for i, entry in enumerate(repaired["entries"], 1):
        entry["eid"] = f"e{i:03d}"
    meta = copy.deepcopy(previous["_meta"])
    metric = json.loads((base / "audit.json").read_text())
    if metric.get("method") == "visual-review":
        warnings.append("structure geometry corrected by explicit visual review; not an automatic model extraction success")
    meta.update(status="ok", errors=[], warnings=warnings, geometry_repair={
        "audit": str(base / "audit.json"), "source_sha256": sha256_file(base / "source.json"),
        "thread_id": metric["thread_id"], "usage": metric["usage"],
        "method": metric.get("method", "model-geometry-only")})
    for usage_key in ("usage", "usage_total"):
        meta[usage_key] = {key: meta.get(usage_key, {}).get(key, 0) + metric["usage"].get(key, 0)
                           for key in set(meta.get(usage_key, {})) | set(metric["usage"])}
    extra = [("structure", f"{e['eid']}-{c['column']}", e["page"], c["structure_bbox"])
             for e in repaired["entries"] for c in e["cells"] if c.get("structure_bbox")]
    with job.pdf_lock:
        meta["overlays"] = job._overlays(doc, block, repaired, bdir, extra)
        job._template_crops(doc, repaired, bdir)
        _cell_crops(job, doc, repaired, bdir)
    write_json(bdir / "inventory.json", {**repaired, "_meta": meta})
    print(json.dumps({"status": "ok", "audit": str(base), "structures": len(targets(repaired))}))


if __name__ == "__main__":
    main()
