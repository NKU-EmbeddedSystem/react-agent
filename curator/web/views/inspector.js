import { html, useEffect, useRef, useState } from '../lib/preact.js';
import { renderUrl } from '../lib/api.js';
import { toast } from '../lib/bus.js';
import { useDebounced } from '../lib/hooks.js';
import { DOC, KIND, ROLE, SOURCE, YIELD_TYPE, cx, name, origin } from '../lib/format.js';
import { getIn, isPrefix, samePath } from '../lib/paths.js';
import { Chip } from '../components/common.js';
import { drawable } from '../components/pagefigure.js';
import { blank, kindOf, list, pathWords } from './editing.js';

// The form of the part selected in the reaction (header, step, participant, condition, outcome or
// source). Every input writes straight into the working copy (onChange(path, value)); lists are
// rewritten whole (add, remove, move) and the selection follows the item. Boxes are typed in or drawn
// (onDraw(path) → the block figure and the PDF pane take a drag).
//
// props: {working, selected, docs, info: {known, templates}, block, problems, drawing, onChange,
//         onSelect, onDraw, onCancelDraw, onTab}
//   problems: parsed validation messages (editing.parseProblems); those of the selected part show here.
//   drawing: the path a box is being drawn for, or null.
//   reveal: a counter; when it changes, the first field with an error is scrolled into view.

const str = (v) => (v == null ? '' : String(v));
const SEP = { separate: true };   // a change that is its own undo step

// ------------------------------------------------------------------ inputs

function Text({ value, onCommit, empty = null, placeholder, mono, invalid, label, datalist }) {
  return html`
    <input class=${cx('input', mono && 'mono', invalid && 'invalid')} value=${str(value)} placeholder=${placeholder || ''}
           aria-label=${label || placeholder || null} list=${datalist || null} spellcheck="false"
           onInput=${(e) => onCommit(e.currentTarget.value === '' ? empty : e.currentTarget.value)} />`;
}

function Area({ value, onCommit, empty = null, placeholder, label, rows = 2, invalid }) {
  return html`
    <textarea class=${cx('textarea', 'ins-area', invalid && 'invalid')} rows=${rows} value=${str(value)}
              placeholder=${placeholder || ''} aria-label=${label || placeholder || null}
              onInput=${(e) => onCommit(e.currentTarget.value === '' ? empty : e.currentTarget.value)}></textarea>`;
}

// Text whose stored form differs from what is typed (numbers, lists): the typed text stays as it is
// while it does not parse (shown invalid) and comes back from the value when that changes elsewhere.
function Lazy({ value, parse, format, onCommit, className, placeholder, label, invalid, inputmode }) {
  const [text, setText] = useState(format(value));
  const parsed = parse(text);
  useEffect(() => {
    if (JSON.stringify(parse(text)) !== JSON.stringify(value)) setText(format(value));
  }, [JSON.stringify(value)]);
  const bad = parsed === undefined;
  return html`
    <input class=${cx('input', className, (bad || invalid) && 'invalid')} value=${text} placeholder=${placeholder || ''}
           aria-label=${label || placeholder || null} inputmode=${inputmode || null} spellcheck="false"
           title=${bad ? '不是有效的值' : null}
           onInput=${(e) => {
             const t = e.currentTarget.value;
             setText(t);
             const v = parse(t);
             if (v !== undefined) onCommit(v);
           }}
           onBlur=${() => { if (parse(text) === undefined) setText(format(value)); }} />`;
}

const parseNum = (int) => (t) => {
  const s = t.trim();
  if (s === '') return null;
  const n = Number(s);
  if (!Number.isFinite(n) || (int && !Number.isInteger(n))) return undefined;
  return n;
};
const fmtNum = (v) => (typeof v === 'number' ? String(v) : '');

const Num = ({ value, onCommit, int, placeholder, label, invalid }) => html`
  <${Lazy} value=${typeof value === 'number' ? value : null} parse=${parseNum(int)} format=${fmtNum} onCommit=${onCommit}
           className="num" placeholder=${placeholder} label=${label} invalid=${invalid} inputmode=${int ? 'numeric' : 'decimal'} />`;

// "b, c" ↔ ['b', 'c']
const Words = ({ value, onCommit, placeholder, label }) => html`
  <${Lazy} value=${list(value)} parse=${(t) => t.split(/[\s,，、;；]+/).filter(Boolean)} format=${(v) => list(v).join(', ')}
           onCommit=${onCommit} placeholder=${placeholder} label=${label} />`;

function Select({ value, options, onCommit, nullLabel, label, invalid }) {
  const known = options.some(([v]) => v === value);
  return html`
    <select class=${cx('select', invalid && 'invalid')} aria-label=${label || null} value=${value ?? ''}
            onChange=${(e) => onCommit(e.currentTarget.value === '' ? null : e.currentTarget.value)}>
      ${nullLabel != null ? html`<option value="">${nullLabel}</option>` : null}
      ${!known && value != null ? html`<option value=${value}>${value}（不是已知的取值）</option>` : null}
      ${options.map(([v, l]) => html`<option key=${v} value=${v}>${l}</option>`)}
    </select>`;
}

const Check = ({ checked, onCommit, children, title }) => html`
  <label class="check" title=${title || null}>
    <input type="checkbox" checked=${!!checked} onChange=${(e) => onCommit(e.currentTarget.checked)} />${children}
  </label>`;

