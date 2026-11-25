import { html, useState } from '../lib/preact.js';
import { getDiff } from '../lib/api.js';
import { toast } from '../lib/bus.js';
import { useLoad } from '../lib/hooks.js';
import { cx, keyNames, stamp } from '../lib/format.js';
import { Dialog, LoadState } from '../components/common.js';
import { DiffList, diffLines } from './history.js';
import { copyText } from './jsonview.js';

// What sits at the bottom of the detail while editing: the state of the working copy (changes, the
// checks), undo/redo, a comment for the history, 放弃 and 保存; above it, on request, the list of
// problems the checks found. Plus the dialogs around saving: the changes, a conflict, discarding.

const Icon = {
  undo: html`<svg width="13" height="13" viewBox="0 0 13 13" aria-hidden="true"><path d="M4.5 3 1.8 5.7l2.7 2.7M2 5.7h5.6a3.4 3.4 0 0 1 0 6.8H6" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  redo: html`<svg width="13" height="13" viewBox="0 0 13 13" aria-hidden="true"><path d="M8.5 3l2.7 2.7-2.7 2.7M11 5.7H5.4a3.4 3.4 0 0 0 0 6.8H7" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  chevron: html`<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="m2.5 6.5 2.5-3 2.5 3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
};

function CheckPill({ v, count, open, onClick }) {
  const errors = v.errors.length;
  const warnings = v.warnings.length;
  let tone;
  let text;
  if (v.status === 'failed') [tone, text] = ['bad', '校验失败'];
  else if (v.status === 'idle' || (v.status === 'checking' && !errors && !warnings && !v.seen)) [tone, text] = ['muted', '校验中…'];
  else if (errors) [tone, text] = ['bad', `${errors} 个错误${warnings ? ` · ${warnings} 个警告` : ''}`];
  else if (warnings) [tone, text] = ['warn', `${warnings} 个警告`];
  else [tone, text] = ['ok', '校验通过'];
  const clickable = count > 0;
  return html`
    <button type="button" class=${cx('eb-pill', 'eb-check', tone, v.status === 'checking' && 'busy', open && 'open')}
            disabled=${!clickable} onClick=${onClick} aria-expanded=${clickable ? String(!!open) : null}
            title=${v.status === 'failed' ? v.message : clickable ? (open ? '收起问题列表' : '展开问题列表') : null}>
      <i class="eb-dot"></i>${text}${clickable ? html`<span class="eb-chev">${Icon.chevron}</span>` : null}
    </button>`;
}

function Tray({ problems, onPick, onClose }) {
  const errors = problems.filter((p) => p.tone === 'bad');
  const warnings = problems.filter((p) => p.tone !== 'bad');
  const item = (p, i) => html`
    <li key=${i} class=${cx(p.tone, p.old && 'old')}>
      ${p.where ? html`<button type="button" class="eb-where" onClick=${() => onPick(p)}
                               title=${p.target ? '选中这一部分' : '在原始 JSON 里修改'}>${p.where}</button>` : null}
      <span class="eb-msg">${p.old ? p.text.replace(/（原有问题）$/, '') : p.text}</span>
      ${p.old ? html`<span class="chip muted" title="编辑开始前就有的问题，不阻止保存">原有</span>` : null}
    </li>`;
  return html`
    <div class="eb-tray" role="region" aria-label="校验结果">
      <div class="eb-tray-head">
        <b>校验结果</b>
        <span class="muted">错误必须改正才能保存；警告不阻止保存。点击位置选中对应的部分。</span>
        <button type="button" class="icon-x" aria-label="收起" title="收起" onClick=${onClose}>×</button>
      </div>
      <div class="eb-tray-body">
        ${errors.length ? html`<div class="eb-group">错误 ${errors.length}</div><ul class="eb-list">${errors.map(item)}</ul>` : null}
        ${warnings.length ? html`<div class="eb-group">警告 ${warnings.length}</div><ul class="eb-list">${warnings.map(item)}</ul>` : null}
      </div>
    </div>`;
}

// props: {ops, validation, problems, draftPending, saving, comment, onComment, onSave, onDiscard, onUndo, onRedo,
//         canUndo, canRedo, onPick(problem), trayOpen, onTray(open), onShowChanges}
export function EditBar(props) {
  const { ops, validation: v, problems, draftPending, saving, comment, onComment, onSave, onDiscard, onUndo, onRedo,
    canUndo, canRedo, onPick, trayOpen, onTray, onShowChanges } = props;
  const n = diffLines(ops).length;
  const errors = v.status !== 'failed' ? v.errors.length : 0;
  const blocked = !n ? '还没有修改' : draftPending ? '原始 JSON 里有未应用的修改：先应用或恢复'
    : errors ? `有 ${errors} 个错误，改正后才能保存` : saving ? '正在保存…' : null;
  return html`
    <div class="editbar">
      ${trayOpen && problems.length ? html`<${Tray} problems=${problems} onPick=${onPick} onClose=${() => onTray(false)} />` : null}
      <div class="eb-row">
        <div class="eb-status">
          ${n ? html`<button type="button" class="eb-pill eb-changes" onClick=${onShowChanges} title="查看未保存的修改">${n} 处修改</button>`
            : html`<span class="eb-pill eb-clean">还没有修改</span>`}
          <${CheckPill} v=${v} count=${problems.length} open=${trayOpen} onClick=${() => onTray(!trayOpen)} />
          ${draftPending ? html`<span class="eb-pill warn" title="在「原始 JSON」标签里应用或恢复">JSON 未应用</span>` : null}
        </div>
        <div class="seg eb-undo" role="group" aria-label="撤销和重做">
          <button type="button" class="btn small" disabled=${!canUndo} onClick=${onUndo} title="撤销（Ctrl+Z）" aria-label="撤销">${Icon.undo}</button>
          <button type="button" class="btn small" disabled=${!canRedo} onClick=${onRedo} title="重做（Ctrl+Shift+Z）" aria-label="重做">${Icon.redo}</button>
        </div>
        <input class="input eb-comment" value=${comment} maxlength="500" placeholder="修改说明（可选，会记在历史里）"
               aria-label="修改说明" onInput=${(e) => onComment(e.currentTarget.value)}
               onKeyDown=${(e) => { if (e.key === 'Enter') { e.preventDefault(); if (!blocked) onSave(); } }} />
        <div class="eb-actions">
          <button type="button" class="btn" disabled=${saving} onClick=${onDiscard}>${n || draftPending ? '放弃' : '退出编辑'}</button>
          <button type="button" class="btn primary eb-save" disabled=${!!blocked} onClick=${onSave}
                  title=${blocked || '保存为新版本（Ctrl+S）'}>${saving ? '保存中…' : '保存'}</button>
        </div>
      </div>
    </div>`;
}

// ------------------------------------------------------------------ dialogs

export function ChangesDialog({ ops, working, onClose }) {
  return html`
    <${Dialog} title=${`未保存的修改（${diffLines(ops).length} 处）`} width=${760} onClose=${onClose}>
      <p class="dialog-lead">每一行是：开始编辑时的值 → 现在的值。保存后，这些就是历史里这一版的改动。</p>
      <${DiffList} diff=${ops} max=${400} empty="没有修改" names=${keyNames(working)} />
    <//>`;
}

