// The embedded PDF viewer (FRONTEND.md "PDF pane"): pdf.js's PDFViewer in a scroll container that
// Preact never renders into, with a Preact toolbar around it. One viewer shows one document at a
// time; switching documents keeps the place each was left at. Boxes arrive in PyMuPDF page.rect
// points; they go through the page's stored to_pdf matrix and the pdf.js viewport, and are placed
// as percentages of the page view, so zooming never moves them. pdf.js empties a page's div when
// it zooms or drops the page from its cache, so every page is painted again when it renders.
import { html, useEffect, useRef, useState } from '../lib/preact.js';
import { useLoad, useOn } from '../lib/hooks.js';
import { emit } from '../lib/bus.js';
import { docById, listPapers, paperDocs, pdfUrl } from '../lib/api.js';
import { fromUser, invertMatrix, isBox, normBox, round1, toUser } from '../lib/geom.js';
import { DOC, cx, name } from '../lib/format.js';
import { dialogOpen } from './common.js';

const VENDOR = new URL('../vendor/pdfjs/', import.meta.url);
const vendor = (path) => new URL(path, VENDOR).href;

const PULSE_MS = 2700;          // the target's pulse (3 × 900 ms in pdf.css), then it stays outlined
const FIT = new Set(['page-width', 'page-fit', 'auto']);
const SCALES = [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];
const MAX_OPEN_DOCS = 4;        // loaded documents kept for switching back without reloading

// ------------------------------------------------------------------ pdf.js, loaded on first use

let libLoading = null;

function loadLib() {
  if (!libLoading) {
    libLoading = (async () => {
      await import('./pdfjs-compat.js');
      const lib = await import('../vendor/pdfjs/build/pdf.min.mjs');
      globalThis.pdfjsLib = lib;   // pdf_viewer.mjs reads the library from here
      lib.GlobalWorkerOptions.workerSrc = new URL('./pdfjs-worker.js', import.meta.url).href;
      const viewer = await import('../vendor/pdfjs/web/pdf_viewer.mjs');
      return { lib, viewer };
    })();
    libLoading.catch(() => { libLoading = null; });
  }
  return libLoading;
}

// One loading task per document, kept (most recently used last) so switching back is instant.
// Range requests only: nothing is fetched before a page needs it, so a 30 MB SI opens at once.
const documents = new Map();   // docId → {task, promise}

function openDocument(lib, docId) {
  const key = String(docId);
  let entry = documents.get(key);
  if (entry) {
    documents.delete(key);
    documents.set(key, entry);
    return entry.promise;
  }
  const task = lib.getDocument({
    url: new URL(pdfUrl(docId), location.href).href,
    cMapUrl: vendor('cmaps/'), cMapPacked: true, standardFontDataUrl: vendor('standard_fonts/'),
    wasmUrl: vendor('wasm/'), iccUrl: vendor('iccs/'),
    disableAutoFetch: true, disableStream: true, rangeChunkSize: 262144,
    verbosity: lib.VerbosityLevel.ERRORS,
  });
  entry = { task, promise: task.promise };
  documents.set(key, entry);
  task.promise.catch(() => { if (documents.get(key) === entry) documents.delete(key); });
  return entry.promise;
}

function trimDocuments(keep) {
  for (const [key, entry] of documents) {
    if (documents.size <= MAX_OPEN_DOCS) return;
    if (key === String(keep)) continue;
    documents.delete(key);
    entry.task.destroy();
  }
}

// What the API knows about a document (paper, name, filename, pages once a reaction of its paper
// has been loaded). The paper list fills the cache when nothing has listed it yet.
async function docInfo(docId) {
  if (!docById(docId)) {
    try { await listPapers(); } catch { /* shown without a name */ }
  }
  return docById(docId);
}

const DOC_ORDER = { main: 0, si: 1 };
const tabsOf = (docs) => Object.entries(docs || {}).map(([doc, d]) => ({ ...d, doc }))
  .sort((a, b) => (DOC_ORDER[a.doc] ?? 9) - (DOC_ORDER[b.doc] ?? 9) || String(a.doc).localeCompare(b.doc));

class Superseded extends Error {}

// Why a document did not open, in words (pdf.js says it in English, with the HTTP status if any).
function failure(e) {
  if (e?.status) return `服务器返回 ${e.status}${e.status === 404 ? '（没有这份文档）' : ''}`;
  if (e?.name === 'InvalidPDFException') return '文件不是有效的 PDF';
  if (e?.name === 'PasswordException') return 'PDF 有密码保护';
  return `${e?.message || e}`;
}

const clamp01 = (v) => Math.min(1, Math.max(0, v));

// A PDF user-space rect in viewport pixels, normalised (pdf.js 6 has no convertToViewportRectangle;
// two opposite corners are enough, pages turn by multiples of 90°).
const viewportRect = (vp, [x0, y0, x1, y1]) =>
  normBox([...vp.convertToViewportPoint(x0, y0), ...vp.convertToViewportPoint(x1, y1)]);
