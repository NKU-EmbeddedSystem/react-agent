import { html, useMemo, useState } from '../lib/preact.js';
import { ApiError, getDiff, getHistory, getRevision, revertReaction } from '../lib/api.js';
import { toast } from '../lib/bus.js';
import { useLoad } from '../lib/hooks.js';
import { REVIEW_STATUS, REV_ACTION, brief, cx, describePath, keyNames, name, stamp } from '../lib/format.js';
import { Chip, Dialog, Empty, Field, LoadState } from '../components/common.js';
import { JsonView } from './jsonview.js';

// The revisions of a reaction, newest first, each with what it changed; a snapshot of any of them,
// going back to one (a new revision with that data), and the changes since the pipeline's version.

const ACTION_TONE = {
  import: 'accent', reimport: 'accent', accept_import: 'accent', dismiss_import: 'muted', review: 'ok',
  delete: 'bad', restore: 'ok', copy: 'accent', create: 'accent', revert: 'warn', edit: null,
};

// A value of a diff line in words; the state fields around the data have names of their own.
function value(path, v) {
  const head = path?.[0];
  if (head === 'review_status' && typeof v === 'string') return name(REVIEW_STATUS, v);
  if (head === 'deleted' && typeof v === 'boolean') return v ? '已删除' : '未删除';
  return brief(v, 90);
}

const OP = { add: '加入', remove: '去掉', change: '修改', reorder: '调整顺序' };

// Two long texts that share a beginning or an end (a sentence added to a note, a word fixed): only the
// part that differs, with a little context, instead of both texts in full.
function textChange(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || Math.max(a.length, b.length) < 40) return null;
  let pre = 0;
  while (pre < a.length && pre < b.length && a[pre] === b[pre]) pre++;
  let post = 0;
  while (post < a.length - pre && post < b.length - pre && a[a.length - 1 - post] === b[b.length - 1 - post]) post++;
  if (pre + post < 12) return null;
  const CONTEXT = 24;
  const head = a.slice(0, pre);
  const tail = a.slice(a.length - post);
  const del = a.slice(pre, a.length - post);
  const ins = b.slice(pre, b.length - post);
  return html`
    <span class="diff-text">${head ? html`<span class="diff-ctx">${head.length > CONTEXT ? '…' : ''}${head.slice(-CONTEXT)}</span>` : null}${
      del ? html`<span class="diff-old">${brief(del, 300)}</span>` : null}${
      ins ? html`<span class="diff-new">${brief(ins, 300)}</span>` : null}${
      tail ? html`<span class="diff-ctx">${tail.slice(0, CONTEXT)}${tail.length > CONTEXT ? '…' : ''}</span>` : null}</span>`;
}

// A box is a list of four numbers, which the server diffs one by one: its changed coordinates make one
// line here ("框  x0 320 → 314 · y1 106.9 → 107"), counted as one change.
const BOX_KEYS = new Set(['bbox', 'entry_bbox']);
const AXES = ['x0', 'y0', 'x1', 'y1'];
export function diffLines(ops) {
  const out = [];
  for (const op of Array.isArray(ops) ? ops : []) {
    const p = op.path || [];
    const i = p[p.length - 1];
    if (op.op === 'change' && Number.isInteger(i) && i >= 0 && i < 4 && BOX_KEYS.has(p[p.length - 2])) {
      const path = p.slice(0, -1);
      const prev = out[out.length - 1];
      if (prev?.coords && JSON.stringify(prev.path) === JSON.stringify(path)) prev.coords.push([i, op.old, op.new]);
      else out.push({ op: 'change', path, coords: [[i, op.old, op.new]] });
    } else {
      out.push(op);
    }
  }
  return out;
}

