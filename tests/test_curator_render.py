"""curator.pdfdocs: page geometry against pdf.js, byte ranges, renders and their caches.

The PDFs are made here with a content stream of our own that fills rectangles given in PDF user space
(page.draw_rect cannot be the reference: on a rotated page it draws in unrotated coordinates), so the
place of a rectangle is known in user space and, worked out by hand from CropBox and /Rotate, in the
page.rect frame.
"""

from __future__ import annotations

import json
import random
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import pymupdf

from curator import db, pdfdocs


def make_pdf(media=(0, 0, 600, 800), crop=None, rotate=0, rects=(), pages=1, text=None, title=None) -> bytes:
    """Pages that fill the rectangles `rects` ([x0, y0, x1, y1] in PDF user space) in black."""
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=media[2] - media[0], height=media[3] - media[1])
        doc.xref_set_key(page.xref, "MediaBox", "[%g %g %g %g]" % tuple(media))
        if crop:
            doc.xref_set_key(page.xref, "CropBox", "[%g %g %g %g]" % tuple(crop))
        if rotate:
            doc.xref_set_key(page.xref, "Rotate", str(rotate))
        ops = " ".join(f"{x0:g} {y0:g} {x1 - x0:g} {y1 - y0:g} re" for x0, y0, x1, y1 in rects)
        xref = doc.get_new_xref()
        doc.update_object(xref, "<<>>")
        doc.update_stream(xref, f"0 g {ops} f".encode() if rects else b"")
        doc.xref_set_key(page.xref, "Contents", f"{xref} 0 R")
        if text:
            page.insert_text((72, 72), text)
    if title:
        doc.set_metadata({"title": title})
    data = doc.tobytes()
    doc.close()
    return data


def pdfjs_viewport(view, rotation, scale=1.0):
    """pdf.js's PageViewport (6.4.299 as vendored): the transform from PDF user space to viewport
    pixels, and the viewport's width and height. `view` is the page's CropBox ∩ MediaBox."""
    cx, cy = (view[2] + view[0]) / 2, (view[3] + view[1]) / 2
    a, b, c, d = {0: (1, 0, 0, -1), 90: (0, 1, 1, 0), 180: (-1, 0, 0, 1), 270: (0, -1, -1, 0)}[rotation % 360]
    if a == 0:
        ox, oy = abs(cy - view[1]) * scale, abs(cx - view[0]) * scale
        w, h = (view[3] - view[1]) * scale, (view[2] - view[0]) * scale
    else:
        ox, oy = abs(cx - view[0]) * scale, abs(cy - view[1]) * scale
        w, h = (view[2] - view[0]) * scale, (view[3] - view[1]) * scale
    t = [a * scale, b * scale, c * scale, d * scale,
         ox - a * scale * cx - c * scale * cy, oy - b * scale * cx - d * scale * cy]
    return t, w, h


def apply(m, x, y):
    """PDF convention: x' = a*x + c*y + e, y' = b*x + d*y + f."""
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def map_rect(m, r):
    (x0, y0), (x1, y1) = apply(m, r[0], r[1]), apply(m, r[2], r[3])
    return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]


