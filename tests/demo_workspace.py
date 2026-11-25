"""A made-up paper in the layout of work/<id>/, for looking at the data without running Codex:

    python -m tests.demo_workspace <dir>      # Step 2 output only
    python -m demo.make                       # the same, plus PDFs and the import-ready files

Its Step 2 results come from the fixtures of test_extract_records, so every state a reaction
can be in is there (extracted, failed, not yet extracted, several steps, inferred, undecided).
Pictures are placeholders.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from pipeline.extract_view import block_head, block_view, index
from pipeline.papers import write_json
from tests.test_extract_records import demo_views

PAGE = (600.0, 800.0)  # pt, as in the fixtures
DPI = 100


def _picture(path: Path, text: str, size=(300, 200)) -> None:
    """A stand-in for a crop: a ring with the name of what it stands for."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    w, h = size
    draw.regular_polygon((w / 2, h / 2 - 12, min(w, h) / 3.4), 6, outline=(40, 60, 120), width=3)
    draw.text((w / 2, h - 22), text, fill=(40, 40, 40), anchor="mm", font=ImageFont.load_default(size=18))
    img.save(path)


def _crops(node, out: Path) -> None:
    """A placeholder for every crop the views name."""
    if isinstance(node, dict):
        if isinstance(node.get("crop"), str) and not (out / node["crop"]).exists():
            _picture(out / node["crop"], str(node.get("label") or node.get("key") or node.get("eid") or ""))
        for value in node.values():
            _crops(value, out)
    elif isinstance(node, list):
        for value in node:
            _crops(value, out)


def _page(path: Path, data: dict) -> None:
    """The page the boxes of the block lie on, with something drawn where each box is."""
    s = DPI / 72
    img = Image.new("RGB", (round(PAGE[0] * s), round(PAGE[1] * s)), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=14)

    def mark(bbox, text):
        x0, y0, x1, y1 = (v * s for v in bbox)
        draw.rounded_rectangle([x0 + 3, y0 + 3, x1 - 3, y1 - 3], radius=6, fill=(236, 240, 246))
        draw.text(((x0 + x1) / 2, (y0 + y1) / 2), text, fill=(70, 80, 100), anchor="mm", font=font)

    template = data["template"]
    for p in template["participants"]:
        if p["bbox"]:
            mark(p["bbox"], p["label"] or p["key"])
    for x in template["structures"]:
        mark(x["bbox"], x["label"] or x["key"])
    for g in data["ignored"]:
        mark(g["bbox"], "Scheme 2. Scope")
    for e in data["entries"]:
        mark(e["bbox"], f"{e['label']}  42%")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def build(root: Path, paper_id: str = "demo") -> Path:
    ws = Path(root) / paper_id
    views = demo_views()
    views[0]["block"] = {**views[0]["block"], "bbox": [40, 15, 320, 170], "title": "Scope of the coupling"}
    views[1]["block"] = {**views[1]["block"], "block_id": "2", "bbox": [40, 590, 320, 670],
                         "title": "A block read before the rules changed"}
    blocks = [block_view(v) for v in views]
    heads = [block_head(b) for b in blocks]
    summary = {"blocks": len(blocks), "inventories_ok": 1, "inventories_stale": 1,
               "entries_listed": 2, "entries_ok": 1, "entries_failed": 1,
               "reactions_listed": 6, "reactions_ok": 5, "reactions_failed": 1, "records": 5}
    paper = {"reaction_class": "A made-up coupling, to look at every state a reaction can record",
             "numbering_convention": "", "notes": ""}

    for data in blocks:
        write_json(ws / "step2" / "blocks" / data["slug"] / "view.json", data)
        _crops(data, ws / "step2")
    write_json(ws / "step2" / "index.json", index(paper_id, paper, summary, heads))
    write_json(ws / "step2" / "summary.json", summary)
    write_json(ws / "step2" / "reactions.json", {"paper_id": paper_id, "records": [
        r["record"] for b in blocks for e in b["entries"] for r in e["reactions"] if r["record"]]})

    _page(ws / "main" / "pages" / "p001.png", blocks[0])
    write_json(ws / "main" / "manifest.json", {
        "pdf": "", "page_count": 1, "dpi": DPI, "metadata": {},
        "pages": [{"page": 1, "size_pt": list(PAGE), "render": "pages/p001.png"}]})
    done = {"status": "done", "started_at": "2026-01-01T00:00:00+00:00", "finished_at": "2026-01-01T00:01:00+00:00",
            "seconds": 60.0}
    write_json(ws / "paper.json", {
        "paper_id": paper_id,
        "documents": {"main": {"pdf": "Demo et al. - J. Made-up Chem. - 2026 - Every state a reaction can be in.pdf"}},
        "steps": {"preprocess": {**done, "summary": {"main": {"pages": 1}}},
                  "extract": {**done, "summary": summary}}})
    return ws


if __name__ == "__main__":
    print(build(Path(sys.argv[1])))
