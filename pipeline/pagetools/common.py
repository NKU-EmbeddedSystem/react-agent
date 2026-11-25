"""Shared helpers for the page tools (workspace = work/<paper_id>)."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import pymupdf


def die(msg: str) -> None:
    sys.exit(f"error: {msg}")


def load_manifest(ws: str | Path, doc: str) -> tuple[Path, dict]:
    doc_dir = Path(ws) / doc
    path = doc_dir / "manifest.json"
    if not path.exists():
        die(f"{path} not found (doc must be 'main' or 'si', ws must be work/<paper_id>)")
    return doc_dir, json.loads(path.read_text(encoding="utf-8"))


def page_entry(manifest: dict, page: int) -> dict:
    if not 1 <= page <= manifest["page_count"]:
        die(f"page {page} out of range 1..{manifest['page_count']}")
    return manifest["pages"][page - 1]


def open_page(manifest: dict, page: int) -> pymupdf.Page:
    page_entry(manifest, page)
    return pymupdf.open(manifest["pdf"])[page - 1]


def parse_bbox(text: str) -> pymupdf.Rect:
    try:
        x0, y0, x1, y1 = (float(v) for v in text.replace(" ", "").split(","))
    except ValueError:
        die(f"bad bbox {text!r}; expected x0,y0,x1,y1 in PDF points")
    if x0 >= x1 or y0 >= y1:
        die(f"bad bbox {text!r}; need x0<x1 and y0<y1")
    return pymupdf.Rect(x0, y0, x1, y1)


def fmt_bbox(r) -> str:
    return "[" + ", ".join(f"{v:.1f}" for v in r) + "]"


def tool_dir(ws: str | Path) -> Path:
    """Shared output dir of the tools. File names are derived from the arguments, so
    concurrent callers asking for the same image get the same file."""
    d = Path(ws) / "scratch" / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_png(image, path: str | Path) -> Path:
    """Atomic save of a PIL image or a pymupdf pixmap (readers never see a partial file)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.stem}.{uuid.uuid4().hex[:8]}.png")
    image.save(str(tmp))
    os.replace(tmp, path)
    return path
