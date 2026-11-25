// The papers: a table of every paper with its review progress, and one paper (#/papers/<pid>) with its
// bibliographic fields (editable, guarded by base_rev), its documents, its blocks (each a link to the
// filtered reaction list), what the pipeline said about it, its imports and the history of its fields.
import { html, useEffect, useState } from '../lib/preact.js';
import { getPaper, getPaperHistory, listPapers, pdfUrl, updatePaper } from '../lib/api.js';
import { useLoad, useOn } from '../lib/hooks.js';
import { emit } from '../lib/bus.js';
import { guard, href, navigate } from '../lib/router.js';
import { DOC, IMPORT_COUNT, IMPORT_OUTCOME, KIND, LAYOUT, REV_ACTION, brief, cx, describePath, name, stamp } from '../lib/format.js';
import { Chip, Empty, Field, LoadState, Where, WhereScope } from '../components/common.js';

// ------------------------------------------------------------------ shared with the list

// The papers, fetched once for the names in the list (forgetPapers after an edit).
let papersCache = null;
export function loadPapers() {
  if (!papersCache) papersCache = listPapers().catch((e) => { papersCache = null; throw e; });
  return papersCache;
}
export const forgetPapers = () => { papersCache = null; };

// How chemists name a paper in passing: first author's surname and year ("Zhang 2024").
export function paperShort(p) {
  if (!p) return '';
  const first = String(p.authors || '').split(/,|;|，|、|\band\b/)[0].replace(/\bet al\.?/i, '').trim();
  const surname = first ? first.split(/\s+/).pop() : '';
  const title = p.title ? (p.title.length > 18 ? `${p.title.slice(0, 17)}…` : p.title) : '';
  return [surname || title, p.year].filter(Boolean).join(' ');
}

const doiUrl = (doi) => `https://doi.org/${encodeURI(doi)}`;
const stop = (e) => e.stopPropagation();

export function DoiLink({ doi }) {
  if (!doi) return null;
  return html`<a class="doi" href=${doiUrl(doi)} target="_blank" rel="noopener noreferrer" onClick=${stop}
                 title="在新标签页打开出版社页面">doi:${doi}</a>`;
}

// The review state of a set of reactions as one thin bar plus its numbers.
const REVIEW_PARTS = [['reviewed', '已审核', 'ok'], ['problem', '有问题', 'bad'], ['excluded', '排除', 'muted'],
  ['unreviewed', '未审核', 'none']];

export function ReviewBar({ counts, link }) {
  const total = counts?.reactions || 0;
  const done = (counts?.reviewed || 0) + (counts?.problem || 0) + (counts?.excluded || 0);
  return html`
    <div class="rbar">
      <div class="rbar-track" role="img" aria-label=${`已处理 ${done} / ${total}`}>
        ${total ? REVIEW_PARTS.slice(0, 3).map(([k, , tone]) => counts[k]
          ? html`<i key=${k} class=${`rbar-seg ${tone}`} style=${`width:${(100 * counts[k]) / total}%`}></i>` : null) : null}
      </div>
      <div class="rbar-legend">
        ${REVIEW_PARTS.map(([k, label, tone]) => {
          const n = counts?.[k] || 0;
          const text = html`<i class=${`rbar-key ${tone}`}></i>${label} <b>${n}</b>`;
          return link && n ? html`<a key=${k} class="rbar-item" href=${link(k)} onClick=${stop}>${text}</a>`
            : html`<span key=${k} class=${cx('rbar-item', !n && 'zero')}>${text}</span>`;
        })}
      </div>
    </div>`;
}

const listLink = (query) => href('reactions', null, query);

// ------------------------------------------------------------------ the view

export function Papers({ route }) {
  return route.id != null ? html`<${PaperDetail} key=${route.id} pid=${String(route.id)} />` : html`<${PaperTable} />`;
}

