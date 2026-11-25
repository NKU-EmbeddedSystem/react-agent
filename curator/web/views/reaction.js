import { html } from '../lib/preact.js';
import { renderUrl } from '../lib/api.js';
import { ACTION, FLAG, FLAG_TONE, KIND, ROLE, SOURCE, YIELD_TYPE, cx, name, origin, originShort } from '../lib/format.js';
import { pathKey, samePath } from '../lib/paths.js';
import { Chip, Inferred, Origin, Problems, Where } from '../components/common.js';
import { drawable } from '../components/pagefigure.js';
import { show } from '../components/lightbox.js';

// One reaction as an equation: per step, reactants → products with the conditions on the arrow; then
// what is wrong with it and what the record says about it. Adapted from the pipeline's own block viewer: the
// pictures are rendered by the server from (source document, page, box), and with `editing` every
// part becomes selectable for the inspector.
//
// Paths of the selectable parts (lib/paths.js), what onSelect(path) reports:
//   reaction header          []
//   a step                   ['steps', i]
//   a participant            ['steps', i, 'reactants' | 'products', j]
//   a condition              ['steps', i, 'conditions', j]      a loose one: ['conditions', j]
//   an outcome               ['steps', i, 'products', j, 'outcomes', k]      ['other_outcomes', k]
//
// In edit mode two more props: `onAdd(listPath, kind)` adds a blank participant / condition / step
// (the + buttons), and `changed` (a Set of pathKeys) marks the parts with unsaved changes.

const label = (p) => p.label || p.text || p.key;
const options = (alternatives) => alternatives.map((a) => a.text).join(' 或 ');

// Everything the parts need: where pictures come from and the edit state.
function context({ row, data, docs, editing, selected, onSelect, onAdd, changed }) {
  const doc = data?.source?.doc || 'main';
  const d = docs?.[doc];
  return { doc, docId: d?.doc_id ?? null, pages: d?.pages || null, paperId: row?.paper_id ?? null, editing: !!editing,
    docs, selected, onSelect, onAdd: editing ? onAdd : null, changed: editing ? changed : null };
}

// A dashed button that adds a blank item to a list of the record (edit mode only).
function AddButton({ ctx, path, kind, children, className }) {
  if (!ctx.onAdd) return null;
  return html`
    <button type="button" class=${cx('eq-add', className)} onClick=${(e) => { e.stopPropagation(); ctx.onAdd(path, kind); }}
            title=${`添加${children}`}><span class="eq-add-plus">+</span><span>${children}</span></button>`;
}

// The props that make an element selectable in edit mode (nothing otherwise).
function selectable(ctx, path, className) {
  if (!ctx.editing) return { class: className };
  const on = samePath(ctx.selected, path);
  const changed = ctx.changed?.has(pathKey(path));
  const pick = (e) => {
    e.stopPropagation();
    ctx.onSelect?.(path);
  };
  return {
    class: cx(className, 'sel-target', on && 'selected', changed && 'changed'), onClick: pick, role: 'button', tabindex: 0,
    title: changed ? '有未保存的修改' : undefined,
    'aria-pressed': on ? 'true' : 'false',
    onKeyDown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(e); } },
  };
}

// A part's picture: a render of its box on the source document, or null when it has none (or one the
// server could not render: a box off the page is drawn as a note instead of a broken image).
function picture(ctx, x) {
  if (!x || x.page == null || !Array.isArray(x.bbox) || ctx.docId == null) return null;
  const p = ctx.pages?.[x.page - 1];
  const ok = (!ctx.pages || p) && drawable(x.bbox, p ? [p[0], p[1]] : null);
  return { ok, src: ok ? renderUrl(ctx.docId, x.page, x.bbox, { dpi: 150, pad: 0 }) : null,
    size: p ? [p[0], p[1]] : null };
}

function enlarge(ctx, x, caption, pic) {
  show({ docId: ctx.docId, doc: ctx.doc, paperId: ctx.paperId, page: x.page, bbox: x.bbox, caption, size: pic.size });
}

