"""Tighten a bbox to the ink inside it (works on vector, raster and scanned pages).

Draw a box generously around a structure, then trim it: the result hugs the
drawing. Trimming only shrinks a box; ink of neighbours that reaches into the
box stays in.

Usage: python -m pipeline.pagetools.trim <ws> <main|si> <page> <x0,y0,x1,y1> [--pad 1.5]
Prints the trimmed bbox and the path of a crop of it.
"""

from __future__ import annotations

import argparse

import numpy as np
import pymupdf

from .common import fmt_bbox, load_manifest, open_page, parse_bbox, tool_dir
from .crop import render_clip
from .layout import cluster

INK_THRESHOLD = 235  # grey levels below this count as ink
BACKGROUND_MARGIN = 25  # on a tinted background, ink is at least this much darker than the background


def ink_mask(page: pymupdf.Page, rect: pymupdf.Rect, dpi: int) -> np.ndarray:
    """Boolean array (rows, cols) that is True where the rendered page has ink.

    The background is the most common grey level of the area: on a light tinted panel (the
    coloured background of many figures) the tint is not ink, only what is drawn on it."""
    pix = page.get_pixmap(dpi=dpi, clip=rect, colorspace=pymupdf.csGRAY)
    grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
    background = int(np.bincount(grey.ravel(), minlength=256).argmax()) if grey.size else 255
    threshold = INK_THRESHOLD if background < 128 else min(INK_THRESHOLD, background - BACKGROUND_MARGIN)
    return grey < threshold


def ink_edges(page: pymupdf.Page, bbox, dpi: int = 200) -> list[str]:
    """The sides of `bbox` whose outermost pixel column or row has ink. After `trim_bbox`, which
    leaves a margin around the ink, ink on a side means the box cuts through a drawing there."""
    rect = pymupdf.Rect(bbox) & page.rect
    if rect.is_empty:
        return []
    mask = ink_mask(page, rect, dpi)
    if not mask.any():
        return []
    sides = [("left", mask[:, 0]), ("top", mask[0, :]), ("right", mask[:, -1]), ("bottom", mask[-1, :])]
    return [name for name, line in sides if line.any()]


def _components(mask: np.ndarray) -> tuple[np.ndarray, int, np.ndarray]:
    """8-connected components of a boolean mask, without scipy: labels, count and sizes by label."""
    from collections import deque
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    sizes = []
    count = 0
    for y, x in zip(*np.nonzero(mask)):
        if labels[y, x]:
            continue
        count += 1
        labels[y, x] = count
        n = 0
        q = deque([(int(y), int(x))])
        while q:
            cy, cx = q.popleft()
            n += 1
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = count
                        q.append((ny, nx))
        sizes.append(n)
    return labels, count, np.asarray(sizes, dtype=float)


def edge_severity(page: pymupdf.Page, bbox, dpi: int = 200) -> dict[str, str]:
    """Classify each side that still touches ink: `cut` when the side's ink belongs to the box's
    largest connected drawing (a structure running through the border), `touch` when it is a thin
    neighbour line or label. Only `cut` means the drawing may be incomplete; `touch` is safe."""
    rect = pymupdf.Rect(bbox) & page.rect
    if rect.is_empty:
        return {}
    mask = ink_mask(page, rect, dpi)
    total = int(mask.sum())
    if total == 0:
        return {}
    labels, count, sizes = _components(mask)
    if count == 0:
        return {}
    largest = int(np.argmax(sizes)) + 1
    largest_size = float(sizes[largest - 1])
    band = max(1, round(3 / (72 / dpi)))
    out = {}
    for name, line in (("left", labels[:, :band]), ("right", labels[:, -band:]),
                       ("top", labels[:band, :]), ("bottom", labels[-band:, :])):
        ids = {int(v) for v in np.unique(line) if v}
        if not ids:
            continue
        out[name] = "cut" if (largest in ids and largest_size / total >= 0.5) else "touch"
    return out