const pct = (v) => `${(v * 100).toFixed(4)}%`;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

// ------------------------------------------------------------------ the viewer, outside Preact

class PdfController {
  constructor(host, setState) {
    this.setState = setState;
    this.open = false;
    this.viewer = null;
    this.shown = null;          // {docId, paperId, doc, filename, pdf}
    this.pending = null;        // a request waiting for the pane to be visible
    this.active = null;         // the request being carried out
    this.failed = null;         // the last request that failed (重试)
    this.seq = 0;               // the newest request; older ones stop at their next await
    this.target = null;         // {docId, page, bbox, label, since}
    this.boxes = { docId: null, list: [] };
    this.draw = null;           // the draw:start request being served
    this.band = null;           // the rectangle being dragged, as fractions of its page
    this.locations = new Map(); // docId → where that document was left {pageNumber, left, top, scaleValue}
    this.scaleValue = 'page-width';
    this.wheel = 0;

    const container = this.container = el('div', 'pdfp-scroll');
    container.tabIndex = 0;
    container.setAttribute('aria-label', 'PDF 页面');
    container.append(el('div', 'pdfViewer'));
    host.append(container);

    this.ac = new AbortController();
    const signal = { signal: this.ac.signal };
    container.addEventListener('pointerdown', (e) => this.onPointerDown(e), signal);
    container.addEventListener('pointermove', (e) => this.onPointerMove(e), signal);
    container.addEventListener('pointerup', (e) => this.onPointerUp(e), signal);
    container.addEventListener('pointercancel', () => this.dropBand(), signal);
    container.addEventListener('wheel', (e) => this.onWheel(e), { ...signal, passive: false });
    // Links inside the PDF go through pdf.js; the location hash is the app's router and stays put.
    container.addEventListener('click', (e) => {
      if (e.target.closest?.('a[href^="#"]')) e.preventDefault();
    }, signal);
    addEventListener('keydown', (e) => this.onKey(e), signal);
    this.resizer = new ResizeObserver(() => this.onResize());
    this.resizer.observe(container);
  }

  destroy() {
    this.destroyed = true;
    this.ac.abort();
    this.resizer.disconnect();
    clearTimeout(this.resizeTimer);
    this.viewer?.setDocument(null);
    this.container.remove();
  }

  visible() {
    return this.open && this.container.isConnected && this.container.clientWidth > 0;
  }

  // -------------------------------------------------------------- pdf.js setup

  async ensureViewer() {
    if (this.viewer) return this.viewer;
    const { lib, viewer: v } = await loadLib();
    if (this.destroyed) throw new Superseded();
    if (this.viewer) return this.viewer;
    const eventBus = new v.EventBus();
    const linkService = new v.PDFLinkService({ eventBus, externalLinkTarget: v.LinkTarget.BLANK,
      externalLinkRel: 'noopener noreferrer' });
    const viewer = new v.PDFViewer({
      container: this.container, eventBus, linkService, abortSignal: this.ac.signal,
      annotationMode: lib.AnnotationMode.ENABLE,               // links work; no form fields
      annotationEditorMode: lib.AnnotationEditorType.DISABLE,  // no editing tools or their shortcuts
    });
    linkService.setViewer(viewer);
    Object.assign(this, { lib, eventBus, linkService, viewer });
    eventBus.on('pagechanging', ({ pageNumber }) => this.setState({ page: pageNumber }));
    eventBus.on('scalechanging', () => this.reportScale());
    eventBus.on('pagerender', ({ pageNumber }) => this.paint(pageNumber));
    eventBus.on('pagerendered', ({ pageNumber }) => this.paint(pageNumber));
    eventBus.on('updateviewarea', ({ location }) => this.remember(location));
    return viewer;
  }

  reportScale() {
    const v = this.viewer;
    this.scaleValue = v.currentScaleValue || this.scaleValue;
    this.setState({ scale: v.currentScale, scaleValue: v.currentScaleValue });
  }

  remember(location) {
    if (!location || !this.shown || this.switching || !this.visible()) return;
    this.locations.set(this.shown.docId, { pageNumber: location.pageNumber, left: location.left,
      top: location.top, scaleValue: this.viewer.currentScaleValue });
  }

  // -------------------------------------------------------------- requests (pdf:open, tabs, follow)

  // kind 'open' (pdf:open: page, bbox → target, boxes), 'tab' (back where the document was left),
  // 'follow' (the current reaction's document, scrolled to its first box, nothing highlighted).
  request(req) {
    if (!req || req.docId == null) return;
    this.pending = { ...req, docId: String(req.docId), seq: ++this.seq };
    this.flush();
  }

  flush() {
    const req = this.pending;
    if (!req || !this.visible()) return;
    this.pending = null;
    this.active = req;
    this.failed = null;
    this.apply(req).catch((e) => {
      if (e instanceof Superseded || req.seq !== this.seq) return;
      this.failed = req;
      this.setState({ loading: false, error: failure(e) });
    }).finally(() => {
      if (this.active === req) this.active = null;
    });
  }

