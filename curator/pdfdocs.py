"""The PDFs inside the database: page geometry, byte ranges for the browser's viewer, renders.

A PDF is a row of `blobs` (by sha256), a paper's main text or SI a row of `documents` pointing at it.
Nothing derived from a PDF is stored: structure pictures are rendered on request from
(document, page, bbox, dpi), so a box a person redraws is pictured at once. Renders, the documents they
come from and the pages' display lists are kept in small LRU caches; the server sends the render's cache
key as the picture's ETag. The display lists matter: a page of vector drawings takes ~30 ms to interpret,
and a list of reactions asks for dozens of small clips of the same few pages.

Coordinates: a bbox is in PyMuPDF's `page.rect` frame (points, origin at the top left of the page as
displayed: CropBox offset and /Rotate applied), the frame of the pipeline's boxes. `pdf_info` stores per
page a matrix from that frame to PDF user space, the space the browser's pdf.js viewport converts from.

PyMuPDF is not thread-safe and the server answers requests in threads: every call into it is made
under RENDER_LOCK, which also guards the caches. SQLite is read with the caller's own connection.
"""

from __future__ import annotations

import math
import re
import threading
from collections import OrderedDict

import pymupdf

from . import db

MIN_DPI, MAX_DPI = 36.0, 600.0
MAX_PIXELS = 30_000_000              # a render larger than this is drawn at a lower dpi
OPEN_DOCS = 4                        # open documents kept, by sha
OPEN_PAGES = 32                      # display lists kept, by (sha, page); ~0.5 MB each on the papers so far
PNG_CACHE_BYTES = 200 * 1024 * 1024  # rendered PNGs kept, by request
RENDER_VERSION = 1                   # part of the ETag: bump when the same request would render differently

RENDER_LOCK = threading.RLock()
_docs: OrderedDict[str, pymupdf.Document] = OrderedDict()
_lists: OrderedDict[tuple[str, int], pymupdf.DisplayList] = OrderedDict()
_pngs: OrderedDict[tuple, bytes] = OrderedDict()
_png_bytes = 0


class NotFound(LookupError):
    """No such document (the server answers 404 for any LookupError)."""


# ----------------------------------------------------------------------------- reading PDFs

def _open(data: bytes) -> pymupdf.Document:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:  # PyMuPDF raises its own FileDataError / RuntimeError variants
        raise ValueError(f"无法读取 PDF：{e}") from e
    if doc.needs_pass:
        doc.close()
        raise ValueError("PDF 已加密，无法读取")
    return doc


def _to_pdf(page: pymupdf.Page) -> pymupdf.Matrix:
    """page.rect -> PDF user space: the inverse of the transform MuPDF draws the page with (CropBox
    offset, /Rotate and UserUnit included). Not `derotation_matrix * ~transformation_matrix`: on a
    rotated page PyMuPDF's transformation_matrix leaves out the CropBox offset (checked in the tests)."""
    mediabox, ctm = pymupdf.mupdf.FzRect(), pymupdf.mupdf.FzMatrix()
    pymupdf.mupdf.pdf_page_transform(page._pdf_page(), mediabox, ctm)
    return ~pymupdf.Matrix(ctm.a, ctm.b, ctm.c, ctm.d, ctm.e, ctm.f)


def pdf_info(pdf_bytes: bytes) -> dict:
    """What the documents table keeps of a PDF: per page [w, h, rotation, [a, b, c, d, e, f]] (w, h of
    page.rect; the matrix maps a page.rect point (x, y) to user space x' = a*x + c*y + e,
    y' = b*x + d*y + f), the metadata dict and the text of page 1 (for the DOI). ValueError if the
    bytes are not a readable PDF."""
    with RENDER_LOCK:
        doc = _open(pdf_bytes)
        try:
            if doc.page_count == 0:
                raise ValueError("PDF 没有页面")
            pages = []
            for page in doc:
                m = _to_pdf(page)
                pages.append([round(page.rect.width, 2), round(page.rect.height, 2), page.rotation,
                              [round(v, 4) + 0.0 for v in m]])  # + 0.0: no -0.0 in the JSON
            return {"page_count": doc.page_count, "pages": pages,
                    "metadata": {k: _utf8(v) for k, v in (doc.metadata or {}).items()},
                    "first_page_text": _utf8(doc[0].get_text())}
        finally:
            doc.close()


