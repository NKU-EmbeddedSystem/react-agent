import { createContext, html, useContext, useLayoutEffect, useMemo, useRef } from '../lib/preact.js';
import { DOC, FLAG, FLAG_TONE, REVIEW_STATUS, REVIEW_TONE, cx, name, origin, originShort, where } from '../lib/format.js';
import { jumpTo } from '../lib/jump.js';

export const Dot = ({ tone, title }) => html`<span class=${cx('dot', tone)} title=${title || null}></span>`;

// A small label. Colour is kept for what needs attention: tone is one of
// plain (default), origin, accent, ok, warn, bad, infer, muted.
export const Chip = ({ tone, title, children }) =>
  html`<span class=${cx('chip', tone)} title=${title || null}>${children}</span>`;

// ------------------------------------------------------------------ places in the PDF

// What a click on a place does: (at) => void, at = {doc, page, paperId?, docId?, bbox?}. The shell
// provides jumpTo (needs paperId or docId in `at`); a view of one paper wraps its content in
// <WhereScope paperId docs> so the bare {doc, page} of the data is enough.
export const WhereContext = createContext(null);

export function WhereScope({ paperId, docs, children }) {
  const value = useMemo(() => (at) => jumpTo({ paperId, ...at, docId: at.docId ?? docs?.[at.doc]?.doc_id }),
    [paperId, docs]);
  return html`<${WhereContext.Provider} value=${value}>${children}<//>`;
}

// Where the paper states something outside the block: "SI p5"; a click opens the PDF there.
export function Where({ at }) {
  const jump = useContext(WhereContext);
  if (!at) return null;
  if (!jump) return html`<${Chip} tone="accent">${where(at)}<//>`;
  const open = (e) => {
    e.stopPropagation();
    jump({ doc: at.doc, page: at.page });
  };
  return html`
    <button type="button" class="chip accent chip-link" onClick=${open}
            title=${`在 PDF 中打开：${name(DOC, at.doc)}第 ${at.page} 页`}>${where(at)}</button>`;
}

// ------------------------------------------------------------------ marks on values

// Which layer set a value; nothing for the scheme's own (base) values.
export const Origin = ({ value }) => {
  const text = originShort(value);
  return text ? html`<${Chip} tone="origin" title=${`这个值来自：${origin(value)}`}>${text}<//>` : null;
};

// Something the document does not state: the reasoning shows on hover.
export const Inferred = ({ mark }) =>
  (mark ? html`<${Chip} tone="infer" title=${mark.basis}>推断<//>` : null);

export const ReviewChip = ({ status }) =>
  html`<${Chip} tone=${REVIEW_TONE[status]}>${name(REVIEW_STATUS, status)}<//>`;

export const ReviewDot = ({ status }) =>
  html`<${Dot} tone=${REVIEW_TONE[status]} title=${name(REVIEW_STATUS, status)} />`;

export const FlagChips = ({ flags = [] }) =>
  flags.map((f) => html`<${Chip} key=${f} tone=${FLAG_TONE[f]}>${name(FLAG, f)}<//>`);

// ------------------------------------------------------------------ states and containers

export const Empty = ({ children }) => html`<div class="empty">${children}</div>`;

export const Problems = ({ errors = [], warnings = [] }) =>
  (errors.length + warnings.length === 0 ? null : html`
    <ul class="problems">
      ${errors.map((x) => html`<li class="bad">${x}</li>`)}
      ${warnings.map((x) => html`<li class="warn">${x}</li>`)}
    </ul>`);

export const Disclosure = ({ summary, open, children }) => html`
  <details class="disclosure" open=${open || null}>
    <summary>${summary}</summary>
    <div class="disclosure-body">${children}</div>
  </details>`;

export function LoadState({ state, what }) {
  if (state.error && !state.data) return html`<${Empty}>${what}读取失败：${String(state.error.message || state.error)}<//>`;
  if (!state.data) return html`<${Empty}>正在读取${what}…<//>`;
  return null;
}

// A labelled form control: <Field label="备注"><input class="input" …/></Field>.
export const Field = ({ label, hint, wide, children }) => html`
  <label class=${cx('field', wide && 'wide')}>
    <span class="field-label">${label}</span>
    ${children}
    ${hint ? html`<small class="field-hint">${hint}</small>` : null}
  </label>`;

// ------------------------------------------------------------------ dialogs

// Open dialogs, innermost last: only the innermost one takes Esc.
const stack = [];
export const dialogOpen = () => stack.length > 0;

// A modal dialog. Esc and the × close it (onClose); so does a click on the backdrop unless
// `closeOnBackdrop` is false (forms that would lose typing). The first [autofocus] element, else
// the first field, gets the focus; it goes back where it was on close.
export function Dialog({ title, onClose, children, footer, headerActions, width = 480, closeOnBackdrop = true, className }) {
  const panel = useRef(null);
  const close = useRef(onClose);
  close.current = onClose;
  const downOnBackdrop = useRef(false);
  // A layout effect: Esc works from the moment the dialog is on screen.
  useLayoutEffect(() => {
    const me = {};
    stack.push(me);
    const before = document.activeElement;
    const first = panel.current?.querySelector('[autofocus]')
      || panel.current?.querySelector('input:not([type=checkbox]):not([type=radio]), textarea, select');
    (first || panel.current)?.focus();
    const onKey = (e) => {
      if (e.key !== 'Escape' || stack[stack.length - 1] !== me) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      close.current?.();
    };
    addEventListener('keydown', onKey, true);
    return () => {
      removeEventListener('keydown', onKey, true);
      stack.splice(stack.indexOf(me), 1);
      if (before && document.contains(before)) before.focus?.();
    };
  }, []);
  return html`
    <div class="modal" onMouseDown=${(e) => { downOnBackdrop.current = e.target === e.currentTarget; }}
         onClick=${(e) => { if (closeOnBackdrop && downOnBackdrop.current && e.target === e.currentTarget) onClose?.(); }}>
      <div class=${cx('modal-panel', className)} ref=${panel} role="dialog" aria-modal="true" aria-label=${title}
           tabindex="-1" style=${`width: min(${typeof width === 'number' ? `${width}px` : width}, calc(100vw - 48px))`}>
        <div class="modal-head">
          <h3>${title}</h3>
          ${headerActions || null}
          <button type="button" class="modal-x" aria-label="关闭" title="关闭（Esc）" onClick=${() => onClose?.()}>×</button>
        </div>
        <div class="modal-body">${children}</div>
        ${footer ? html`<div class="modal-foot">${footer}</div>` : null}
      </div>
    </div>`;
}