// A labelled control; `problem` (a parsed validation message) marks it and says what is wrong.
const F = ({ label, wide, problem, hint, children }) => html`
  <label class=${cx('field', 'ins-field', wide && 'wide', problem && `has-${problem.tone}`)}>
    <span class="field-label">${label}</span>
    ${children}
    ${problem ? html`<small class=${cx('field-problem', problem.tone)}>${problem.text}</small>`
      : hint ? html`<small class="field-hint">${hint}</small>` : null}
  </label>`;

const Section = ({ title, aside, children, className }) => html`
  <section class=${cx('ins-section', className)}>
    ${title ? html`<div class="ins-section-title"><span>${title}</span>${aside ? html`<span class="ins-aside">${aside}</span>` : null}</div>` : null}
    ${children}
  </section>`;

const Icon = {
  up: html`<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M6 9.5v-7M2.8 5.5 6 2.3l3.2 3.2" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  down: html`<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M6 2.5v7M2.8 6.5 6 9.7l3.2-3.2" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  frame: html`<svg width="13" height="13" viewBox="0 0 13 13" aria-hidden="true"><path d="M1.5 4V1.5H4M9 1.5h2.5V4M11.5 9v2.5H9M4 11.5H1.5V9" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/><rect x="4.25" y="4.25" width="4.5" height="4.5" rx=".6" fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="1.6 1.2"/></svg>`,
  plus: html`<svg width="11" height="11" viewBox="0 0 11 11" aria-hidden="true"><path d="M5.5 1.5v8M1.5 5.5h8" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  x: html`<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="m2 2 6 6m0-6-6 6" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
};

const Add = ({ onClick, children, title }) => html`
  <button type="button" class="btn small ins-add" onClick=${onClick} title=${title || null}>${Icon.plus}${children}</button>`;

const RemoveRow = ({ onClick, label }) => html`
  <button type="button" class="ins-x" onClick=${onClick} aria-label=${label} title=${label}>${Icon.x}</button>`;

// ------------------------------------------------------------------ composite editors

// Rows of objects (variables, selectivity): one line each, fields side by side.
function Rows({ items, fields, onCommit, make, addLabel, empty }) {
  const rows = list(items);
  const set = (i, key, v) => onCommit(rows.map((r, n) => (n === i ? { ...r, [key]: v } : r)));
  return html`
    <div class="ins-rows">
      ${rows.length === 0 && empty ? html`<div class="ins-none">${empty}</div>` : null}
      ${rows.map((r, i) => html`
        <div class="ins-row" key=${i}>
          ${fields.map(([key, placeholder, sep, datalist]) => html`
            ${sep ? html`<span class="ins-row-sep">${sep}</span>` : null}
            <${Text} value=${r?.[key]} empty="" placeholder=${placeholder} label=${placeholder} datalist=${datalist}
                     onCommit=${(v) => set(i, key, v)} />`)}
          ${r?.origin && r.origin !== 'curator' ? html`<${Chip} tone="origin" title=${`来自：${origin(r.origin) || r.origin}`}>${origin(r.origin) || r.origin}<//>` : null}
          <${RemoveRow} label="删除这一行" onClick=${() => onCommit(rows.filter((_, n) => n !== i), SEP)} />
        </div>`)}
      <${Add} onClick=${() => onCommit([...rows, make()], SEP)}>${addLabel}<//>
    </div>`;
}

// A list of strings (issues, printed results).
function Strings({ items, onCommit, addLabel, placeholder, multiline }) {
  const rows = list(items);
  const set = (i, v) => onCommit(rows.map((r, n) => (n === i ? v : r)));
  return html`
    <div class="ins-rows">
      ${rows.map((r, i) => html`
        <div class="ins-row" key=${i}>
          ${multiline ? html`<${Area} value=${r} empty="" rows=${1} placeholder=${placeholder} onCommit=${(v) => set(i, v)} />`
            : html`<${Text} value=${r} empty="" placeholder=${placeholder} onCommit=${(v) => set(i, v)} />`}
          <${RemoveRow} label="删除这一项" onClick=${() => onCommit(rows.filter((_, n) => n !== i), SEP)} />
        </div>`)}
      <${Add} onClick=${() => onCommit([...rows, ''], SEP)}>${addLabel}<//>
    </div>`;
}

// {doc, page} or null: where the paper states a value outside the block.
function Ref({ value, docs, onCommit, label }) {
  const v = value && typeof value === 'object' ? value : null;
  const names = Object.keys(docs || {});
  const n = v ? docs?.[v.doc]?.page_count : null;
  return html`
    <div class="ins-ref" role="group" aria-label=${label}>
      <select class="select" aria-label=${`${label}：文档`} value=${v?.doc ?? ''}
              onChange=${(e) => {
                const doc = e.currentTarget.value;
                onCommit(doc ? { ...(v || {}), doc, page: v?.page ?? 1 } : null, SEP);
              }}>
        <option value="">（没有）</option>
        ${names.map((d) => html`<option key=${d} value=${d}>${name(DOC, d)}</option>`)}
        ${v && v.doc && !names.includes(v.doc) ? html`<option value=${v.doc}>${v.doc}（没有导入）</option>` : null}
      </select>
      ${v ? html`
        <span class="ins-unit">第</span>
        <${Num} int value=${v.page} label=${`${label}：页码`} onCommit=${(p) => onCommit({ ...v, page: p })} />
        <span class="ins-unit">页${n ? html`<span class="muted">（共 ${n} 页）</span>` : null}</span>` : null}
    </div>`;
}

