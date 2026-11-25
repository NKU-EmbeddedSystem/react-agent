import { html, useMemo } from '../lib/preact.js';
import { toast } from '../lib/bus.js';

// A record as pretty-printed JSON, read-only, with a copy button. Keys, strings, numbers and
// literals are coloured; nothing is collapsed (find-in-page has to see everything).

const TOKEN = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;

// The JSON text as strings and spans (no innerHTML: the text is the data's own).
function tokens(text) {
  const out = [];
  let last = 0;
  let m;
  TOKEN.lastIndex = 0;
  while ((m = TOKEN.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] !== undefined) {
      out.push(html`<span class=${m[2] ? 'j-key' : 'j-str'}>${m[1]}</span>`);
      if (m[2]) out.push(m[2]);
    } else if (m[3] !== undefined) {
      out.push(html`<span class=${m[3] === 'null' ? 'j-null' : 'j-bool'}>${m[3]}</span>`);
    } else {
      out.push(html`<span class="j-num">${m[0]}</span>`);
    }
    last = TOKEN.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// Copies text to the clipboard; the old way when the async API is not available (or refused).
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = Object.assign(document.createElement('textarea'), { value: text });
    area.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch { ok = false; }
    area.remove();
    return ok;
  }
}

// props: {data, title?, compact?}; `compact` drops the outer card (inside a dialog).
export function JsonView({ data, title = '原始 JSON', compact = false }) {
  const text = useMemo(() => JSON.stringify(data, null, 2) ?? 'null', [data]);
  const parts = useMemo(() => tokens(text), [text]);
  const lines = useMemo(() => text.split('\n').length, [text]);
  const copy = async () => {
    const ok = await copyText(text);
    toast(ok ? '已复制 JSON' : '复制失败，请手动选择文字复制', ok ? 'ok' : 'warn');
  };
  return html`
    <section class=${compact ? 'jsonview compact' : 'card dcard jsonview'}>
      <div class="jsonview-bar">
        ${compact ? null : html`<h3>${title}</h3>`}
        <span class="muted">${lines} 行 · ${(new Blob([text]).size / 1024).toFixed(1)} KB · 只读</span>
        <button type="button" class="btn small" onClick=${copy}>复制</button>
      </div>
      <pre class="json">${parts}</pre>
    </section>`;
}
