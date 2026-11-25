import { html, render, useEffect, useRef, useState } from './lib/preact.js';
import { ApiError, getInfo } from './lib/api.js';
import { getAuthor, onAuthor, askAuthor, setPromptHost } from './lib/author.js';
import { useLoad, useOn, useStored } from './lib/hooks.js';
import { emit } from './lib/bus.js';
import { jumpTo } from './lib/jump.js';
import { href, listHref, navigate, useRoute } from './lib/router.js';
import { cx, displayId } from './lib/format.js';
import { Dialog, Field, WhereContext } from './components/common.js';
import { Lightbox } from './components/lightbox.js';
import { PdfPane } from './components/pdfpane.js';
import { ReactionList } from './views/list.js';
import { ReactionDetail } from './views/detail.js';
import { Papers } from './views/papers.js';
import { Imports } from './views/imports.js';

// The shell: top bar, then a grid of panes — list | detail | pdf on the reactions page, page | pdf
// elsewhere. Each pane scrolls on its own; the page never does. The PDF column is closed by default,
// opens on the PDF button or any `pdf:open`, and is resized by dragging its left edge (open/closed
// and width are kept in localStorage).

const PDF_DEFAULT = 520;
const PDF_MIN = 360;
const pdfMax = () => Math.round(innerWidth * 0.7);
const clampWidth = (w) => Math.round(Math.max(PDF_MIN, Math.min(pdfMax(), w)));

const Logo = () => html`
  <svg class="logo" width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
    <path d="M9 1.5 15.5 5.25v7.5L9 16.5 2.5 12.75v-7.5z" fill="none" stroke="currentColor" stroke-width="1.6"
          stroke-linejoin="round" />
    <circle cx="9" cy="9" r="3.5" fill="none" stroke="currentColor" stroke-width="1.4" />
  </svg>`;

// ------------------------------------------------------------------ top bar

function useAuthorName() {
  const [author, setAuthorState] = useState(getAuthor());
  useEffect(() => onAuthor(setAuthorState), []);
  return author;
}

function TopBar({ route, counts, pdfOpen, onTogglePdf, instanceLabel }) {
  const author = useAuthorName();
  const nav = [
    ['reactions', '反应', listHref(), counts?.reactions],
    ['papers', '文献', href('papers'), counts?.papers],
    ['imports', '导入记录', href('imports'), counts?.imports],
  ];
  return html`
    <header class="topbar">
      <a class="brand" href=${listHref()}><${Logo} />反应数据集</a>
      <nav class="nav" aria-label="页面">
        ${nav.map(([page, label, link, n]) => html`
          <a key=${page} class=${cx('tab', route.page === page && 'active')} href=${link}
             aria-current=${route.page === page ? 'page' : null}>
            <span>${label}${n != null ? html`<span class="tab-count">${n}</span>` : null}</span>
          </a>`)}
      </nav>
      <div class="topbar-right">
        ${instanceLabel ? html`<span class="chip warn" role="status">${instanceLabel}</span>` : null}
        <button type="button" class=${cx('who', !author && 'unset')} onClick=${() => askAuthor()}
                title=${author ? '每次修改都会记下这个名字；点击更换' : '修改前需要填写编辑者'}>
          ${author ? html`<span>编辑者</span><b>${author}</b>` : html`<b>设置编辑者</b>`}
        </button>
        <button type="button" class=${cx('btn', 'pdf-toggle', pdfOpen && 'on')} aria-pressed=${pdfOpen}
                onClick=${onTogglePdf} title=${pdfOpen ? '收起 PDF 面板' : '打开 PDF 面板'}>
          <svg width="13" height="13" viewBox="0 0 13 13" aria-hidden="true">
            <rect x="1" y="1.5" width="11" height="10" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.3" />
            <path d="M8 1.5v10" stroke="currentColor" stroke-width="1.3" />
          </svg>
          PDF
        </button>
      </div>
    </header>`;
}

// ------------------------------------------------------------------ editor name