  retry() {
    if (this.failed) this.request(this.failed);
  }

  async apply(req) {
    const check = () => {
      if (req.seq !== this.seq || this.destroyed) throw new Superseded();
      if (!this.visible()) {
        // Closed meanwhile: pdf.js cannot scroll or fit a hidden container. Go on when it reopens.
        this.pending = req;
        throw new Superseded();
      }
    };
    this.setState({ error: null });
    const switched = await this.showDoc(req.docId, check);
    check();
    if (!this.viewer.currentScaleValue) this.viewer.currentScaleValue = this.scaleValue || 'page-width';
    if (req.kind === 'open') {
      if (Array.isArray(req.boxes)) this.boxes = { docId: req.docId, list: req.boxes };
      const page = Number(req.page) || 1;
      await this.goTo(page, req.bbox, check);
      this.target = isBox(req.bbox)
        ? { docId: req.docId, page, bbox: req.bbox.map(Number), label: req.label || null, since: performance.now() }
        : null;
    } else if (req.kind === 'follow') {
      await this.goTo(Number(req.page) || 1, req.bbox, check);
    } else if (switched) {
      this.restore();
    }
    this.setState({ loading: false });
    this.paintAll();
    this.reportMarks();
    this.syncDrawDoc();
  }

  // Shows document docId (loading it when needed); false when it was shown already.
  async showDoc(docId, check) {
    if (this.shown?.docId === docId) return false;
    this.setState({ loading: true, error: null });
    const viewer = await this.ensureViewer();
    check();
    const [pdf, info] = await Promise.all([openDocument(this.lib, docId), docInfo(docId)]);
    check();
    this.switching = true;   // the old document's place is kept; nothing is noted while switching
    try {
      viewer.setDocument(pdf);
      this.linkService.setDocument(pdf);
      const ready = Promise.race([
        new Promise((resolve) => this.eventBus.on('pagesinit', resolve, { once: true })),
        viewer.pagesPromise,
      ]);
      this.shown = { docId, pdf, paperId: info?.paper_id ?? null, doc: info?.doc ?? null,
        filename: info?.filename || `文档 ${docId}` };
      this.setState({ docId, paperId: this.shown.paperId, doc: this.shown.doc, filename: this.shown.filename,
        pages: pdf.numPages, page: 1 });
      this.loadTabs();
      await ready;
      check();
      viewer.currentScaleValue = this.locations.get(docId)?.scaleValue || this.scaleValue || 'page-width';
    } finally {
      this.switching = false;
    }
    trimDocuments(docId);
    return true;
  }

  loadTabs() {
    const { paperId, docId } = this.shown;
    if (paperId == null) {
      this.setState({ tabs: [{ doc_id: docId, doc: this.shown.doc, filename: this.shown.filename }] });
      return;
    }
    paperDocs(paperId).then((docs) => {
      if (this.shown?.paperId === paperId) this.setState({ tabs: tabsOf(docs) });
    }, () => {});
  }

  restore() {
    const at = this.locations.get(this.shown?.docId);
    if (!at || !this.viewer) return;
    this.viewer.scrollPageIntoView({ pageNumber: at.pageNumber,
      destArray: [null, { name: 'XYZ' }, at.left, at.top, null], allowNegativeOffset: true });
  }

  // Scrolls to page n, or to bbox on it with some room above and to the left.
  async goTo(n, bbox, check = () => {}) {
    const viewer = this.viewer;
    const page = Math.min(Math.max(1, Math.round(n) || 1), viewer.pagesCount);
    const pv = viewer.getPageView(page - 1);
    if (!pv) return;
    if (!pv.pdfPage) {
      // Pages load lazily; until then a page view has the first page's size.
      const pdfPage = await this.shown.pdf.getPage(page);
      check();
      if (!pv.pdfPage) pv.setPdfPage(pdfPage);
    }
    if (!isBox(bbox)) {
      viewer.scrollPageIntoView({ pageNumber: page });
      return;
    }
    const vp = pv.viewport;
    const r = viewportRect(vp, toUser(this.matrix(page, pv.pdfPage), bbox.map(Number)));
    const above = Math.min(140, this.container.clientHeight * 0.3);
    // The destination is the box's top-left corner moved up and left (in viewport pixels), back in
    // PDF user space: right for rotated pages too.
    const [x, y] = vp.convertToPdfPoint(r[0] - 24, r[1] - above);
    viewer.scrollPageIntoView({ pageNumber: page, destArray: [null, { name: 'XYZ' }, x, y, null] });
  }

  revealTarget() {
    const t = this.target;
    if (!t || t.docId !== this.shown?.docId) return;
    this.goTo(t.page, t.bbox).then(() => {
      t.since = performance.now();
      this.paint(t.page);
    }, () => {});
  }

  // -------------------------------------------------------------- the pane opening and closing

