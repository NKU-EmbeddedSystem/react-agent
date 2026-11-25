"""Small helpers shared by the Step 2 drivers: the generic one (s2_extract) and the ones written
for one block layout (s2_table, with s2_ctable, s2_rtable and s2_pscope for condition tables, reactant
tables and product scopes).

Nothing here knows about a particular skill or layout.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw


def sha(*parts) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def files_sha(paths) -> str:
    """Hash of the contents of `paths` (a skill's text, its schemas): editing any of them makes the
    results that depend on them stale."""
    return sha([Path(p).read_text(encoding="utf-8") for p in paths])


def grow(bbox, d: float) -> list[float]:
    return [bbox[0] - d, bbox[1] - d, bbox[2] + d, bbox[3] + d]


def outlined(page: pymupdf.Page, clip, box, max_px: int = 1400) -> Image.Image:
    """Image of `clip` without a grid, with `box` outlined in red."""
    clip = pymupdf.Rect(clip) & page.rect
    dpi = max(100, min(400, int(max_px / max(clip.width, clip.height) * 72)))
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    s = dpi / 72
    ImageDraw.Draw(img).rectangle([(box[0] - clip.x0) * s - 3, (box[1] - clip.y0) * s - 3,
                                   (box[2] - clip.x0) * s + 3, (box[3] - clip.y0) * s + 3],
                                  outline=(230, 0, 0), width=3)
    return img


def numbers(usage) -> dict:
    return {k: v for k, v in (usage or {}).items() if isinstance(v, (int, float))}


def usage_delta(total: dict, prior: dict | None) -> dict:
    """What one call added to its thread: Codex reports a running total per thread."""
    prior = prior or {}
    return {k: max(0, v - prior.get(k, 0)) for k, v in numbers(total).items()}


def thread_usage(metas) -> dict:
    """Tokens spent by the Codex sessions behind `metas`.

    Codex reports a running total for the whole thread, also across `exec resume`, so each thread
    counts once, with the largest total any of its calls saw. Metas written before this
    bookkeeping (no `usage_total`) count their own `usage`."""
    best: dict = {}
    loose = Counter()
    expanded = []
    for meta in metas:
        expanded.append(meta)
        expanded.extend({"thread_id": repair.get("thread_id"), "usage_total": repair.get("usage", {}),
                         "usage": repair.get("usage", {})}
                        for repair in meta.get("geometry_repairs", []))
    for m in expanded:
        tid, total = m.get("thread_id"), m.get("usage_total")
        if tid and total:
            cur = best.setdefault(tid, {})
            for k, v in numbers(total).items():
                cur[k] = max(cur.get(k, 0), v)
        else:
            loose.update(numbers(m.get("usage")))
    for total in best.values():
        loose.update(total)
    return dict(loose)


def load_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def repair_prompt(errors: list[str]) -> str:
    listed = "\n".join(f"- {e}" for e in errors[:60])
    more = f"\n- ... and {len(errors) - 60} more" if len(errors) > 60 else ""
    return (
        "Your JSON failed validation:\n"
        f"{listed}{more}\n\n"
        "Fix these problems (look at the page again where needed) and reply with the complete "
        "corrected JSON object."
    )