// ------------------------------------------------------------------ compounds

function TilePicture({ ctx, p, pic, generic }) {
  const title = generic ? '通式中的画法（这条反应没有自己的结构图）' : '点击放大';
  if (!pic.ok) return html`<div class="tile-pic broken" title="框不在页面上">框无效<br />第 ${p.page} 页</div>`;
  const img = html`<img src=${pic.src} loading="lazy" alt=${label(p)} />`;
  // While editing a click selects the compound; the picture only enlarges outside edit mode.
  return ctx.editing ? html`<div class="tile-pic">${img}</div>`
    : html`<button type="button" class="tile-pic" onClick=${() => enlarge(ctx, p, label(p), pic)} title=${title}>${img}</button>`;
}

function Tile({ ctx, p, path }) {
  // Without a drawing of its own, the compound is shown by the generic drawing of the scheme.
  const generic = p.source === 'derived';
  // Not printed in any form (the product of a reactant table): to be worked out from the reactants.
  const unknown = p.unknown;
  const pic = picture(ctx, p);
  return html`
    <div ...${selectable(ctx, path, cx('tile', generic && 'generic', !pic && 'textual'))}>
      ${pic ? html`
        <${TilePicture} ctx=${ctx} p=${p} pic=${pic} generic=${generic} />
        <div class="tile-name">${p.label ? html`<b>${p.label}</b>` : null}${p.label && p.text ? ' ' : ''}${p.text || (p.label ? '' : p.key)}</div>`
        : html`
        <div class="tile-pic" title=${p.source === 'derived' ? '没有结构图：由通式推出' : '文中只有名称，没有结构图'}>
          ${unknown && !p.text ? '未知' : p.text || p.label || p.key}</div>
        ${p.label && p.text ? html`<div class="tile-name"><b>${p.label}</b></div>` : null}`}
      ${p.amount ? html`<div class="tile-line">${p.amount} <${Origin} value=${p.amount_origin} /> <${Where} at=${p.amount_stated_at} /></div>` : null}
      ${(p.variables || []).map((v) => html`
        <div class="tile-line" title=${v.basis || null}>${v.name} = ${v.value} <${Origin} value=${v.origin} /></div>`)}
      <div class="tile-chips">
        ${generic && pic ? html`<${Chip} title=${p.basis}>通式画法<//>` : null}
        ${p.role === 'intermediate' ? html`<${Chip}>中间体${p.isolated === true ? '·已分离' : p.isolated === false ? '·未分离' : ''}<//>` : null}
        ${p.role === 'byproduct' ? html`<${Chip}>副产物<//>` : null}
        <${Where} at=${p.stated_at} />
        <${Inferred} mark=${p.inferred} />
        ${p.undecided_with && p.undecided_with.length ? html`<${Chip} tone="bad">未确定：与 ${p.undecided_with.join('、')} 二选一<//>` : null}
        ${p.alternatives && p.alternatives.length ? html`<${Chip} tone="bad">未确定：${options(p.alternatives)}<//>` : null}
        ${p.preparation ? html`<${Chip}>事先制备<//>` : null}
      </div>
    </div>`;
}

function Side({ ctx, items, path, products }) {
  return html`
    <div class=${cx('eq-side', products && 'products', items.length > 1 && 'multi')}>
      ${items.length === 0 && !ctx.onAdd ? html`<span class="none">—</span>` : null}
      ${items.map((p, j) => html`
        ${j ? html`<span class="plus">+</span>` : null}
        <${Tile} key=${p.key ?? j} ctx=${ctx} p=${p} path=${[...path, j]} />`)}
      <${AddButton} ctx=${ctx} path=${path} kind="participant">${products ? '产物' : '反应物'}<//>
    </div>`;
}

// ----------------------------------------------------------------- conditions

// Reagent-like conditions go above the arrow, one per line; the medium (solvent, temperature,
// time, atmosphere) goes below it on one line.
const BELOW = new Set(['solvent', 'temperature', 'time', 'atmosphere']);

const marks = (c) => [originShort(c.origin), c.stated_at, c.inferred, c.value_missing,
  c.alternatives && c.alternatives.length].filter(Boolean).length;

function Marks({ c }) {
  return html`
    <${Origin} value=${c.origin} /><${Where} at=${c.stated_at} /><${Inferred} mark=${c.inferred} />
    ${c.value_missing ? html`<${Chip} tone="bad">本条未给出<//>` : null}
    ${c.alternatives && c.alternatives.length ? html`<${Chip} tone="bad">未确定：${options(c.alternatives)}<//>` : null}`;
}

function Drawn({ ctx, x }) {
  if (x?.doc) {
    const doc = ctx.docs?.[x.doc];
    ctx = { ...ctx, doc: x.doc, docId: doc?.doc_id ?? null, pages: doc?.pages || null };
  }
  const pic = picture(ctx, x);
  if (!pic) return null;
  if (!pic.ok) return html`<span class="cond-pic broken" title="结构的框不在页面上">框无效</span>`;
  const img = html`<img src=${pic.src} loading="lazy" alt=${x.label || x.text || x.key || ''} />`;
  return ctx.editing ? html`<span class="cond-pic">${img}</span>`
    : html`<button type="button" class="cond-pic" onClick=${() => enlarge(ctx, x, x.label || x.text || x.key, pic)}
                   title="点击放大">${img}</button>`;
}

function Arrow({ ctx, conditions, removed, notGiven, addPath }) {
  const above = conditions.filter(({ c }) => !BELOW.has(c.role));
  const below = conditions.filter(({ c }) => BELOW.has(c.role));
  // In edit mode every condition gets its own line: an inline run is too small a target.
  const inline = !ctx.editing && below.reduce((n, { c }) => n + marks(c), 0) <= 2;
  const line = ({ c, path }) => html`
    <div key=${c.key ?? path.join('.')} ...${selectable(ctx, path, 'cond')}>
      <span class="cond-role">${name(ROLE, c.role)}</span>
      <span class="cond-value"><${Drawn} ctx=${ctx} x=${c.structure} />${c.text}
        ${c.amount ? html` <span class="cond-amount">${c.amount}</span>` : null} <${Where} at=${c.amount_stated_at} /> <${Marks} c=${c} />
        ${c.definition ? html`<details class="more"><summary>核查补全的身份定义</summary>${c.definition.text}
          ${c.structure?.doc ? html`<${Where} at=${c.structure} />` : null}</details>` : null}
      </span>
    </div>`;
  return html`
    <div class="eq-above">
      <div class="conds">
        ${notGiven ? html`<div class="cond"><${Chip} tone="warn">本文没有给出这套条件<//></div>` : null}
        ${above.map(line)}
        ${addPath ? html`<div class="cond cond-add"><span></span><${AddButton} ctx=${ctx} path=${addPath} kind="condition" className="small">条件<//></div>` : null}
      </div>
    </div>
    <div class="eq-below">
      <div class="shaft"></div>
      <div class=${inline ? 'conds below' : 'conds'}>
        ${inline ? below.map(({ c }, i) => html`
          <span class="cond-inline" key=${c.key ?? i} title=${name(ROLE, c.role)}>${i ? html`<i>·</i>` : null}${c.text}
            ${c.amount ? html` <span class="cond-amount">${c.amount}</span>` : null} <${Marks} c=${c} /></span>`)
          : below.map(line)}
        ${removed.length ? html`
          <details class="more">
            <summary>这条反应不用的条件 ${removed.length}</summary>
            ${removed.map((c, i) => html`
              <div class="cond-removed" key=${c.key ?? i}><s>${name(ROLE, c.role)}　${c.text}</s> <${Origin} value=${c.origin} /></div>`)}
          </details>` : null}
      </div>
    </div>`;
}

// --------------------------------------------------------------------- yields

const list = (x) => (Array.isArray(x) ? x : []);

// Every outcome of the reaction with its path: those of products, then the other outcomes (a value
// measured on a compound the reaction does not form, such as a recovered starting material, names it).
export function outcomes(rec) {
  const steps = list(rec?.steps);
  const parts = Object.fromEntries(steps.flatMap((st) => [...list(st.reactants), ...list(st.products)])
    .filter((p) => p && p.key != null).map((p) => [p.key, p]));
  const made = [];
  steps.forEach((st, i) => list(st.products).forEach((p, j) => {
    if (p && list(p.outcomes).length) made.push({ p, i, j });
  }));
  const named = made.length > 1;
  // Several steps with results (alternative protocols for one product): say which step a value is of.
  const perStep = new Set(made.map((m) => m.i)).size > 1;
  return [
    ...made.flatMap(({ p, i, j }) => p.outcomes.map((o, k) => ({
      o, product: named ? label(p) : null, step: perStep ? i + 1 : null, path: ['steps', i, 'products', j, 'outcomes', k],
    }))),
    ...list(rec?.other_outcomes).map((o, k) => ({
      o, product: parts[o?.participant_key] ? label(parts[o.participant_key]) : null, step: null, path: ['other_outcomes', k],
    })),
  ];
}

function Yield({ ctx, o, product, step, path }) {
  const y = o?.yield || {};
  const meta = [
    o?.measurement_kind === 'recovered_starting_material' ? '回收起始物（非产物产率）' : null,
    y.type ? name(YIELD_TYPE, y.type) + (y.type_origin === 'default' ? '（默认）' : '') : null,
    ...list(o?.selectivity).map((s) => `${s.type} ${s.text}`),
  ].filter(Boolean).join(' · ');
  const of = [step ? `第 ${step} 步` : null, product].filter(Boolean).join(' · ');
  return html`
    <span ...${selectable(ctx, path, 'yield')} title=${o?.notes || null}>
      ${of ? html`<span class="yield-of">${of}</span>` : null}
      <b>${y.text || y.qualifier || '—'}</b>${list(o?.footnote_markers).map((m) => html`<sup>${m}</sup>`)}
      ${meta ? html`<span class="yield-meta">${meta}</span>` : null}
      ${o?.stated_at ? html`<${Where} at=${o.stated_at} />` : null}
    </span>`;
}

// -------------------------------------------------------------------- details

const Passage = ({ p }) => html`
  <div class="passage"><${Where} at=${p} /> ${p.about}<q>${p.text}</q></div>`;

function PrepPicture({ ctx, x, caption }) {
  const pic = picture(ctx, x);
  if (!pic || !pic.ok) return null;
  return html`<button type="button" class="prep-pic" onClick=${() => enlarge(ctx, x, caption, pic)} title="点击放大">
    <img src=${pic.src} loading="lazy" alt=${caption || ''} /></button>`;
}

function Preparation({ ctx, prep }) {
  return html`
    <div class="prep">
      <div>${prep.description}（不计入产率）</div>
      ${list(prep.from).map((src, i) => html`
        <div class="prep-item" key=${i}><${PrepPicture} ctx=${ctx} x=${src} caption=${label(src)} />
          <span class="muted">由</span> ${label(src)}</div>`)}
      ${list(prep.items).map((item, i) => html`
        <div class="prep-item" key=${`i${i}`}><${PrepPicture} ctx=${ctx} x=${item.structure}
            caption=${item.text || item.structure?.label || ''} />
          <span class="muted">${name(ROLE, item.role)}</span>
          ${item.text || (item.structure && (item.structure.text || item.structure.label || item.structure.key)) || ''} ${item.amount || ''}</div>`)}
      ${prep.basis ? html`<div class="muted">${prep.basis}</div>` : null}
    </div>`;
}

// What there is to say about single compounds: where each comes from and what was decided for it.
function compoundNotes(ctx, rec) {
  const seen = new Set();
  const rows = [];
  for (const p of list(rec.steps).flatMap((st) => [...list(st.reactants), ...list(st.products)])) {
    if (!p || seen.has(p.key)) continue;
    seen.add(p.key);
    const lines = [];
    if (p.basis) lines.push(html`<div>${p.basis}</div>`);
    if (p.choice) lines.push(html`<div>备选之一，由${origin(p.choice.origin) || '通式'}选定 <${Where} at=${p.choice.stated_at} /> ${p.choice.basis}</div>`);
    if (p.inferred) lines.push(html`<div><${Chip} tone="infer">推断<//> ${p.inferred.basis}</div>`);
    if (p.preparation) lines.push(html`<${Preparation} ctx=${ctx} prep=${p.preparation} />`);
    if (lines.length) rows.push(html`
      <div class="note-row" key=${p.key}><span class="note-key">${label(p)}<small>${name(SOURCE, p.source)}</small></span><div>${lines}</div></div>`);
  }
  return rows;
}