// Page + bbox of something drawn in the source document, typed or drawn; a preview of what the box holds.
// obj: the object holding page and the box (`bboxKey`); path: where obj is; drawPath: the part 框选 is for.
function Box({ ctx, obj, path, bboxKey = 'bbox', drawPath, onClear, clearLabel = '清除框' }) {
  const page = obj?.page;
  const bbox = obj?.[bboxKey];
  const doc = ctx.doc;
  const d = ctx.docs?.[doc];
  const p = typeof page === 'number' ? d?.pages?.[page - 1] : null;
  const size = p ? [p[0], p[1]] : null;
  const drawingHere = ctx.drawing && samePath(ctx.drawing, drawPath);
  const coords = Array.isArray(bbox) && bbox.length === 4 ? bbox : [null, null, null, null];
  const setCoord = (i, v) => {
    const b = coords.slice();
    b[i] = v;
    ctx.onChange([...path, bboxKey], b.every((x) => x == null) ? null : b);
  };
  const shown = useDebounced(JSON.stringify([page, bbox]), 350);
  const [sp, sb] = JSON.parse(shown);
  const ok = d?.doc_id != null && typeof sp === 'number' && drawable(sb, size);
  const pageProblem = ctx.problemAt([...path, 'page']);
  const boxProblem = ctx.problemAt([...path, bboxKey]);
  return html`
    <div class="ins-box">
      <div class="ins-box-line">
        <label class="ins-page"><span>第</span>
          <${Num} int value=${page} label="页码" invalid=${!!pageProblem} onCommit=${(v) => ctx.onChange([...path, 'page'], v)} />
          <span>页</span></label>
        <span class="muted ins-doc">${name(DOC, doc)}${d?.page_count ? ` · 共 ${d.page_count} 页` : ''}</span>
      </div>
      <div class="ins-coords" role="group" aria-label="框的坐标（pt）">
        ${['x0', 'y0', 'x1', 'y1'].map((k, i) => html`
          <label key=${k}><span>${k}</span>
            <${Num} value=${coords[i]} label=${k} invalid=${!!boxProblem} onCommit=${(v) => setCoord(i, v)} /></label>`)}
      </div>
      ${pageProblem || boxProblem ? html`<small class=${cx('field-problem', (boxProblem || pageProblem).tone)}>${(boxProblem || pageProblem).text}</small>` : null}
      <div class="ins-box-tools">
        ${drawingHere ? html`
          <span class="ins-drawing"><span class="pulse"></span>在来源块的图上或 PDF 里拖出一个框</span>
          <button type="button" class="btn small" onClick=${ctx.onCancelDraw}>取消</button>` : html`
          <button type="button" class="btn small ins-draw" onClick=${() => ctx.onDraw(drawPath)}
                  title="在来源块的图上或 PDF 面板里拖出一个框">${Icon.frame}框选</button>
          ${bbox != null || page != null ? html`<button type="button" class="btn small quiet" onClick=${onClear}>${clearLabel}</button>` : null}`}
      </div>
      ${ok ? html`<div class="ins-preview"><img src=${renderUrl(d.doc_id, sp, sb, { dpi: 110, pad: 2 })} alt="框里的内容" /></div>` : null}
    </div>`;
}

// ------------------------------------------------------------------ parts of a form

function Problems({ items }) {
  if (!items.length) return null;
  return html`
    <ul class="ins-problems">
      ${items.map((p, i) => html`
        <li key=${i} class=${cx(p.tone, p.old && 'old')}>${p.where && p.where !== '整条记录' ? html`<b>${p.where}</b>` : null}${p.text}</li>`)}
    </ul>`;
}

// Where an item sits and what to do with it: move within its list, delete (one undo step each).
function ItemTools({ ctx, path, noun, children }) {
  const listPath = path.slice(0, -1);
  const i = path[path.length - 1];
  const items = list(getIn(ctx.working, listPath));
  const move = (to) => {
    const next = items.slice();
    const [x] = next.splice(i, 1);
    next.splice(to, 0, x);
    ctx.onChange(listPath, next, SEP);
    ctx.onSelect([...listPath, to]);
  };
  const remove = () => {
    ctx.onChange(listPath, items.filter((_, n) => n !== i), SEP);
    ctx.onSelect(parentOf(path));
    toast(`已删除${noun}，可以撤销（Ctrl+Z）`);
  };
  return html`
    <div class="ins-tools">
      <button type="button" class="btn small quiet" disabled=${i <= 0} onClick=${() => move(i - 1)} title="上移">${Icon.up}上移</button>
      <button type="button" class="btn small quiet" disabled=${i >= items.length - 1} onClick=${() => move(i + 1)} title="下移">${Icon.down}下移</button>
      ${children}
      <button type="button" class="btn small danger ins-delete" onClick=${remove}>删除</button>
    </div>`;
}

function parentOf(path) {
  const k = kindOf(path);
  if (k === 'outcome' && path[0] === 'steps') return path.slice(0, 4);
  if ((k === 'participant' || k === 'condition') && path[0] === 'steps') return path.slice(0, 2);
  return [];
}

function Head({ ctx, kind, title, extra, path, tools }) {
  return html`
    <div class="ins-head">
      <div class="ins-kind">${kind}${path?.length ? html`<span class="ins-crumb">${pathWords(ctx.working, path)}</span>` : null}</div>
      <div class="ins-title">${title}${extra}</div>
      ${tools}
    </div>`;
}