def _utf8(value):
    """A str that UTF-8 (SQLite, JSON) can carry: MuPDF decodes a malformed /Info string with lone
    surrogates (a truncated UTF-16 pair, an invalid byte after a UTF-8 mark), which become U+FFFD."""
    return re.sub("[\ud800-\udfff]", "�", value) if isinstance(value, str) else value


# ----------------------------------------------------------------------------- blobs

def store_pdf(conn, pdf_bytes: bytes) -> str:
    """Keep a PDF's bytes (once per content); returns its sha256."""
    sha = db.sha_bytes(pdf_bytes)
    with db.write(conn):
        if conn.execute("SELECT 1 FROM blobs WHERE sha256 = ?", (sha,)).fetchone() is None:
            conn.execute("INSERT INTO blobs (sha256, size, data) VALUES (?,?,?)", (sha, len(pdf_bytes), pdf_bytes))
    return sha


def doc_row(conn, doc_id) -> dict:
    """The documents row as stored (pages, pdf_meta still JSON text) plus `blob_rowid` and `size` of its
    PDF. NotFound (a LookupError) if there is no such document."""
    try:
        number = int(doc_id)
    except (TypeError, ValueError):  # also a str of thousands of digits
        raise NotFound(f"没有这个文档：{doc_id}") from None
    if not -2 ** 63 <= number < 2 ** 63:  # beyond what SQLite can bind (OverflowError)
        raise NotFound(f"没有这个文档：{doc_id}")
    doc_id = number
    row = conn.execute("SELECT d.*, b.rowid AS blob_rowid, b.size AS size FROM documents d"
                       " JOIN blobs b ON b.sha256 = d.sha256 WHERE d.doc_id = ?", (doc_id,)).fetchone()
    if row is None:
        raise NotFound(f"没有这个文档：{doc_id}")
    return dict(row)


def read_range(conn, blob_rowid: int, start: int, end_inclusive: int, chunk: int = 1 << 20):
    """Bytes start..end_inclusive of a blob, in pieces of at most `chunk`; the end is clamped to the
    blob's size, and a start at or past it yields nothing. The blob stays open (a read transaction on
    `conn`) until the generator is exhausted or closed."""
    if start < 0 or chunk < 1:
        raise ValueError(f"无效的字节范围：{start}-{end_inclusive}")
    return _read(conn, blob_rowid, start, end_inclusive, chunk)


def _read(conn, blob_rowid, start, end_inclusive, chunk):
    with conn.blobopen("blobs", "data", blob_rowid, readonly=True) as blob:
        end = min(end_inclusive + 1, len(blob))
        if start >= end:
            return
        blob.seek(start)
        pos = start
        while pos < end:
            data = blob.read(min(chunk, end - pos))
            if not data:
                break
            pos += len(data)
            yield data


# ----------------------------------------------------------------------------- renders

def _number(value, name: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 不是数字：{value!r}") from None
    if not math.isfinite(x):
        raise ValueError(f"{name} 不是有限的数：{value!r}")
    return x


def _page_number(page, page_count: int) -> int:
    p = _number(page, "页码")
    if p != int(p) or not 1 <= p <= page_count:
        raise ValueError(f"页码 {page} 不在 1–{page_count} 之内")
    return int(p)


def _bbox(bbox) -> tuple:
    if isinstance(bbox, (str, bytes)) or not hasattr(bbox, "__len__") or len(bbox) != 4:
        raise ValueError(f"框应是四个数 [x0, y0, x1, y1]：{bbox!r}")
    x0, y0, x1, y1 = (round(_number(v, "框坐标"), 1) + 0.0 for v in bbox)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"框是空的：{[x0, y0, x1, y1]}")
    return x0, y0, x1, y1


def _clip(rect: pymupdf.Rect, box, pad: float) -> pymupdf.Rect:
    """(box ± pad) ∩ page.rect; the whole page without a box."""
    if box is None:
        return pymupdf.Rect(rect)
    x0, y0 = max(box[0] - pad, rect.x0), max(box[1] - pad, rect.y0)
    x1, y1 = min(box[2] + pad, rect.x1), min(box[3] + pad, rect.y1)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"框 {list(box)} 不在页面 {[round(v, 2) for v in rect]} 之内")
    return pymupdf.Rect(x0, y0, x1, y1)


def _pixels(clip: pymupdf.Rect, zoom: float) -> int:
    r = (clip * pymupdf.Matrix(zoom, zoom)).irect  # rounded outwards, as MuPDF sizes the pixmap
    return r.width * r.height