  setOpen(open) {
    const was = this.open;
    this.open = open;
    if (!open || was) return;
    requestAnimationFrame(() => {
      if (!this.visible()) return;
      if (this.pending) {
        this.flush();
      } else if (this.shown && this.viewer && !this.active) {
        // The width may have changed and the scroll position may not survive display:none.
        const v = this.viewer.currentScaleValue;
        if (FIT.has(v)) this.viewer.currentScaleValue = v;
        this.restore();
        this.viewer.update();
      }
      this.follow();
      this.syncDrawDoc();
    });
  }

  onResize() {
    if (!this.visible() || !this.viewer?.pdfDocument) return;
    clearTimeout(this.resizeTimer);
    this.resizeTimer = setTimeout(() => {
      if (!this.visible() || this.switching) return;
      const v = this.viewer.currentScaleValue;
      if (FIT.has(v)) this.viewer.currentScaleValue = v;   // "fit width" keeps fitting
      this.viewer.update();
    }, 120);
  }

  // -------------------------------------------------------------- boxes

  setBoxes(payload) {
    const docId = payload?.docId != null ? String(payload.docId) : null;
    this.boxes = { docId, list: Array.isArray(payload?.boxes) ? payload.boxes : [] };
    // No reaction any more (the detail closed, or another reaction replaces it): its highlight goes too.
    if (docId == null) this.target = null;
    this.paintAll();
    this.reportMarks();
    this.follow();
  }

  // When the pane shows nothing or another paper, it moves to the current reaction's document.
  follow() {
    const { docId, list } = this.boxes;
    if (!docId || !this.visible() || this.pending || this.active) return;
    if (this.shown) {
      if (this.shown.docId === docId) return;
      const info = docById(docId);
      if (!info || String(info.paper_id) === String(this.shown.paperId)) return;
    }
    const first = list.find((b) => isBox(b?.bbox)) || list[0];
    this.request({ kind: 'follow', docId, page: first?.page ?? 1, bbox: first?.bbox ?? null });
  }

  // Which documents hold the current reaction's boxes or the target (a dot on their tab).
  reportMarks() {
    const marked = new Set();
    if (this.boxes.docId != null && this.boxes.list.length) marked.add(this.boxes.docId);
    if (this.target) marked.add(this.target.docId);
    this.setState({ marked: [...marked], hasTarget: !!this.target && this.target.docId === this.shown?.docId });
  }

  // page.rect → PDF user space for page n of the shown document: the stored to_pdf when the API
  // has it, else the same thing read from pdf.js (the inverse of its scale-1 viewport transform).
  matrix(n, pdfPage) {
    const m = docById(this.shown?.docId)?.pages?.[n - 1]?.[3];
    if (Array.isArray(m) && m.length === 6 && m.every(Number.isFinite)) return m;
    return invertMatrix(pdfPage.getViewport({ scale: 1 }).transform);
  }

  pageSize(n, pdfPage) {
    const p = docById(this.shown?.docId)?.pages?.[n - 1];
    if (p && Number.isFinite(p[0]) && Number.isFinite(p[1])) return [p[0], p[1]];
    const vp = pdfPage.getViewport({ scale: 1 });
    return [vp.width, vp.height];
  }

  itemsOn(n) {
    const docId = this.shown?.docId;
    const items = [];
    if (docId == null) return items;
    const t = this.target?.docId === docId && this.target.page === n ? this.target : null;
    if (this.boxes.docId === docId) {
      for (const b of this.boxes.list) {
        const bbox = Array.isArray(b?.bbox) ? b.bbox.map(Number) : null;
        if (Number(b.page) !== n || !isBox(bbox)) continue;
        if (t && bbox.every((v, i) => Math.abs(v - t.bbox[i]) < 0.05)) continue;   // the target says it already
        items.push({ ...b, bbox });
      }
    }
    if (t) items.push({ ...t, kind: 'target' });
    return items;
  }

  layerOf(pv, create) {
    let layer = pv.div.querySelector(':scope > .pdfp-layer');
    if (!layer && create) layer = el('div', 'pdfp-layer');
    if (layer && layer !== pv.div.lastElementChild) pv.div.append(layer);   // above the text layer
    return layer;
  }

  paint(n) {
    const pv = this.viewer?.getPageView(n - 1);
    if (!pv?.div) return;
    const items = this.itemsOn(n);
    const band = this.band?.page === n;
    if (!items.length && !band) {
      pv.div.querySelector(':scope > .pdfp-layer')?.remove();
      return;
    }
    if (!pv.pdfPage) return;
    const layer = this.layerOf(pv, true);
    const vp = pv.viewport;
    const m = this.matrix(n, pv.pdfPage);
    const nodes = items.map((it) => {
      const r = viewportRect(vp, toUser(m, it.bbox));
      const target = it.kind === 'target';
      const node = el('div', cx('pdfp-box', target ? 'target' : `faint k-${it.kind || 'participant'}`));
      Object.assign(node.style, { left: pct(r[0] / vp.width), top: pct(r[1] / vp.height),
        width: pct((r[2] - r[0]) / vp.width), height: pct((r[3] - r[1]) / vp.height) });
      const tag = it.label ? el('span', 'pdfp-tag', it.label) : null;
      if (tag) node.append(tag);
      if (target) {
        // Painted again on zoom: the pulse goes on from where it was instead of starting over. The
        // label goes with the pulse, so the outline left behind hides nothing printed above it.
        const age = performance.now() - it.since;
        if (age < PULSE_MS) {
          node.classList.add('pulse');
          node.style.animationDelay = `${-age}ms`;
        }
        if (tag) tag.style.animationDelay = `${PULSE_MS - age}ms`;
      }
      return node;
    });
    if (band && this.bandEl) nodes.push(this.bandEl);
    layer.replaceChildren(...nodes);
  }