function PaperTable() {
  const [changes, setChanges] = useState(0);
  useOn('reaction:changed', () => setChanges((n) => n + 1));
  const state = useLoad(listPapers, [], { refresh: changes });
  if (!state.data) return html`<div class="pg"><${LoadState} state=${state} what="文献列表" /></div>`;
  const papers = state.data;
  const sum = (k) => papers.reduce((n, p) => n + (p.counts?.[k] || 0), 0);
  return html`
    <div class="pg">
      <header class="pg-head">
        <h1>文献<span class="count">${papers.length}</span></h1>
        <p class="pg-lead">共 ${sum('reactions')} 条反应，已审核 ${sum('reviewed')} 条，有问题 ${sum('problem')} 条。</p>
      </header>
      ${papers.length === 0 ? html`<${Empty}>还没有导入文献（运行 <code>python -m curator import</code>）。<//>` : html`
        <table class="list pt">
          <thead>
            <tr><th class="pt-id">#</th><th>文献</th><th class="pt-docs">文档</th><th class="pt-n">反应</th>
                <th class="pt-review">审核</th></tr>
          </thead>
          <tbody>
            ${papers.map((p) => html`<${PaperRow} key=${p.paper_id} p=${p} />`)}
          </tbody>
        </table>`}
    </div>`;
}

function PaperRow({ p }) {
  const c = p.counts || {};
  const extra = [['edited', '已修改', 'accent', { edited: '1' }], ['deleted', '已删除', 'muted', { deleted: '1' }],
    ['old', '旧版本', 'muted', { latest: '0' }]].filter(([k]) => c[k]);
  return html`
    <tr onClick=${(e) => { if (!e.target.closest('a')) navigate('papers', p.paper_id); }}>
      <td class="num">${p.paper_id}</td>
      <td>
        <a class="paper-title" href=${href('papers', p.paper_id)}>${p.title || '（没有标题）'}</a>
        ${p.authors ? html`<div class="cell-detail">${p.authors}</div>` : null}
        <div class="cell-detail pt-meta">
          ${[p.journal, p.year].filter(Boolean).join(' ')}
          <${DoiLink} doi=${p.doi} />
          ${p.meta_origin === 'edited' ? html`<${Chip} tone="accent" title="题录改过；重新导入不会覆盖">题录已修改<//>` : null}
          ${p.note ? html`<span class="pt-note" title=${p.note}>备注：${brief(p.note, 40)}</span>` : null}
        </div>
      </td>
      <td class="pt-docs">
        ${(p.documents || []).map((d) => html`<div key=${d.doc}><span class="muted">${name(DOC, d.doc)}</span> ${d.page_count} 页</div>`)}
      </td>
      <td class="pt-n"><a href=${listLink({ paper: p.paper_id })} title="查看这篇文献的反应">${c.reactions || 0}</a></td>
      <td class="pt-review">
        <${ReviewBar} counts=${c} link=${(k) => listLink({ paper: p.paper_id, status: k })} />
        ${extra.length ? html`
          <div class="pt-extra">
            ${extra.map(([k, label, tone, q]) => html`
              <a key=${k} href=${listLink({ paper: p.paper_id, ...q })} onClick=${stop}><${Chip} tone=${tone}>${label} ${c[k]}<//></a>`)}
          </div>` : null}
      </td>
    </tr>`;
}

// ------------------------------------------------------------------ one paper

function PaperDetail({ pid }) {
  const [changes, setChanges] = useState(0);
  const bump = () => setChanges((n) => n + 1);
  useOn('reaction:changed', bump);
  const paper = useLoad(() => getPaper(pid), [pid], { refresh: changes });
  // After the paper: a paper that does not exist is one failed request, not two.
  const history = useLoad(() => (paper.data ? getPaperHistory(pid) : Promise.resolve(null)), [pid, !!paper.data],
    { refresh: changes });
  const back = html`<a class="pg-back" href=${href('papers')}>‹ 全部文献</a>`;
  if (!paper.data && paper.error?.status === 404) return html`<div class="pg">${back}<${Empty}>没有文献 ${pid}<//></div>`;
  if (!paper.data) return html`<div class="pg">${back}<${LoadState} state=${paper} what="文献" /></div>`;
  const p = paper.data;
  const docs = p.documents || {};
  return html`
    <${WhereScope} paperId=${p.paper_id} docs=${docs}>
      <div class="pg pd">
        ${back}
        <header class="pd-head">
          <div class="pd-kicker">
            <span>文献 ${p.paper_id}</span>
            ${p.meta_origin === 'edited'
              ? html`<${Chip} tone="accent" title="题录改过；重新导入不会再覆盖">题录已人工修改<//>`
              : html`<${Chip} tone="muted" title="题录取自 PDF 元数据、文件名和首页；修改后重新导入不会再覆盖">题录自动提取<//>`}
            <span class="muted">第 ${p.rev} 版${p.updated_by ? ` · ${p.updated_by} ${stamp(p.updated_at)}` : ''}</span>
          </div>
          <h1>${p.title || '（没有标题）'}</h1>
          ${p.authors ? html`<p class="pd-byline">${p.authors}</p>` : null}
          <p class="pd-pub">${[p.journal, p.year].filter(Boolean).join(' ')} <${DoiLink} doi=${p.doi} /></p>
        </header>
        <${PaperStats} p=${p} />
        <div class="pd-grid">
          <section class="card pd-card">
            <div class="card-head"><h3>题录</h3><span class="card-sub">修改后重新导入不会覆盖</span></div>
            <${MetaForm} key=${p.paper_id} paper=${p} onSaved=${bump} />
          </section>
          <div class="pd-side">
            <${DocumentsCard} p=${p} />
            <${ContextCard} context=${p.context} />
            <${PaperImports} imports=${p.imports} />
          </div>
        </div>
        <${BlocksCard} p=${p} />
        <${HistoryCard} state=${history} />
      </div>
    <//>`;
}

