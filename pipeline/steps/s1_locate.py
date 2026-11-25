"""Step 1: let Codex (skill `locate-reactions`) map where reaction information lives.

Only the documents named in `cfg.locate.docs` are searched (the main text by default).

Python only prepares a caption checklist, runs Codex, validates its JSON (sending
errors back to the same session for repair), and renders crops.

Outputs in work/<paper_id>/step1/:
  caption_candidates.json  caption-like text blocks Codex must account for
  codex_raw*.json          raw Codex answers (first run, repair rounds)
  validation.json          remaining errors/warnings
  regions.json             validated inventory (see pipeline/schemas/locate_output.schema.json)
  crops/                   region and block crops
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from collections import Counter
from pathlib import Path

import pymupdf
from jsonschema import Draft202012Validator

from ..codex import page_environment, resume_codex, run_codex
from ..config import REPO_ROOT, repo_rel
from ..pagetools.crop import render_clip
from ..pagetools.grid import render_grid
from ..pagetools.trim import ink_edges
from ..papers import write_json

NAME = "locate"
VERSION = 3

SKILL_NAME = "locate-reactions"
SKILL_DIR = REPO_ROOT / ".agents" / "skills" / SKILL_NAME
SCHEMA_PATH = REPO_ROOT / "pipeline" / "schemas" / "locate_output.schema.json"

CAPTION_RE = re.compile(
    r"^(?:Supplementary\s+)?(?:Scheme|Table|Figure|Fig\.?|Chart)\s*S?\d+[A-Za-z]?(?=[\s.:|,)]|$)",
    re.IGNORECASE,
)
BBOX_TOLERANCE = 10.0  # pt; how far a block box may stick out of its region box
CROP_DPI = 150


def _tree_sha(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        h.update(str(path.relative_to(root)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


def params(cfg) -> dict:
    return {
        "codex": cfg.codex.identity(),
        "docs": list(cfg.locate.docs),
        "skill_sha": _tree_sha(SKILL_DIR),
        "schema_sha": hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()[:16],
    }


# --------------------------------------------------------------------------- run

def run(ws, cfg, log, force: bool = False) -> dict:
    page_environment()  # do not erase an existing locate result before a failed environment check
    out = ws.root / "step1"
    if out.exists():
        shutil.rmtree(out)
    (out / "scratch").mkdir(parents=True)

    manifests = {doc: json.loads((ws.doc_dir(doc) / "manifest.json").read_text(encoding="utf-8"))
                 for doc in ws.paper.documents()}
    docs = [d for d in manifests if d in cfg.locate.docs]
    if not docs:
        raise RuntimeError(f"none of the documents in scope {list(cfg.locate.docs)} exist for this paper")
    candidates = find_caption_candidates(ws, {d: manifests[d] for d in docs})
    write_json(out / "caption_candidates.json", candidates)
    log.info("caption candidates: %d", len(candidates))

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    events = ws.log_dir / "step1_codex.jsonl"
    log.info("codex: locating regions in %s", docs)
    # The page tools write under the workspace's scratch/, the session's own files go to step1/scratch.
    writable = (out / "scratch", ws.root / "scratch")
    images = []
    # A short SI can be supplied whole, avoiding dependence on a potentially failed tool read.
    # Long documents still use page tools instead of unbounded attachment fanout.
    if sum(manifests[d]["page_count"] for d in docs) <= 8:
        for doc in docs:
            with pymupdf.open(manifests[doc]["pdf"]) as pdf:
                for page in pdf:
                    path = out / f"context-{doc}-{page.number + 1:03d}.png"
                    image, _, _ = render_grid(page, page.rect, max_px=1800)
                    image.save(path)
                    images.append(path)
    res = run_codex(build_prompt(ws, out, docs), images=images, schema=SCHEMA_PATH, out_json=out / "codex_raw.json",
                    events_log=events, cfg=cfg.codex, writable=writable)
    usages = [res.usage]
    errors, warnings = validate(res.data, manifests, candidates, schema, docs)
    rounds = 0
    while errors and rounds < cfg.codex.max_repair_rounds and res.thread_id:
        rounds += 1
        log.warning("validation: %d errors, repair round %d", len(errors), rounds)
        res = resume_codex(res.thread_id, repair_prompt(errors), schema=SCHEMA_PATH,
                           out_json=out / f"codex_raw_repair{rounds}.json",
                           events_log=events, cfg=cfg.codex, writable=writable)
        usages.append(res.usage)
        errors, warnings = validate(res.data, manifests, candidates, schema, docs)
    if res.salvaged:
        warnings.append("codex: the final message was not one JSON object (prose around it, or the object repeated); "
                        "the last complete object in it was taken")

    write_json(out / "validation.json",
               {"errors": errors, "warnings": warnings, "repair_rounds": rounds})
    if errors:
        raise RuntimeError(f"{len(errors)} validation errors remain after {rounds} repair "
                           f"round(s); see step1/validation.json")

    regions = {**res.data, "docs_in_scope": docs}
    # A bad general-scheme proposal must not stop unrelated tables. Keep the crop and
    # local warning on every affected block; extraction re-boxes against the full page
    # and still requires its own geometry validation before handles/records are emitted.
    edge_issues = scheme_edge_issues(regions, manifests)
    annotate_scheme_issues(regions, edge_issues)
    warnings.extend(message for messages in edge_issues.values() for message in messages)
    write_json(out / "validation.json", {"errors": [], "warnings": warnings, "repair_rounds": rounds,
                                         "scheme_geometry_issues": edge_issues})
    write_json(out / "regions.json", regions)
    render_crops(regions, manifests, out / "crops")

    regs = regions["regions"]
    summary = {
        "docs": docs,
        "regions": len(regs),
        "included": sum(r["include"] for r in regs),
        "blocks_included": sum(b["include"] for r in regs if r["include"] for b in r["blocks"]),
        "kinds": dict(Counter(r["kind"] for r in regs if r["include"])),
        "layouts": dict(Counter(b["layout"] for r in regs if r["include"] for b in r["blocks"] if b["include"])),
        "schemes": len(regions["schemes"]),
        "si_sections": len(regions["si_sections"]),
        "caption_candidates": len(candidates),
        "warnings": len(warnings),
        "repair_rounds": rounds,
        "tokens": _sum_usage(usages),
    }
    log.info("  -> %s", summary)
    return summary


def annotate_scheme_issues(data, issues):
    """Preserve included blocks; attach local diagnostics without hiding failures."""
    for region in data["regions"]:
        for block in region["blocks"]:
            if block.get("scheme_id") in issues:
                block["locate_geometry_issues"] = list(issues[block["scheme_id"]])


def scheme_edge_issues(data, manifests):
    return {sc["scheme_id"]: messages for sc in data.get("schemes", [])
            if (messages := scheme_edges({"schemes": [sc]}, manifests))}


def scheme_edges(data, manifests):
    errors = []
    for scheme in data.get("schemes", []):
        with pymupdf.open(manifests[scheme["doc"]]["pdf"]) as pdf:
            sides = ink_edges(pdf[scheme["page"] - 1], scheme["bbox"])
            if sides:
                errors.append(f"scheme {scheme['scheme_id']}: crop cuts ink at {'/'.join(sides)} edges. "
                              "Re-check the whole page and include the complete reaction including leftmost "
                              "reactants; leave a white margin, do not estimate from text positions.")
    return errors


def build_prompt(ws, out: Path, docs: list[str]) -> str:
    dirs = ", ".join(f"{d}: {repo_rel(ws.doc_dir(d))}" for d in docs)
    scope = f"Documents in scope: {', '.join(docs)}."
    if "si" in ws.paper.documents() and "si" not in docs:
        scope += (" The SI is out of scope for this run: do not open it, leave si_sections empty, "
                  "and let no region, scheme or related entry refer to it.")
    return (
        f"Use the ${SKILL_NAME} skill.\n\n"
        f"Paper workspace: {repo_rel(ws.root)} ({dirs})\n"
        f"{scope}\n"
        f"Caption candidates to account for: {repo_rel(out / 'caption_candidates.json')}\n"
        f"Scratch directory for your own temporary files: {repo_rel(out / 'scratch')}\n\n"
        "Locate every place in the documents in scope that contains reaction information, "
        "following the skill. Your final message must be only the JSON object required by the "
        "output schema."
    )


def repair_prompt(errors: list[str]) -> str:
    listed = "\n".join(f"- {e}" for e in errors[:80])
    more = f"\n- ... and {len(errors) - 80} more" if len(errors) > 80 else ""
    return (
        "Your JSON failed validation:\n"
        f"{listed}{more}\n\n"
        "Fix these problems (re-check the pages where needed) and reply with the complete "
        "corrected JSON object."
    )


def _sum_usage(usages) -> dict:
    """Tokens of one Codex thread (the first run and its repair rounds). Codex reports a running
    total of the thread with every turn, so the largest value per key is the thread's total."""
    total: dict = {}
    for u in usages:
        for k, v in (u or {}).items():
            if isinstance(v, (int, float)):
                total[k] = max(total.get(k, 0), v)
    return total