def _zoom(clip: pymupdf.Rect, dpi: float) -> float:
    """dpi / 72, lowered until the picture has at most MAX_PIXELS."""
    zoom = min(dpi / 72, math.sqrt(MAX_PIXELS / (clip.width * clip.height)))
    while _pixels(clip, zoom) > MAX_PIXELS:
        zoom *= 0.999
    return zoom


def _remember(key: tuple, png: bytes) -> None:
    global _png_bytes
    if len(png) > PNG_CACHE_BYTES:
        return
    _pngs[key] = png
    _png_bytes += len(png)
    while _png_bytes > PNG_CACHE_BYTES:
        _png_bytes -= len(_pngs.popitem(last=False)[1])


def _document(sha: str, data: bytes | None) -> pymupdf.Document | None:
    """The open document of a blob, opened from `data` if it is not cached (None without data)."""
    doc = _docs.get(sha)
    if doc is not None:
        _docs.move_to_end(sha)
        return doc
    if data is None:
        return None
    doc = _docs[sha] = _open(data)
    while len(_docs) > OPEN_DOCS:
        _close(*_docs.popitem(last=False))
    return doc


def _close(sha: str, doc: pymupdf.Document) -> None:
    """Close a document and drop the display lists made from it."""
    for key in [k for k in _lists if k[0] == sha]:
        del _lists[key]
    doc.close()


def _display_list(sha: str, doc: pymupdf.Document, page: int) -> pymupdf.DisplayList:
    """The page's content interpreted once; clips of it then cost only the drawing of the clip.
    Renders from it are the same bytes as from the page itself."""
    key = (sha, page)
    dl = _lists.get(key)
    if dl is not None:
        _lists.move_to_end(key)
        return dl
    dl = _lists[key] = doc[page - 1].get_displaylist()
    while len(_lists) > OPEN_PAGES:
        _lists.popitem(last=False)
    return dl


def _request(conn, doc_id, page, bbox, dpi, pad) -> tuple[dict, tuple, str]:
    """(documents row, cache key, ETag) of a render request, checked; nothing is drawn."""
    row = doc_row(conn, doc_id)
    page = _page_number(page, row["page_count"])
    dpi = round(min(MAX_DPI, max(MIN_DPI, _number(dpi, "dpi"))), 2)
    pad = round(_number(pad, "pad"), 1) + 0.0
    if pad < 0:
        raise ValueError(f"pad 不能是负数：{pad}")
    box = None if bbox is None else _bbox(bbox)
    key = (row["sha256"], page, box, dpi, pad)
    return row, key, db.sha_json([RENDER_VERSION, *key])[:20]


def render_etag(conn, doc_id, page, bbox=None, dpi=150, pad=0.0) -> str:
    """The ETag render_png gives for these arguments, without rendering: the key it stands for names a
    PDF by content, so a client holding it already has the picture (a 304 needs no render). Raises
    what render_png raises for the arguments themselves."""
    return _request(conn, doc_id, page, bbox, dpi, pad)[2]


def render_png(conn, doc_id, page, bbox=None, dpi=150, pad=0.0) -> tuple[bytes, str]:
    """A page (or the part of it in bbox ± pad, cut to the page) as PNG, with its ETag. dpi is clamped
    to 36–600 and lowered further for pictures over MAX_PIXELS. The box is rounded to 0.1 pt before
    anything else, so requests that round alike get the same picture. NotFound for an unknown document,
    ValueError for a bad page, box, dpi or pad, or a box that misses the page."""
    row, key, etag = _request(conn, doc_id, page, bbox, dpi, pad)
    _, page, box, dpi, pad = key
    data = None
    while True:
        with RENDER_LOCK:
            png = _pngs.get(key)
            if png is not None:
                _pngs.move_to_end(key)
                return png, etag
            doc = _document(row["sha256"], data)
            if doc is not None:
                dl = _display_list(row["sha256"], doc, page)
                clip = _clip(dl.rect, box, pad)
                zoom = _zoom(clip, dpi)
                png = dl.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False).tobytes("png")
                _remember(key, png)
                return png, etag
        # Not open: read the blob outside the lock (other renders go on meanwhile), then open it.
        data = conn.execute("SELECT data FROM blobs WHERE rowid = ?", (row["blob_rowid"],)).fetchone()[0]


def clear_caches() -> None:
    """Forget every render and close the open documents (tests; a database replaced under a server)."""
    global _png_bytes
    with RENDER_LOCK:
        _pngs.clear()
        _png_bytes = 0
        while _docs:
            _close(*_docs.popitem())
        _lists.clear()