function PaperStats({ p }) {
  const c = p.counts || {};
  const base = { paper: p.paper_id };
  const tiles = [
    ['反应', c.reactions, base, null],
    ['未审核', c.unreviewed, { ...base, status: 'unreviewed' }, null],
    ['已审核', c.reviewed, { ...base, status: 'reviewed' }, 'ok'],
    ['有问题', c.problem, { ...base, status: 'problem' }, 'bad'],
    ['排除', c.excluded, { ...base, status: 'excluded' }, 'muted'],
    ['已修改', c.edited, { ...base, edited: '1' }, 'accent'],
    ['已删除', c.deleted, { ...base, deleted: '1' }, 'muted'],
    ['旧版本', c.old, { ...base, latest: '0' }, 'muted'],
  ];
  return html`
    <nav class="pd-stats" aria-label="这篇文献的反应">
      ${tiles.map(([label, n, q, tone], i) => html`
        <a key=${label} class=${cx('pd-stat', tone, !n && 'zero', i === 0 && 'lead')} href=${listLink(q)}
           title=${`在反应列表里查看：${label}`}>
          <b>${n || 0}</b><span>${label}${i === 0 ? ' ›' : ''}</span>
        </a>`)}
    </nav>`;
}

// ------------------------------------------------------------------ bibliographic fields

const FIELDS = ['title', 'authors', 'journal', 'year', 'doi', 'note'];
const LABEL = { title: '标题', authors: '作者', journal: '期刊', year: '年份', doi: 'DOI', note: '备注' };
const valuesOf = (p) => Object.fromEntries(FIELDS.map((k) => [k, p?.[k] == null ? '' : String(p[k])]));

