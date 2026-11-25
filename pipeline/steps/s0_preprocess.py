"""Step 0: render every page and dump the text layer with coordinates.

Deliberately interpretation-free: no caption detection, no compound parsing.
Everything here is an objective by-product of the PDF that later (Codex-driven)
steps can browse.

Per document (work/<paper_id>/<main|si>/):
  pages/pNNN.png      full-page render
  text/pNNN.txt       plain text layer
  words/pNNN.jsonl    {"text", "bbox", "block", "line"} per word
  blocks/pNNN.jsonl   {"bbox", "type", "text"} per text/image block
  sheets/sheet_NN.png thumbnails of consecutive pages tiled into a grid
  manifest.json       document info + per-page statistics

All bboxes are in PDF points (1/72 inch), origin at the top-left of the page;
pixel = pt * dpi / 72 for the full-page renders.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from ..papers import write_json

NAME = "preprocess"
VERSION = 1

COORDS_NOTE = "bbox in PDF points (1/72 in), origin top-left; pixel = pt * dpi / 72"


def params(cfg) -> dict:
    return cfg.preprocess.to_dict()


def run(ws, cfg, log, force: bool = False) -> dict:
    pc = cfg.preprocess
    summary = {}
    for doc_name, pdf in ws.paper.documents().items():
        dpi = pc.dpi_main if doc_name == "main" else pc.dpi_si
        log.info("preprocess %s: %s (dpi=%d)", doc_name, pdf.name, dpi)
        summary[doc_name] = preprocess_document(pdf, ws.doc_dir(doc_name), dpi, pc, log)
    return summary


def _r(bbox) -> list[float]:
    return [round(float(v), 2) for v in bbox]


def _write_jsonl(path: Path, rows) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _covered_fraction(bboxes, page_rect: pymupdf.Rect) -> float:
    area = sum(abs(pymupdf.Rect(b) & page_rect) for b in bboxes)
    return round(min(1.0, area / abs(page_rect)), 3) if abs(page_rect) else 0.0


def preprocess_document(pdf: Path, out: Path, dpi: int, pc, log) -> dict:
    if out.exists():
        shutil.rmtree(out)
    for sub in ("pages", "text", "words", "blocks", "sheets"):
        (out / sub).mkdir(parents=True)

    doc = pymupdf.open(pdf)
    width = max(3, len(str(doc.page_count)))
    sheets = _SheetWriter(out / "sheets", pc)
    pages = []

    for page in doc:
        no = page.number + 1
        tag = f"p{no:0{width}d}"
        rect = page.rect

        page.get_pixmap(dpi=dpi).save(out / "pages" / f"{tag}.png")

        text = page.get_text("text")
        (out / "text" / f"{tag}.txt").write_text(text, encoding="utf-8")

        words = page.get_text("words")
        _write_jsonl(
            out / "words" / f"{tag}.jsonl",
            ({"text": w[4], "bbox": _r(w[:4]), "block": w[5], "line": w[6]} for w in words),
        )

        blocks = page.get_text("blocks")
        _write_jsonl(
            out / "blocks" / f"{tag}.jsonl",
            (
                {"bbox": _r(b[:4]), "type": "text" if b[6] == 0 else "image", "text": b[4]}
                for b in blocks
            ),
        )

        images = [
            {"bbox": _r(info["bbox"]), "px": [info["width"], info["height"]]}
            for info in page.get_image_info()
        ]

        pages.append(
            {
                "page": no,
                "tag": tag,
                "label": page.get_label() or None,
                "size_pt": _r([rect.width, rect.height]),
                "rotation": page.rotation,
                "n_chars": len(text.strip()),
                "n_words": len(words),
                "n_text_blocks": sum(1 for b in blocks if b[6] == 0),
                "n_images": len(images),
                "image_coverage": _covered_fraction([i["bbox"] for i in images], rect),
                "images": images,
                "n_drawings": len(page.get_cdrawings()),
                "render": f"pages/{tag}.png",
            }
        )
        sheets.add(page, tag)

    sheet_index = sheets.close()
    manifest = {
        "pdf": str(pdf),
        "page_count": doc.page_count,
        "dpi": dpi,
        "coords": COORDS_NOTE,
        "metadata": {k: doc.metadata.get(k) for k in ("title", "author", "subject")},
        "toc": doc.get_toc(),
        "sheets": sheet_index,
        "pages": pages,
    }
    write_json(out / "manifest.json", manifest)
    doc.close()

    summary = {
        "pages": len(pages),
        "sheets": len(sheet_index),
        "low_text_pages": sum(1 for p in pages if p["n_chars"] < 200),
        "image_covered_pages": sum(1 for p in pages if p["image_coverage"] > 0.9),
        "rotated_pages": sum(1 for p in pages if p["rotation"]),
    }
    log.info("  -> %s", summary)
    return summary


class _SheetWriter:
    """Tiles page thumbnails into fixed-size grids, flushing one sheet at a time."""

    LABEL_H = 26

    def __init__(self, out_dir: Path, pc):
        self.out_dir = out_dir
        self.pc = pc
        self.per_sheet = pc.sheet_cols * pc.sheet_rows
        self.font = ImageFont.load_default(size=18)
        self.buffer: list[tuple[int, str, Image.Image]] = []
        self.index: list[dict] = []

    def add(self, page: pymupdf.Page, tag: str) -> None:
        zoom = self.pc.thumb_width / page.rect.width
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        self.buffer.append((page.number + 1, tag, img))
        if len(self.buffer) == self.per_sheet:
            self._flush()

    def close(self) -> list[dict]:
        if self.buffer:
            self._flush()
        return self.index

    def _flush(self) -> None:
        cols = self.pc.sheet_cols
        rows = -(-len(self.buffer) // cols)
        cell_w = self.pc.thumb_width + 8
        cell_h = max(img.height for _, _, img in self.buffer) + self.LABEL_H + 8
        sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "white")
        draw = ImageDraw.Draw(sheet)
        for i, (_, tag, img) in enumerate(self.buffer):
            x, y = (i % cols) * cell_w + 4, (i // cols) * cell_h + 4
            draw.text((x, y), tag, fill="red", font=self.font)
            sheet.paste(img, (x, y + self.LABEL_H))
            draw.rectangle(
                [x - 1, y + self.LABEL_H - 1, x + img.width, y + self.LABEL_H + img.height],
                outline="gray",
            )
        name = f"sheet_{len(self.index) + 1:02d}.png"
        sheet.save(self.out_dir / name)
        self.index.append(
            {"file": f"sheets/{name}", "pages": [self.buffer[0][0], self.buffer[-1][0]]}
        )
        self.buffer = []