# ------------------------------------------------------------ caption checklist

def find_caption_candidates(ws, manifests: dict) -> list[dict]:
    cands = []
    for doc, manifest in manifests.items():
        for page in manifest["pages"]:
            path = ws.doc_dir(doc) / "blocks" / f"{page['tag']}.jsonl"
            for i, line in enumerate(open(path, encoding="utf-8")):
                block = json.loads(line)
                text = " ".join(block["text"].split())
                if block["type"] == "text" and CAPTION_RE.match(text):
                    cands.append({"candidate_id": f"{doc}:p{page['page']}:b{i}", "doc": doc,
                                  "page": page["page"], "bbox": block["bbox"], "text": text[:200]})
    return cands


# ------------------------------------------------------------------- validation

def _full_schema(schema: dict) -> dict:
    """Codex's strict schema plus the constraints it cannot express."""
    full = copy.deepcopy(schema)
    bbox = {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}
    region = full["properties"]["regions"]["items"]["properties"]
    region["boxes"]["items"]["properties"]["bbox"] = bbox
    region["boxes"]["minItems"] = 1
    region["blocks"]["items"]["properties"]["bbox"] = bbox
    full["properties"]["schemes"]["items"]["properties"]["bbox"] = bbox
    return full


def validate(data: dict, manifests: dict, candidates: list[dict], schema: dict, docs=None):
    """`docs`: the documents in scope (default: every document of the paper)."""
    docs = list(manifests) if docs is None else list(docs)
    errors: list[str] = []
    warnings: list[str] = []
    for e in Draft202012Validator(_full_schema(schema)).iter_errors(data):
        errors.append(f"schema at /{'/'.join(map(str, e.absolute_path))}: {e.message}")
    if errors:
        return errors, warnings  # the semantic checks below assume a well-formed object

    def page_ok(where, doc, page):
        if doc not in manifests:
            errors.append(f"{where}: document '{doc}' does not exist for this paper")
            return False
        if doc not in docs:
            errors.append(f"{where}: document '{doc}' is out of scope for this run (in scope: "
                          f"{', '.join(docs)}); leave it out")
            return False
        n = manifests[doc]["page_count"]
        if not 1 <= page <= n:
            hint = (" (pages inside a region refer to the region's own doc; link the other "
                    "document through related)") if where.startswith("region") else ""
            errors.append(f"{where}: page {page} out of range 1..{n} for {doc}{hint}")
            return False
        return True

    def bbox_ok(where, doc, page, bbox):
        if not page_ok(where, doc, page):
            return False
        x0, y0, x1, y1 = bbox
        w, h = manifests[doc]["pages"][page - 1]["size_pt"]
        if not (x0 < x1 and y0 < y1):
            errors.append(f"{where}: bbox {bbox} needs x0<x1 and y0<y1")
            return False
        if x0 < -2 or y0 < -2 or x1 > w + 2 or y1 > h + 2:
            errors.append(f"{where}: bbox {bbox} exceeds page size {w}x{h} pt")
            return False
        return True

    # SI sections
    section_ids = set()
    sections = data["si_sections"]
    if sections and "si" not in manifests:
        errors.append("si_sections given but this paper has no SI document")
    elif sections and "si" not in docs:
        errors.append("si_sections must be empty: the SI is out of scope for this run")
    for s in sections:
        where = f"si_sections[{s['section_id']}]"
        if s["section_id"] in section_ids:
            errors.append(f"{where}: duplicate section_id")
        section_ids.add(s["section_id"])
        if "si" in docs and "si" in manifests:
            page_ok(where, "si", s["first_page"])
            page_ok(where, "si", s["last_page"])
        if s["first_page"] > s["last_page"]:
            errors.append(f"{where}: first_page > last_page")
    ordered = sorted(sections, key=lambda s: (s["first_page"], s["last_page"]))
    for a, b in zip(ordered, ordered[1:]):
        if b["first_page"] < a["last_page"]:
            warnings.append(f"si_sections {a['section_id']} and {b['section_id']} overlap "
                            f"(pages {a['first_page']}-{a['last_page']} / {b['first_page']}-{b['last_page']})")

    # General schemes
    scheme_docs: dict = {}
    for sc in data["schemes"]:
        where = f"scheme {sc['scheme_id']}"
        if sc["scheme_id"] in scheme_docs:
            errors.append(f"{where}: duplicate scheme_id")
        scheme_docs[sc["scheme_id"]] = sc["doc"]
        bbox_ok(where, sc["doc"], sc["page"], sc["bbox"])
    used_schemes = set()

    # Regions and blocks
    region_ids = set()
    for r in data["regions"]:
        rid = r["region_id"]
        where = f"region {rid}"
        if rid in region_ids:
            errors.append(f"{where}: duplicate region_id")
        region_ids.add(rid)
        doc = r["doc"]
        if r["first_page"] > r["last_page"]:
            errors.append(f"{where}: first_page > last_page")
        if not (page_ok(where, doc, r["first_page"]) and page_ok(where, doc, r["last_page"])):
            continue
        boxes_by_page: dict[int, list] = {}
        for i, box in enumerate(r["boxes"]):
            bw = f"{where} boxes[{i}]"
            if not r["first_page"] <= box["page"] <= r["last_page"]:
                errors.append(f"{bw}: page {box['page']} outside region pages "
                              f"{r['first_page']}-{r['last_page']}")
            if bbox_ok(bw, doc, box["page"], box["bbox"]):
                boxes_by_page.setdefault(box["page"], []).append(pymupdf.Rect(box["bbox"]))
        if r["include"] and not any(b["include"] for b in r["blocks"]):
            errors.append(f"{where}: included region needs at least one included block")
        if not r["include"] and not (r["exclude_reason"] or "").strip():
            errors.append(f"{where}: excluded region needs exclude_reason")

        block_ids = set()
        for b in r["blocks"]:
            bw = f"{where} block {b['block_id']}"
            if b["block_id"] in block_ids:
                errors.append(f"{bw}: duplicate block_id")
            block_ids.add(b["block_id"])
            if not r["first_page"] <= b["page"] <= r["last_page"]:
                errors.append(f"{bw}: page {b['page']} outside region pages "
                              f"{r['first_page']}-{r['last_page']}")
            if bbox_ok(bw, doc, b["page"], b["bbox"]) and b["page"] in boxes_by_page:
                outer = pymupdf.Rect(boxes_by_page[b["page"]][0])
                for extra in boxes_by_page[b["page"]][1:]:
                    outer |= extra
                t = BBOX_TOLERANCE
                grown = pymupdf.Rect(outer.x0 - t, outer.y0 - t, outer.x1 + t, outer.y1 + t)
                if not grown.contains(pymupdf.Rect(b["bbox"])):
                    errors.append(f"{bw}: bbox {b['bbox']} is not inside the region box "
                                  f"{[round(v, 1) for v in outer]} on page {b['page']}")
            ef, el = b["entries_first_page"], b["entries_last_page"]
            if (ef is None) != (el is None):
                errors.append(f"{bw}: set both entries_first_page and entries_last_page, or neither")
            elif ef is not None:
                if page_ok(bw, doc, ef) and page_ok(bw, doc, el) and ef > el:
                    errors.append(f"{bw}: entries_first_page > entries_last_page")
            if b["n_entries_est"] < 0:
                errors.append(f"{bw}: n_entries_est must be >= 0")
            if b["scheme_id"] is not None:
                used_schemes.add(b["scheme_id"])
                if b["scheme_id"] not in scheme_docs:
                    errors.append(f"{bw}: scheme_id '{b['scheme_id']}' is not listed under schemes")
                elif scheme_docs[b["scheme_id"]] != doc:
                    errors.append(f"{bw}: scheme '{b['scheme_id']}' is in '{scheme_docs[b['scheme_id']]}' but "
                                  f"the block is in '{doc}'; a block follows a scheme of its own document")

    for sid in sorted(set(scheme_docs) - used_schemes):
        warnings.append(f"scheme {sid} is not referenced by any block")

    targets = region_ids | section_ids
    for r in data["regions"]:
        for rel in r["related"]:
            if rel["target_id"] not in targets:
                errors.append(f"region {r['region_id']}: related target '{rel['target_id']}' "
                              "is neither a region_id nor a section_id")
            elif rel["target_id"] == r["region_id"]:
                errors.append(f"region {r['region_id']}: related to itself")

    # Caption checklist
    known = {c["candidate_id"] for c in candidates}
    seen = set()
    for item in data["caption_check"]:
        cid = item["candidate_id"]
        if cid not in known:
            warnings.append(f"caption_check: unknown candidate_id {cid}")
            continue
        seen.add(cid)
        if item["region_id"] is not None:
            if item["region_id"] not in region_ids:
                errors.append(f"caption_check {cid}: region '{item['region_id']}' does not exist")
        elif not (item["reason"] or "").strip():
            errors.append(f"caption_check {cid}: give a region_id or a reason")
    for cid in sorted(known - seen):
        errors.append(f"caption_check: candidate {cid} is not accounted for")
    return errors, warnings