  paintAll() {
    const v = this.viewer;
    if (!v?.pdfDocument) return;
    for (let i = 0; i < v.pagesCount; i += 1) {
      const pv = v.getPageView(i);
      if (pv?.pdfPage || pv?.div.querySelector(':scope > .pdfp-layer')) this.paint(i + 1);
    }
  }

  // -------------------------------------------------------------- drawing a box

  startDraw(req) {
    if (!req) return;
    const docId = req.docId != null ? String(req.docId) : null;
    this.draw = { ...req, docId };
    this.dropBand();
    this.reportDraw();
    this.syncDrawDoc();
  }

  endDraw() {
    if (!this.draw) return;
    this.draw = null;
    this.dropBand();
    this.reportDraw();
  }

  cancelDraw() {
    const d = this.draw;
    if (!d) return;
    this.endDraw();
    try {
      d.onCancel?.();
    } finally {
      emit('draw:end', {});
    }
  }

  reportDraw() {
    const d = this.draw;
    this.container.classList.toggle('pdfp-drawing', !!d);
    this.setState({ drawing: d ? { label: d.label || null, doc: d.doc || null, docId: d.docId } : null });
  }

  // A box is drawn on the reaction's own document: switch to it when another one is shown.
  syncDrawDoc() {
    const d = this.draw;
    if (!d || !this.visible()) return;
    if (d.docId == null && d.doc && this.shown?.paperId != null) {
      paperDocs(this.shown.paperId).then((docs) => {
        const id = docs?.[d.doc]?.doc_id;
        if (this.draw === d && id != null) {
          d.docId = String(id);
          this.reportDraw();
          this.syncDrawDoc();
        }
      }, () => {});
      return;
    }
    if (d.docId == null || this.shown?.docId === d.docId) return;
    if (this.pending?.docId === d.docId || this.active?.docId === d.docId) return;
    this.request({ kind: 'tab', docId: d.docId });
  }

  pagePoint(div, e) {
    const r = div.getBoundingClientRect();
    return [clamp01((e.clientX - r.left - div.clientLeft) / div.clientWidth),
      clamp01((e.clientY - r.top - div.clientTop) / div.clientHeight)];
  }

  onPointerDown(e) {
    const d = this.draw;
    if (!d || e.button !== 0 || !this.shown || !this.viewer) return;
    if (d.docId != null && d.docId !== this.shown.docId) return;
    const div = e.target.closest?.('.page');
    if (!div || !this.container.contains(div)) return;
    const n = Number(div.dataset.pageNumber);
    const pv = this.viewer.getPageView(n - 1);
    if (!pv?.pdfPage) return;
    e.preventDefault();
    this.container.setPointerCapture(e.pointerId);
    const [x, y] = this.pagePoint(div, e);
    this.band = { page: n, div, pointerId: e.pointerId, x0: x, y0: y, x1: x, y1: y };
    this.bandEl ||= el('div', 'pdfp-band');
    this.placeBand();
  }

  onPointerMove(e) {
    const b = this.band;
    if (!b || e.pointerId !== b.pointerId) return;
    [b.x1, b.y1] = this.pagePoint(b.div, e);
    this.placeBand();
  }

  placeBand() {
    const b = this.band;
    const pv = this.viewer.getPageView(b.page - 1);
    const layer = this.layerOf(pv, true);
    if (this.bandEl.parentNode !== layer) layer.append(this.bandEl);
    const [x0, y0, x1, y1] = normBox([b.x0, b.y0, b.x1, b.y1]);
    Object.assign(this.bandEl.style, { left: pct(x0), top: pct(y0), width: pct(x1 - x0), height: pct(y1 - y0) });
  }

  dropBand() {
    this.band = null;
    this.bandEl?.remove();
  }