function AuthorPrompt() {
  const [ask, setAsk] = useState(null);   // {current, reason, resolve}
  const [value, setValue] = useState('');
  useEffect(() => setPromptHost(async ({ current, reason }) => {
    // The suggestion comes first so the field opens filled and selected.
    const suggestion = current || (await getInfo().then((info) => info.default_author, () => '')) || '';
    return new Promise((resolve) => {
      setValue(suggestion);
      setAsk({ current, reason, resolve });
    });
  }), []);
  if (!ask) return null;
  const finish = (name) => {
    ask.resolve(name);
    setAsk(null);
  };
  const ok = value.trim().length > 0;
  return html`
    <${Dialog} title=${ask.current ? '更换编辑者' : '填写编辑者'} width=${420} onClose=${() => finish(null)}
               footer=${html`
                 <button type="button" class="btn" onClick=${() => finish(null)}>取消</button>
                 <button type="submit" form="author-form" class="btn primary" disabled=${!ok}>确定</button>`}>
      <form id="author-form" onSubmit=${(e) => { e.preventDefault(); if (ok) finish(value); }}>
        ${ask.reason ? html`<p class="dialog-lead">${ask.reason}</p>` : null}
        <${Field} label="编辑者" hint="名字只保存在这个浏览器里，会记在你做的每一次修改上。">
          <input class="input" autofocus value=${value} maxlength="80" placeholder="你的名字"
                 onFocus=${(e) => e.currentTarget.select()} onInput=${(e) => setValue(e.currentTarget.value)} />
        <//>
      </form>
    <//>`;
}

// ------------------------------------------------------------------ toasts

let toastSeq = 0;

function Toasts() {
  const [items, setItems] = useState([]);
  const dismiss = (id) => setItems((xs) => xs.filter((x) => x.id !== id));
  useOn('toast', (t) => {
    if (!t || !t.text) return;
    const id = ++toastSeq;
    setItems((xs) => [...xs.slice(-3), { id, text: t.text, tone: t.tone || 'ok' }]);
    setTimeout(() => dismiss(id), 4000);
  });
  return html`
    <div class="toasts" role="status" aria-live="polite">
      ${items.map((t) => html`
        <div key=${t.id} class=${cx('toast', t.tone)} onClick=${() => dismiss(t.id)}>${t.text}</div>`)}
    </div>`;
}

// ------------------------------------------------------------------ the PDF column

// The handle on the column's left edge. While dragging, the width goes straight to the grid's CSS
// variable (re-rendering the list and detail on every pointer move would be slow); it is stored
// on release, as the width the column actually got.
function Resizer({ workspace, width, onWidth }) {
  const set = (w) => workspace.current?.style.setProperty('--pdf-w', `${w}px`);
  const commit = (el) => {
    const actual = clampWidth(el.parentElement.getBoundingClientRect().width || width);
    set(actual);  // Preact leaves the style alone when the stored width does not change
    onWidth(actual);
  };
  const onPointerDown = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const el = e.currentTarget;
    el.setPointerCapture(e.pointerId);
    document.body.classList.add('resizing');
    const move = (ev) => set(clampWidth(innerWidth - ev.clientX));
    const up = () => {
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', up);
      document.body.classList.remove('resizing');
      commit(el);
    };
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
  };
  const onKeyDown = (e) => {
    const step = e.shiftKey ? 96 : 24;
    if (e.key === 'ArrowLeft') onWidth(clampWidth(width + step));
    else if (e.key === 'ArrowRight') onWidth(clampWidth(width - step));
    else return;
    e.preventDefault();
  };
  return html`
    <div class="resizer" role="separator" aria-orientation="vertical" aria-label="调整 PDF 面板宽度"
         aria-valuenow=${width} aria-valuemin=${PDF_MIN} tabindex="0" title="拖动调整宽度，双击恢复默认"
         onPointerDown=${onPointerDown} onKeyDown=${onKeyDown} onDblClick=${() => onWidth(clampWidth(PDF_DEFAULT))}></div>`;
}

