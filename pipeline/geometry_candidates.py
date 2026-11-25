"""Numbered geometric proposals, not chemical recognition and never auto-selected boxes."""
from __future__ import annotations

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from .pagetools.layout import cluster, graphic_rects
from .papers import write_json


def proposals(page, area):
    area = pymupdf.Rect(area) & page.rect
    groups = cluster(graphic_rects(page, area), gap=4)
    # Text atom labels may be separate PDF text objects. Include nearby words conservatively;
    # proposal selection/crop review remains the reader's responsibility.
    words = page.get_text("words", clip=area)
    result = []
    for group in sorted(groups, key=lambda b: (round(b.y0 / 5), b.x0)):
        if group.width < 4 and group.height < 4:
            continue
        nearby = pymupdf.Rect(group) + (-3, -3, 3, 3)
        for word in words:
            r = pymupdf.Rect(word[:4])
            if nearby.intersects(r):
                group |= r
        group = (group + (-2, -2, 2, 2)) & page.rect
        result.append({"id": f"G{len(result)+1}", "bbox": [round(x, 1) for x in group]})
        if len(result) >= 100:
            break
    return result


def attach(job, doc, block, scheme, directory):
    """Write model-visible proposals and outlined images outside source/preprocessed files."""
    directory.mkdir(parents=True, exist_ok=True)
    areas = [(block["page"], block["bbox"], "block")]
    if scheme:
        areas.append((scheme["page"], scheme["bbox"], "scheme"))
    images, pages = [], []
    with job.pdf_lock:
        for number, (page_no, box, role) in enumerate(areas, 1):
            page = job._page(doc, page_no)
            area = (pymupdf.Rect(box) + (-10, -10, 10, 10)) & page.rect
            choices = proposals(page, area)
            dpi = max(100, min(160, int(1800 / max(area.width, area.height) * 72)))
            pix = page.get_pixmap(dpi=dpi, clip=area)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            draw = ImageDraw.Draw(image)
            font = ImageFont.load_default(size=15)
            scale = dpi / 72
            for choice in choices:
                x0, y0, x1, y1 = choice["bbox"]
                xy = [(x0-area.x0)*scale, (y0-area.y0)*scale,
                      (x1-area.x0)*scale, (y1-area.y0)*scale]
                draw.rectangle(xy, outline="#c22545", width=1)
                draw.text((xy[0]+2, xy[1]+2), choice["id"], fill="#c22545", font=font)
            path = directory / f"candidates-{number}.png"
            image.save(path)
            images.append(path)
            pages.append({"doc": doc, "page": page_no, "role": role, "area": list(area), "candidates": choices})
    write_json(directory / "candidates.json", {"proposals_only": True, "pages": pages})
    return images, (f" Candidate overlays follow; exact PDF-point proposals are in {directory / 'candidates.json'}. "
                    "They can merge neighbours or omit atom labels: choose a candidate only after visually checking "
                    "it. Use grid/layout/crop to refine and inspect final molecular crops, including every label, "
                    "excluding arrows, plus signs and adjacent structures. Do not estimate from image pixel coordinates.")
