import { html, useEffect, useMemo, useRef, useState } from '../lib/preact.js';
import { useOn, useStored } from '../lib/hooks.js';
import { toast } from '../lib/bus.js';
import { jumpTo } from '../lib/jump.js';
import { href } from '../lib/router.js';
import { BLOCK_STATUS, DOC, ENTRY_STATUS, cx, name } from '../lib/format.js';
import { around, isBox } from '../lib/geom.js';
import { pathKey } from '../lib/paths.js';
import { Chip, Disclosure, Empty, Problems, ReviewChip } from '../components/common.js';
import { PageFigure, clipDpi, drawable } from '../components/pagefigure.js';

// The block a reaction comes from, drawn on its page(s): the block, its region, what the pipeline
// ignored, the template's boxes and the other entries faintly, this entry highlighted, and this
// reaction's own compounds and structures (from the data shown, so edits move them). Adapted from the
// viewer's block.js (SourceFigure, boxesByPage, entryBoxes).

const list = (x) => (Array.isArray(x) ? x : []);
const label = (p) => p.label || p.text || p.key;
const DOC_ORDER = { main: 0, si: 1 };

// Every box of the reaction itself, once per place (a compound repeated in several steps is one box
// naming each path), with the path of its first appearance. kind: participant | structure.
export function reactionParts(data) {
  const out = new Map();
  const add = (kind, x, path, what) => {
    if (!x || x.page == null || !isBox(x.bbox)) return;
    const key = `${kind}|${x.page}|${x.bbox.join(',')}`;
    const prev = out.get(key);
    if (prev) {
      prev.paths.push(path);
      if (what && !prev.names.includes(what)) prev.names.push(what);
      return;
    }
    out.set(key, { kind, page: x.page, bbox: x.bbox, path, paths: [path], names: what ? [what] : [] });
  };
  list(data?.steps).forEach((st, i) => {
    for (const side of ['reactants', 'products']) {
      list(st?.[side]).forEach((p, j) => {
        const path = ['steps', i, side, j];
        add('participant', p, path, p && label(p));
        list(p?.preparation?.from).forEach((f) => add('participant', f, path, f && label(f)));
        list(p?.preparation?.items).forEach((it) => add('structure', it?.structure, path,
          it?.structure && (it.structure.label || it.structure.text || it.text)));
      });
    }
    list(st?.conditions).forEach((c, j) => add('structure', c?.structure, ['steps', i, 'conditions', j],
      c?.structure && (c.structure.label || c.structure.text || c.text)));
  });
  list(data?.conditions).forEach((c, j) => add('structure', c?.structure, ['conditions', j],
    c?.structure && (c.structure.label || c.structure.text || c.text)));
  return [...out.values()];
}

// The reaction's boxes for the PDF pane (`pdf:boxes`, `pdf:open`): its entry, compounds, structures.
export function reactionBoxes(data) {
  const src = data?.source || {};
  const boxes = reactionParts(data).map((b) => ({ page: b.page, bbox: b.bbox, label: b.names.join(' / '), kind: b.kind }));
  if (src.page != null && isBox(src.entry_bbox)) {
    boxes.unshift({ page: src.page, bbox: src.entry_bbox, label: src.entry_id || '条目', kind: 'entry' });
  }
  return boxes;
}

// The entries' boxes. Entries listed under one drawing share a box: they get one rectangle, named
// after all of them ("e003–e005, e008": neighbours in the list as a range).
function entryBoxes(entries) {
  const groups = new Map();
  entries.forEach((e, i) => {
    if (!isBox(e.bbox)) return;
    const key = `${e.page}:${e.bbox.join(',')}`;
    groups.set(key, [...(groups.get(key) || []), i]);
  });
  return [...groups.values()].map((at) => {
    const es = at.map((i) => entries[i]);
    const runs = [];
    at.forEach((i, n) => {
      if (n && at[n - 1] === i - 1) runs[runs.length - 1][1] = entries[i].eid;
      else runs.push([entries[i].eid, entries[i].eid]);
    });
    return {
      ids: es.map((e) => e.eid), page: es[0].page, bbox: es[0].bbox,
      label: runs.map(([a, b]) => (a === b ? a : `${a}–${b}`)).join(', '),
      title: es.map((e) => `${e.eid}　${e.label || ''}　${e.descriptor || ''}`).join('\n'),
    };
  });
}