// Buttons that add to a step: reactant, product, condition.
function StepAdds({ ctx, step }) {
  const add = (side, kind) => {
    const listPath = ['steps', step, side];
    const items = list(getIn(ctx.working, listPath));
    ctx.onChange(listPath, [...items, blank(ctx.info, ctx.working, kind, listPath)], SEP);
    ctx.onSelect([...listPath, items.length]);
  };
  return html`
    <div class="ins-adds">
      <span class="ins-adds-label">${list(ctx.working?.steps).length > 1 ? `第 ${step + 1} 步` : '本步骤'}</span>
      <${Add} onClick=${() => add('reactants', 'participant')}>反应物<//>
      <${Add} onClick=${() => add('products', 'participant')}>产物<//>
      <${Add} onClick=${() => add('conditions', 'condition')}>条件<//>
    </div>`;
}

const options = (values, table) => values.map((v) => [v, table[v] ? `${table[v]}` : v]);

// ------------------------------------------------------------------ the forms

function HeaderForm({ ctx }) {
  const w = ctx.working;
  const set = (key) => (v, o) => ctx.onChange([key], v, o);
  const steps = list(w.steps);
  const others = list(w.other_outcomes);
  const addStep = () => {
    ctx.onChange(['steps'], [...steps, blank(ctx.info, w, 'step', ['steps'])], SEP);
    ctx.onSelect(['steps', steps.length]);
  };
  const addOther = () => {
    ctx.onChange(['other_outcomes'], [...others, blank(ctx.info, w, 'outcome', ['other_outcomes'])], SEP);
    ctx.onSelect(['other_outcomes', others.length]);
  };
  const v = w.variant && typeof w.variant === 'object' ? w.variant : null;
  return html`
    <${Head} ctx=${ctx} kind="反应信息" title=${w.label || html`<span class="muted">（无标签）</span>`} />
    <${Problems} items=${ctx.mine} />
    <${Section}>
      <div class="ins-grid">
        <${F} label="标签" problem=${ctx.problemAt(['label'])}><${Text} value=${w.label} onCommit=${set('label')} placeholder="如 3a、entry 5" /><//>
        <${F} label="类型" problem=${ctx.problemAt(['kind'])}>
          <${Select} value=${w.kind} options=${options(ctx.info.known.kind, KIND)} nullLabel="（未设置）" onCommit=${(x) => set('kind')(x, SEP)} /><//>
      </div>
      <div class="ins-checks">
        <${Check} checked=${w.conditions_given !== false} onCommit=${(x) => set('conditions_given')(x, SEP)}
                  title="取消勾选：文中没有给出这条反应的条件">文中给出了这套条件<//>
      </div>
    <//>
    <${Section} title="条件套" aside=${v ? html`<button type="button" class="btn small quiet" onClick=${() => set('variant')(null, SEP)}>去掉</button>` : null}>
      ${v ? html`
        <div class="ins-grid">
          <${F} label="名称"><${Text} value=${v.title} onCommit=${(x) => ctx.onChange(['variant', 'title'], x)} placeholder="印出的写法，如 [in situ]" /><//>
          <${F} label="键"><${Text} mono value=${v.key} onCommit=${(x) => ctx.onChange(['variant', 'key'], x)} /><//>
          <${F} label="说明" wide><${Area} value=${v.notes} onCommit=${(x) => ctx.onChange(['variant', 'notes'], x)} /><//>
        </div>` : html`
        <div class="ins-none">这条反应不属于某个条件套
          <button type="button" class="btn small" onClick=${() => set('variant')({ key: 'curator', title: '', notes: null }, SEP)}>设置条件套</button></div>`}
    <//>
    <${Section} title="备注">
      <${Area} value=${w.notes} empty="" rows=${3} label="备注" onCommit=${set('notes')} placeholder="关于这条反应的说明" />
    <//>
    <${Section} title=${html`问题 <span class="muted">${list(w.issues).length || ''}</span>`}>
      <${Strings} items=${w.issues} multiline addLabel="添加问题" placeholder="记录里的疑点" onCommit=${set('issues')} />
    <//>
    <${Section} title=${html`印出的结果 <span class="muted">${list(w.results).length || ''}</span>`}>
      <${Strings} items=${w.results} addLabel="添加" placeholder="原文印出的样子，如 12/8/50" onCommit=${set('results')} />
    <//>
    <${Section} title="步骤">
      <div class="ins-links">
        ${steps.map((st, i) => html`
          <button type="button" key=${i} class="ins-link" onClick=${() => ctx.onSelect(['steps', i])}>
            第 ${st?.step ?? i + 1} 步<span class="muted">${list(st?.reactants).length} 反应物 · ${list(st?.products).length} 产物 · ${list(st?.conditions).length} 条件</span></button>`)}
      </div>
      <${Add} onClick=${addStep}>添加步骤<//>
    <//>
    <${Section} title=${html`其他结果 <span class="muted">${others.length || ''}</span>`}>
      <div class="ins-hint">测在反应没有生成的化合物上的值（如回收的原料、转化率）。</div>
      <div class="ins-links">
        ${others.map((o, i) => html`
          <button type="button" key=${i} class="ins-link" onClick=${() => ctx.onSelect(['other_outcomes', i])}>
            ${o?.yield?.text || o?.yield?.qualifier || '—'}<span class="muted">${o?.yield?.type ? name(YIELD_TYPE, o.yield.type) : ''}</span></button>`)}
      </div>
      <${Add} onClick=${addOther}>添加其他结果<//>
    <//>
    <div class="ins-foot">推断、脚注、相关段落等其余字段在
      <button type="button" class="link" onClick=${() => ctx.onTab?.('json')}>原始 JSON</button> 里修改。</div>`;
}