  onPointerUp(e) {
    const b = this.band;
    if (!b || e.pointerId !== b.pointerId) return;
    [b.x1, b.y1] = this.pagePoint(b.div, e);
    this.dropBand();
    const d = this.draw;
    const pv = this.viewer.getPageView(b.page - 1);
    if (!d || !pv?.pdfPage) return;
    const vp = pv.viewport;
    const [fx0, fy0, fx1, fy1] = normBox([b.x0, b.y0, b.x1, b.y1]);
    if ((fx1 - fx0) * vp.width < 4 || (fy1 - fy0) * vp.height < 4) return;   // a click, not a box
    // CSS pixels → viewport → PDF user space → page.rect points (the inverse of how boxes are drawn).
    const [ax, ay] = vp.convertToPdfPoint(fx0 * vp.width, fy0 * vp.height);
    const [bx, by] = vp.convertToPdfPoint(fx1 * vp.width, fy1 * vp.height);
    const rect = fromUser(this.matrix(b.page, pv.pdfPage), [ax, ay, bx, by]);
    const [w, h] = this.pageSize(b.page, pv.pdfPage);
    const bbox = round1([Math.max(0, rect[0]), Math.max(0, rect[1]), Math.min(w, rect[2]), Math.min(h, rect[3])]);
    this.endDraw();
    try {
      d.onDone?.({ page: b.page, bbox });
    } finally {
      emit('draw:end', {});
    }
  }

  onKey(e) {
    if (e.key !== 'Escape' || !this.draw || !this.visible() || e.defaultPrevented || dialogOpen()) return;
    e.preventDefault();
    this.cancelDraw();
  }

  // -------------------------------------------------------------- toolbar actions

  goPage(n) {
    const v = this.viewer;
    if (!v?.pdfDocument) return;
    v.currentPageNumber = Math.min(Math.max(1, Math.round(n)), v.pagesCount);
  }

  step(delta) {
    const v = this.viewer;
    if (!v?.pdfDocument) return;
    if (delta > 0) v.nextPage();
    else v.previousPage();
  }

  // − / + / a percentage keep a point still: the highlighted box while it is in view, else the middle of
  // the view (pdf.js alone keeps the top-left corner, and a box on the right of the page leaves the view).
  zoom(value) {
    const v = this.viewer;
    if (!v?.pdfDocument) return;
    if (FIT.has(value)) {
      v.currentScaleValue = value;
      return;
    }
    const { origin, keep } = this.zoomOrigin();
    if (value === 'in') v.increaseScale({ origin });
    else if (value === 'out') v.decreaseScale({ origin });
    else if (Number(value) > 0 && v.currentScale > 0) v.updateScale({ scaleFactor: Number(value) / v.currentScale, origin });
    if (keep) this.keepInView(keep);
  }

  // origin in the frame pdf.js measures it in (the container's offset box); keep: the target when it is in view.
  zoomOrigin() {
    const c = this.container;
    const r = c.getBoundingClientRect();
    let [x, y] = [r.left + c.clientWidth / 2, r.top + c.clientHeight / 2];
    const t = this.target;
    const node = t && t.docId === this.shown?.docId
      ? this.viewer.getPageView(t.page - 1)?.div?.querySelector(':scope > .pdfp-layer > .pdfp-box.target') : null;
    const b = node?.getBoundingClientRect();
    const seen = !!b && b.right > r.left && b.left < r.right && b.bottom > r.top && b.top < r.bottom;
    if (seen) {
      x = (Math.max(b.left, r.left) + Math.min(b.right, r.right)) / 2;
      y = (Math.max(b.top, r.top) + Math.min(b.bottom, r.bottom)) / 2;
    }
    return { origin: [x - r.left + c.offsetLeft, y - r.top + c.offsetTop], keep: seen ? t : null };
  }

  // Scrolls the least needed for box t to be wholly in view (when it fits); pdf.js has resized the
  // pages already, but may not have painted the overlay again, so the place is computed.
  keepInView(t) {
    const pv = this.viewer.getPageView(t.page - 1);
    if (!pv?.pdfPage || !pv.div) return;
    const r = viewportRect(pv.viewport, toUser(this.matrix(t.page, pv.pdfPage), t.bbox));
    const d = pv.div.getBoundingClientRect();
    const c = this.container;
    const cr = c.getBoundingClientRect();
    const M = 16;
    const shift = (lo, hi, from, size) => (hi - lo > size - 2 * M ? 0
      : lo < from + M ? lo - from - M : hi > from + size - M ? hi - (from + size - M) : 0);
    const x0 = d.left + pv.div.clientLeft;
    const y0 = d.top + pv.div.clientTop;
    c.scrollLeft += shift(x0 + r[0], x0 + r[2], cr.left, c.clientWidth);
    c.scrollTop += shift(y0 + r[1], y0 + r[3], cr.top, c.clientHeight);
  }

  // Ctrl/⌘ + wheel (and trackpad pinch) zooms around the pointer.
  onWheel(e) {
    if (!(e.ctrlKey || e.metaKey) || !this.viewer?.pdfDocument) return;
    e.preventDefault();
    this.wheel += e.deltaY * (e.deltaMode === 1 ? 30 : e.deltaMode === 2 ? 300 : 1);
    const factor = Math.exp(-this.wheel / 650);
    if (Math.abs(factor - 1) < 0.04) return;
    this.wheel = 0;
    const r = this.container.getBoundingClientRect();
    this.viewer.updateScale({ scaleFactor: factor, origin: [e.clientX - r.left, e.clientY - r.top], drawingDelay: 250 });
  }
}