// Equation blocks and prose passages give every equation or experiment a template of its own: the
// block's participants are then its compounds, not the parts of a general reaction.
const ownTemplates = (view) => !!(view?.equations || view?.experiments);

// What the boxes are, in drawing order (later layers lie on top and take the clicks).
function layerNames(view) {
  return [
    ['region', '区域'], ['block', '块'], ['ignored', '忽略的区域'], ['scheme', '通式区域'],
    ['tpl', ownTemplates(view) ? '块中的化合物' : '通式成分'], ['tplstruct', '模板中的条件结构'],
    ['shared', '共享定义'], ['other', '其他条目'], ['current', '本条目'], ['mine', '本反应的成分'], ['minestruct', '本反应的条件结构'],
  ];
}
const ORDER = Object.fromEntries(layerNames(null).map(([k], i) => [k, i]));

// Every box to draw, each with the document and page it is on.
function allBoxes(data, block) {
  const src = data?.source || {};
  const out = [];
  const add = (doc, page, box) => { if (doc && page != null && isBox(box.bbox)) out.push({ doc, page, ...box }); };

  const parts = reactionParts(data);
  const mine = new Set(parts.map((b) => `${b.page}|${b.bbox.join(',')}`));
  for (const b of parts) {
    const id = pathKey(b.path);
    add(src.doc, b.page, {
      kind: b.kind === 'participant' ? 'mine' : 'minestruct', bbox: b.bbox, id, ids: b.paths.map(pathKey),
      path: b.path, label: b.names.join(' / ') || null, labelled: true,
      title: `${b.kind === 'participant' ? '本反应的成分' : '本反应的条件结构'}：${b.names.join(' / ')}`,
    });
  }
  add(src.doc, src.page, { kind: 'current', id: 'current', bbox: src.entry_bbox, label: src.entry_id || '本条目',
    labelled: true, title: `本条目 ${src.entry_id || ''}` });

  const view = block?.view;
  if (view) {
    const doc = block.doc || view.region?.doc;
    for (const r of list(block.region?.boxes)) add(doc, r.page, { kind: 'region', bbox: r.bbox, pick: false });
    if (view.block) add(doc, view.block.page, { kind: 'block', bbox: view.block.bbox, pick: false });
    list(view.ignored).forEach((g, i) => add(doc, g.page, { kind: 'ignored', id: `ig${i}`, bbox: g.bbox, title: `忽略：${g.reason}` }));
    const t = view.template;
    if (t) {
      if (t.scheme) add(doc, t.scheme.page, { kind: 'scheme', bbox: t.scheme.bbox, pick: false, title: '通式区域' });
      const word = ownTemplates(view) ? '块中的化合物' : '通式成分';
      // A template box this reaction uses as it is would only be drawn twice.
      const fresh = (x) => !mine.has(`${x.page}|${list(x.bbox).join(',')}`);
      list(t.participants).filter(fresh).forEach((p, i) => add(doc, p.page, {
        kind: 'tpl', id: `tp${i}`, bbox: p.bbox, label: label(p), title: `${word}：${label(p)}` }));
      list(t.structures).filter(fresh).forEach((x, i) => add(doc, x.page, {
        kind: 'tplstruct', id: `ts${i}`, bbox: x.bbox, label: x.label || x.text || x.key,
        title: `模板中的条件结构：${x.label || x.text || x.key}` }));
    }
    list(view.shared_geometry_regions).forEach((g, i) => add(doc, g.page,
      { kind: 'shared', id: `shared${i}`, bbox: g.bbox, label: g.label, labelled: true, title: g.label }));
    for (const e of entryBoxes(list(view.entries))) {
      const ids = e.ids.filter((x) => x !== src.entry_id);
      if (!ids.length) continue;
      add(doc, e.page, { kind: 'other', id: ids[0], ids, bbox: e.bbox, label: e.label, title: e.title });
    }
  }
  return out;
}

const area = (b) => Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]);
const union = (boxes) => [Math.min(...boxes.map((b) => b[0])), Math.min(...boxes.map((b) => b[1])),
  Math.max(...boxes.map((b) => b[2])), Math.max(...boxes.map((b) => b[3]))];

