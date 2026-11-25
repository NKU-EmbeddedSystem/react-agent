"""Render a page (or part of it) with a labelled grid in PDF-point coordinates.

Use it to read off bbox coordinates where the layout tool has nothing to offer
(raster figures, scanned pages) or to fine-tune a box.

Usage: python -m pipeline.pagetools.grid <ws> <main|si> <page> [--clip x0,y0,x1,y1] [--step PT] [--dpi D]
Prints the path of the PNG.
"""

from __future__ import annotations

import argparse

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from .common import load_manifest, open_page, parse_bbox, save_png, tool_dir

MARGIN = 44  # px reserved on the top/left edges for coordinate labels


def nice_step(span: float) -> int:
    # Keep the grid fine enough to read row-level boxes on a dense table: an A4 page gets 50 pt.
    for step in (5, 10, 20, 25, 50):
        if span / step <= 20:
            return step
    return 50


def render_grid(page: pymupdf.Page, clip: pymupdf.Rect, dpi: int | None = None,
                step: int | None = None, outline=(), max_px: int = 1600):
    """Image of `clip` with a point grid. `outline` boxes (PDF points) are drawn in red.

    Returns (image, step, dpi)."""
    clip = pymupdf.Rect(clip) & page.rect
    dpi = dpi or max(100, min(600, int(max_px / max(clip.width, clip.height) * 72)))
    step = step or nice_step(max(clip.width, clip.height))

    pix = page.get_pixmap(dpi=dpi, clip=clip)
    body = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    img = Image.new("RGB", (body.width + MARGIN, body.height + MARGIN), "white")
    img.paste(body, (MARGIN, MARGIN))
    draw = ImageDraw.Draw(img, "RGBA")
    font = ImageFont.load_default(size=13)
    s = dpi / 72

    first_x = int(clip.x0 // step + 1) * step
    for x in range(first_x, int(clip.x1) + 1, step):
        px = MARGIN + (x - clip.x0) * s
        major = x % (step * 2) == 0
        draw.line([(px, MARGIN), (px, img.height)], fill=(0, 120, 255, 150 if major else 70), width=1)
        draw.text((px - 10, 4 if major else 22), str(x), fill=(0, 80, 200), font=font)
    first_y = int(clip.y0 // step + 1) * step
    for y in range(first_y, int(clip.y1) + 1, step):
        py = MARGIN + (y - clip.y0) * s
        major = y % (step * 2) == 0
        draw.line([(MARGIN, py), (img.width, py)], fill=(255, 60, 0, 150 if major else 70), width=1)
        draw.text((2, py - 7), str(y), fill=(200, 40, 0), font=font)

    for box in outline:
        b = pymupdf.Rect(box)
        draw.rectangle([MARGIN + (b.x0 - clip.x0) * s, MARGIN + (b.y0 - clip.y0) * s,
                        MARGIN + (b.x1 - clip.x0) * s, MARGIN + (b.y1 - clip.y0) * s],
                       outline=(230, 0, 0, 255), width=3)
    return img, step, dpi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ws")
    ap.add_argument("doc", choices=["main", "si"])
    ap.add_argument("page", type=int)
    ap.add_argument("--clip", help="x0,y0,x1,y1 in pt (default: whole page)")
    ap.add_argument("--step", type=int, help="grid spacing in pt (default: auto)")
    ap.add_argument("--dpi", type=int, help="default: manifest dpi for full page, else sized to ~1600 px")
    args = ap.parse_args()

    _, manifest = load_manifest(args.ws, args.doc)
    page = open_page(manifest, args.page)
    clip = parse_bbox(args.clip) & page.rect if args.clip else page.rect
    dpi = args.dpi or (manifest["dpi"] if not args.clip else None)
    img, step, dpi = render_grid(page, clip, dpi, args.step)

    suffix = "" if not args.clip else "_clip_" + "_".join(str(int(v)) for v in clip)
    out = save_png(img, tool_dir(args.ws) / f"grid_{args.doc}_p{args.page:03d}{suffix}_s{step}_d{dpi}.png")
    print(f"grid step={step}pt dpi={dpi} clip=[{clip.x0:.0f}, {clip.y0:.0f}, {clip.x1:.0f}, {clip.y1:.0f}]")
    print(f"image: {out}")


if __name__ == "__main__":
    main()