def trim_bbox(page: pymupdf.Page, bbox, pad: float = 1.5, dpi: int = 200) -> pymupdf.Rect | None:
    """Shrink `bbox` to its ink plus `pad` points; None if the box is blank.

    The pad may extend past the original box, up to the page edge: a reader that gives a tight
    box gets its white margin here, so an edge that merely touches the ink is not a cut. Ink that
    really runs past `pad` still reaches the edge and is reported by `ink_edges`."""
    rect = pymupdf.Rect(bbox) & page.rect
    if rect.is_empty:
        return None
    mask = ink_mask(page, rect, dpi)
    rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
    if rows.size == 0:
        return None
    s = 72 / dpi
    tight = pymupdf.Rect(rect.x0 + cols[0] * s - pad, rect.y0 + rows[0] * s - pad,
                         rect.x0 + (cols[-1] + 1) * s + pad, rect.y0 + (rows[-1] + 1) * s + pad)
    return tight & page.rect


def _rule_line(b: pymupdf.Rect, thin: float = 10.0, length: float = 20.0) -> bool:
    """A table rule or separator: a long, thin band, not a drawing and not a line of text.
    The coverage check ignores these so a printed rule does not fail a whole block. The band is
    measured after cells of `uncovered_blobs` are coarsened, so it can be up to ~8 pt thick."""
    return min(b.width, b.height) <= thin and max(b.width, b.height) >= length


def uncovered_blobs(page: pymupdf.Page, area, covered: list, tolerance: float = 3.0,
                    cell: float = 4.0, gap: float = 8.0, min_side: float = 14.0) -> list[pymupdf.Rect]:
    """Ink inside `area` that none of the `covered` boxes accounts for.

    Returns the boxes of leftover ink clusters with at least one side >= `min_side`
    points (smaller specks such as stray punctuation are ignored)."""
    area = pymupdf.Rect(area) & page.rect
    dpi = 72  # one pixel per point is enough here
    mask = ink_mask(page, area, dpi)
    h, w = mask.shape
    for box in covered:
        b = pymupdf.Rect(box)
        x0 = max(0, int(b.x0 - tolerance - area.x0))
        y0 = max(0, int(b.y0 - tolerance - area.y0))
        x1 = min(w, int(b.x1 + tolerance - area.x0) + 1)
        y1 = min(h, int(b.y1 + tolerance - area.y0) + 1)
        if x0 < x1 and y0 < y1:
            mask[y0:y1, x0:x1] = False

    # Coarsen to cells of `cell` points, then cluster the inked cells.
    n = int(cell)
    padded = np.zeros((-(-h // n) * n, -(-w // n) * n), dtype=bool)
    padded[:h, :w] = mask
    grid = padded.reshape(padded.shape[0] // n, n, padded.shape[1] // n, n).any(axis=(1, 3))
    cells = [pymupdf.Rect(area.x0 + cx * n, area.y0 + cy * n, area.x0 + (cx + 1) * n, area.y0 + (cy + 1) * n)
             for cy, cx in zip(*np.nonzero(grid))]
    blobs = [b for b in cluster(cells, gap)
             if (b.width >= min_side or b.height >= min_side) and not _rule_line(b)]
    return sorted(blobs, key=lambda r: (round(r.y0 / 5), r.x0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ws")
    ap.add_argument("doc", choices=["main", "si"])
    ap.add_argument("page", type=int)
    ap.add_argument("bbox", help="x0,y0,x1,y1 in pt")
    ap.add_argument("--pad", type=float, default=1.5, help="pt kept around the ink")
    args = ap.parse_args()

    _, manifest = load_manifest(args.ws, args.doc)
    page = open_page(manifest, args.page)
    box = parse_bbox(args.bbox)
    tight = trim_bbox(page, box, args.pad)
    if tight is None:
        print("no ink inside this box")
        return
    name = f"trim_{args.doc}_p{args.page:03d}_" + "_".join(f"{v:.0f}" for v in tight) + ".png"
    out = render_clip(page, tight, tool_dir(args.ws) / name, dpi=300, margin=0)
    print(f"trimmed bbox: {fmt_bbox(tight)}")
    print(f"image: {out}")


if __name__ == "__main__":
    main()