function DiffLine({ op, names }) {
  const where = describePath(op.path, names);
  if (op.coords) {
    return html`
      <li class="diff-line op-change">
        <span class="diff-op">${OP.change}</span>
        <span class="diff-path" title=${JSON.stringify(op.path)}>${where}</span>
        <span class="diff-values">${op.coords.map(([i, a, b], n) => html`
          ${n ? html`<span class="diff-ctx"> · </span>` : null}<span class="diff-axis">${AXES[i]}</span> <span class="diff-old">${brief(a)}</span><span class="diff-arrow">→</span><span class="diff-new">${brief(b)}</span>`)}
        </span>
      </li>`;
  }
  const text = op.op === 'change' ? textChange(op.old, op.new) : null;
  return html`
    <li class=${cx('diff-line', `op-${op.op}`)}>
      <span class="diff-op">${OP[op.op] || op.op}</span>
      <span class="diff-path" title=${JSON.stringify(op.path)}>${where}</span>
      <span class="diff-values">
        ${text || (op.op === 'add' ? html`<span class="diff-new">${value(op.path, op.new)}</span>`
          : op.op === 'remove' ? html`<span class="diff-old">${value(op.path, op.old)}</span>`
            : html`<span class="diff-old">${value(op.path, op.old)}</span><span class="diff-arrow">→</span><span class="diff-new">${value(op.path, op.new)}</span>`)}
      </span>
    </li>`;
}

// diff: [{op, path, old, new}] (server diff.py); the first `max` lines show, the rest on request.
// names: keyNames of the record, so items read as their labels.
export function DiffList({ diff, max = 12, empty = '没有改动', names = null }) {
  const [all, setAll] = useState(false);
  const ops = diffLines(diff);
  if (!ops.length) return html`<p class="diff-empty">${empty}</p>`;
  const shown = all ? ops : ops.slice(0, max);
  return html`
    <ul class="diff">
      ${shown.map((op, i) => html`<${DiffLine} key=${i} op=${op} names=${names} />`)}
      ${ops.length > shown.length ? html`
        <li class="diff-more"><button type="button" class="link" onClick=${() => setAll(true)}>展开其余 ${ops.length - shown.length} 处改动</button></li>` : null}
    </ul>`;
}

// A diff fetched when the dialog opens (e.g. pipeline → current).
export function DiffDialog({ title, lead, load, empty, onClose, footer, names = null }) {
  const state = useLoad(load, [title]);
  return html`
    <${Dialog} title=${title} width=${760} onClose=${onClose} footer=${footer}>
      ${lead ? html`<p class="dialog-lead">${lead}</p>` : null}
      ${state.data ? html`
        <p class="diff-count">${state.data.length ? `共 ${diffLines(state.data).length} 处不同` : ''}</p>
        <${DiffList} diff=${state.data} max=${400} empty=${empty} names=${names} />` : html`<${LoadState} state=${state} what="差异" />`}
    <//>`;
}

function SnapshotDialog({ id, rev, onClose }) {
  const state = useLoad(() => getRevision(id, rev), [id, rev]);
  return html`
    <${Dialog} title=${`第 ${rev} 版的快照`} width=${820} onClose=${onClose}>
      ${state.data ? html`
        <p class="dialog-lead">这个版本保存下来的完整状态：数据、审核状态、审核备注和删除标记。</p>
        <${JsonView} data=${state.data.snapshot} compact />` : html`<${LoadState} state=${state} what="快照" />`}
    <//>`;
}

function RevertDialog({ rev, onConfirm, onClose }) {
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    const ok = await onConfirm(comment.trim() || null);
    setBusy(false);
    if (ok) onClose();
  };
  return html`
    <${Dialog} title=${`回退到第 ${rev} 版`} width=${460} onClose=${onClose} closeOnBackdrop=${false}
               footer=${html`
                 <button type="button" class="btn" onClick=${onClose}>取消</button>
                 <button type="button" class="btn primary" disabled=${busy} onClick=${go}>回退</button>`}>
      <p class="dialog-lead">把数据恢复成第 ${rev} 版的样子。这会新增一个版本，原来的版本都还在；审核状态和删除标记不变。</p>
      <${Field} label="备注（可选）" hint="会记在这次回退的历史里">
        <input class="input" autofocus value=${comment} maxlength="500" placeholder="为什么回退"
               onInput=${(e) => setComment(e.currentTarget.value)}
               onKeyDown=${(e) => { if (e.key === 'Enter') { e.preventDefault(); go(); } }} />
      <//>
    <//>`;
}