function MetaForm({ paper, onSaved }) {
  const [base, setBase] = useState(paper);          // the version the edit started from
  const [form, setForm] = useState(() => valuesOf(paper));
  const [comment, setComment] = useState('');
  const [conflict, setConflict] = useState(null);   // the paper as it is now, after a 409
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const baseValues = valuesOf(base);
  const changed = FIELDS.filter((k) => form[k].trim() !== baseValues[k].trim());
  const dirty = changed.length > 0;
  const yearBad = form.year.trim() !== '' && !/^\d{1,4}$/.test(form.year.trim());

  // A newer version (another tab, a re-import) is taken over while nothing is typed.
  useEffect(() => {
    if (paper.rev !== base.rev && !dirty) {
      setBase(paper);
      setForm(valuesOf(paper));
    }
  }, [paper.rev]);

  useEffect(() => {
    if (!dirty) return undefined;
    const off = guard(() => '文献信息有未保存的修改，确定离开吗？');
    const onBeforeUnload = (e) => { e.preventDefault(); e.returnValue = ''; };
    addEventListener('beforeunload', onBeforeUnload);
    return () => { off(); removeEventListener('beforeunload', onBeforeUnload); };
  }, [dirty]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.currentTarget.value });
  const reset = () => { setForm(valuesOf(base)); setError(null); };

  const save = async (baseRev) => {
    if (!dirty || busy || yearBad) return;
    setBusy(true);
    setError(null);
    const fields = Object.fromEntries(changed.map((k) => [k, form[k].trim()]));
    try {
      const p = await updatePaper(paper.paper_id, { base_rev: baseRev, fields, comment: comment.trim() || null });
      setBase(p);
      setForm(valuesOf(p));
      setComment('');
      setConflict(null);
      forgetPapers();
      emit('toast', { text: `已保存文献 ${p.paper_id} 的题录（第 ${p.rev} 版）`, tone: 'ok' });
      onSaved(p);
    } catch (e) {
      if (e.status === 409 && e.body?.current) setConflict(e.body.current);
      else if (e.status === 0 && e.message === '未设置编辑者') setError('没有填写编辑者，修改没有保存。');
      else setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const loadLatest = () => {
    setBase(conflict);
    setForm(valuesOf(conflict));
    setConflict(null);
    onSaved(conflict);
  };
  const theirs = conflict ? FIELDS.filter((k) => valuesOf(conflict)[k] !== baseValues[k]) : [];
  const label = (k) => html`${LABEL[k]}${changed.includes(k) ? html`<i class="changed-dot" title="已修改，未保存"></i>` : null}`;

  return html`
    <form class="meta-form" onSubmit=${(e) => { e.preventDefault(); save(base.rev); }}>
      <${Field} label=${label('title')}>
        <textarea class="textarea" rows="2" value=${form.title} onInput=${set('title')} placeholder="文献标题"></textarea>
      <//>
      <${Field} label=${label('authors')}>
        <textarea class="textarea" rows="2" value=${form.authors} onInput=${set('authors')} placeholder="作者，用逗号分隔"></textarea>
      <//>
      <div class="meta-row">
        <${Field} label=${label('journal')}>
          <input class="input" value=${form.journal} onInput=${set('journal')} placeholder="期刊" />
        <//>
        <${Field} label=${label('year')} hint=${yearBad ? html`<span class="bad-text">年份应为整数</span>` : null}>
          <input class="input" value=${form.year} inputmode="numeric" maxlength="4" onInput=${set('year')} placeholder="年份" />
        <//>
        <${Field} label=${label('doi')}>
          <input class="input mono" value=${form.doi} onInput=${set('doi')} placeholder="10.xxxx/…" spellcheck="false" />
        <//>
      </div>
      <${Field} label=${label('note')} hint="给整理数据的人看的说明，不进入反应记录。">
        <textarea class="textarea" rows="3" value=${form.note} onInput=${set('note')} placeholder="备注"></textarea>
      <//>
      ${conflict ? html`
        <div class="pd-conflict" role="alert">
          <p><b>这篇文献的题录已被${conflict.updated_by ? ` ${conflict.updated_by} ` : '他人'}修改</b>（现在是第 ${conflict.rev} 版，${stamp(conflict.updated_at)}）。</p>
          ${theirs.length ? html`<p class="muted">对方改了：${theirs.map((k) => LABEL[k]).join('、')}</p>` : null}
          <div class="pd-conflict-actions">
            <button type="button" class="btn small" onClick=${loadLatest}>载入最新版本（放弃我的修改）</button>
            <button type="button" class="btn small primary" disabled=${busy} onClick=${() => save(conflict.rev)}>
              在最新版本上保存我的修改</button>
          </div>
        </div>` : null}
      ${error ? html`<p class="form-error" role="alert">${error}</p>` : null}
      <div class="meta-foot">
        <input class="input" value=${comment} maxlength="500" placeholder="修改说明（可不填）" aria-label="修改说明"
               onInput=${(e) => setComment(e.currentTarget.value)} />
        <button type="button" class="btn quiet" disabled=${!dirty || busy} onClick=${reset}>还原</button>
        <button type="submit" class="btn primary" disabled=${!dirty || busy || yearBad || !!conflict}>
          ${busy ? '正在保存…' : dirty ? `保存（${changed.length} 项）` : '保存'}</button>
      </div>
    </form>`;
}

// ------------------------------------------------------------------ side cards

function DocumentsCard({ p }) {
  const docs = Object.entries(p.documents || {});
  return html`
    <section class="card pd-card">
      <div class="card-head"><h3>文档</h3></div>
      ${docs.length ? html`
        <ul class="docs">
          ${docs.map(([doc, d]) => html`
            <li key=${doc} class="doc">
              <span class="doc-kind">${name(DOC, doc)}</span>
              <span class="doc-name" title=${d.filename}>${d.filename}</span>
              <span class="doc-pages">${d.page_count} 页</span>
              <span class="doc-actions">
                <button type="button" class="btn small"
                        onClick=${() => emit('pdf:open', { docId: d.doc_id, doc, paperId: p.paper_id, page: 1 })}>在 PDF 中打开</button>
                <a class="btn small quiet" href=${pdfUrl(d.doc_id)} target="_blank" rel="noopener" title="在新标签页打开原文件">原文件</a>
              </span>
            </li>`)}
        </ul>` : html`<p class="card-empty">没有文档。</p>`}
    </section>`;
}

const CONTEXT_WORD = { reaction_class: '反应类别', numbering_convention: '编号规则', notes: '说明' };

function ContextCard({ context }) {
  const order = Object.keys(CONTEXT_WORD);
  const rank = (k) => (order.includes(k) ? order.indexOf(k) : order.length);
  const items = Object.entries(context || {}).filter(([, v]) => v != null && v !== '')
    .sort(([a], [b]) => rank(a) - rank(b));
  if (!items.length) return null;
  return html`
    <section class="card pd-card">
      <div class="card-head"><h3>流水线的文献概述</h3><span class="card-sub">定位步骤写下的</span></div>
      <dl class="ctx">
        ${items.map(([k, v]) => html`
          <div key=${k}><dt>${CONTEXT_WORD[k] || k}</dt><dd>${typeof v === 'string' ? v : JSON.stringify(v)}</dd></div>`)}
      </dl>
    </section>`;
}

function countLine(counts) {
  return Object.entries(counts || {}).filter(([, n]) => n).map(([k, n]) => `${IMPORT_COUNT[k] || k} ${n}`).join(' · ');
}

function PaperImports({ imports }) {
  if (!imports?.length) return null;
  return html`
    <section class="card pd-card">
      <div class="card-head"><h3>导入</h3><a class="card-link" href=${href('imports')}>全部导入记录 ›</a></div>
      <ul class="pd-imports">
        ${imports.map((i) => html`
          <li key=${i.import_id}>
            <span class="pd-imp-id">#${i.import_id}</span>
            <span class="muted">${stamp(i.started_at)}</span>
            <${Chip} tone=${i.outcome === 'imported' ? 'ok' : i.outcome === 'refused' ? 'bad' : 'warn'}>${name(IMPORT_OUTCOME, i.outcome)}<//>
            <div class="pd-imp-counts">${i.reason || countLine(i.counts) || '没有变化'}</div>
          </li>`)}
      </ul>
    </section>`;
}

function BlocksCard({ p }) {
  const blocks = p.blocks || [];
  return html`
    <section class="card pd-card pd-blocks">
      <div class="card-head"><h3>块<span class="count">${blocks.length}</span></h3>
        <span class="card-sub">点一行查看这个块的反应</span></div>
      ${blocks.length ? html`
        <table class="plain pd-btable">
          <thead><tr><th>图表</th><th>块</th><th>标题</th><th>版式</th><th>类型</th><th>位置</th><th class="num">反应</th></tr></thead>
          <tbody>
            ${blocks.map((b) => {
              const link = listLink({ paper: p.paper_id, block: b.block_pk });
              return html`
                <tr key=${b.block_pk} class=${cx(!b.in_latest && 'stale')}
                    onClick=${(e) => { if (!e.target.closest('a, button')) navigate(link); }}>
                  <td class="nowrap"><b>${b.figure || '—'}</b></td>
                  <td class="mono nowrap">${b.block_id}</td>
                  <td>${b.title || html`<span class="muted">—</span>`}
                    ${!b.in_latest ? html` <${Chip} tone="muted">不在最新导入<//>` : null}</td>
                  <td class="nowrap">${name(LAYOUT, b.layout)}</td>
                  <td class="nowrap">${name(KIND, b.kind)}</td>
                  <td class="nowrap">${b.doc ? html`<${Where} at=${{ doc: b.doc, page: b.page }} />` : '—'}</td>
                  <td class="num"><a href=${link}>${b.reactions}</a></td>
                </tr>`;
            })}
          </tbody>
        </table>` : html`<p class="card-empty">这篇文献没有导入块。</p>`}
    </section>`;
}

// ------------------------------------------------------------------ history

// The changes of one revision as readable lines: where (in words), old → new.
export function DiffLines({ diff }) {
  if (!diff?.length) return null;
  return html`
    <ul class="dlines">
      ${diff.map((d, i) => html`
        <li key=${i} class=${`dl dl-${d.op}`}>
          <span class="dl-path">${describePath(d.path)}</span>
          ${d.op === 'change' ? html`
            <span class="dl-old">${brief(d.old)}</span><span class="dl-arrow" aria-label="改为">→</span><span class="dl-new">${brief(d.new)}</span>`
          : d.op === 'add' ? html`<span class="dl-tag">加入</span><span class="dl-new">${brief(d.new)}</span>`
          : d.op === 'remove' ? html`<span class="dl-tag">去掉</span><span class="dl-old">${brief(d.old)}</span>`
          : html`<span class="dl-tag">调整顺序</span><span class="dl-new">${brief(d.new)}</span>`}
        </li>`)}
    </ul>`;
}

function HistoryCard({ state }) {
  const items = state.data || [];
  return html`
    <section class="card pd-card">
      <div class="card-head"><h3>题录的修改历史</h3>${items.length ? html`<span class="card-sub">${items.length} 个版本</span>` : null}</div>
      ${!state.data ? html`<div class="card-pad"><${LoadState} state=${state} what="修改历史" /></div>` : html`
        <ol class="hist">
          ${items.map((r) => html`
            <li key=${r.rev} class="hist-item">
              <div class="hist-head">
                <span class="hist-rev">第 ${r.rev} 版</span>
                <${Chip} tone=${r.action === 'meta' ? 'accent' : null}>${name(REV_ACTION, r.action)}<//>
                <span class="hist-who">${r.author || '—'}</span>
                <span class="hist-when">${stamp(r.created_at)}</span>
                ${r.import_id != null ? html`<a class="hist-imp" href=${href('imports')}>导入 #${r.import_id}</a>` : null}
              </div>
              ${r.comment ? html`<p class="hist-comment">${r.comment}</p>` : null}
              ${r.diff?.length ? html`<${DiffLines} diff=${r.diff} />`
                : html`<p class="hist-none">${r.action === 'import' ? '首次导入时的题录' : '没有内容变化'}</p>`}
            </li>`)}
        </ol>`}
    </section>`;
}
