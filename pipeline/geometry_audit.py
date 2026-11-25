"""Render all saved structure crops for human verification; this is not a model quality score.

Server-only use: python -m pipeline.geometry_audit WORKSPACE --block si-table-s1__1
Output stays inside the workspace scratch directory and includes explicit edge checks and crop images.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

from .pagetools.grid import render_grid
from .pagetools.trim import ink_edges
from .papers import write_json


def run(workspace: Path, block: str):
    if not block or Path(block).name != block:
        raise ValueError("block must be a directory basename")
    inv = json.loads((workspace / "step2/blocks" / block / "inventory.json").read_text())
    view = json.loads((workspace / "step2/blocks" / block / "view.json").read_text())
    doc_name = view["region"]["doc"]
    manifest = json.loads((workspace / doc_name / "manifest.json").read_text())
    output = workspace / "scratch/geometry-audit" / block
    output.mkdir(parents=True, exist_ok=True)
    boxes = []
    for part in inv["template"]["participants"]:
        if part.get("bbox"):
            boxes.append((f"participant-{part['key']}", part["page"], part["bbox"]))
    for part in inv["template"]["structures"]:
        boxes.append((f"structure-{part['key']}", part["page"], part["bbox"]))
    for entry in inv["entries"]:
        for cell in entry["cells"]:
            if cell.get("structure_bbox"):
                boxes.append((f"{entry['eid']}-{cell['column']}", entry["page"], cell["structure_bbox"]))
    report, tiles = [], []
    with pymupdf.open(manifest["pdf"]) as pdf:
        for i, (key, page, box) in enumerate(boxes):
            source = pdf[page - 1]
            rect = pymupdf.Rect(box)
            pix = source.get_pixmap(dpi=220, clip=rect)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            filename = f"crop-{i:03d}.png"
            image.save(output / filename)
            edges = ink_edges(source, box)
            report.append({"key": key, "doc": doc_name, "page": page, "bbox": box,
                           "ink_edges": edges, "crop": filename})
            tile = Image.new("RGB", (340, 220), "white")
            draw = ImageDraw.Draw(tile)
            draw.text((8, 8), f"{key} | {doc_name} p{page}", fill="black")
            draw.text((8, 25), f"edges: {','.join(edges) or 'clear'}", fill="red" if edges else "green")
            image.thumbnail((320, 155))
            tile.paste(image, ((340 - image.width) // 2, 52 + (155 - image.height) // 2))
            draw.rectangle((0, 0, 339, 219), outline="#aaaaaa")
            tiles.append(tile)
        for page in sorted({r["page"] for r in report}):
            source = pdf[page - 1]
            image, _, _ = render_grid(source, source.rect, max_px=1800,
                                      outline=[r["bbox"] for r in report if r["page"] == page])
            image.save(output / f"overlay-{page:03d}.png")
    sheet = Image.new("RGB", (340 * 4, 220 * max(1, (len(tiles) + 3) // 4)), "#dddddd")
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % 4) * 340, (i // 4) * 220))
    sheet.save(output / "contact-sheet.png")
    write_json(output / "report.json", {"structures": report, "all_edges_clear": not any(r["ink_edges"] for r in report),
                                         "visual_review_required": True})
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--block", required=True)
    args = parser.parse_args()
    print(run(args.workspace, args.block))


if __name__ == "__main__":
    main()
