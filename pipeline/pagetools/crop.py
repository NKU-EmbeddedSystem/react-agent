"""Render a bbox of a page at high resolution, to check that a box is right.

Usage: python -m pipeline.pagetools.crop <ws> <main|si> <page> <x0,y0,x1,y1> [--dpi 300] [--margin 4] [--out PATH]
Prints the path of the PNG.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf

from .common import load_manifest, open_page, parse_bbox, save_png, tool_dir


def render_clip(page: pymupdf.Page, bbox, path: str | Path, dpi: int = 300, margin: float = 4.0) -> Path:
    """Render `bbox` (PDF points) plus a margin to `path`."""
    b = pymupdf.Rect(bbox)
    clip = pymupdf.Rect(b.x0 - margin, b.y0 - margin, b.x1 + margin, b.y1 + margin) & page.rect
    return save_png(page.get_pixmap(dpi=dpi, clip=clip), path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ws")
    ap.add_argument("doc", choices=["main", "si"])
    ap.add_argument("page", type=int)
    ap.add_argument("bbox", help="x0,y0,x1,y1 in pt")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--margin", type=float, default=4.0, help="extra pt around the box")
    ap.add_argument("--out", help="output path (default: the shared tool dir)")
    args = ap.parse_args()

    _, manifest = load_manifest(args.ws, args.doc)
    page = open_page(manifest, args.page)
    box = parse_bbox(args.bbox)
    name = (f"crop_{args.doc}_p{args.page:03d}_" + "_".join(f"{v:.0f}" for v in box)
            + f"_d{args.dpi}_m{args.margin:g}.png")
    out = render_clip(page, box, args.out or tool_dir(args.ws) / name, args.dpi, args.margin)
    print(f"image: {out}")


if __name__ == "__main__":
    main()