export function DiscardDialog({ count, onConfirm, onClose }) {
  return html`
    <${Dialog} title="放弃修改" width=${420} onClose=${onClose}
               footer=${html`
                 <button type="button" class="btn" onClick=${onClose} autofocus>继续编辑</button>
                 <button type="button" class="btn danger" onClick=${onConfirm}>放弃修改</button>`}>
      <p class="dialog-lead">${count ? `${count} 处修改还没有保存，放弃后无法找回。` : '原始 JSON 里的修改还没有应用，放弃后无法找回。'}</p>
    <//>`;
}

// The save found a newer version: what changed since the edit started, and what to do about it.
export function ConflictDialog({ id, baseRev, current, ops, working, busy, onReload, onOverwrite, onClose }) {
  const state = useLoad(() => getDiff(id, baseRev, 'current'), [id, baseRev, current.rev]);
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    const ok = await copyText(JSON.stringify(working, null, 2));
    setCopied(ok);
    toast(ok ? '已复制我的 JSON' : '复制失败', ok ? 'ok' : 'warn');
  };
  return html`
    <${Dialog} title=${`这条反应已被其他人修改（第 ${current.rev} 版）`} width=${760} onClose=${onClose} closeOnBackdrop=${false}
               className="conflict"
               footer=${html`
                 <button type="button" class="btn quiet conflict-copy" onClick=${copy}>${copied ? '已复制' : '复制我的 JSON'}</button>
                 <button type="button" class="btn" disabled=${busy} onClick=${onClose}>继续编辑</button>
                 <button type="button" class="btn" disabled=${busy} onClick=${onReload}>载入最新版本（放弃我的修改）</button>
                 <button type="button" class="btn primary" disabled=${busy} onClick=${onOverwrite}>在最新版本上覆盖</button>`}>
      <p class="dialog-lead">你从第 ${baseRev} 版开始编辑；之后 <b>${current.updated_by || '别人'}</b> 在 ${stamp(current.updated_at)}
        保存了第 ${current.rev} 版。这期间的改动：</p>
      ${state.data ? html`<${DiffList} diff=${state.data} max=${200} empty="数据没有变化（只是版本号变了）" names=${keyNames(current.data)} />`
        : html`<${LoadState} state=${state} what="改动" />`}
      <div class="conflict-mine">
        <b>你的 ${diffLines(ops).length} 处修改</b>还在编辑器里。
        <span class="muted">「覆盖」把你的数据存为第 ${current.rev + 1} 版，上面那些数据改动会被替换（审核状态和备注不受影响）；
          「载入最新版本」丢掉你的修改，可以先复制你的 JSON。</span>
      </div>
    <//>`;
}
