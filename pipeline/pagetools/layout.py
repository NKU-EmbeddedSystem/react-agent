"""List the geometric blocks of a page and draw them as numbered boxes.

Graphic blocks (G#) are clusters of vector drawings and raster images whose
boxes lie within --gap points of each other; text blocks (T#) come from the
PDF text layer. Outlined text inside vector schemes counts as drawings, so a
scheme usually shows up as one G block. Use --within with a smaller --gap to
split a region into its sub-panels.

Usage: python -m pipeline.pagetools.layout <ws> <main|si> <page> [--gap 12] [--min-size 20]
       [--within x0,y0,x1,y1] [--no-text] [--json]
Prints the block list and the path of the annotated PNG.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from .common import fmt_bbox, load_manifest, open_page, page_entry, parse_bbox, save_png, tool_dir

CELL = 24.0  # spatial hash cell size (pt)


def _visible(d: dict) -> bool:
    # Pure white fills without a stroke are invisible backgrounds.
    fill, stroke = d.get("fill"), d.get("color")
    return not (stroke is None and fill is not None and all(c > 0.98 for c in fill))


def cluster(rects: list[pymupdf.Rect], gap: float) -> list[pymupdf.Rect]:
    """Union-find over rects whose gap-expanded boxes intersect (spatial hashing)."""
    n = len(rects)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    grown = [pymupdf.Rect(r.x0 - gap / 2, r.y0 - gap / 2, r.x1 + gap / 2, r.y1 + gap / 2)
             for r in rects]
    cells = defaultdict(list)
    for i, r in enumerate(grown):
        for cx in range(int(r.x0 // CELL), int(r.x1 // CELL) + 1):
            for cy in range(int(r.y0 // CELL), int(r.y1 // CELL) + 1):
                for j in cells[(cx, cy)]:
                    if find(i) != find(j) and grown[i].intersects(grown[j]):
                        parent[find(i)] = find(j)
                cells[(cx, cy)].append(i)

    groups: dict[int, pymupdf.Rect] = {}
    for i, r in enumerate(rects):
        root = find(i)
        groups[root] = groups[root] | r if root in groups else pymupdf.Rect(r)
    return list(groups.values())


def graphic_rects(page: pymupdf.Page, area: pymupdf.Rect) -> list[pymupdf.Rect]:
    """Boxes of visible vector drawings and raster images inside `area`."""
    page_area = abs(page.rect)
    rects = []
    for d in page.get_drawings():
        r = pymupdf.Rect(d["rect"])
        if abs(r) > 0.9 * page_area or not _visible(d):
            continue
        # Straight lines have zero width or height; give them some thickness so
        # intersection tests treat them as non-empty.
        if r.width < 0.5:
            r.x0, r.x1 = r.x0 - 0.25, r.x1 + 0.25
        if r.height < 0.5:
            r.y0, r.y1 = r.y0 - 0.25, r.y1 + 0.25
        if r.intersects(area):
            rects.append(r & area)
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"])
        if r.intersects(area):
            rects.append(r & area)
    return rects


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ws")
    ap.add_argument("doc", choices=["main", "si"])
    ap.add_argument("page", type=int)
    ap.add_argument("--gap", type=float, default=12.0,
                    help="merge distance in pt; 12 ~ whole schemes/tables, 4-8 ~ sub-panels (with --within)")
    ap.add_argument("--within", help="x0,y0,x1,y1: only consider this area")
    ap.add_argument("--min-size", type=float, default=20.0,
                    help="drop graphic blocks whose width and height are both below this (pt)")
    ap.add_argument("--no-text", action="store_true", help="omit text blocks")
    ap.add_argument("--json", action="store_true", help="print the block list as JSON")
    args = ap.parse_args()

    doc_dir, manifest = load_manifest(args.ws, args.doc)
    entry = page_entry(manifest, args.page)
    page = open_page(manifest, args.page)
    area = page.rect if not args.within else parse_bbox(args.within) & page.rect

    rects = graphic_rects(page, area)

    graphics = sorted(
        (g for g in cluster(rects, args.gap) if g.width >= args.min_size or g.height >= args.min_size),
        key=lambda r: (round(r.y0 / 5), r.x0),
    )
    blocks = []
    for i, g in enumerate(graphics, 1):
        blocks.append({"id": f"G{i}", "type": "graphic", "bbox": [round(v, 1) for v in g]})

    if not args.no_text:
        texts = [json.loads(line) for line in open(doc_dir / "blocks" / f"{entry['tag']}.jsonl", encoding="utf-8")]
        texts = [t for t in texts if t["type"] == "text" and pymupdf.Rect(t["bbox"]).intersects(area)]
        for i, t in enumerate(sorted(texts, key=lambda t: (round(t["bbox"][1] / 5), t["bbox"][0])), 1):
            snippet = " ".join(t["text"].split())[:80]
            blocks.append({"id": f"T{i}", "type": "text", "bbox": t["bbox"], "text": snippet})

    # Annotated image: start from the stored render, crop to --within if given.
    scale = manifest["dpi"] / 72
    img = Image.open(doc_dir / entry["render"]).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=max(14, int(9 * scale)))
    for b in blocks:
        x0, y0, x1, y1 = (v * scale for v in b["bbox"])
        color = "red" if b["type"] == "graphic" else "blue"
        draw.rectangle([x0, y0, x1, y1], outline=color, width=3 if color == "red" else 1)
        draw.text((x0 + 2, y0 + 1), b["id"], fill=color, font=font)
    suffix = ""
    if args.within:
        m = 10
        img = img.crop(tuple(int(v) for v in ((area.x0 - m) * scale, (area.y0 - m) * scale,
                                               (area.x1 + m) * scale, (area.y1 + m) * scale)))
        suffix = "_within_" + "_".join(str(int(v)) for v in area)
    gap_tag = f"_gap{args.gap:g}" + ("_notext" if args.no_text else "")
    out = save_png(img, tool_dir(args.ws) / f"layout_{args.doc}_p{args.page:03d}{suffix}{gap_tag}.png")

    if args.json:
        print(json.dumps({"page": args.page, "size_pt": entry["size_pt"], "image": str(out),
                          "blocks": blocks}, ensure_ascii=False, indent=1))
        return
    print(f"{args.doc} page {args.page}  size_pt={entry['size_pt']}  gap={args.gap}"
          + (f"  within={fmt_bbox(area)}" if args.within else ""))
    for b in blocks:
        w, h = b["bbox"][2] - b["bbox"][0], b["bbox"][3] - b["bbox"][1]
        extra = f"  {b['text']!r}" if b["type"] == "text" else ""
        print(f"  {b['id']:>4} {b['type']:<7} {fmt_bbox(b['bbox'])}  {w:.0f}x{h:.0f}{extra}")
    print(f"annotated image: {out}")


if __name__ == "__main__":
    main()