// A box grown to at least `w` × `h` around its centre, inside the page.
function atLeast(b, [w, h], size) {
  const grow = (lo, hi, min, max) => {
    const extra = Math.max(0, min - (hi - lo)) / 2;
    let [a, z] = [lo - extra, hi + extra];
    if (a < 0) [a, z] = [0, Math.min(max, z - a)];
    if (z > max) [a, z] = [Math.max(0, a - (z - max)), max];
    return [a, z];
  };
  const [x0, x1] = grow(b[0], b[2], w, size[0]);
  const [y0, y1] = grow(b[1], b[3], h, size[1]);
  return [x0, y0, x1, y1];
}

// The clip of a figure. "block": what was read on the page (the region too when it is not much
// larger: then captions and footnotes are not cut in half). "entry": this entry and the parts of the
// reaction close to it, for blocks of many small entries.
function clipOf(g, size, zoom) {
  const ok = g.boxes.filter((b) => drawable(b.bbox, size));
  const framing = ok.filter((b) => b.kind !== 'region');
  if (!framing.length) return null;
  const own = (b) => b.kind === 'mine' || b.kind === 'minestruct' || b.kind === 'current';
  if (zoom === 'entry') {
    const entry = framing.find((b) => b.kind === 'current');
    if (entry) {
      const near = [entry.bbox[0] - 120, entry.bbox[1] - 120, entry.bbox[2] + 120, entry.bbox[3] + 120];
      const inside = (b) => b[0] >= near[0] && b[1] >= near[1] && b[2] <= near[2] && b[3] <= near[3];
      const parts = framing.filter((b) => own(b) && inside(b.bbox)).map((b) => b.bbox);
      return atLeast(around(parts, size, 30), [260, 150], size);
    }
  }
  const core = union(framing.map((b) => b.bbox));
  const region = ok.filter((b) => b.kind === 'region').map((b) => b.bbox);
  const withRegion = region.length ? union([core, ...region]) : core;
  const frame = area(withRegion) <= 2 * area(core) ? withRegion : core;
  return around([frame], size, framing.every(own) ? 28 : 10);
}

// One figure per (document, page): the block's page first.
function figures(boxes, docs, block, zoom) {
  const groups = new Map();
  for (const b of boxes) {
    const key = `${b.doc}|${b.page}`;
    if (!groups.has(key)) groups.set(key, { doc: b.doc, page: b.page, boxes: [] });
    groups.get(key).boxes.push(b);
  }
  const home = block ? `${block.doc}|${block.page}` : null;
  return [...groups.values()].map((g) => {
    const p = docs?.[g.doc]?.pages?.[g.page - 1];
    const size = p ? [p[0], p[1]] : null;
    return { ...g, size, clip: size ? clipOf(g, size, zoom) : null, docId: docs?.[g.doc]?.doc_id ?? null,
      boxes: g.boxes.sort((a, b) => ORDER[a.kind] - ORDER[b.kind]) };
  }).filter((g) => g.docId != null && g.clip)
    .sort((a, b) => ((`${a.doc}|${a.page}` === home) ? -1 : (`${b.doc}|${b.page}` === home) ? 1
      : (DOC_ORDER[a.doc] ?? 2) - (DOC_ORDER[b.doc] ?? 2) || a.page - b.page));
}

// Tall clips (a scope figure of a whole column) may grow taller than wide ones, so they stay readable.
const figureHeight = (clip) => Math.round(Math.max(560, Math.min(1100, ((clip[3] - clip[1]) / (clip[2] - clip[0])) * 720)));

// ------------------------------------------------------------------ entries

