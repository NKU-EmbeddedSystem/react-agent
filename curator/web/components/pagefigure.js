import { html, useEffect, useRef, useState } from '../lib/preact.js';
import { docById, renderUrl } from '../lib/api.js';
import { cx } from '../lib/format.js';
import { isBox, normBox, round1 } from '../lib/geom.js';

// A page, or the part `clip` of it, with boxes drawn on top. The drawing's units are PDF points in
// the page.rect frame, so every bbox of the data is used as it is; the picture is the server's render
// of exactly the clip, placed at the clip's origin.

// The page's [w, h] in points: from `size`, else from what the api cache knows about the document.
export function pageSize(docId, page, size) {
  if (size) return size;
  const p = docById(docId)?.pages?.[page - 1];
  return p ? [p[0], p[1]] : null;
}

// A clip ~1600 px wide (sharp at twice the usual figure width), within the server's sensible range.
export const clipDpi = (width) => Math.round(Math.max(72, Math.min(300, (1600 * 72) / Math.max(width, 1))));

// Whether `bbox` can be rendered on a page of `size` (the server refuses boxes off the page, and a
// refused picture would be a console error): four finite numbers, a positive area, on the page ± 2pt.
export function drawable(bbox, size) {
  if (!isBox(bbox)) return false;
  if (!size) return true;
  return bbox[0] >= -2 && bbox[1] >= -2 && bbox[2] <= size[0] + 2 && bbox[3] <= size[1] + 2;
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

// boxes: [{id, ids?, kind, bbox, label?, title?, labelled?, pick?}]; a box is clickable when onPick is
// given and its `pick` is not false, and onPick gets the box itself. `active` (an id) is emphasised,
// also on a box that stands for several things and lists it in `ids`;
// labels show for the active box, for boxes marked `labelled`, on hover, or for all with `labels`.
//
// The figure is as wide as its container, but no taller than `maxHeight` and no larger than
// `maxScale` px per point (a small clip would otherwise be blown up to the container's width).
//
// draw: {onDone(bbox), onCancel()} turns the figure into a drawing surface: a drag makes a box (in
// points, rounded to 0.1, kept inside the clip), Esc cancels.
export function PageFigure({ docId, page, size, clip, boxes = [], active, labels, onPick, onHover, maxHeight = 560,
  maxScale = 2.5, dpi, draw, className }) {
  const svg = useRef(null);
  const [drag, setDrag] = useState(null);   // [x0, y0, x1, y1] while a box is being drawn
  const drawing = !!draw;
  const latestDraw = useRef(draw);
  latestDraw.current = draw;

  useEffect(() => {
    if (!drawing) {
      setDrag(null);
      return undefined;
    }
    const onKey = (e) => {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      e.stopImmediatePropagation();
      setDrag(null);
      latestDraw.current?.onCancel?.();
    };
    addEventListener('keydown', onKey, true);
    return () => removeEventListener('keydown', onKey, true);
  }, [drawing]);

  const wh = pageSize(docId, page, size);
  if (!wh && !clip) return html`<div class="empty">没有第 ${page} 页的页面尺寸</div>`;
  const [w, h] = wh || [clip[2], clip[3]];
  // The clip, inside the page and rounded as the render URL rounds it, so picture and boxes line up.
  const c = clip ? round1([clamp(clip[0], 0, w), clamp(clip[1], 0, h), clamp(clip[2], 0, w), clamp(clip[3], 0, h)])
    : [0, 0, w, h];
  const [x0, y0, x1, y1] = c;
  const [vw, vh] = [Math.max(x1 - x0, 1), Math.max(y1 - y0, 1)];
  const src = renderUrl(docId, page, clip ? c : null, { dpi: dpi || clipDpi(vw), pad: 0 });
  const font = Math.max(5.5, Math.min(vw, vh * 1.6) / 70);

  const toPoint = (e) => {
    const m = svg.current?.getScreenCTM();
    if (!m) return null;
    const p = svg.current.createSVGPoint();
    p.x = e.clientX;
    p.y = e.clientY;
    const q = p.matrixTransform(m.inverse());
    return [clamp(q.x, x0, x1), clamp(q.y, y0, y1)];
  };
  const onDown = (e) => {
    if (e.button !== 0) return;
    const at = toPoint(e);
    if (!at) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setDrag([...at, ...at]);
  };
  const onMove = (e) => {
    if (!drag) return;
    const at = toPoint(e);
    if (at) setDrag([drag[0], drag[1], ...at]);
  };
  const onUp = (e) => {
    if (!drag) return;
    const at = toPoint(e) || [drag[2], drag[3]];
    const box = round1(normBox([drag[0], drag[1], ...at]));
    setDrag(null);
    // A click without a drag is not a box (and must not replace one by accident).
    if (box[2] - box[0] >= 1 && box[3] - box[1] >= 1) latestDraw.current?.onDone?.(box);
  };

  const dragBox = drag ? normBox(drag) : null;
  return html`
    <svg ref=${svg} class=${cx('pagefig', 'cfig', drawing && 'drawing', className)} viewBox="${x0} ${y0} ${vw} ${vh}"
         style=${`aspect-ratio:${vw} / ${vh};max-height:${maxHeight}px;max-width:${Math.round(Math.min((maxHeight * vw) / vh, vw * maxScale))}px`}>
      <image href=${src} x=${x0} y=${y0} width=${vw} height=${vh} preserveAspectRatio="none" />
      ${boxes.map((b, i) => {
        if (!isBox(b.bbox)) return null;
        const [bx0, by0, bx1, by1] = b.bbox;
        const pick = !drawing && onPick && b.pick !== false;
        const on = active != null && (b.id === active || (b.ids || []).includes(active));
        const showLabel = b.label && (labels || on || b.labelled);
        return html`
          <g key=${`${b.kind}:${b.id ?? i}`} class=${cx('box', `box-${b.kind}`, on && 'active', pick && 'pick',
                                                     b.label && !showLabel && 'hover-label')}
             onClick=${pick ? (e) => { e.stopPropagation(); onPick(b); } : null}
             onMouseEnter=${onHover && b.id != null ? () => onHover(b) : null}
             onMouseLeave=${onHover && b.id != null ? () => onHover(null) : null}>
            <rect x=${bx0} y=${by0} width=${bx1 - bx0} height=${by1 - by0} vector-effect="non-scaling-stroke">
              ${b.title ? html`<title>${b.title}</title>` : null}
            </rect>
            ${b.label ? html`
              <text x=${bx0 + font * 0.25} y=${by0 + font * 0.95} font-size=${font}>${b.label}</text>` : null}
          </g>`;
      })}
      ${drawing ? html`
        <rect class="draw-catch" x=${x0} y=${y0} width=${vw} height=${vh}
              onPointerDown=${onDown} onPointerMove=${onMove} onPointerUp=${onUp}
              onPointerCancel=${() => setDrag(null)} />` : null}
      ${dragBox ? html`
        <rect class="draw-box" x=${dragBox[0]} y=${dragBox[1]} width=${dragBox[2] - dragBox[0]}
              height=${dragBox[3] - dragBox[1]} vector-effect="non-scaling-stroke" />` : null}
    </svg>`;
}