# ------------------------------------------------------------- crops

def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")


def render_crops(data: dict, manifests: dict, out: Path) -> dict:
    """Returns {(region_id, None|block_id): [relative png paths]}."""
    out.mkdir(parents=True, exist_ok=True)
    pdfs = {doc: pymupdf.open(m["pdf"]) for doc, m in manifests.items()}
    crops: dict = {}

    def crop(doc, page, bbox, name):
        render_clip(pdfs[doc][page - 1], bbox, out / name, dpi=CROP_DPI, margin=3)
        return f"crops/{name}"

    for sc in data["schemes"]:
        crops[("scheme", sc["scheme_id"])] = [
            crop(sc["doc"], sc["page"], sc["bbox"], f"scheme__{_safe(sc['scheme_id'])}.png")]
    for r in data["regions"]:
        base = _safe(r["region_id"])
        crops[(r["region_id"], None)] = [
            crop(r["doc"], box["page"], box["bbox"], f"{base}__p{box['page']}_{i}.png")
            for i, box in enumerate(r["boxes"])]
        for b in r["blocks"]:
            crops[(r["region_id"], b["block_id"])] = [
                crop(r["doc"], b["page"], b["bbox"], f"{base}__blk-{_safe(b['block_id'])}.png")]
    for doc in pdfs.values():
        doc.close()
    return crops

