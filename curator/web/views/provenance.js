import { html } from '../lib/preact.js';
import { href } from '../lib/router.js';
import { DOC, KIND, LAYOUT, REACTION_STATUS, REVIEW_STATUS, STEP_STATUS, cx, displayId, name, seconds, stamp } from '../lib/format.js';
import { samePath } from '../lib/paths.js';
import { Chip, ReviewDot, Where } from '../components/common.js';

// The card "来源与采集": where in the paper the reaction is printed (document, page, figure, block,
// entry and what the entry prints) and how it got here (pipeline id, imports, the extract run, edits).

const short = (sha) => (sha ? String(sha).slice(0, 7) : '');

// The entry of the block view the reaction was read from.
export const entryOf = (block, entryId) => (block?.view?.entries || []).find((e) => e.eid === entryId) || null;

function ImportLine({ imp }) {
  if (!imp) return html`<span class="muted">—</span>`;
  return html`
    <span><a href=${href('imports')}>导入 #${imp.import_id}</a>
      <span class="sep">·</span>${stamp(imp.started_at)}<span class="sep">·</span>${imp.author}
      ${imp.repo_commit ? html`<span class="sep">·</span><span class="mono" title=${imp.repo_commit}>${short(imp.repo_commit)}</span>` : null}
      ${imp.repo_dirty ? html` <${Chip} tone="warn" title="导入时代码仓库里有未提交的改动">有未提交改动<//>` : null}</span>`;
}