// The names of participants and conditions by key, for lists of keys (unresolved).
function namesByKey(rec) {
  const out = {};
  for (const st of list(rec.steps)) {
    for (const p of [...list(st.reactants), ...list(st.products)]) if (p?.key != null) out[p.key] = label(p);
    for (const c of list(st.conditions)) if (c?.key != null) out[c.key] = c.text || c.key;
  }
  for (const c of list(rec.conditions)) if (c?.key != null) out[c.key] = c.text || c.key;
  return out;
}

// The problems of the reaction: what the pipeline reported when it read it, and the record's issues.
export function ProblemsCard({ row, data }) {
  const info = row?.pipeline_info || {};
  const errors = list(info.errors);
  const warnings = list(info.warnings);
  const issues = list(data?.issues);
  const n = errors.length + warnings.length + issues.length;
  if (!n) return null;
  const group = (title, body) => html`<div class="problem-group"><div class="problem-title">${title}</div>${body}</div>`;
  return html`
    <section class="card dcard problems-card">
      <div class="card-head"><h3>问题<span class="card-count">${n}</span></h3>
        <span class="card-hint">流水线读这条反应时报告的问题，和记录里写下的疑点</span></div>
      <div class="dcard-body">
        ${errors.length ? group(`流水线错误 ${errors.length}`, html`<${Problems} errors=${errors} />`) : null}
        ${warnings.length ? group(`流水线警告 ${warnings.length}`, html`<${Problems} warnings=${warnings} />`) : null}
        ${issues.length ? group(`记录中的问题 ${issues.length}`, html`<${Problems} warnings=${issues} />`) : null}
      </div>
    </section>`;
}