def png_size(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", png[16:24])


DARK = bytes(1 if v < 128 else 0 for v in range(256))


def ink(png: bytes):
    """Pixel box [x0, y0, x1, y1] of the dark pixels of a PNG, or None."""
    pix = pymupdf.Pixmap(png)
    if pix.n != 1:
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
    s, box = pix.samples, None
    for y in range(pix.height):
        row = s[y * pix.stride: y * pix.stride + pix.width].translate(DARK)
        i = row.find(1)
        if i < 0:
            continue
        j = row.rfind(1) + 1
        box = [i, y, j, y + 1] if box is None else [min(box[0], i), box[1], max(box[2], j), y + 1]
    return box


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "curator.sqlite"
        self.conn = db.connect(self.path, create=True)
        pdfdocs.clear_caches()

    def tearDown(self):
        self.conn.close()
        pdfdocs.clear_caches()
        self.tmp.cleanup()

    def add_doc(self, pdf: bytes, paper_id="p1", doc="main") -> int:
        sha = pdfdocs.store_pdf(self.conn, pdf)
        info = pdfdocs.pdf_info(pdf)
        now = db.now_iso()
        with db.write(self.conn):
            self.conn.execute("INSERT OR IGNORE INTO papers (paper_id, rev, created_at, updated_at)"
                              " VALUES (?, 1, ?, ?)", (paper_id, now, now))
            cur = self.conn.execute(
                "INSERT INTO documents (paper_id, doc, filename, sha256, page_count, pages, pdf_meta)"
                " VALUES (?,?,?,?,?,?,?)", (paper_id, doc, f"{paper_id}-{doc}.pdf", sha, info["page_count"],
                                            db.dumps(info["pages"]), db.dumps(info["metadata"])))
        return cur.lastrowid


RECT = (100, 200, 300, 260)  # user space
# name: (MediaBox, CropBox, /Rotate, page.rect size, where RECT lands in page.rect (worked out by hand))
CASES = {
    "plain": ((0, 0, 600, 800), None, 0, (600, 800), (100, 540, 300, 600)),
    "cropbox": ((0, 0, 612, 792), (50, 100, 450, 700), 0, (400, 600), (50, 440, 250, 500)),
    "rotate90": ((0, 0, 600, 800), None, 90, (800, 600), (200, 100, 260, 300)),
    "rotate90+cropbox": ((0, 0, 612, 792), (50, 100, 450, 700), 90, (600, 400), (100, 50, 160, 250)),
    "rotate180+cropbox": ((0, 0, 612, 792), (50, 100, 450, 700), 180, (400, 600), (150, 100, 350, 160)),
    "rotate270+cropbox": ((0, 0, 612, 792), (50, 100, 450, 700), 270, (600, 400), (440, 150, 500, 350)),
    "rotate90+offset mediabox": ((10, 20, 612, 792), (50, 100, 450, 700), 90, (600, 400), (100, 50, 160, 250)),
}


class Geometry(Base):
    def test_page_rect_to_user_space(self):
        for name, (media, crop, rotate, size, where) in CASES.items():
            with self.subTest(name):
                pdf = make_pdf(media, crop, rotate, rects=[RECT])
                (w, h, rot, m), = pdfdocs.pdf_info(pdf)["pages"]
                self.assertEqual((w, h, rot), (*size, rotate))
                # The matrix takes the rectangle's place in page.rect back to where the stream drew it.
                self.assertEqual([round(v, 3) for v in map_rect(m, where)], list(RECT))
                # pdf.js: from user space to its viewport and back is the identity on page.rect, and the
                # rectangle lands where it is in page.rect.
                t, vw, vh = pdfjs_viewport(crop or media, rotate)
                self.assertEqual((vw, vh), size)
                for p in ((0, 0), (w, h), (w, 0), where[:2]):
                    self.assertEqual([round(v, 3) for v in apply(t, *apply(m, *p))], list(p))
                self.assertEqual([round(v, 3) for v in map_rect(t, RECT)], list(where))

                # The renderer agrees: at 72 dpi a pixel is a point of page.rect ...
                doc_id = self.add_doc(pdf, paper_id=name)
                png, _ = pdfdocs.render_png(self.conn, doc_id, 1, dpi=72)
                self.assertEqual(png_size(png), size)
                self.assertEqual(ink(png), list(where))
                # ... and a clip is cut in that frame: 10 pt of white around the rectangle at 144 dpi.
                png, _ = pdfdocs.render_png(self.conn, doc_id, 1, bbox=where, dpi=144, pad=10)
                rw, rh = where[2] - where[0], where[3] - where[1]
                pw, ph = png_size(png)
                self.assertLessEqual(abs(pw - (rw + 20) * 2), 1)
                self.assertLessEqual(abs(ph - (rh + 20) * 2), 1)
                for got, want in zip(ink(png), (20, 20, 20 + 2 * rw, 20 + 2 * rh)):
                    self.assertLessEqual(abs(got - want), 1)

    def test_info(self):
        pdf = make_pdf(pages=2, text="doi:10.1000/xyz123", title="A made-up paper")
        info = pdfdocs.pdf_info(pdf)
        self.assertEqual(info["page_count"], 2)
        self.assertEqual(info["metadata"]["title"], "A made-up paper")
        self.assertIn("10.1000/xyz123", info["first_page_text"])
        self.assertEqual(info["pages"][0], [600.0, 800.0, 0, [1.0, 0.0, 0.0, -1.0, 0.0, 800.0]])
        self.assertNotIn("-0.0", json.dumps(info["pages"]))
        # What the documents table stores survives JSON.
        self.assertEqual(json.loads(db.dumps(info))["pages"], info["pages"])
        with self.assertRaises(ValueError):
            pdfdocs.pdf_info(b"not a pdf")

    def test_malformed_metadata(self):
        # MuPDF decodes these /Info strings with lone surrogates, which UTF-8 (SQLite) cannot encode: a
        # UTF-16 pair cut short, a low surrogate alone, an invalid byte after a UTF-8 mark.
        doc = pymupdf.open(stream=make_pdf(title="t"), filetype="pdf")
        info_xref = int(doc.xref_get_key(-1, "Info")[1].split()[0])
        for key, value in (("Author", "<FEFF0041D835>"), ("Producer", "<FEFF00410042DC00>"),
                           ("Keywords", "<EFBBBF436166E9>"), ("Subject", "(Caf\\351)")):
            doc.xref_set_key(info_xref, key, value)
        info = pdfdocs.pdf_info(doc.tobytes())
        meta = info["metadata"]
        self.assertEqual((meta["author"][0], meta["producer"][:2], meta["keywords"][:3], meta["subject"]),
                         ("A", "AB", "Caf", "Café"))
        for value in meta.values():
            if isinstance(value, str):
                value.encode("utf-8")  # no lone surrogate left
        self.add_doc(doc.tobytes())  # stored as the importer stores it (pdf_meta)
        self.assertEqual(json.loads(self.conn.execute("SELECT pdf_meta FROM documents").fetchone()[0]), meta)


class Blobs(Base):
    DATA = bytes(i % 251 for i in range(10_000))

    def blob(self) -> int:
        sha = pdfdocs.store_pdf(self.conn, self.DATA)
        return self.conn.execute("SELECT rowid FROM blobs WHERE sha256 = ?", (sha,)).fetchone()[0]

    def read(self, *args, **kw) -> list[bytes]:
        return list(pdfdocs.read_range(self.conn, self.blob(), *args, **kw))

    def test_store_dedupes(self):
        sha = pdfdocs.store_pdf(self.conn, b"%PDF-1 one")
        self.assertEqual(sha, db.sha_bytes(b"%PDF-1 one"))
        self.assertEqual(pdfdocs.store_pdf(self.conn, b"%PDF-1 one"), sha)
        pdfdocs.store_pdf(self.conn, b"%PDF-1 two")
        rows = self.conn.execute("SELECT sha256, size FROM blobs ORDER BY rowid").fetchall()
        self.assertEqual([tuple(r) for r in rows], [(sha, 10), (db.sha_bytes(b"%PDF-1 two"), 10)])

    def test_doc_row(self):
        pdf = make_pdf()
        doc_id = self.add_doc(pdf)
        row = pdfdocs.doc_row(self.conn, doc_id)
        self.assertEqual((row["doc_id"], row["paper_id"], row["doc"], row["page_count"], row["size"]),
                         (doc_id, "p1", "main", 1, len(pdf)))
        self.assertEqual(pdfdocs.doc_row(self.conn, str(doc_id))["doc_id"], doc_id)
        self.assertEqual(json.loads(row["pages"])[0][:3], [600.0, 800.0, 0])
        self.assertEqual(b"".join(pdfdocs.read_range(self.conn, row["blob_rowid"], 0, row["size"] - 1)), pdf)
        for missing in (doc_id + 1, "x", None, 10 ** 20, "9" * 20, "9" * 5000):  # not an OverflowError
            with self.assertRaises(pdfdocs.NotFound):
                pdfdocs.doc_row(self.conn, missing)
        self.assertTrue(issubclass(pdfdocs.NotFound, LookupError))

    def test_ranges(self):
        d = self.DATA
        self.assertEqual(self.read(0, 0), [d[:1]])
        self.assertEqual(self.read(9_999, 9_999), [d[-1:]])
        pieces = self.read(950, 3_050, chunk=1_000)  # spans two chunk boundaries
        self.assertEqual([len(p) for p in pieces], [1_000, 1_000, 101])
        self.assertEqual(b"".join(pieces), d[950:3_051])
        self.assertEqual(b"".join(self.read(9_990, 50_000, chunk=4)), d[9_990:])  # end clamped
        self.assertEqual(self.read(0, 10 ** 9), [d])
        self.assertEqual(self.read(10_000, 10_005), [])
        self.assertEqual(self.read(5, 4), [])
        with self.assertRaises(ValueError):
            pdfdocs.read_range(self.conn, self.blob(), -1, 5)

    def test_range_closed_early(self):
        gen = pdfdocs.read_range(self.conn, self.blob(), 0, 9_999, chunk=100)
        self.assertEqual(next(gen), self.DATA[:100])
        gen.close()
        pdfdocs.store_pdf(self.conn, b"after")  # the blob's read no longer holds the connection
        self.assertEqual(self.conn.execute("SELECT count(*) FROM blobs").fetchone()[0], 2)


class Render(Base):
    def setUp(self):
        super().setUp()
        self.doc_id = self.add_doc(make_pdf(rects=[RECT]))  # plain 600 x 800

    def render(self, *args, **kw):
        return pdfdocs.render_png(self.conn, self.doc_id, *args, **kw)

    def test_whole_page(self):
        self.assertEqual(png_size(self.render(1, dpi=72)[0]), (600, 800))
        w, h = png_size(self.render(1)[0])  # 150 dpi
        self.assertLessEqual(abs(w - 1250), 1)
        self.assertLessEqual(abs(h - 1667), 1)

    def test_clip_and_pad(self):
        self.assertEqual(png_size(self.render(1, [100, 100, 200, 200], dpi=72)[0]), (100, 100))
        self.assertEqual(png_size(self.render(1, [100, 100, 200, 200], dpi=72, pad=10)[0]), (120, 120))
        self.assertEqual(png_size(self.render(1, [0, 0, 50, 50], dpi=72, pad=10)[0]), (60, 60))
        self.assertEqual(png_size(self.render(1, [550, 750, 700, 900], dpi=72)[0]), (50, 50))  # cut to the page

    def test_dpi_clamped(self):
        self.assertEqual(png_size(self.render(1, [0, 0, 72, 72], dpi=1)[0]), (36, 36))
        self.assertEqual(png_size(self.render(1, [0, 0, 72, 72], dpi=5000)[0]), (600, 600))
        self.assertEqual(self.render(1, [0, 0, 72, 72], dpi=1)[1], self.render(1, [0, 0, 72, 72], dpi=36)[1])
        self.assertEqual(png_size(self.render(1, [0, 0, 72, 72], dpi="144")[0]), (144, 144))

    def test_megapixel_cap(self):
        w, h = png_size(self.render(1, dpi=600)[0])  # 5000 x 6667 asked for
        self.assertLessEqual(w * h, pdfdocs.MAX_PIXELS)
        self.assertGreater(w * h, 0.99 * pdfdocs.MAX_PIXELS)
        self.assertAlmostEqual(w / h, 0.75, places=3)
        self.assertEqual(png_size(self.render(1, dpi=300)[0]), (2500, 3334))  # under the cap: as asked

    def test_bad_requests(self):
        for args, kw in [((0,), {}), ((2,), {}), (("x",), {}), ((1.5,), {}),
                         ((1, [700, 0, 800, 100]), {}),          # beside the page
                         ((1, [10, 10, 10, 20]), {}),            # no area
                         ((1, [20, 10, 10, 20]), {}),            # inverted
                         ((1, [1, 2, 3]), {}), ((1, "1,2,3,4"), {}), ((1, [0, 0, "a", 1]), {}),
                         ((1,), {"dpi": float("nan")}), ((1,), {"dpi": "fast"}),
                         ((1, [0, 0, 10, 10]), {"pad": -1})]:
            with self.subTest(args=args, kw=kw), self.assertRaises(ValueError):
                self.render(*args, **kw)
        with self.assertRaises(pdfdocs.NotFound):
            pdfdocs.render_png(self.conn, self.doc_id + 1, 1)

    def test_etag(self):
        png, etag = self.render(1, [100, 200, 300, 260], dpi=100)
        self.assertEqual(self.render(1, [100, 200, 300, 260], dpi=100), (png, etag))
        self.assertEqual(self.render(1, [100.01, 199.98, 300, 260.04], dpi=100)[1], etag)  # rounded to 0.1
        others = {self.render(1, [100, 200, 300, 261], dpi=100)[1], self.render(1, [100, 200, 300, 260], dpi=101)[1],
                  self.render(1, [100, 200, 300, 260], dpi=100, pad=2)[1], self.render(1, dpi=100)[1]}
        self.assertEqual(len(others), 4)
        self.assertNotIn(etag, others)
        other_doc = self.add_doc(make_pdf(rects=[RECT], title="another"), paper_id="p2")
        self.assertNotEqual(pdfdocs.render_png(self.conn, other_doc, 1, [100, 200, 300, 260], dpi=100)[1], etag)
        # Known without rendering (a revalidation needs no picture), for the same arguments.
        pdfdocs.clear_caches()
        with mock.patch.object(pymupdf.DisplayList, "get_pixmap", side_effect=AssertionError("rendered")):
            self.assertEqual(pdfdocs.render_etag(self.conn, self.doc_id, 1, [100.01, 199.98, 300, 260.04], dpi=100),
                             etag)
            self.assertEqual(pdfdocs.render_etag(self.conn, self.doc_id, "1", ["100", "200", "300", "260"], dpi="100"),
                             etag)  # as a query string gives them
            with self.assertRaises(ValueError):
                pdfdocs.render_etag(self.conn, self.doc_id, 2)
        self.assertEqual(self.render(1, [100, 200, 300, 260], dpi=100)[1], etag)

    def test_document_lru(self):
        ids = [self.doc_id] + [self.add_doc(make_pdf(rects=[(10 * i, 10, 10 * i + 10, 20)]), paper_id=f"p{i}")
                               for i in range(2, 7)]
        shas = [pdfdocs.doc_row(self.conn, i)["sha256"] for i in ids]
        for i in ids:
            self.render(1, dpi=36) if i == self.doc_id else pdfdocs.render_png(self.conn, i, 1, dpi=36)
        self.assertEqual(list(pdfdocs._docs), shas[-pdfdocs.OPEN_DOCS:])
        # The first document was closed; rendering it again opens it again.
        png, _ = self.render(1, [90, 530, 310, 610], dpi=72)
        self.assertEqual(ink(png), [10, 10, 210, 70])
        self.assertEqual(list(pdfdocs._docs)[-1], shas[0])
        self.assertEqual(len(pdfdocs._docs), pdfdocs.OPEN_DOCS)

    def test_display_lists(self):
        """A page is interpreted once: clips of it come from its cached display list, which goes when
        its document is closed, and they are the very bytes a render of the page itself gives."""
        sha = pdfdocs.doc_row(self.conn, self.doc_id)["sha256"]
        two = self.add_doc(make_pdf(pages=2, rects=[RECT]), paper_id="p2")
        sha2 = pdfdocs.doc_row(self.conn, two)["sha256"]
        for x in range(0, 400, 100):
            self.render(1, [x, 500, x + 100, 620], dpi=90)
        self.assertEqual(list(pdfdocs._lists), [(sha, 1)])
        with mock.patch.object(pdfdocs, "OPEN_PAGES", 2):
            for dpi, page in enumerate((1, 2, 1), 50):  # each a new request: not answered from the PNG cache
                pdfdocs.render_png(self.conn, two, page, [90, 530, 310, 610], dpi=dpi)
            self.assertEqual(list(pdfdocs._lists), [(sha2, 2), (sha2, 1)])
        pdfdocs.clear_caches()
        pdfdocs.render_png(self.conn, two, 2, [0, 0, 50, 50], dpi=72)
        with mock.patch.object(pdfdocs, "OPEN_DOCS", 1):
            self.render(1, [0, 0, 50, 50], dpi=72)  # opens the first document, closing the other
            self.assertEqual(list(pdfdocs._docs), [sha])
            self.assertEqual(list(pdfdocs._lists), [(sha, 1)])

        for name, (media, crop, rotate, size, where) in CASES.items():
            with self.subTest(name):
                pdf = make_pdf(media, crop, rotate, rects=[RECT])
                doc_id = self.add_doc(pdf, paper_id=name)
                png, _ = pdfdocs.render_png(self.conn, doc_id, 1, bbox=where, dpi=144, pad=10)
                with pymupdf.open(stream=pdf, filetype="pdf") as doc:
                    page = doc[0]
                    clip = pymupdf.Rect(where[0] - 10, where[1] - 10, where[2] + 10, where[3] + 10) & page.rect
                    direct = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=clip, alpha=False).tobytes("png")
                self.assertEqual(png, direct)

    def test_png_budget(self):
        first, _ = self.render(1, [0, 0, 100, 100], dpi=72)
        with mock.patch.object(pdfdocs, "PNG_CACHE_BYTES", int(len(first) * 2.5)):
            pdfdocs.clear_caches()
            for x in range(0, 500, 100):
                self.render(1, [x, 0, x + 100, 100], dpi=72)
            self.assertEqual(len(pdfdocs._pngs), 2)
            self.assertEqual(pdfdocs._png_bytes, sum(map(len, pdfdocs._pngs.values())))
            self.assertLessEqual(pdfdocs._png_bytes, pdfdocs.PNG_CACHE_BYTES)
            self.assertEqual(self.render(1, [0, 0, 100, 100], dpi=72)[0], first)  # evicted, rendered again
        with mock.patch.object(pdfdocs, "PNG_CACHE_BYTES", 10):
            pdfdocs.clear_caches()
            self.render(1, dpi=72)  # larger than the whole budget: not kept
            self.assertEqual((len(pdfdocs._pngs), pdfdocs._png_bytes), (0, 0))

    def test_threads(self):
        """Renders from several threads at once, each with its own connection, give what one thread
        gives. Nothing is cached and one document is open at a time, so every request renders and the
        documents are closed and opened again under the others' feet."""
        si = self.add_doc(make_pdf(pages=2, rects=[(50, 50, 150, 90)]), doc="si")
        jobs = [(d, p, box, dpi) for d, p in ((self.doc_id, 1), (si, 1), (si, 2))
                for box in (None, (90, 530, 310, 610), (40, 700, 160, 760)) for dpi in (40, 90)]
        want = {job: pdfdocs.render_png(self.conn, *job[:2], bbox=job[2], dpi=job[3])[0] for job in jobs}
        got, errors = [], []

        def worker(seed):
            conn = db.connect(self.path)
            try:
                order = jobs[:]
                random.Random(seed).shuffle(order)
                for job in order:
                    got.append((job, pdfdocs.render_png(conn, *job[:2], bbox=job[2], dpi=job[3])[0]))
            except Exception as e:  # reported below
                errors.append(e)
            finally:
                conn.close()

        with mock.patch.object(pdfdocs, "PNG_CACHE_BYTES", 0), mock.patch.object(pdfdocs, "OPEN_DOCS", 1):
            pdfdocs.clear_caches()
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(got), 6 * len(jobs))
        for job, png in got:
            self.assertEqual(png, want[job], job)


if __name__ == "__main__":
    unittest.main()