// One pipeline step of the import: version, model, when it finished, whether it ran on part of the paper.
function StepLine({ step }) {
  if (!step) return html`<span class="muted">—</span>`;
  const p = step.params || {};
  const codex = p.codex || {};
  const partial = p.blocks || p.kinds || p.limit != null || p.entries === false;
  return html`
    <span>v${step.version ?? '?'}${codex.model ? html`<span class="sep">·</span><span class="mono">${codex.model}</span>${
      codex.reasoning_effort ? html`<span class="muted">（${codex.reasoning_effort}）</span>` : null}` : null}
      ${step.finished_at ? html`<span class="sep">·</span>${stamp(step.finished_at)}` : null}
      ${step.seconds ? html`<span class="sep">·</span>用时 ${seconds(step.seconds)}` : null}
      ${step.status && step.status !== 'done' ? html` <${Chip} tone="warn">${name(STEP_STATUS, step.status)}<//>` : null}
      ${partial ? html` <${Chip} tone="warn" title="提取时限定了块、类型或条数，不是整篇文献的结果">部分运行<//>` : null}</span>`;
}

// props: {row, data, block, query, editing, selected, onSelect, onTab}; `block` is the getBlock answer
// (null while loading or when the reaction has none), `query` the list filters links keep.
export function Provenance({ row, data, block, query, editing, selected, onSelect, onTab }) {
  const src = data?.source || {};
  const docInfo = row.documents?.[src.doc];
  const b = row.block;
  const entry = entryOf(block, src.entry_id);
  const printed = entry?.expansion?.printed || entry?.descriptor || null;
  const siblings = (block?.reactions || []).filter((r) => r.entry_id && r.entry_id === src.entry_id && r.id !== row.id);
  const prov = row.provenance || {};
  const imp = prov.last_import || prov.first_import;
  const steps = imp?.steps || {};
  const info = row.pipeline_info;

  const rows = (items) => items.filter(Boolean).map(([key, title, body]) => html`
    <div class="kv-key" key=${`k-${key}`}>${title}</div><div class="kv-value" key=${`v-${key}`}>${body}</div>`);

  const sourceRows = rows([
    ['doc', '文档', html`
      <span>${src.doc ? html`<${Where} at=${src.page ? { doc: src.doc, page: src.page } : null} />` : '—'}
        ${!src.page && src.doc ? name(DOC, src.doc) : null}
        ${docInfo ? html` <span class="muted file" title=${docInfo.filename}>${docInfo.filename}</span>` : null}</span>`],
    (src.figure || src.caption) && ['figure', '图表', html`
      <div>${src.figure || '—'}${src.section ? html`<span class="sep">·</span>${src.section}` : null}</div>
      ${src.caption ? html`<div class="muted">${src.caption}</div>` : null}`],
    ['block', '块', b ? html`
      <span><button type="button" class="link" onClick=${() => onTab?.('block')} title="查看来源块">${b.title || `${b.region_id}/${b.block_id}`}</button>
        ${b.layout ? html` <${Chip}>${name(LAYOUT, b.layout)}<//>` : null}
        ${b.kind ? html` <${Chip}>${name(KIND, b.kind)}<//>` : null}
        <span class="muted mono"> ${b.region_id}/${b.block_id}</span></span>`
      : html`<span class="muted">${src.region_id ? `${src.region_id}/${src.block_id || '?'}（库里没有这个块）` : '不属于任何块（人工新建）'}</span>`],
    ['entry', '条目', src.entry_id ? html`
      <div><span class="mono">${src.entry_id}</span>${entry?.label ? html`<span class="sep">·</span><b>${entry.label}</b>` : null}
        ${src.reaction_id ? html`<span class="sep">·</span><span class="muted mono" title="条目里的第几条反应">${src.reaction_id}</span>` : null}</div>
      ${printed ? html`<pre class="printed">${printed}</pre>` : null}
      ${siblings.length ? html`
        <div class="siblings"><span class="muted">同一条目还有：</span>
          ${siblings.map((s) => html`
            <a key=${s.id} class=${cx('sibling', s.deleted && 'deleted')} href=${href('reactions', s.id, query)}>
              <${ReviewDot} status=${s.review_status} /><span class="mono">${s.rid}</span> ${s.label || ''}</a>`)}
        </div>` : null}`
      : html`<span class="muted">—</span>`],
  ]);

  const extractRows = rows([
    ['origin', '流水线编号', row.origin_id ? html`<span class="mono">${row.origin_id}</span>`
      : html`<span class="muted">没有（${row.copied_from ? '复制得到' : '人工新建'}）</span>`],
    row.copied_from && ['copied', '复制自', html`
      <a href=${href('reactions', row.copied_from, query)}><span class="mono">${displayId(row.copied_from)}</span></a>`],
    info && ['pipeline', '流水线状态', html`
      <span>${name(REACTION_STATUS, info.status)}${info.seconds ? html`<span class="sep">·</span>用时 ${seconds(info.seconds)}` : null}
        ${(info.errors || []).length ? html` <${Chip} tone="bad">错误 ${info.errors.length}<//>` : null}
        ${(info.warnings || []).length ? html` <${Chip} tone="warn">警告 ${info.warnings.length}<//>` : null}</span>`],
    prov.first_import && ['first', '首次导入', html`<${ImportLine} imp=${prov.first_import} />`],
    prov.last_import && prov.last_import.import_id !== prov.first_import?.import_id
      && ['last', '最近导入', html`<${ImportLine} imp=${prov.last_import} />`],
    steps.extract && ['extract', '提取', html`<${StepLine} step=${steps.extract} />`],
    steps.locate && ['locate', '定位', html`<${StepLine} step=${steps.locate} />`],
    ['state', '版本', html`
      <span>第 ${row.rev} 版<span class="sep">·</span>${stamp(row.updated_at)} ${row.updated_by || ''}
        ${row.edited ? html` <${Chip} tone="accent" title=${row.origin_id ? '数据和流水线版本不同' : '人工新建或复制的反应'}>已修改<//>` : null}</span>`],
    row.review_note && ['note', '审核备注', html`
      <span><span class="muted">${name(REVIEW_STATUS, row.review_status)}：</span>${row.review_note}</span>`],
  ]);

  const on = editing && samePath(selected, ['source']);
  const pickSource = editing ? {
    class: cx('prov-source', 'sel-target', on && 'selected'), role: 'button', tabindex: 0,
    onClick: () => onSelect?.(['source']),
    onKeyDown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect?.(['source']); } },
  } : { class: 'prov-source' };

  return html`
    <section class="card dcard prov">
      <div class="card-head"><h3>来源与采集</h3></div>
      <div class="dcard-body prov-body">
        <div ...${pickSource}>
          <div class="prov-title">来源${editing ? html`<span class="muted">（点击编辑页码、条目框、图表、条目）</span>` : null}</div>
          <div class="kv">${sourceRows}</div>
        </div>
        <div class="prov-extract">
          <div class="prov-title">采集</div>
          <div class="kv">${extractRows}</div>
        </div>
      </div>
    </section>`;
}