// What the record says around the equation: notes, printed results, inferences, footnotes, open
// questions, notes on single compounds, and the passages of the paper it was read from.
function NotesCard({ ctx, rec }) {
  const rows = [];
  const row = (key, title, body) => rows.push(html`<div class="kv-key" key=${`k-${key}`}>${title}</div><div class="kv-value" key=${`v-${key}`}>${body}</div>`);
  if (rec.notes) row('notes', '备注', rec.notes);
  if (list(rec.results).length) {
    row('results', '印出的结果', html`<span class="printed-results">${rec.results.map((t, i) => html`<code key=${i}>${t}</code>`)}</span>`);
  }
  if (list(rec.unresolved).length) {
    const names = namesByKey(rec);
    row('unresolved', '未确定项', html`${rec.unresolved.map((k, i) => html`<${Chip} key=${i} tone="bad">${names[k] || k}<//> `)}`);
  }
  if (list(rec.inferences).length) {
    row('inferred', html`推断 <span class="muted">${rec.inferences.length}</span>`, rec.inferences.map((i, n) => html`
      <div key=${n}><span class="muted">${origin(i.origin) || '通式'}：</span>${name(ACTION, i.action)} ${i.text || i.key}。${i.basis}</div>`));
  }
  if (list(rec.footnotes).length) {
    row('footnotes', '脚注', rec.footnotes.map((f, n) => html`
      <div key=${n}><b class="fn-mark">${f.marker}</b> ${f.text || html`<span class="muted">（模板里没有这个脚注）</span>`}</div>`));
  }
  const compounds = compoundNotes(ctx, rec);
  if (compounds.length) row('compounds', '成分说明', compounds);
  if (list(rec.related).length) {
    row('related', html`相关段落 <span class="muted">${rec.related.length}</span>`, rec.related.map((p, i) => html`<${Passage} key=${i} p=${p} />`));
  }
  if (!rows.length) return null;
  return html`
    <section class="card dcard">
      <div class="card-head"><h3>说明</h3></div>
      <div class="dcard-body"><div class="kv notes-kv">${rows}</div></div>
    </section>`;
}

// Review supplements are self-contained: a ligand definition and its source image live here,
// even when several reactions reuse the same evidence. Original extraction remains inspectable.
function EvidenceCard({ ctx, rec }) {
  const review = rec.review;
  if (!review) return null;
  const evidence = new Map(list(review.evidence).map((e) => [e.id, e]));
  const refs = (item) => list(item.evidence_ids).map((id) => {
    const e = evidence.get(id);
    if (!e) return null;
    const doc = ctx.docs?.[e.doc];
    const local = { ...ctx, doc: e.doc, docId: doc?.doc_id, pages: doc?.pages, editing: false };
    return html`<div class="passage"><${Where} at=${e} /> <q>${e.quote}</q>
      <${PrepPicture} ctx=${local} x=${e} caption=${e.quote} /></div>`;
  });
  return html`<section class="card dcard">
    <div class="card-head"><h3>核查与补全</h3><span class="card-hint">原始条目保留，补全均带证据</span></div>
    <div class="dcard-body">
      ${list(review.findings).map((f) => html`<div class="problem-group">
        <${Chip} tone=${f.status === 'resolved' ? 'ok' : FLAG_TONE[f.code]}>${name(FLAG, f.code)}${f.status === 'resolved' ? '·已解决' : ''}<//>
        ${f.message} <small>${f.field}</small>${refs(f)}</div>`)}
      ${list(review.definitions).map((d) => html`<div class="note-row"><b>${d.label}</b><div>${d.text}${refs(d)}</div></div>`)}
      ${list(review.measurements).map((m) => html`<div class="note-row"><b>${m.kind === 'nmr_integral' ? 'NMR 积分（非产率）' : '测量原值'}</b>
        <div>${m.text}${refs(m)}</div></div>`)}
      ${list(review.changes).length ? html`<details><summary>字段修正及原值 ${review.changes.length}</summary>
        ${review.changes.map((c) => html`<div><code>${c.path}</code>：${JSON.stringify(c.old_value)} → ${JSON.stringify(c.new_value)}
          <p>${c.reason}</p>${refs(c)}</div>`)}</details>` : null}
      ${list(review.patch_results).length ? html`<details><summary>修改执行审计 ${review.patch_results.length}</summary>
        ${review.patch_results.map((e) => html`<div><b>${({applied: '已应用', unchanged: '原值已符合', rejected: '拒绝应用', postcheck_failed: '应用后校验失败'})[e.status] || e.status}</b>
          <code>${e.patch?.path}</code>：${JSON.stringify(e.old_value)} → ${JSON.stringify(e.new_value)}
          <p>${e.reason || e.patch?.reason || ''}</p></div>`)}</details>` : null}
      ${list(review.resolution_checks).length ? html`<details><summary>解决状态核验 ${review.resolution_checks.length}</summary>
        ${review.resolution_checks.map((e) => html`<div><code>${e.field}</code>：${({verified: '字段应用后已核对', evidence_added: '已补充独立定义证据', relocated: '已修正结果归属', model_confirmation: '模型确认原字段，无修改', unverified: '缺少执行记录，已恢复待核对', unapplied: '修改未落地'})[e.state] || e.state}</div>`)}</details>` : null}
      ${list(review.relations).length ? html`<details><summary>跨条目关系 ${review.relations.length}</summary>
        ${review.relations.map((r) => html`<p>${r.relation === 'candidate' ? '待确认候选' : r.relation === 'distinct' ? '独立实验' : '同一实验'}：
          <code>${r.left}</code> / <code>${r.right}</code>。${r.reason} ${r.validation_note || ''}</p>`)}</details>` : null}
      <details><summary>原始提取记录 ${list(review.raw_records).length}</summary>
        <pre>${JSON.stringify(review.raw_records, null, 2)}</pre></details>
    </div></section>`;
}

// ------------------------------------------------------------------- reaction

// The equation card: the reaction's header (kind, flags, results) and its steps.
export function Equation(props) {
  const { data: rec } = props;
  const ctx = context(props);
  const steps = list(rec?.steps);
  const multi = steps.length > 1 || ctx.editing;
  const last = steps.length - 1;
  const flags = props.row?.flags || [];
  return html`
    <div class=${cx('rxn', 'rxn-card', ctx.editing && 'editing')}>
      <div ...${selectable(ctx, [], 'rxn-head')}>
        ${ctx.editing ? html`<span class="head-target" title="反应头：标签、类型、条件套、备注、问题、印出的结果">反应信息</span>` : null}
        ${rec?.kind ? html`<${Chip}>${name(KIND, rec.kind)}<//>` : null}
        ${flags.includes('inferred') ? html`<${Chip} tone="infer">含推断<//>` : null}
        ${flags.includes('unresolved') ? html`<${Chip} tone="bad">有未确定项<//>` : null}
        ${flags.filter((f) => !['inferred', 'unresolved', 'issues', 'warned'].includes(f)).map((f) =>
          html`<${Chip} tone=${FLAG_TONE[f]}>${name(FLAG, f)}<//>`)}
        <div class="yields">
          ${outcomes(rec).map((x) => html`<${Yield} key=${x.path.join('.')} ctx=${ctx} ...${x} />`)}
        </div>
      </div>
      ${steps.length === 0 ? html`<div class="rxn-empty">这条反应还没有步骤</div>` : null}
      ${steps.map((st, i) => html`
        <div class="step" key=${st.step ?? i}>
          ${multi ? html`
            <div ...${selectable(ctx, ['steps', i], 'step-title')}>第 ${st.step ?? i + 1} 步${st.description ? html`<span>${st.description}</span>` : null}</div>` : null}
          <div class="eq">
            <${Side} ctx=${ctx} items=${list(st.reactants)} path=${['steps', i, 'reactants']} />
            <${Arrow} ctx=${ctx}
                      conditions=${[
                        ...list(st.conditions).map((c, j) => ({ c, path: ['steps', i, 'conditions', j] })),
                        ...(i === last ? list(rec.conditions).map((c, j) => ({ c, path: ['conditions', j] })) : []),
                      ]}
                      removed=${i === last ? list(rec.removed_conditions) : []}
                      notGiven=${i === 0 && rec.conditions_given === false} addPath=${ctx.onAdd ? ['steps', i, 'conditions'] : null} />
            <${Side} ctx=${ctx} items=${list(st.products)} path=${['steps', i, 'products']} products />
          </div>
        </div>`)}
      ${ctx.onAdd ? html`<div class="step-add"><${AddButton} ctx=${ctx} path=${['steps']} kind="step" className="wide">步骤<//></div>` : null}
    </div>`;
}

// The whole 反应 tab body except the source card: equation, problems, notes.
// props: {row, data, docs, editing, selected, onSelect}; `data` is what is shown (the working copy
// while editing), `row` the reaction as stored (pipeline_info, flags).
export function Reaction(props) {
  const { row, data } = props;
  if (!data || typeof data !== 'object') return html`<div class="empty">这条反应的数据不是一个对象</div>`;
  const ctx = context(props);
  return html`
    <div class="reaction">
      <section class="card dcard rxn-wrap"><${Equation} ...${props} /></section>
      <${EvidenceCard} ctx=${ctx} rec=${data} />
      <${ProblemsCard} row=${row} data=${data} />
      <${NotesCard} ctx=${ctx} rec=${data} />
    </div>`;
}