function Revision({ r, latest, origin, names, onSnapshot, onRevert }) {
  const first = r.rev === 1;
  const what = !r.diff?.length && (first ? (r.action === 'import' ? '首次导入的版本'
    : r.action === 'create' ? '人工新建的空白反应' : '最初的版本') : r.action === 'dismiss_import'
    ? '保留当前数据，不再提示这个流水线版本' : '数据没有变化');
  return html`
    <li class=${cx('rev', latest && 'latest')}>
      <div class="rev-head">
        <span class="rev-no">第 ${r.rev} 版</span>
        <${Chip} tone=${ACTION_TONE[r.action]}>${name(REV_ACTION, r.action)}<//>
        <b class="rev-author">${r.author}</b>
        <span class="muted">${stamp(r.created_at)}</span>
        ${r.import_id != null ? html`<span class="muted">导入 #${r.import_id}</span>` : null}
        ${r.target_rev != null ? html`<span class="muted">回到第 ${r.target_rev} 版</span>` : null}
        ${latest ? html`<${Chip} tone="muted">当前<//>` : null}
        <span class="rev-actions">
          <button type="button" class="btn small quiet" onClick=${() => onSnapshot(r.rev)}>查看快照</button>
          ${latest ? null : html`<button type="button" class="btn small quiet" onClick=${() => onRevert(r.rev)}
                                         title="新增一个版本，数据和这个版本相同">回退到此版本</button>`}
        </span>
      </div>
      ${r.comment ? html`<div class="rev-comment">${r.comment}</div>` : null}
      ${what ? html`<p class="diff-empty">${what}${first && origin ? html`<span class="mono">　${origin}</span>` : null}</p>`
        : html`<${DiffList} diff=${r.diff} names=${names} />`}
    </li>`;
}

// props: {id, row, onReverted(newRow)}; reloads whenever the reaction's rev changes.
export function History({ id, row, onReverted }) {
  const state = useLoad(() => getHistory(id), [id], { refresh: row?.rev });
  const [dialog, setDialog] = useState(null);   // {kind: 'snapshot'|'revert'|'pipeline', rev?}
  const close = () => setDialog(null);

  const revert = async (rev, comment) => {
    try {
      const next = await revertReaction(id, { base_rev: row.rev, to_rev: rev, comment });
      if (next.rev === row.rev) toast(`数据和第 ${rev} 版相同，没有新增版本`, 'warn');
      else toast(`已回退到第 ${rev} 版的数据（现在是第 ${next.rev} 版）`);
      onReverted?.(next);
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.body?.current) {
        onReverted?.(e.body.current);
        toast(`这条反应刚被修改过（现在是第 ${e.body.current.rev} 版），请看过最新版本后再回退`, 'warn');
        return true;
      }
      toast(e.status === 0 && e.message === '未设置编辑者' ? '没有填写编辑者，没有回退' : e.message || String(e),
        e.status === 0 ? 'warn' : 'bad');
      return false;
    }
  };

  const revs = state.data || [];
  // Items are named by their labels in the current data (keys rarely change between revisions).
  const names = useMemo(() => keyNames(row?.data), [row?.data]);
  return html`
    <section class="card dcard history">
      <div class="card-head">
        <h3>历史<span class="card-count">${revs.length || ''}</span></h3>
        <span class="card-hint">每次修改都记一个版本；回退也是新增一个版本</span>
        ${row?.origin_id ? html`
          <button type="button" class="btn small history-pipeline" onClick=${() => setDialog({ kind: 'pipeline' })}>与流水线版本比较</button>` : null}
      </div>
      <div class="dcard-body">
        ${!state.data ? html`<${LoadState} state=${state} what="历史" />`
          : !revs.length ? html`<${Empty}>没有历史记录<//>`
            : html`
              <ol class="revs">
                ${revs.map((r, i) => html`
                  <${Revision} key=${r.rev} r=${r} latest=${i === 0 && r.rev === row?.rev} origin=${row?.origin_id} names=${names}
                               onSnapshot=${(rev) => setDialog({ kind: 'snapshot', rev })}
                               onRevert=${(rev) => setDialog({ kind: 'revert', rev })} />`)}
              </ol>`}
      </div>
      ${dialog?.kind === 'snapshot' ? html`<${SnapshotDialog} id=${id} rev=${dialog.rev} onClose=${close} />` : null}
      ${dialog?.kind === 'revert' ? html`
        <${RevertDialog} rev=${dialog.rev} onClose=${close} onConfirm=${(comment) => revert(dialog.rev, comment)} />` : null}
      ${dialog?.kind === 'pipeline' ? html`
        <${DiffDialog} title="与流水线版本比较" onClose=${close} empty="当前数据和流水线版本相同"
                       lead="从流水线最近一次给出的版本到现在的数据，有哪些不同（只比较数据，不含审核状态）。"
                       load=${() => getDiff(id, 'pipeline', 'current')} names=${names} />` : null}
    </section>`;
}