function StepForm({ ctx, path }) {
  const st = getIn(ctx.working, path) || {};
  const i = path[1];
  const parts = (side, noun) => list(st[side]).map((x, j) => html`
    <button type="button" key=${`${side}${j}`} class="ins-chip" onClick=${() => ctx.onSelect([...path, side, j])}
            title=${noun}>${side === 'conditions' ? x?.text || x?.key : x?.label || x?.text || x?.key}</button>`);
  return html`
    <${Head} ctx=${ctx} path=${path} kind="步骤" title=${`第 ${st.step ?? i + 1} 步`}
             tools=${html`<${ItemTools} ctx=${ctx} path=${path} noun=${`第 ${i + 1} 步`} />`} />
    <${Problems} items=${ctx.mine} />
    <${Section}>
      <div class="ins-grid">
        <${F} label="步骤号" problem=${ctx.problemAt([...path, 'step'])}>
          <${Num} int value=${st.step} onCommit=${(v) => ctx.onChange([...path, 'step'], v)} /><//>
        <${F} label="描述" wide><${Area} value=${st.description} empty="" onCommit=${(v) => ctx.onChange([...path, 'description'], v)} placeholder="这一步做了什么" /><//>
      </div>
    <//>
    <${Section} title="这一步的成分">
      <div class="ins-parts"><span class="ins-parts-label">反应物</span>${parts('reactants', '反应物')}</div>
      <div class="ins-parts"><span class="ins-parts-label">产物</span>${parts('products', '产物')}</div>
      <div class="ins-parts"><span class="ins-parts-label">条件</span>${parts('conditions', '条件')}</div>
      <${StepAdds} ctx=${ctx} step=${i} />
    <//>`;
}

