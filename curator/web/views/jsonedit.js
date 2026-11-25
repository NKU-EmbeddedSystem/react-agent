import { html, useMemo, useRef, useState } from '../lib/preact.js';
import { toast } from '../lib/bus.js';
import { cx } from '../lib/format.js';
import { copyText } from './jsonview.js';

// The working copy as editable JSON, for every field the inspector has no form for. The text is a
// draft until 应用: it replaces the working copy only when it parses (a parse error is shown with its
// line and column and the caret is put there); 恢复 throws the draft away.
//
// props: {working, draft, onDraft(draft|null), onApply(data)}; draft = {text, base} is kept by the
// detail so it survives a change of tab, `base` being the working copy it was started from.

const pretty = (data) => JSON.stringify(data, null, 2) ?? 'null';

// Line and column (1-based) of a character offset.
function lineCol(text, offset) {
  const before = text.slice(0, offset);
  const line = before.split('\n').length;
  return { line, col: offset - before.lastIndexOf('\n') };
}

// Where JSON.parse stopped, from its message ("… at position 123 (line 5 column 3)" in Chrome,
// "… at line 5 column 3 …" in Firefox).
function parseError(text, e) {
  const msg = String(e?.message || e);
  const pos = /position (\d+)/.exec(msg);
  let offset = pos ? Number(pos[1]) : null;
  let at = offset != null ? lineCol(text, offset) : null;
  const lc = /line (\d+) column (\d+)/.exec(msg);
  if (lc) {
    at = { line: Number(lc[1]), col: Number(lc[2]) };
    if (offset == null) {
      const lines = text.split('\n');
      offset = lines.slice(0, at.line - 1).reduce((n, l) => n + l.length + 1, 0) + at.col - 1;
    }
  }
  if (/Unexpected end of JSON input|end of data/i.test(msg)) {
    offset = text.length;
    at = lineCol(text, offset);
  }
  return { offset, at, message: msg };
}

export function JsonEdit({ working, draft, onDraft, onApply }) {
  const area = useRef(null);
  const [error, setError] = useState(null);
  const [caret, setCaret] = useState({ line: 1, col: 1 });
  const current = useMemo(() => pretty(working), [working]);
  const text = draft ? draft.text : current;
  const pending = !!draft && draft.text !== current;
  const stale = !!draft && draft.base !== working;

  const setText = (t) => {
    setError(null);
    onDraft(t === current ? null : { text: t, base: draft?.base ?? working });
  };
  const moveCaret = (el) => {
    const { line, col } = lineCol(el.value, el.selectionStart);
    setCaret({ line, col });
  };
  const jump = (offset) => {
    const el = area.current;
    if (!el || offset == null) return;
    el.focus();
    el.setSelectionRange(offset, Math.min(el.value.length, offset + 1));
    // Bring the line into view: the textarea scrolls to the selection only on some browsers.
    const { line } = lineCol(el.value, offset);
    const lh = parseFloat(getComputedStyle(el).lineHeight) || 18;
    el.scrollTop = Math.max(0, (line - 4) * lh);
    moveCaret(el);
  };
  const apply = () => {
    let data;
    try {
      data = JSON.parse(text);
    } catch (e) {
      const err = parseError(text, e);
      setError(err);
      jump(err.offset);
      return;
    }
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      setError({ offset: null, at: null, message: '记录应为一个 JSON 对象（{ … }）' });
      return;
    }
    setError(null);
    onApply(data);
    onDraft(null);
  };
  const reset = () => {
    setError(null);
    onDraft(null);
  };
  const copy = async () => {
    const ok = await copyText(text);
    toast(ok ? '已复制 JSON' : '复制失败，请手动选择文字复制', ok ? 'ok' : 'warn');
  };
  const onKeyDown = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      apply();
    } else if (e.key === 'Tab' && !e.shiftKey && !e.ctrlKey && !e.altKey) {
      // Two spaces, as the text is indented; Shift+Tab still leaves the field.
      e.preventDefault();
      const el = e.currentTarget;
      const [a, b] = [el.selectionStart, el.selectionEnd];
      el.setRangeText('  ', a, b, 'end');
      setText(el.value);
    }
  };

  return html`
    <section class="card dcard jsonedit">
      <div class="jsonview-bar">
        <h3>原始 JSON</h3>
        <span class=${cx('je-state', pending && 'pending')}>${pending ? '有未应用的修改' : '与工作副本一致'}</span>
        <span class="muted je-caret">第 ${caret.line} 行，第 ${caret.col} 列</span>
        <span class="je-actions">
          <button type="button" class="btn small quiet" onClick=${copy}>复制</button>
          <button type="button" class="btn small" disabled=${!pending} onClick=${reset} title="丢掉这里的修改，回到工作副本">恢复</button>
          <button type="button" class="btn small primary" disabled=${!pending} onClick=${apply} title="Ctrl+Enter">应用</button>
        </span>
      </div>
      ${stale && pending ? html`
        <div class="je-note warn">开始改 JSON 之后，表单里又有了修改；应用会用这里的文字整个替换工作副本（包括那些修改）。</div>` : null}
      ${error ? html`
        <div class="je-note bad" role="alert">
          <b>JSON 解析失败${error.at ? `：第 ${error.at.line} 行，第 ${error.at.col} 列` : ''}</b>
          <span class="je-msg">${error.message}</span>
          ${error.offset != null ? html`<button type="button" class="btn small" onClick=${() => jump(error.offset)}>定位</button>` : null}
        </div>` : null}
      <textarea ref=${area} class=${cx('je-text', error && 'invalid')} spellcheck="false" autocomplete="off"
                autocapitalize="off" aria-label="原始 JSON" value=${text}
                onInput=${(e) => { setText(e.currentTarget.value); moveCaret(e.currentTarget); }}
                onKeyUp=${(e) => moveCaret(e.currentTarget)} onClick=${(e) => moveCaret(e.currentTarget)}
                onKeyDown=${onKeyDown}></textarea>
      <div class="je-foot muted">应用后才会进入工作副本并参与校验；保存仍用下方的保存栏。<kbd>Ctrl</kbd>+<kbd>Enter</kbd> 应用。</div>
    </section>`;
}