function EntryReactions({ block, ids, query, current, onPickEntry }) {
  const entries = list(block?.view?.entries).filter((e) => ids.includes(e.eid));
  return entries.map((e) => {
    const rs = list(block?.reactions).filter((r) => r.entry_id === e.eid && r.id !== current);
    return html`
      <div class="entry-info" key=${e.eid}>
        <div class="entry-info-head">
          <span class="mono">${e.eid}</span>${e.label ? html`<b>${e.label}</b>` : null}
          ${e.status && e.status !== 'ok' ? html`<${Chip} tone=${e.status === 'failed' ? 'bad' : 'warn'}>${name(ENTRY_STATUS, e.status)}<//>` : null}
        </div>
        ${e.geometry_note ? html`<p class="small">${e.geometry_note}</p>` : null}
        ${e.expansion?.printed || e.descriptor ? html`<pre class="printed">${e.expansion?.printed || e.descriptor}</pre>` : null}
        ${rs.length ? html`
          <ul class="entry-rxns">
            ${rs.map((r) => html`
              <li key=${r.id}>
                <a class=${cx(r.deleted && 'deleted')} href=${href('reactions', r.id, query)}
                   onClick=${onPickEntry ? (ev) => { ev.preventDefault(); onPickEntry(r.id); } : null}>
                  <span class="mono">${r.rid}</span> <b>${r.label || '—'}</b></a>
                <${ReviewChip} status=${r.review_status} />
                ${r.deleted ? html`<${Chip} tone="muted">已删除<//>` : null}
                ${r.origin_id ? null : html`<${Chip} tone="muted">人工<//>`}
              </li>`)}
          </ul>`
          : html`<p class="muted small">${current != null && list(block?.reactions).some((r) => r.entry_id === e.eid)
            ? '这个条目没有别的反应。' : list(e.reactions).some((r) => r.status === 'skipped')
              ? '此条目已枚举，本次小样本未展开为反应记录。' : '库里没有这个条目的反应（可能提取失败）。'}</p>`}
      </div>`;
  });
}

// ------------------------------------------------------------------ the figure

// props: {row, data, block, docs, query, onPickEntry(id), editing, selected, onSelect, drawing}; `block` is the
// getBlock answer (null: the reaction has no block, only its own boxes are drawn). onPickEntry opens
// another reaction (default: a link with the list's filters). `drawing`: the editor's draw:start request,
// passed in as well because 框选 may switch to this tab after the event went out.
export function BlockFigure({ row, data, block, docs, query, onPickEntry, editing, selected, onSelect, drawing }) {
  const view = block?.view || null;
  const [hidden, setHidden] = useState({});
  const [labels, setLabels] = useState(false);
  const [picked, setPicked] = useState(null);    // {box, fig, x, y}: an "other" entry box and where it was clicked
  const pointer = useRef({ x: 0, y: 0 });
  const [drawReq, setDrawReq] = useState(null);  // a draw:start request this figure takes part in
  const [zoomPref, setZoom] = useStored('curator.blockZoom', 'block');
  const req = drawing || drawReq;
  const drawRef = useRef(null);
  drawRef.current = req;
  const boxes = useMemo(() => allBoxes(data, block), [data, block]);
  const src = data?.source || {};
  const canZoom = !!view && src.page != null && isBox(src.entry_bbox);
  const zoom = canZoom && zoomPref === 'entry' ? 'entry' : 'block';
  const figs = useMemo(() => figures(boxes, docs, block, zoom), [boxes, docs, block, zoom]);
  const names = layerNames(view);
  const present = new Set(boxes.map((b) => b.kind));

  // Draw mode (F4's 框选): every figure of the requested document takes a drag; the result goes back
  // with its page. The pane's request may arrive for the other document: then nothing changes here.
  useOn('draw:start', (req) => setDrawReq(req && (req.docId != null || req.doc) ? req : null));
  useOn('draw:end', () => setDrawReq(null));
  const finish = (fn) => {
    const req = drawRef.current;
    if (!req) return;
    drawRef.current = null;
    setDrawReq(null);
    fn(req);
  };

  // Esc closes the popover of another entry (and nothing else).
  useEffect(() => {
    if (!picked) return undefined;
    const onKey = (e) => {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      e.stopImmediatePropagation();
      setPicked(null);
    };
    addEventListener('keydown', onKey, true);
    return () => removeEventListener('keydown', onKey, true);
  }, [picked]);

  const pdfBoxes = useMemo(() => reactionBoxes(data), [data]);
  const jump = (fig, b) => jumpTo({ paperId: row.paper_id, doc: fig.doc, docId: fig.docId, page: fig.page, bbox: b.bbox,
    label: b.label || b.title || null, boxes: pdfBoxes });
  const pick = (fig) => (b) => {
    if (b.kind === 'other') {
      const key = `${fig.doc}|${fig.page}`;
      setPicked(picked && picked.box.id === b.id ? null : { box: b, fig: key, ...pointer.current });
      return;
    }
    if (editing && b.kind === 'current') return onSelect?.(['source']);
    if (editing && b.path) return onSelect?.(b.path);
    jump(fig, b);
  };
  const active = editing && selected ? (selected.length === 1 && selected[0] === 'source' ? 'current' : pathKey(selected))
    : picked?.box.id ?? null;

  const head = view ? html`
    <div class="bf-title">
      <h3>${block.figure || view.region?.label ? html`${block.figure || view.region.label}<span class="sep">·</span>` : null}${block.title || `块 ${block.block_id}`}</h3>
      ${view.status && view.status !== 'ok' ? html`<${Chip} tone=${view.status === 'failed' ? 'bad' : 'warn'}>${name(BLOCK_STATUS, view.status)}<//>` : null}
      ${block.in_latest === false ? html`<${Chip} tone="warn" title="最近一次导入里没有这个块">不在最新导入中<//>` : null}
    </div>` : html`<div class="bf-title"><h3>本反应的框</h3><span class="muted">这条反应不属于任何块</span></div>`;

  return html`
    <section class="card dcard figure-card bf">
      <div class="card-head bf-head">${head}</div>
      ${view?.geometry_correction ? html`<div class="dcard-body small">
        <b>来源块已人工校正</b> · ${view.geometry_correction.reason}
        <p>${view.geometry_correction.notes}</p><span class="muted">仅校正来源框及阅读说明，原始导入快照保留；不代表未展开条目已完成反应提取。</span>
      </div>` : null}
      <div class="bf-tools">
        ${canZoom ? html`
          <div class="seg" role="group" aria-label="显示范围">
            <button type="button" class=${cx('btn', 'small', zoom === 'block' && 'on')} aria-pressed=${zoom === 'block' ? 'true' : 'false'}
                    onClick=${() => setZoom('block')}>整个块</button>
            <button type="button" class=${cx('btn', 'small', zoom === 'entry' && 'on')} aria-pressed=${zoom === 'entry' ? 'true' : 'false'}
                    onClick=${() => setZoom('entry')} title="放大到本条目和它附近的框">本条目附近</button>
          </div>` : null}
        <div class="legend">
          ${names.filter(([k]) => present.has(k)).map(([kind, text]) => html`
            <button type="button" key=${kind} class=${cx('legend-item', `k-${kind}`, hidden[kind] && 'off')}
                    aria-pressed=${hidden[kind] ? 'false' : 'true'}
                    onClick=${() => setHidden({ ...hidden, [kind]: !hidden[kind] })}><i></i>${text}</button>`)}
          <button type="button" class=${cx('legend-item', 'k-labels', !labels && 'off')} aria-pressed=${labels ? 'true' : 'false'}
                  onClick=${() => setLabels(!labels)}>全部编号</button>
        </div>
      </div>
      ${req ? html`
        <div class="draw-banner">
          <span>框选${req.label ? html`「<b>${req.label}</b>」` : ''}：在${name(DOC, req.doc) || '来源文档'}的图上拖出一个框（也可以在 PDF 里画），按 Esc 取消</span>
          ${figs.length === 0 ? html`
            <button type="button" class="btn small" onClick=${() => jumpTo({ paperId: row.paper_id, doc: req.doc, docId: req.docId,
              page: src.page || 1, boxes: pdfBoxes })}>在 PDF 里画</button>` : null}
          <button type="button" class="btn small" onClick=${() => finish((r) => r.onCancel?.())}>取消</button>
        </div>` : null}
      ${figs.length === 0 ? html`<div class="dcard-body"><${Empty}>${req ? '这条反应还没有页码和框，这里没有可以画框的图：请在 PDF 面板里画。'
        : '没有可以画出的框：这条反应没有页码和框。'}<//></div>` : null}
      ${figs.map((fig) => {
        const drawHere = req && (req.docId != null ? String(req.docId) === String(fig.docId) : req.doc === fig.doc);
        return html`
          <figure key=${`${fig.doc}|${fig.page}`} class="bf-fig"
                  onPointerDown=${(e) => {
                    const r = e.currentTarget.getBoundingClientRect();
                    pointer.current = { x: e.clientX - r.left, y: e.clientY - r.top, w: r.width };
                  }}>
            <${PageFigure} docId=${fig.docId} page=${fig.page} size=${fig.size} clip=${fig.clip} maxHeight=${figureHeight(fig.clip)}
                           dpi=${fig.clip ? clipDpi(fig.clip[2] - fig.clip[0]) : null} active=${active} labels=${labels}
                           boxes=${fig.boxes.filter((b) => !hidden[b.kind])} onPick=${pick(fig)}
                           draw=${drawHere ? {
                             onDone: (bbox) => finish((r) => r.onDone?.({ page: fig.page, bbox })),
                             onCancel: () => finish((r) => r.onCancel?.()),
                           } : req ? {
                             // A figure of the other document: a box there cannot belong to this reaction.
                             onDone: () => toast(`框必须画在本反应的来源文档（${name(DOC, req.doc) || req.doc}）上`, 'warn'),
                             onCancel: () => finish((r) => r.onCancel?.()),
                           } : null} />
            <figcaption>
              <span>${name(DOC, fig.doc)} 第 ${fig.page} 页</span>
              <span class="muted">${editing ? '点击本反应的框选中对应的成分；' : '点击框在 PDF 中定位；'}点击其他条目的框查看它们的反应</span>
              <button type="button" class="link" onClick=${() => jumpTo({ paperId: row.paper_id, doc: fig.doc, docId: fig.docId,
                page: fig.page, boxes: pdfBoxes })}>在 PDF 中打开这一页</button>
            </figcaption>
            ${picked && picked.fig === `${fig.doc}|${fig.page}` ? html`
              <div class="bf-pop" role="dialog" aria-label="其他条目的反应"
                   style=${`left:${Math.max(8, Math.min(picked.x - 24, (picked.w || 600) - 328))}px;top:${picked.y + 16}px`}
                   onPointerDown=${(e) => e.stopPropagation()}>
                <div class="bf-pop-head">
                  <b>其他条目</b>
                  <button type="button" class="btn small" onClick=${() => jump(fig, picked.box)}>在 PDF 中定位</button>
                  <button type="button" class="icon-x" aria-label="关闭" title="关闭" onClick=${() => setPicked(null)}>×</button>
                </div>
                <${EntryReactions} block=${block} ids=${picked.box.ids || [picked.box.id]} query=${query} current=${row.id}
                                   onPickEntry=${onPickEntry} />
              </div>` : null}
          </figure>`;
      })}
      ${view ? html`
        <div class="bf-entry">
          ${src.entry_id ? html`
            <div class="bf-entry-head"><b>本条目</b><span class="muted">点击图中其他条目的框可以查看它们的反应</span></div>
            <${EntryReactions} block=${block} ids=${[src.entry_id]} query=${query} current=${row.id}
                               onPickEntry=${onPickEntry} />`
            : html`<div class="bf-entry-head"><span class="muted">这条反应没有指定条目；点击图中条目的框可以查看它们的反应</span></div>`}
        </div>` : null}
    </section>
    ${view ? html`<${BlockAbout} block=${block} />` : null}`;
}

// What the block is about: its general reaction, caption, footnotes, notes and the pipeline's remarks.
function BlockAbout({ block }) {
  const view = block.view || {};
  const region = view.region || block.region || {};
  const rows = [
    view.block?.general_reaction && ['通式', view.block.general_reaction],
    region.caption && ['图注', region.caption],
    (region.footnotes || block.region?.footnotes) && ['脚注', region.footnotes || block.region.footnotes],
    view.block?.conditions_text && ['条件文字', view.block.conditions_text],
    view.notes && ['读块备注', view.notes],
  ].filter(Boolean);
  const problems = list(view.errors).length + list(view.warnings).length;
  if (!rows.length && !problems) return null;
  return html`
    <${Disclosure} summary=${html`关于这个块${problems ? html` <span class="muted">· 流水线问题 ${problems}</span>` : null}`}>
      <div class="kv">${rows.map(([k, v]) => html`<div class="kv-key" key=${`k${k}`}>${k}</div><div class="kv-value" key=${`v${k}`}>${v}</div>`)}</div>
      <${Problems} errors=${list(view.errors)} warnings=${list(view.warnings)} />
    <//>`;
}