function ParticipantForm({ ctx, path }) {
  const p = getIn(ctx.working, path) || {};
  const side = path[2];
  const at = (k) => [...path, k];
  const set = (k) => (v, o) => ctx.onChange(at(k), v, o);
  const outcomes = list(p.outcomes);
  // To the other side of the arrow: products carry their outcomes, reactants none.
  const moveSide = () => {
    const to = side === 'reactants' ? 'products' : 'reactants';
    const stepPath = path.slice(0, 2);
    const st = getIn(ctx.working, stepPath);
    const item = { ...p };
    if (to === 'products') {
      item.outcomes = list(item.outcomes);
      if (item.role === 'reactant') item.role = 'product';
    } else {
      if (!outcomes.length) delete item.outcomes;
      if (item.role === 'product' || item.role === 'byproduct') item.role = 'reactant';
    }
    const next = { ...st, [side]: list(st[side]).filter((_, n) => n !== path[3]), [to]: [...list(st[to]), item] };
    ctx.onChange(stepPath, next, SEP);
    ctx.onSelect([...stepPath, to, next[to].length - 1]);
  };
  const addOutcome = () => {
    ctx.onChange(at('outcomes'), [...outcomes, blank(ctx.info, ctx.working, 'outcome', at('outcomes'))], SEP);
    ctx.onSelect([...at('outcomes'), outcomes.length]);
  };
  const noun = side === 'products' ? '产物' : '反应物';
  return html`
    <${Head} ctx=${ctx} path=${path} kind=${noun} title=${p.label || p.text || html`<span class="muted">（未命名）</span>`}
             extra=${p.role && p.role !== (side === 'products' ? 'product' : 'reactant') ? html` <${Chip}>${name(ROLE, p.role)}<//>` : null}
             tools=${html`<${ItemTools} ctx=${ctx} path=${path} noun=${`${noun} ${p.label || p.key || ''}`}>
               <button type="button" class="btn small quiet" onClick=${moveSide} title="移到箭头的另一侧">移到${side === 'reactants' ? '产物' : '反应物'}一侧</button>
             <//>`} />
    <${Problems} items=${ctx.mine} />
    <${Section}>
      <div class="ins-grid">
        <${F} label="标签" problem=${ctx.problemAt(at('label'))}><${Text} value=${p.label} onCommit=${set('label')} placeholder="编号，如 1a" /><//>
        <${F} label="角色" problem=${ctx.problemAt(at('role'))}>
          <${Select} value=${p.role} options=${options(ctx.info.known.participant_role, ROLE)} onCommit=${(v) => set('role')(v, SEP)} /><//>
        <${F} label="名称" wide problem=${ctx.problemAt(at('text'))}><${Text} value=${p.text} onCommit=${set('text')} placeholder="文中的名称或化学式" /><//>
        <${F} label="用量" wide problem=${ctx.problemAt(at('amount'))}><${Text} value=${p.amount} onCommit=${set('amount')} placeholder="如 0.2 mmol, 1.0 equiv" /><//>
        <${F} label="结构来源" problem=${ctx.problemAt(at('source'))}>
          <${Select} value=${p.source} options=${options(ctx.info.known.participant_source, SOURCE)} nullLabel="（未设置）" onCommit=${(v) => set('source')(v, SEP)} /><//>
        <${F} label="键" problem=${ctx.problemAt(at('key'))} hint="本反应里唯一"><${Text} mono value=${p.key} empty="" onCommit=${set('key')} /><//>
      </div>
      <div class="ins-checks">
        <${Check} checked=${p.unknown} onCommit=${(v) => set('unknown')(v, SEP)} title="文中没有以任何形式给出，留待推断">未知（待推断）<//>
        <${Check} checked=${p.generic} onCommit=${(v) => set('generic')(v, SEP)} title="通式中的位置（R、X …），不是具体化合物">通式<//>
      </div>
    <//>
    <${Section} title="结构图的位置">
      <${Box} ctx=${ctx} obj=${p} path=${path} drawPath=${path}
              onClear=${() => ctx.onChange(path, { ...p, page: null, bbox: null }, SEP)} />
    <//>
    <${Section} title="出处" aside=${html`<span class="muted">文中别处给出它的地方</span>`}>
      <${Ref} value=${p.stated_at} docs=${ctx.docs} label="出处" onCommit=${set('stated_at')} />
    <//>
    <${Section} title=${html`变量 <span class="muted">${list(p.variables).length || ''}</span>`}>
      <${Rows} items=${p.variables} fields=${[['name', '名称，如 R'], ['value', '取值', '=']]} empty="没有变量"
               make=${() => ({ name: '', value: '', origin: 'curator' })} addLabel="添加变量" onCommit=${set('variables')} />
    <//>
    ${side === 'products' ? html`
      <${Section} title=${html`结果 <span class="muted">${outcomes.length || ''}</span>`}>
        <div class="ins-links">
          ${outcomes.map((o, k) => html`
            <button type="button" key=${k} class="ins-link" onClick=${() => ctx.onSelect([...at('outcomes'), k])}>
              ${o?.yield?.text || o?.yield?.qualifier || '—'}<span class="muted">${o?.yield?.type ? name(YIELD_TYPE, o.yield.type) : ''}</span></button>`)}
        </div>
        <${Add} onClick=${addOutcome}>添加结果<//>
      <//>` : null}
    ${path[0] === 'steps' ? html`<${Section} className="ins-section-adds"><${StepAdds} ctx=${ctx} step=${path[1]} /><//>` : null}`;
}

function ConditionForm({ ctx, path }) {
  const c = getIn(ctx.working, path) || {};
  const at = (k) => [...path, k];
  const set = (k) => (v, o) => ctx.onChange(at(k), v, o);
  const s = c.structure && typeof c.structure === 'object' ? c.structure : null;
  return html`
    <${Head} ctx=${ctx} path=${path} kind=${path[0] === 'conditions' ? '条件（所有步骤）' : '条件'}
             title=${c.text || html`<span class="muted">（空）</span>`}
             extra=${c.role ? html` <${Chip}>${name(ROLE, c.role)}<//>` : null}
             tools=${html`<${ItemTools} ctx=${ctx} path=${path} noun=${`条件 ${c.text || c.key || ''}`} />`} />
    <${Problems} items=${ctx.mine} />
    <${Section}>
      <div class="ins-grid">
        <${F} label="角色" problem=${ctx.problemAt(at('role'))}>
          <${Select} value=${c.role} options=${options(ctx.info.known.condition_role, ROLE)} onCommit=${(v) => set('role')(v, SEP)} /><//>
        <${F} label="键" problem=${ctx.problemAt(at('key'))}><${Text} mono value=${c.key} empty="" onCommit=${set('key')} /><//>
        <${F} label="文字" wide problem=${ctx.problemAt(at('text'))}><${Text} value=${c.text} empty="" onCommit=${set('text')} placeholder="如 FeCl2、THF、60 °C" /><//>
        <${F} label="用量" wide problem=${ctx.problemAt(at('amount'))}><${Text} value=${c.amount} onCommit=${set('amount')} placeholder="如 5 mol %" /><//>
      </div>
      <div class="ins-checks">
        <${Check} checked=${c.value_missing} onCommit=${(v) => set('value_missing')(v, SEP)} title="这条反应应有这个条件，但条目里没有给出它的值">本条未给出<//>
      </div>
    <//>
    <${Section} title="结构图" aside=${s ? html`<button type="button" class="btn small quiet" onClick=${() => set('structure')(null, SEP)}>去掉结构</button>` : null}>
      ${s ? html`
        <div class="ins-grid">
          <${F} label="标签"><${Text} value=${s.label} onCommit=${(v) => ctx.onChange([...at('structure'), 'label'], v)} placeholder="如 C1" /><//>
          <${F} label="名称"><${Text} value=${s.text} onCommit=${(v) => ctx.onChange([...at('structure'), 'text'], v)} /><//>
        </div>
        <${Box} ctx=${ctx} obj=${s} path=${at('structure')} drawPath=${path} clearLabel="清除框"
                onClear=${() => ctx.onChange(at('structure'), { ...s, page: null, bbox: null }, SEP)} />` : html`
        <div class="ins-none">没有结构图
          ${ctx.drawing && samePath(ctx.drawing, path) ? html`
            <span class="ins-drawing"><span class="pulse"></span>拖出一个框</span>
            <button type="button" class="btn small" onClick=${ctx.onCancelDraw}>取消</button>`
            : html`<button type="button" class="btn small ins-draw" onClick=${() => ctx.onDraw(path)}>${Icon.frame}框选结构</button>`}
        </div>`}
    <//>
    <${Section} title="出处" aside=${html`<span class="muted">文中别处给出它的地方</span>`}>
      <${Ref} value=${c.stated_at} docs=${ctx.docs} label="出处" onCommit=${set('stated_at')} />
    <//>
    ${path[0] === 'steps' ? html`<${Section} className="ins-section-adds"><${StepAdds} ctx=${ctx} step=${path[1]} /><//>` : null}`;
}

const SELECTIVITY = ['dr', 'ee', 'er', 'rr', 'E/Z', 'Z/E', 'b/l', 'l/b'];

function OutcomeForm({ ctx, path }) {
  const o = getIn(ctx.working, path) || {};
  const y = o.yield && typeof o.yield === 'object' ? o.yield : {};
  const at = (...k) => [...path, ...k];
  const product = path[0] === 'steps' ? getIn(ctx.working, path.slice(0, 4)) : null;
  const others = path[0] === 'other_outcomes';
  const parts = list(ctx.working?.steps).flatMap((st) => [...list(st?.reactants), ...list(st?.products)])
    .filter((p, i, all) => p?.key && all.findIndex((q) => q?.key === p.key) === i);
  const of = product ? `${product.label || product.text || product.key}` : null;
  const addHere = () => {
    const listPath = path.slice(0, -1);
    const items = list(getIn(ctx.working, listPath));
    ctx.onChange(listPath, [...items, blank(ctx.info, ctx.working, 'outcome', listPath)], SEP);
    ctx.onSelect([...listPath, items.length]);
  };
  return html`
    <${Head} ctx=${ctx} path=${path} kind=${others ? '其他结果' : `结果 · ${of}`}
             title=${y.text || y.qualifier || html`<span class="muted">（空）</span>`}
             extra=${y.type ? html` <${Chip}>${name(YIELD_TYPE, y.type)}<//>` : null}
             tools=${html`<${ItemTools} ctx=${ctx} path=${path} noun="这个结果">
               <button type="button" class="btn small quiet" onClick=${addHere}>${Icon.plus}再加一个</button><//>`} />
    <${Problems} items=${ctx.mine} />
    <${Section} title="产率">
      <div class="ins-grid">
        <${F} label="印出的文字" problem=${ctx.problemAt(at('yield', 'text'))}>
          <${Text} value=${y.text} onCommit=${(v) => ctx.onChange(at('yield', 'text'), v)} placeholder="如 81、>98、trace" /><//>
        <${F} label="数值（%）" problem=${ctx.problemAt(at('yield', 'value'))}>
          <${Num} value=${y.value} onCommit=${(v) => ctx.onChange(at('yield', 'value'), v)} placeholder="81" /><//>
        <${F} label="限定" problem=${ctx.problemAt(at('yield', 'qualifier'))}>
          <${Text} value=${y.qualifier} onCommit=${(v) => ctx.onChange(at('yield', 'qualifier'), v)} placeholder="如 >、trace" /><//>
        <${F} label="类型" problem=${ctx.problemAt(at('yield', 'type'))}>
          <${Select} value=${y.type} options=${options(ctx.info.known.yield_type, YIELD_TYPE)} nullLabel="（未设置）"
                     onCommit=${(v) => ctx.onChange(at('yield'), { ...y, type: v, type_origin: 'curator' }, SEP)} /><//>
      </div>
    <//>
    <${Section} title=${html`选择性 <span class="muted">${list(o.selectivity).length || ''}</span>`}>
      <datalist id="ins-selectivity">${SELECTIVITY.map((s) => html`<option value=${s} />`)}</datalist>
      <${Rows} items=${o.selectivity} fields=${[['type', '类型，如 dr', null, 'ins-selectivity'], ['text', '数值，如 4.4:1']]} empty="没有选择性"
               make=${() => ({ type: '', text: '' })} addLabel="添加选择性" onCommit=${(v, opt) => ctx.onChange(at('selectivity'), v, opt)} />
    <//>
    <${Section}>
      <div class="ins-grid">
        <${F} label="脚注标记" hint="用逗号分开，如 b, c"><${Words} value=${o.footnote_markers} label="脚注标记"
              onCommit=${(v) => ctx.onChange(at('footnote_markers'), v)} /><//>
        ${others ? html`
          <${F} label="测在哪个化合物上" problem=${ctx.problemAt(at('participant_key'))}>
            <${Select} value=${o.participant_key ?? null} nullLabel="（不指定）" onCommit=${(v) => ctx.onChange(at('participant_key'), v, SEP)}
                       options=${parts.map((p) => [p.key, p.label || p.text || p.key])} /><//>` : null}
        <${F} label="备注" wide><${Area} value=${o.notes} onCommit=${(v) => ctx.onChange(at('notes'), v)} /><//>
      </div>
    <//>
    <${Section} title="出处" aside=${html`<span class="muted">只在别处给出时填写</span>`}>
      <${Ref} value=${o.stated_at} docs=${ctx.docs} label="出处" onCommit=${(v, opt) => ctx.onChange(at('stated_at'), v, opt)} />
    <//>`;
}