// ------------------------------------------------------------------ the toolbar

const Icon = ({ d, size = 14 }) => html`
  <svg width=${size} height=${size} viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor"
       stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;

const ICONS = {
  prev: html`<path d="M10 3.5 5.5 8l4.5 4.5" />`,
  next: html`<path d="M6 3.5 10.5 8 6 12.5" />`,
  minus: html`<path d="M3.5 8h9" />`,
  plus: html`<path d="M3.5 8h9M8 3.5v9" />`,
  fit: html`<rect x="1.75" y="3" width="12.5" height="10" rx="1.5" /><path d="M4.5 8h7M6 6.5 4.5 8 6 9.5M10 6.5 11.5 8 10 9.5" />`,
  target: html`<circle cx="8" cy="8" r="4.75" /><path d="M8 1.5v2.5M8 12v2.5M1.5 8H4M12 8h2.5" />`,
  close: html`<path d="M4 4l8 8M12 4l-8 8" />`,
  cross: html`<path d="M8 2v12M2 8h12" /><rect x="5.5" y="5.5" width="5" height="5" rx=".5" stroke-dasharray="1.5 1.5" />`,
};

const IconBtn = ({ icon, label, onClick, disabled, className }) => html`
  <button type="button" class=${cx('btn quiet small icon', className)} title=${label} aria-label=${label}
          disabled=${disabled} onClick=${onClick}><${Icon} d=${ICONS[icon]} /></button>`;

function PageInput({ page, pages, disabled, onGo }) {
  const [draft, setDraft] = useState(null);
  const go = () => {
    const n = parseInt(draft, 10);
    if (Number.isFinite(n)) onGo(n);
    setDraft(null);
  };
  return html`
    <input class="input pdfp-page" inputmode="numeric" aria-label="页码" disabled=${disabled}
           value=${draft ?? (pages ? String(page) : '')} placeholder="页"
           onFocus=${(e) => e.currentTarget.select()}
           onInput=${(e) => setDraft(e.currentTarget.value)}
           onKeyDown=${(e) => {
             if (e.key === 'Enter') { e.preventDefault(); go(); e.currentTarget.blur(); }
             if (e.key === 'Escape') { setDraft(null); e.currentTarget.blur(); }
           }}
           onBlur=${() => setDraft(null)} />`;
}

function ScaleSelect({ scale, scaleValue, disabled, onPick }) {
  const percent = `${Math.round((scale || 1) * 100)}%`;
  return html`
    <select class="select pdfp-scale" aria-label="缩放" disabled=${disabled} value="current"
            title=${scaleValue === 'page-width' ? `适合宽度（${percent}）` : '缩放'}
            onChange=${(e) => { const v = e.currentTarget.value; if (v !== 'current') onPick(v); }}>
      <option value="current" hidden>${percent}</option>
      ${SCALES.map((s) => html`<option key=${s} value=${String(s)}>${Math.round(s * 100)}%</option>`)}
      <option value="page-width">适合宽度</option>
      <option value="page-fit">适合整页</option>
    </select>`;
}

// What the pane shows when no document is open yet: a way to open one directly.
function Picker({ onPick }) {
  const papers = useLoad(listPapers, []);
  return html`
    <div class="pdfp-empty">
      <div class="pdfp-empty-title">还没有打开 PDF</div>
      <p>点反应里的页码或「在 PDF 中定位」，原文会在这里打开到那个位置。也可以直接打开一篇：</p>
      ${papers.data ? html`
        <ul class="pdfp-papers">
          ${papers.data.map((p) => html`
            <li key=${p.paper_id}>
              <span class="pdfp-paper" title=${p.title || ''}><b>${p.paper_id}</b>${p.title || '（无标题）'}</span>
              <span class="pdfp-paper-docs">
                ${(p.documents || []).map((d) => html`
                  <button key=${d.doc_id} type="button" class="btn small" title=${`${d.filename} · ${d.page_count} 页`}
                          onClick=${() => onPick(d.doc_id)}>${name(DOC, d.doc)}</button>`)}
              </span>
            </li>`)}
        </ul>` : papers.error ? html`<p class="bad-text">文献列表读取失败：${papers.error.message}</p>`
        : html`<p class="muted">正在读取文献…</p>`}
    </div>`;
}

const INITIAL = {
  docId: null, paperId: null, doc: null, filename: '', pages: 0, page: 1, scale: 1, scaleValue: null,
  loading: false, error: null, tabs: [], drawing: null, hasTarget: false, marked: [],
};

export function PdfPane({ open, onClose }) {
  const host = useRef(null);
  const ctl = useRef(null);
  const [st, setSt] = useState(INITIAL);

  useEffect(() => {
    const c = new PdfController(host.current, (patch) => setSt((s) => ({ ...s, ...patch })));
    ctl.current = c;
    return () => c.destroy();
  }, []);
  useEffect(() => { ctl.current?.setOpen(open); }, [open]);

  useOn('pdf:open', (at) => ctl.current?.request({ ...at, kind: 'open' }));
  useOn('pdf:boxes', (b) => ctl.current?.setBoxes(b));
  useOn('draw:start', (d) => ctl.current?.startDraw(d));
  useOn('draw:end', () => ctl.current?.endDraw());

  const c = () => ctl.current;
  const ready = st.docId != null && st.pages > 0;
  const tabs = st.tabs.length ? st.tabs : st.docId != null ? [{ doc_id: st.docId, doc: st.doc, filename: st.filename }] : [];
  const drawing = st.drawing;
  const drawDocOther = drawing && drawing.docId != null && drawing.docId !== st.docId;

  return html`
    <div class="pdfp" role="region" aria-label="PDF 原文">
      <div class="pdfp-head">
        ${tabs.length ? html`
          <div class="seg pdfp-docs" role="tablist" aria-label="文档">
            ${tabs.map((t) => {
              const on = String(t.doc_id) === st.docId;
              const marked = !on && st.marked.includes(String(t.doc_id));
              return html`
                <button key=${t.doc_id} type="button" role="tab" aria-selected=${on}
                        class=${cx('btn small', on && 'on')}
                        title=${`${t.filename || ''}${t.page_count ? ` · ${t.page_count} 页` : ''}${marked ? '\n本反应的框在这份文档里' : ''}`}
                        onClick=${() => c().request({ kind: 'tab', docId: t.doc_id })}>
                  ${name(DOC, t.doc) || `文档 ${t.doc_id}`}${marked ? html`<span class="pdfp-mark" aria-label="有本反应的框"></span>` : null}
                </button>`;
            })}
          </div>` : html`<b class="pdfp-title">PDF</b>`}
        <span class="pdfp-file" title=${st.filename}>${st.filename}</span>
        <${IconBtn} icon="close" label="收起 PDF 面板" onClick=${onClose} />
      </div>

      <div class="pdfp-tools">
        <div class="pdfp-group">
          <${IconBtn} icon="prev" label="上一页" disabled=${!ready || st.page <= 1} onClick=${() => c().step(-1)} />
          <${PageInput} page=${st.page} pages=${st.pages} disabled=${!ready} onGo=${(n) => c().goPage(n)} />
          <span class="pdfp-count">/ ${st.pages || '–'}</span>
          <${IconBtn} icon="next" label="下一页" disabled=${!ready || st.page >= st.pages} onClick=${() => c().step(1)} />
        </div>
        ${st.hasTarget ? html`
          <${IconBtn} icon="target" label="回到高亮的位置" className="pdfp-target" onClick=${() => c().revealTarget()} />` : null}
        <div class="pdfp-group pdfp-zoom">
          <${IconBtn} icon="minus" label="缩小" disabled=${!ready} onClick=${() => c().zoom('out')} />
          <${ScaleSelect} scale=${st.scale} scaleValue=${st.scaleValue} disabled=${!ready} onPick=${(v) => c().zoom(v)} />
          <${IconBtn} icon="plus" label="放大" disabled=${!ready} onClick=${() => c().zoom('in')} />
          <button type="button" class=${cx('btn quiet small pdfp-fit', st.scaleValue === 'page-width' && 'on')}
                  title="适合宽度" aria-label="适合宽度" aria-pressed=${st.scaleValue === 'page-width'} disabled=${!ready}
                  onClick=${() => c().zoom('page-width')}>
            <${Icon} d=${ICONS.fit} /><span>适合宽度</span>
          </button>
        </div>
      </div>

      ${drawing ? html`
        <div class="pdfp-drawbar" role="status">
          <${Icon} d=${ICONS.cross} />
          <span class="pdfp-drawbar-text">
            ${drawing.label ? html`为 <b>${drawing.label}</b> 画框：` : '画框：'}${drawDocOther
              ? `正在切换到${name(DOC, drawing.doc) || '来源文档'}…` : html`拖动画框，<kbd>Esc</kbd> 取消`}
          </span>
          <button type="button" class="btn small" onClick=${() => c().cancelDraw()}>取消</button>
        </div>` : null}

      <div class="pdfp-stage">
        <div class="pdfp-host" ref=${host}></div>
        ${st.loading ? html`<div class="pdfp-progress" aria-hidden="true"></div>` : null}
        ${st.error ? html`
          <div class="pdfp-status">
            <div class="pdfp-card bad">
              <b>PDF 打不开</b>
              <span>${st.error}</span>
              <button type="button" class="btn small" onClick=${() => c().retry()}>重试</button>
            </div>
          </div>`
        : st.docId == null && st.loading ? html`
          <div class="pdfp-status"><div class="pdfp-card"><span class="pdfp-spinner"></span>正在打开 PDF…</div></div>`
        : st.docId == null && open ? html`
          <div class="pdfp-status top"><${Picker} onPick=${(docId) => c().request({ kind: 'tab', docId })} /></div>`
        : null}
      </div>
    </div>`;
}
