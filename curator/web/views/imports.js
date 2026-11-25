// The import batches, newest first: when and by whom, from which work directory at which commit, with
// which options, and per paper what happened (outcome, counts, the reason of a skip or refusal, warnings,
// the pipeline reactions that failed and so were not imported, record validation problems).
import { html } from '../lib/preact.js';
import { listImports } from '../lib/api.js';
import { useLoad } from '../lib/hooks.js';
import { href } from '../lib/router.js';
import { IMPORT_COUNT, IMPORT_OUTCOME, cx, name, seconds, stamp } from '../lib/format.js';
import { Chip, Empty, LoadState } from '../components/common.js';
import { loadPapers, paperShort } from './papers.js';

const OUTCOME_TONE = { imported: 'ok', skipped: 'warn', refused: 'bad' };
// Columns of the per-paper table, in the order the importer counts them.
const COLUMNS = ['inserted', 'superseded', 'superseded_touched', 'failed_not_imported', 'blocks'];
const ATTENTION = new Set(['superseded_touched', 'failed_not_imported']);

const stop = (e) => e.stopPropagation();

function duration(b) {
  const a = Date.parse(b.started_at);
  const z = Date.parse(b.finished_at);
  if (Number.isNaN(a) || Number.isNaN(z)) return null;
  const s = Math.max(0, (z - a) / 1000);
  return s < 1 ? '不到 1 秒' : seconds(s);
}