// ------------------------------------------------------------------ the app

function useDocumentTitle(route) {
  useEffect(() => {
    const page = route.page === 'papers' ? (route.id ? `文献 ${route.id}` : '文献')
      : route.page === 'imports' ? '导入记录'
        : route.id != null ? (typeof route.id === 'number' ? displayId(route.id) : String(route.id)) : '反应';
    document.title = `${page} · 反应数据集`;
  }, [route.key]);
}

function App() {
  const route = useRoute();
  const [pdfOpen, setPdfOpen] = useStored('curator.pdfOpen', false);
  const [pdfWidth, setPdfWidth] = useStored('curator.pdfWidth', PDF_DEFAULT);
  const [changes, setChanges] = useState(0);
  const workspace = useRef(null);
  const detailPane = useRef(null);
  const info = useLoad(getInfo, [], { refresh: changes });

  useOn('pdf:open', () => setPdfOpen(true));
  useOn('reaction:changed', () => setChanges((n) => n + 1));
  useDocumentTitle(route);

  // A new reaction starts at its top.
  useEffect(() => { if (detailPane.current) detailPane.current.scrollTop = 0; }, [route.page, route.id]);

  const detailOpen = route.page === 'reactions' && route.id != null;
  const width = clampWidth(Number(pdfWidth) || PDF_DEFAULT);
  const closeDetail = () => navigate('reactions', null, route.filters);

  let panes;
  if (route.page === 'papers') {
    panes = html`<section class="pane pane-page" key="papers"><${Papers} route=${route} /></section>`;
  } else if (route.page === 'imports') {
    panes = html`<section class="pane pane-page" key="imports"><${Imports} route=${route} /></section>`;
  } else {
    panes = html`
      <section class="pane pane-list" key="list" aria-label="反应列表">
        <${ReactionList} route=${route} compact=${detailOpen} />
      </section>
      ${detailOpen ? html`
        <section class="pane pane-detail" key="detail" ref=${detailPane} aria-label="反应详情">
          <${ReactionDetail} key=${route.id} route=${route} onClose=${closeDetail} />
        </section>` : null}`;
  }

  // The panes before the PDF column change with the page. They sit in one wrapper (display: contents) so
  // the column's node is never moved: a moved node loses its scroll position, and pdf.js its place.
  return html`
    <${WhereContext.Provider} value=${jumpTo}>
      <div class="app">
        <${TopBar} route=${route} counts=${info.data?.counts} pdfOpen=${pdfOpen} instanceLabel=${info.data?.instance_label}
                   onTogglePdf=${() => setPdfOpen(!pdfOpen)} />
        <main class=${cx('workspace', detailOpen && 'has-detail', pdfOpen && 'has-pdf')} ref=${workspace}
              style=${{ '--pdf-w': `${width}px` }}>
          <div class="panes">${panes}</div>
          <aside class="pane-pdf" key="pdf" hidden=${!pdfOpen} aria-label="PDF">
            <${Resizer} workspace=${workspace} width=${width} onWidth=${setPdfWidth} />
            <div class="pdf-host">
              <${PdfPane} open=${pdfOpen} onClose=${() => setPdfOpen(false)} />
            </div>
          </aside>
        </main>
        <${Toasts} />
        <${AuthorPrompt} />
        <${Lightbox} />
      </div>
    <//>`;
}

// A failed request nobody caught still tells the person what happened (and is not a silent console
// line): a cancelled editor prompt as a warning, anything else as an error.
addEventListener('unhandledrejection', (e) => {
  if (!(e.reason instanceof ApiError)) return;
  e.preventDefault();
  const cancelled = e.reason.status === 0 && e.reason.message === '未设置编辑者';
  emit('toast', { text: cancelled ? '没有填写编辑者，这次修改没有保存' : e.reason.message,
    tone: e.reason.status === 0 ? 'warn' : 'bad' });
});

render(html`<${App} />`, document.getElementById('app'));