function SourceForm({ ctx }) {
  const src = ctx.working?.source || {};
  const set = (k) => (v, o) => ctx.onChange(['source', k], v, o);
  const entries = list(ctx.block?.view?.entries);
  const entry = entries.find((e) => e.eid === src.entry_id);
  const sameBox = entry && entry.page === src.page && JSON.stringify(entry.bbox) === JSON.stringify(src.entry_bbox);
  const file = ctx.docs?.[src.doc]?.filename;
  return html`
    <${Head} ctx=${ctx} kind="来源" title=${[src.figure, src.entry_id].filter(Boolean).join(' · ') || html`<span class="muted">（未指定）</span>`} />
    <${Problems} items=${ctx.mine} />
    <${Section}>
      <div class="ins-grid">
        <${F} label="文档" wide hint="所有框都在这份文档上；要换文档请在原始 JSON 里改 source.doc">
          <div class="ins-static">${name(DOC, src.doc) || src.doc || '—'}${file ? html` <span class="muted" title=${file}>${file}</span>` : null}</div><//>
        <${F} label="图表" problem=${ctx.problemAt(['source', 'figure'])}><${Text} value=${src.figure} onCommit=${set('figure')} placeholder="如 Table 1" /><//>
        <${F} label="条目" problem=${ctx.problemAt(['source', 'entry_id'])}>
          ${entries.length ? html`
            <${Select} value=${src.entry_id ?? null} nullLabel="（不指定）" onCommit=${(v) => set('entry_id')(v, SEP)}
                       options=${entries.map((e) => [e.eid, `${e.eid}${e.label ? ` · ${e.label}` : ''}`])} />`
            : html`<${Text} mono value=${src.entry_id} onCommit=${set('entry_id')} placeholder="如 e001" />`}<//>
      </div>
      ${entry && isBoxLike(entry.bbox) && !sameBox ? html`
        <div class="ins-suggest">条目 ${entry.eid} 在第 ${entry.page} 页有自己的框
          <button type="button" class="btn small" onClick=${() => ctx.onChange(['source'], { ...src, page: entry.page, entry_bbox: entry.bbox }, SEP)}>用这个框</button></div>` : null}
    <//>
    <${Section} title="条目框">
      <${Box} ctx=${ctx} obj=${src} path=${['source']} bboxKey="entry_bbox" drawPath=${['source']} clearLabel="清除框"
              onClear=${() => ctx.onChange(['source', 'entry_bbox'], null, SEP)} />
    <//>`;
}