export function Imports() {
  const state = useLoad(listImports, []);
  const papers = useLoad(loadPapers, []);
  if (!state.data) return html`<div class="pg"><${LoadState} state=${state} what="导入记录" /></div>`;
  const batches = state.data;
  const names = Object.fromEntries((papers.data || []).map((p) => [p.paper_id, paperShort(p)]));
  return html`
    <div class="pg">
      <header class="pg-head">
        <h1>导入记录<span class="count">${batches.length}</span></h1>
        <p class="pg-lead">每次运行 <code>python -m curator import</code> 记一批：从哪个工作目录、哪个代码版本导入，每篇文献的结果。
          同一篇文献再导入时，新的提取结果整体替换上次的反应（旧的留作只读的旧版本）；内容没有变化的文献跳过。</p>
      </header>
      ${batches.length === 0 ? html`<${Empty}>还没有导入过。<//>`
        : batches.map((b, i) => html`<${Batch} key=${b.import_id} b=${b} names=${names} open=${i === 0} />`)}
    </div>`;
}

function Batch({ b, names, open }) {
  const report = b.report || {};
  const totals = report.totals || {};
  const outcomes = ['imported', 'skipped', 'refused'].filter((k) => totals[k]);
  const opts = b.options || {};
  const papers = (b.papers || []).map((p) => ({ ...(report.papers?.[p.paper_id] || {}), ...p }));
  return html`
    <details class="card imp" open=${open || null}>
      <summary class="imp-head">
        <span class="imp-id">#${b.import_id}</span>
        <span class="imp-when">${stamp(b.started_at)}</span>
        <span class="imp-sum">
          ${outcomes.length ? outcomes.map((k) => html`<${Chip} key=${k} tone=${OUTCOME_TONE[k]}>${name(IMPORT_OUTCOME, k)} ${totals[k]}<//>`)
            : html`<span class="muted">${papers.length} 篇文献</span>`}
          ${report.dry_run ? html`<${Chip} tone="warn">试运行<//>` : null}
        </span>
        <span class="imp-counts">${COLUMNS.filter((k) => totals[k] && k !== 'blocks').map((k) => html`
          <span key=${k} class=${cx('imp-count', ATTENTION.has(k) && 'attn')}>${IMPORT_COUNT[k]} <b>${totals[k]}</b></span>`)}</span>
        <a class="imp-link" href=${href('reactions', null, { import: b.import_id })} onClick=${stop}
           title="反应列表里只看这次导入新增或更新的反应">查看这批反应 ›</a>
      </summary>
      <div class="imp-body">
        <dl class="imp-meta">
          <div><dt>导入者</dt><dd>${b.author || '—'}</dd></div>
          <div><dt>用时</dt><dd>${duration(b) || '—'}<span class="muted">（${stamp(b.finished_at) || '未完成'} 结束）</span></dd></div>
          <div><dt>代码版本</dt><dd>
            ${b.repo_commit ? html`<code title=${b.repo_commit}>${b.repo_commit.slice(0, 10)}</code>` : html`<span class="muted">不知道</span>`}
            ${b.repo_dirty ? html` <${Chip} tone="warn" title="导入时仓库里有没提交的改动：流水线的代码可能和这个版本不完全一样">有未提交的改动<//>` : null}
          </dd></div>
          <div><dt>选项</dt><dd>
            文献 ${opts.papers?.length ? opts.papers.join('、') : '全部'}
            ${opts.force ? html` <${Chip} tone="warn" title="内容和上次导入相同的文献也重新覆盖">强制覆盖<//>` : null}
            ${opts.accept_id_change ? html` <${Chip} tone="warn">接受反应编号大面积变化<//>` : null}
            ${opts.dry_run ? html` <${Chip}>试运行<//>` : null}
          </dd></div>
          <div class="wide"><dt>工作目录</dt><dd><code class="imp-path">${b.work_dir || '—'}</code></dd></div>
        </dl>
        <div class="imp-table" role="table" aria-label="每篇文献的结果">
          <div class="imp-row imp-th" role="row">
            <span></span><span>文献</span><span>结果</span>
            ${COLUMNS.map((k) => html`<span key=${k} class="n">${IMPORT_COUNT[k]}</span>`)}
            <span class="n">校验</span>
          </div>
          ${papers.map((p) => html`<${PaperResult} key=${p.paper_id} p=${p} names=${names} />`)}
        </div>
      </div>
    </details>`;
}

function PaperResult({ p, names }) {
  const c = p.counts || {};
  const warnings = p.warnings || [];
  const failed = p.failed_ids || [];
  const validation = Object.entries(p.validation || {});
  const problems = (c.validation_errors || 0) + (c.validation_warnings || 0);
  const more = !!(p.reason || warnings.length || failed.length || validation.length);
  const cells = html`
    <span class="imp-paper">
      <a href=${href('papers', p.paper_id)} onClick=${stop}><b>${p.paper_id}</b></a>
      <span class="muted">${names[p.paper_id] || ''}</span>
      ${warnings.length ? html`<span class="imp-warn" title=${warnings.join('\n')}>${warnings.length} 条提示</span>` : null}
    </span>
    <span>${p.unchanged ? html`<${Chip} title="内容和上次导入相同，没有重新覆盖">没有变化<//>`
      : html`<${Chip} tone=${OUTCOME_TONE[p.outcome]}>${p.outcome === 'imported' && c.superseded ? '已覆盖' : name(IMPORT_OUTCOME, p.outcome)}<//>`}</span>
    ${COLUMNS.map((k) => html`<span key=${k} class=${cx('n', !c[k] && 'zero', c[k] && ATTENTION.has(k) && 'attn')}>${c[k] ?? '—'}</span>`)}
    <span class=${cx('n', !problems && 'zero', c.validation_errors && 'attn')}
          title=${`校验错误 ${c.validation_errors || 0}，警告 ${c.validation_warnings || 0}`}>
      ${problems ? `${c.validation_errors || 0} / ${c.validation_warnings || 0}` : '0'}</span>`;
  if (!more) return html`<div class="imp-row" role="row"><span></span>${cells}</div>`;
  return html`
    <details class="imp-pd">
      <summary class="imp-row" role="row">${cells}</summary>
      <div class="imp-detail">
        ${p.reason ? html`<div class="imp-reason"><b>原因：</b>${p.reason}</div>` : null}
        ${warnings.length ? html`
          <div class="imp-sec"><h4>提示</h4><ul class="problems">${warnings.map((w, i) => html`<li key=${i} class="warn">${w}</li>`)}</ul></div>` : null}
        ${failed.length ? html`
          <div class="imp-sec">
            <h4>流水线失败、没有导入的反应（${failed.length}）</h4>
            <p class="muted">重跑流水线后再导入一次就会补进来。</p>
            <ul class="imp-ids">${failed.map((id) => html`<li key=${id}><code>${id}</code></li>`)}</ul>
          </div>` : null}
        ${validation.length ? html`
          <div class="imp-sec">
            <h4>记录校验（${validation.length} 条反应有问题）</h4>
            ${validation.map(([oid, v]) => html`
              <div key=${oid} class="imp-val">
                <code>${oid}</code>
                <ul class="problems">
                  ${(v.errors || []).map((x, i) => html`<li key=${`e${i}`} class="bad">${x}</li>`)}
                  ${(v.warnings || []).map((x, i) => html`<li key=${`w${i}`} class="warn">${x}</li>`)}
                </ul>
              </div>`)}
          </div>` : null}
      </div>
    </details>`;
}
