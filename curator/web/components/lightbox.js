import { html, useEffect, useState } from '../lib/preact.js';
import { docById, renderUrl } from '../lib/api.js';
import { emit } from '../lib/bus.js';
import { DOC, name } from '../lib/format.js';
import { PageFigure, drawable, pageSize } from './pagefigure.js';

// One enlarged picture at a time, opened from anywhere with show(item); the shell mounts <Lightbox />
// once. The picture is rendered by the server at a high resolution from (document, page, box).
//
// item: {docId, page, bbox, caption?, doc?, paperId?, size?}; `size` is the page's [w, h] (else taken
// from what the api knows about the document).
let listener = null;
let current = null;

export const show = (item) => listener && listener(item);
// Whether a picture is open (keyboard shortcuts of the page stay quiet meanwhile).
export const lightboxOpen = () => current != null;

const PAD = 6;
// ~1400 px across, as sharp as the server allows for small boxes.
const bigDpi = (bbox) => Math.round(Math.max(150, Math.min(600, (1400 * 72) / (bbox[2] - bbox[0] + 2 * PAD))));

export function Lightbox() {
  const [item, setItem] = useState(null);
  const [onPage, setOnPage] = useState(false);
  current = item;
  useEffect(() => {
    listener = (next) => { setItem(next || null); setOnPage(false); };
    return () => { listener = null; current = null; };
  }, []);
  useEffect(() => {
    if (!item) return undefined;
    // Capture phase, so Esc closes the picture and nothing underneath (a dialog, the draw mode) too.
    const onKey = (e) => {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      e.stopImmediatePropagation();
      setItem(null);
    };
    addEventListener('keydown', onKey, true);
    return () => removeEventListener('keydown', onKey, true);
  }, [item]);
  if (!item) return null;

  const { docId, page, bbox, caption } = item;
  const known = docById(docId);
  const doc = item.doc || known?.doc || null;
  const size = pageSize(docId, page, item.size);
  const ok = drawable(bbox, size);
  const close = () => setItem(null);
  const openPdf = () => {
    emit('pdf:open', { docId, doc, paperId: item.paperId ?? known?.paper_id ?? null, page, bbox, label: caption });
    close();
  };
  return html`
    <div class="lightbox" onClick=${close}>
      <div class="lightbox-panel" role="dialog" aria-modal="true" aria-label=${caption || '放大的图'}
           onClick=${(e) => e.stopPropagation()}>
        <div class="lightbox-bar">
          <span class="lightbox-caption">${caption}</span>
          <span class="muted">${doc ? `${name(DOC, doc)} ` : ''}第 ${page} 页</span>
          ${ok ? html`
            <button type="button" class="btn" onClick=${() => setOnPage(!onPage)}>${onPage ? '只看截图' : '在页面中的位置'}</button>` : null}
          <button type="button" class="btn" onClick=${openPdf}>在 PDF 中打开</button>
          <button type="button" class="btn quiet" onClick=${close} title="关闭（Esc）">关闭</button>
        </div>
        <div class="lightbox-body">
          ${!ok ? html`<div class="empty">这个框不在页面上，无法截图</div>`
            : onPage ? html`
              <${PageFigure} docId=${docId} page=${page} size=${size} maxHeight=${2000}
                             boxes=${[{ id: 'x', kind: 'focus', bbox }]} />`
              : html`<img src=${renderUrl(docId, page, bbox, { dpi: bigDpi(bbox), pad: PAD })} alt=${caption || ''} />`}
        </div>
      </div>
    </div>`;
}