const isBoxLike = (b) => Array.isArray(b) && b.length === 4;

// The fields each form shows a problem under (paths below the selected part); the problems of anything
// else go in the list at the top of the form.
const FIELDS = {
  header: [['label'], ['kind']],
  step: [['step']],
  participant: [['label'], ['role'], ['text'], ['amount'], ['source'], ['key'], ['page'], ['bbox']],
  condition: [['role'], ['key'], ['text'], ['amount'], ['structure', 'page'], ['structure', 'bbox']],
  outcome: [['yield', 'text'], ['yield', 'value'], ['yield', 'qualifier'], ['yield', 'type'], ['participant_key']],
  source: [['figure'], ['entry_id'], ['page'], ['entry_bbox']],
};

// ------------------------------------------------------------------ the inspector

export function Inspector({ working, selected, docs, info, block, problems = [], drawing, onChange, onSelect, onDraw,
  onCancelDraw, onTab, reveal }) {
  const root = useRef(null);
  useEffect(() => {
    if (!reveal || !root.current) return;
    const el = root.current.querySelector('.input.invalid, .select.invalid, .textarea.invalid')
      || root.current.querySelector('.ins-problems');
    el?.scrollIntoView({ block: 'center' });
  }, [reveal]);
  if (!working || typeof working !== 'object') {
    return html`<div class="inspector"><div class="ins-empty">记录不是一个对象，请在原始 JSON 里修改</div></div>`;
  }
  const path = selected && getIn(working, selected) !== undefined ? selected : selected?.length === 0 ? [] : null;
  const kind = path ? kindOf(path) : null;
  const doc = working.source?.doc;
  const mine = problems.filter((p) => p.target && path && samePath(p.target, path));
  const atField = (p) => p.field && (FIELDS[kind] || []).some((f) => isPrefix([...path, ...f], p.field));
  const ctx = {
    working, docs, doc, info, block, drawing, onChange, onSelect, onDraw, onCancelDraw, onTab,
    mine: mine.filter((p) => !atField(p)),
    // The first problem about a field (or something inside it).
    problemAt: (field) => mine.find((p) => p.field && isPrefix(field, p.field)) || null,
  };
  let body;
  if (kind === 'header') body = html`<${HeaderForm} ctx=${ctx} />`;
  else if (kind === 'step') body = html`<${StepForm} ctx=${ctx} path=${path} />`;
  else if (kind === 'participant') body = html`<${ParticipantForm} ctx=${ctx} path=${path} />`;
  else if (kind === 'condition') body = html`<${ConditionForm} ctx=${ctx} path=${path} />`;
  else if (kind === 'outcome') body = html`<${OutcomeForm} ctx=${ctx} path=${path} />`;
  else if (kind === 'source') body = html`<${SourceForm} ctx=${ctx} />`;
  else {
    body = html`
      <div class="ins-empty">
        <p>点击反应式里的任一部分（标签行、步骤、化合物、条件、产率），或来源块图里本反应的框，在这里修改它。</p>
        <p><button type="button" class="btn small" onClick=${() => onSelect([])}>编辑反应信息</button></p>
      </div>`;
  }
  // Remounting per selection resets the inputs that keep typed text (numbers, lists).
  return html`<div class="inspector" key=${JSON.stringify(path)} ref=${root}>${body}</div>`;
}
