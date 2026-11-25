import { html, useEffect, useMemo, useRef, useState } from '../lib/preact.js';
import {
  ApiError, acceptPending, copyReaction, deleteReaction, dismissPending, exportOneUrl, getBlock, getDiff,
  getNeighbours, getReaction, restoreReaction, reviewReaction, updateReaction,
} from '../lib/api.js';
import { emit, toast } from '../lib/bus.js';
import { useLoad, useOn } from '../lib/hooks.js';
import { jumpTo } from '../lib/jump.js';
import { currentRoute, guard, href, navigate, setQuery } from '../lib/router.js';
import { DOC, LAYOUT, REVIEW_STATUS, cx, displayId, keyNames, name, stamp } from '../lib/format.js';
import { getIn, pathKey, setIn } from '../lib/paths.js';
import { Chip, Dialog, Empty, Field, LoadState, Where, WhereScope, dialogOpen } from '../components/common.js';
import { lightboxOpen } from '../components/lightbox.js';
import { Reaction } from './reaction.js';
import { BlockFigure, reactionBoxes } from './blockfig.js';
import { DiffDialog, History, diffLines } from './history.js';
import { JsonView } from './jsonview.js';
import { JsonEdit } from './jsonedit.js';
import { Inspector } from './inspector.js';
import { ChangesDialog, ConflictDialog, DiscardDialog, EditBar } from './editbar.js';
import {
  applyBox, blank, changedParts, clone, diff, drawTarget, exists, list, parseProblems, pushHistory, redo, undo,
  useEditorInfo, useValidation,
} from './editing.js';
import { Provenance } from './provenance.js';

// One reaction next to the list: a header (who it is, where it is printed, its review state and what
// can be done with it), banners for states that need a decision, and four tabs — the reaction, its
// source block, its history and its JSON.
//
// Edit mode: 编辑 copies the data into a working copy, which every view below then shows; clicks on its
// parts select them for the inspector (a column next to the views), the JSON tab becomes editable, a
// save bar holds the comment and 保存. The working copy is checked by the server as it changes, saved
// with the rev it started from (a newer rev → the conflict dialog), and guarded against leaving.

const STATUSES = ['unreviewed', 'reviewed', 'problem', 'excluded'];
const TABS = [['reaction', '反应'], ['block', '来源块'], ['history', '历史'], ['json', '原始 JSON']];
const tabOf = (route) => (TABS.some(([t]) => t === route.tab) ? route.tab : 'reaction');

// "Zhang 等, J. Am. Chem. Soc. 2024": enough to recognise a paper in a header.
function paperShort(p) {
  if (!p) return null;
  const authors = (p.authors || '').trim();
  const etal = /\s*(et al\.?|等)\s*$/i;
  const first = authors.replace(etal, '').split(/[,;，；]|\band\b/)[0].trim();
  const surname = first.split(/\s+/).pop();
  const many = etal.test(authors) || /[,;，；]|\band\b/.test(authors);
  const who = surname ? `${surname}${many ? ' 等' : ''}` : null;
  const where = [p.journal, p.year].filter(Boolean).join(' ');
  return [who, where].filter(Boolean).join(', ') || p.title || `文献 ${p.paper_id}`;
}

const typing = (el) => el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
// A field with its own text undo (Ctrl+Z there is the browser's, not the editor's).
const textField = (el) => el && (el.isContentEditable || el.tagName === 'TEXTAREA'
  || (el.tagName === 'INPUT' && !/^(checkbox|radio|button|submit|reset|range|color|file)$/i.test(el.type)));

// A [ or ] pressed while this detail gives way to the next one (the route has moved, the page has not
// re-rendered yet): {key, id}, carried out by the detail of reaction `id` only.
let carriedStep = null;

const EMPTY_EDIT = { editing: false, working: null, base: null, baseRev: null, selected: null, past: [], future: [],
  lastKey: null, lastAt: 0, draft: null };
const refuseText = (doc) => `框必须画在本反应的来源文档（${name(DOC, doc) || doc}）上`;

const Icon = {
  prev: html`<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M8.5 3 4.5 7l4 4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  next: html`<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="m5.5 3 4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  close: html`<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="m3.5 3.5 7 7m0-7-7 7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>`,
};

// ------------------------------------------------------------------ header parts

function ReviewBar({ row, busy, onReview }) {
  const [note, setNote] = useState(row.review_note || '');
  // A new version (from here or elsewhere) brings its own note.
  useEffect(() => setNote(row.review_note || ''), [row.rev, row.id]);
  const changed = note.trim() !== (row.review_note || '');
  const submit = (status) => {
    if (status === row.review_status && !changed) return;
    onReview(status, note);
  };
  return html`
    <div class="review">
      <div class="seg review-seg" role="group" aria-label="审核状态">
        ${STATUSES.map((s) => html`
          <button type="button" key=${s} class=${cx('btn', 'rv', `rv-${s}`, row.review_status === s && 'on')}
                  aria-pressed=${row.review_status === s ? 'true' : 'false'} disabled=${busy}
                  onClick=${() => submit(s)}>${name(REVIEW_STATUS, s)}</button>`)}
      </div>
      <input class="input review-note" value=${note} maxlength="2000" aria-label="审核备注"
             placeholder="审核备注（回车保存）" disabled=${busy}
             onInput=${(e) => setNote(e.currentTarget.value)}
             onKeyDown=${(e) => {
               if (e.key === 'Enter') { e.preventDefault(); submit(row.review_status); }
               if (e.key === 'Escape' && changed) { e.preventDefault(); e.stopPropagation(); setNote(row.review_note || ''); }
             }} />
      ${changed ? html`
        <button type="button" class="btn small primary" disabled=${busy} onClick=${() => submit(row.review_status)}>保存备注</button>` : null}
    </div>`;
}

function Banner({ tone, children, actions }) {
  return html`
    <div class=${cx('banner', tone)} role="status">
      <div class="banner-text">${children}</div>
      ${actions ? html`<div class="banner-actions">${actions}</div>` : null}
    </div>`;
}

// A yes/no question about a change, with an optional comment for the history.
function ConfirmDialog({ title, lead, confirm, danger, onConfirm, onClose, children }) {
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const go = async () => {
    if (busy) return;
    setBusy(true);
    const ok = await onConfirm(comment.trim() || null);
    setBusy(false);
    if (ok) onClose();
  };
  return html`
    <${Dialog} title=${title} width=${480} onClose=${onClose} closeOnBackdrop=${false}
               footer=${html`
                 <button type="button" class="btn" onClick=${onClose}>取消</button>
                 <button type="button" class=${cx('btn', danger ? 'danger' : 'primary')} disabled=${busy} onClick=${go}>${confirm}</button>`}>
      ${lead ? html`<p class="dialog-lead">${lead}</p>` : null}
      ${children}
      <${Field} label="备注（可选）" hint="会记在这次修改的历史里">
        <input class="input" autofocus value=${comment} maxlength="500" placeholder="说明原因"
               onInput=${(e) => setComment(e.currentTarget.value)}
               onKeyDown=${(e) => { if (e.key === 'Enter') { e.preventDefault(); go(); } }} />
      <//>
    <//>`;
}

// ------------------------------------------------------------------ the detail

export function ReactionDetail({ route, onClose }) {
  const id = route.id;
  const [row, setRow] = useState(null);
  const [failed, setFailed] = useState(null);
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState(null);   // 'delete' | 'restore' | 'accept' | 'dismiss' | 'pending'
  const [edit, setEdit] = useState(EMPTY_EDIT);
  const editRef = useRef(edit);
  editRef.current = edit;
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);
  const [trayOpen, setTrayOpen] = useState(false);
  const [editDialog, setEditDialog] = useState(null);   // 'changes' | 'discard' | 'since' | {conflict: row}
  const [drawing, setDrawing] = useState(null);         // {path, req, session}: a box being drawn
  const [reveal, setReveal] = useState(0);              // bumped to scroll the inspector to an error
  const drawRef = useRef(null);
  drawRef.current = drawing;
  const info = useEditorInfo();
  const rowRef = useRef(null);
  rowRef.current = row;
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const reload = () => getReaction(id).then((r) => {
    // A read that started before one of our own changes may answer after it: revs only go up.
    if (!alive.current || (rowRef.current && r.rev < rowRef.current.rev)) return;
    rowRef.current = r;
    setRow(r);
    setFailed(null);
  }, (e) => {
    if (!alive.current) return;
    if (!rowRef.current) setFailed(e);
    else toast(`重新读取 ${displayId(id)} 失败：${e.message || e}`, 'bad');
  });
  useEffect(() => { reload(); }, [id]);
  // Someone changed it (another view, another tab of the list): show the stored version.
  useOn('reaction:changed', (p) => {
    if (p && p.id != null && p.id !== id) return;
    if (p && p.rev != null && rowRef.current?.rev === p.rev) return;
    reload();
  });

  const data = edit.editing && edit.working ? edit.working : row?.data;
  const tab = tabOf(route);
  const blockState = useLoad(() => (row?.block_pk != null ? getBlock(row.block_pk) : Promise.resolve(null)),
    [row?.block_pk ?? null]);
  const nbState = useLoad(() => getNeighbours(id, route.filters), [id, route.filters], { refresh: row?.rev ?? null });
  const nb = nbState.data;
  const nbRef = useRef(null);
  nbRef.current = nb;

  // Where a reaction's links go: the list keeps its filters, the tab stays.
  const linkQuery = { ...route.filters, t: route.query.t };
  const go = (target) => navigate('reactions', target, linkQuery);

  // The PDF pane draws this reaction's boxes faintly (and forgets them when the detail closes).
  const docId = row?.documents?.[data?.source?.doc]?.doc_id ?? null;
  useEffect(() => {
    if (data) emit('pdf:boxes', { docId, boxes: reactionBoxes(data) });
  }, [docId, data]);
  useEffect(() => () => emit('pdf:boxes', { docId: null, boxes: [] }), []);

  // ---------------------------------------------------------------- edit state (hooks)

  // The changes since editing started, as the history will show them, and what they touch.
  const ops = useMemo(() => (edit.editing ? diff(edit.base, edit.working) : []), [edit.editing, edit.base, edit.working]);
  const changed = useMemo(() => changedParts(ops, edit.working), [ops]);
  const draftPending = !!edit.draft;
  const dirty = ops.length > 0 || draftPending;
  const validation = useValidation({ editing: edit.editing, working: edit.working, row, baseRev: edit.baseRev });
  const problems = useMemo(() => (edit.editing ? parseProblems(validation, edit.working) : []),
    [edit.editing, validation.errors, validation.warnings, edit.working]);

  // Unsaved changes: leaving the reaction (another one, the list, another page) or the page asks first.
  useEffect(() => {
    if (!dirty) return undefined;
    const off = guard((next) => (next.page === 'reactions' && next.id === id ? null
      : `${displayId(id)} 还有未保存的修改，离开后会丢失。确定离开吗？`));
    const unload = (e) => {
      e.preventDefault();
      e.returnValue = '';
    };
    addEventListener('beforeunload', unload);
    return () => {
      off();
      removeEventListener('beforeunload', unload);
    };
  }, [dirty, id]);

  // A reaction made by hand or copied arrives with ?edit=1: open it in edit mode, once.
  const autoEdit = useRef(false);
  useEffect(() => {
    if (!row || !route.edit || autoEdit.current) return;
    autoEdit.current = true;
    if (!edit.editing && row.superseded_by == null) begin(row);
    setQuery({ edit: '' }, { replace: true });
  }, [row, route.edit]);

  // Every surface leaves draw mode with the detail (or the drawing ends elsewhere: the pane's 取消).
  useOn('draw:end', () => {
    if (!drawRef.current) return;
    drawRef.current = null;
    setDrawing(null);
  });
  useEffect(() => () => { if (drawRef.current) emit('draw:end', {}); }, []);
  // The PDF pane only takes a drag on the document it was asked for; a drag on the other one (its tab
  // switched by hand) would silently do nothing, so say why.
  useEffect(() => {
    if (!drawing) return undefined;
    const onDown = (e) => {
      if (!e.target.closest?.('.pdfp-host .page')) return;
      const shown = document.querySelector('.pdfp-docs [aria-selected="true"]')?.textContent.trim();
      if (shown && shown !== name(DOC, drawing.req.doc)) toast(refuseText(drawing.req.doc), 'warn');
    };
    addEventListener('pointerdown', onDown, true);
    return () => removeEventListener('pointerdown', onDown, true);
  }, [drawing]);

  // Ctrl+S saves; Ctrl+Z / Ctrl+Shift+Z undo and redo outside text fields (inside, the field's own).
  const saveRef = useRef(null);
  useEffect(() => {
    if (!edit.editing) return undefined;
    const onKey = (e) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === 's') {
        e.preventDefault();
        if (!dialogOpen()) saveRef.current?.();
        return;
      }
      if (dialogOpen() || lightboxOpen() || textField(e.target)) return;
      if (k === 'z' && !e.shiftKey) {
        e.preventDefault();
        setEdit(undo);
      } else if ((k === 'z' && e.shiftKey) || k === 'y') {
        e.preventDefault();
        setEdit(redo);
      }
    };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
  }, [edit.editing]);

  function begin(r) {
    if (r.superseded_by != null) return;  // an old version is read-only
    setEdit({ ...EMPTY_EDIT, editing: true, working: clone(r.data), base: clone(r.data), baseRev: r.rev, selected: [] });
    setComment('');
    setTrayOpen(false);
  }
  function leave() {
    if (drawRef.current) emit('draw:end', {});
    setEdit(EMPTY_EDIT);
    setComment('');
    setTrayOpen(false);
    setEditDialog(null);
  }

  // [ and ] step through the list as it is filtered. A key pressed before this reaction's neighbours
  // are known (right after the previous step) is kept and carried out when they arrive.
  const queuedStep = useRef(null);
  useEffect(() => {
    if (carriedStep?.id === id) queuedStep.current = carriedStep.key;
    carriedStep = null;
  }, []);
  const stepTo = (key, n) => {
    const target = key === '[' ? n?.prev : n?.next;
    if (target != null) navigate('reactions', target, { ...route.filters, t: route.query.t });
  };
  useEffect(() => {
    const onKey = (e) => {
      if ((e.key !== '[' && e.key !== ']') || e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
      if (typing(e.target) || dialogOpen() || lightboxOpen()) return;
      e.preventDefault();
      const now = currentRoute();
      if (now.page !== 'reactions' || now.id !== id) {
        if (now.page === 'reactions' && now.id != null) carriedStep = { key: e.key, id: now.id };
      } else if (nbRef.current) {
        stepTo(e.key, nbRef.current);
      } else {
        queuedStep.current = e.key;
      }
    };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
  }, [route.key]);
  useEffect(() => {
    if (!nb || !queuedStep.current) return;
    const key = queuedStep.current;
    queuedStep.current = null;
    stepTo(key, nb);
  }, [nb]);

  if (!row) {
    return html`
      <div class="detail">
        <div class="detail-loading">
          ${failed ? html`
            <${Empty}>
              <p>${failed.status === 404 ? `没有反应 ${displayId(id)}` : `读取失败：${failed.message || failed}`}</p>
              <p><button type="button" class="btn" onClick=${onClose}>回到列表</button></p>
            <//>` : html`<${LoadState} state=${{ data: null, error: null }} what="反应" />`}
        </div>
      </div>`;
  }

  // ---------------------------------------------------------------- changes

  const apply = (next) => {
    rowRef.current = next;
    setRow(next);
    emit('reaction:changed', { id: next.id, rev: next.rev });
  };
  const fail = (e) => {
    if (e instanceof ApiError && e.status === 409 && e.body?.current) {
      apply(e.body.current);
      toast(`这条反应刚被修改过（现在是第 ${e.body.current.rev} 版），已载入最新版本，请再操作一次`, 'warn');
    } else if (e instanceof ApiError && e.status === 0 && e.message === '未设置编辑者') {
      toast('没有填写编辑者，这次修改没有保存', 'warn');
    } else {
      toast(e.message || String(e), 'bad');
    }
  };
  // Runs a change of this reaction; resolves true when it went through.
  const run = async (fn, ok) => {
    setBusy(true);
    try {
      const next = await fn();
      apply(next);
      if (ok) toast(typeof ok === 'function' ? ok(next) : ok);
      return true;
    } catch (e) {
      fail(e);
      return false;
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const review = (status, note) => run(
    () => reviewReaction(id, { base_rev: row.rev, status, note: note.trim() || null }),
    (next) => (status !== row.review_status ? `已标为「${name(REVIEW_STATUS, next.review_status)}」` : '已保存审核备注'),
  );
  const copy = async () => {
    setBusy(true);
    try {
      const made = await copyReaction(id, {});
      emit('reaction:changed', { id: made.id, rev: made.rev });
      toast(`已复制为 ${made.rid}`);
      // A copy is a current reaction: out of the archive view if the original was an old version.
      const { latest, ...filters } = route.filters;
      navigate('reactions', made.id, { ...(row.superseded_by != null ? filters : route.filters), edit: '1' });
    } catch (e) {
      fail(e);
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  const locate = () => {
    const src = data?.source || {};
    if (src.page == null) {
      toast('这条反应没有页码，无法在 PDF 中定位', 'warn');
      return;
    }
    jumpTo({ paperId: row.paper_id, doc: src.doc, docId, page: src.page, bbox: src.entry_bbox || null,
      label: [row.rid, data.label].filter(Boolean).join(' '), boxes: reactionBoxes(data) });
  };
  const select = (path) => setEdit((s) => ({ ...s, selected: path }));
  const setTab = (t) => setQuery({ t: t === 'reaction' ? '' : t }, { replace: true });

  // ---------------------------------------------------------------- editing

  // One value of the working copy. Typing into one field makes one undo step; {separate} for the rest.
  const change = (path, value, opts = {}) => setEdit((s) => (s.editing
    ? pushHistory(s, setIn(s.working, path, value), opts.separate ? null : `${pathKey(path)}`) : s));
  // A blank item appended to a list of the working copy (the + buttons of the equation), then selected.
  const add = (listPath, kind) => setEdit((s) => {
    if (!s.editing) return s;
    const items = list(getIn(s.working, listPath));
    const next = pushHistory(s, setIn(s.working, listPath, [...items, blank(info, s.working, kind, listPath)]), null);
    return { ...next, selected: [...listPath, items.length] };
  });
  const applyJson = (data) => setEdit((s) => {
    const next = pushHistory(s, data, null);
    return { ...next, selected: exists(data, s.selected) ? s.selected : [] };
  });
  const setDraft = (draft) => setEdit((s) => ({ ...s, draft }));

  // 框选: the block figure (this detail passes it the request) and the PDF pane (bus) take one drag.
  const startDraw = (path) => {
    const w = edit.working;
    const target = drawTarget(w, path);
    if (!target) return;
    const doc = w?.source?.doc;
    const did = row.documents?.[doc]?.doc_id ?? null;
    if (did == null) {
      toast(`这篇文献没有「${name(DOC, doc) || doc || '来源文档'}」的 PDF，不能框选`, 'warn');
      return;
    }
    if (drawRef.current) emit('draw:end', {});
    const session = {};
    const mine = () => drawRef.current?.session === session;
    // The part is found again by its key when the drag ends: lists may change while drawing.
    const key = path.length > 1 ? getIn(w, path)?.key : null;
    const same = (data) => path.length <= 1 || getIn(data, path)?.key === key;
    const end = () => {
      drawRef.current = null;
      setDrawing(null);
      emit('draw:end', {});
    };
    const req = {
      doc, docId: did, label: target.label,
      onDone: ({ page, bbox }) => {
        if (!mine()) return;
        end();
        if (!same(editRef.current.working)) {
          toast(`「${target.label}」已经不在原来的位置，框没有写入`, 'warn');
          return;
        }
        setEdit((s) => (s.editing ? { ...pushHistory(s, applyBox(s.working, path, { page, bbox }), null), selected: path } : s));
        toast(`已更新「${target.label}」的框（第 ${page} 页）`);
      },
      onCancel: () => { if (mine()) end(); },
    };
    const d = { path, req, session };
    drawRef.current = d;
    setDrawing(d);
    select(path);
    if (tab !== 'block') setTab('block');
    emit('draw:start', req);
  };
  const cancelDraw = () => drawRef.current?.req.onCancel();

  const finishSave = (next, baseRev) => {
    const same = next.rev === baseRev;
    apply(next);
    leave();
    const warned = (next.warnings || []).length;
    toast(same ? '数据和保存的版本相同，没有新增版本'
      : `已保存 ${next.rid}，现在是第 ${next.rev} 版${warned ? `（${warned} 个警告）` : ''}`, same ? 'warn' : 'ok');
  };
  const save = async (baseRev = edit.baseRev) => {
    if (!edit.editing || saving) return;
    if (draftPending) {
      toast('原始 JSON 里有未应用的修改：先应用或恢复', 'warn');
      return;
    }
    if (!ops.length && baseRev === edit.baseRev) {
      toast('还没有修改', 'warn');
      return;
    }
    if (validation.status === 'done' && validation.errors.length) {
      setTrayOpen(true);
      toast(`有 ${validation.errors.length} 个错误，改正后才能保存`, 'bad');
      return;
    }
    setSaving(true);
    try {
      const next = await updateReaction(id, { base_rev: baseRev, data: edit.working, comment: comment.trim() || null });
      if (alive.current) finishSave(next, baseRev);
    } catch (e) {
      if (!alive.current) return;
      if (e instanceof ApiError && e.status === 409 && e.body?.current) {
        rowRef.current = e.body.current;
        setRow(e.body.current);
        setEditDialog({ conflict: e.body.current });
      } else if (e instanceof ApiError && e.status === 422) {
        validation.setServer(e.body);
        setTrayOpen(true);
        toast(`${e.message}：${(e.body?.errors || []).length} 个错误`, 'bad');
      } else {
        fail(e);
      }
    } finally {
      if (alive.current) setSaving(false);
    }
  };
  saveRef.current = () => save();
  // The conflict dialog: my data on top of the newer version (its data is the base of the diff now).
  const overwrite = () => {
    const cur = editDialog?.conflict;
    if (!cur) return;
    setEditDialog(null);
    setEdit((s) => ({ ...s, base: clone(cur.data), baseRev: cur.rev }));
    save(cur.rev);
  };
  const reloadLatest = () => {
    const cur = editDialog?.conflict;
    leave();
    if (cur) toast(`已载入第 ${cur.rev} 版，你的修改已放弃`);
  };
  const discard = () => (dirty ? setEditDialog('discard') : leave());
  // A problem of the checks: select the part it is about (or open the JSON when no form has it).
  const pickProblem = (p) => {
    if (p.target) {
      select(p.target);
      setReveal((n) => n + 1);
      if (tab === 'json' || tab === 'history') setTab('reaction');
    } else {
      setTab('json');
    }
  };

  // ---------------------------------------------------------------- render

  const src = data?.source || {};
  const paper = row.paper;
  const pending = row.pending;
  const editing = edit.editing;
  const editProps = { editing, selected: edit.selected, onSelect: select };
  const showInspector = editing && (tab === 'reaction' || tab === 'block');
  const lock = busy || editing;   // actions that change the stored reaction wait while it is being edited
  // An old version: its paper was imported again and the new results replaced it. Read-only.
  const old = row.superseded_by != null;

  const banners = html`
    ${editing && row.rev !== edit.baseRev ? html`
      <${Banner} tone="warn" actions=${html`<button type="button" class="btn small" onClick=${() => setEditDialog('since')}>查看改动</button>`}>
        <b>你编辑时这条反应被修改了</b>　现在是第 ${row.rev} 版（你从第 ${edit.baseRev} 版开始）；保存时可以选择覆盖或载入最新版本。
      <//>` : null}
    ${old ? html`
      <${Banner} tone="info" actions=${html`<a class="btn small" href=${href('imports')}>导入记录</a>`}>
        <b>旧版本</b>　这篇文献在导入批次 #${row.superseded_by}${row.superseded?.started_at ? `（${stamp(row.superseded.started_at)}）` : ''}重新导入时，
        这条反应被新的提取结果替换了：它已不在当前数据里（列表默认不显示，导出也不包含），只能查看。要沿用这里的修改，可以复制成一条新的反应。
      <//>` : null}
    ${row.deleted ? html`
      <${Banner} tone="bad" actions=${old ? null : html`<button type="button" class="btn small" disabled=${lock} onClick=${() => setDialog('restore')}>恢复</button>`}>
        <b>已删除</b>　列表默认不显示这条反应，导出也不包含它；恢复后一切照旧。
      <//>` : null}
    ${pending ? html`
      <${Banner} tone="warn" actions=${html`
        <button type="button" class="btn small" onClick=${() => setDialog('pending')}>查看差异</button>
        <button type="button" class="btn small primary" disabled=${lock} onClick=${() => setDialog('accept')}>采用</button>
        <button type="button" class="btn small" disabled=${lock} onClick=${() => setDialog('dismiss')}>忽略</button>`}>
        <b>流水线有新版本（导入 #${pending.import_id}）</b>　这条反应被人修改或审核过，导入时没有覆盖它${
          Array.isArray(pending.diff) ? `；共 ${pending.diff.length} 处不同` : ''}。
      <//>` : null}
    ${!old && row.origin_id && row.in_latest === false ? html`
      <${Banner} tone="info"><b>不在最新导入中</b>　最近一次导入这篇文献时，流水线没有输出这条反应。<//>` : null}`;

  const content = html`
    ${tab === 'reaction' ? html`
      <${Reaction} row=${row} data=${data} docs=${row.documents} ...${editProps} changed=${editing ? changed : null}
                   onAdd=${editing ? add : null} />
      <${Provenance} row=${row} data=${data} block=${blockState.data} query=${linkQuery} onTab=${setTab} ...${editProps} />` : null}
    ${tab === 'block' ? (row.block_pk != null && !blockState.data
      ? html`<${LoadState} state=${blockState} what="来源块" />`
      : html`<${BlockFigure} row=${row} data=${data} block=${blockState.data} docs=${row.documents} query=${linkQuery}
                             onPickEntry=${go} drawing=${drawing?.req || null} ...${editProps} />`) : null}
    ${tab === 'history' ? html`<${History} id=${id} row=${row} onReverted=${apply} />` : null}
    ${tab === 'json' ? (editing
      ? html`<${JsonEdit} working=${edit.working} draft=${edit.draft} onDraft=${setDraft} onApply=${applyJson} />`
      : html`<${JsonView} data=${data} />`) : null}`;

  return html`
    <${WhereScope} paperId=${row.paper_id} docs=${row.documents}>
      <div class=${cx('detail', row.deleted && 'is-deleted', editing && 'is-editing')}>
        <header class="dh">
          <div class="dh-row dh-ident">
            <span class="dh-rid mono" title="反应编号">${row.rid}</span>
            <h2 class="dh-label">${data?.label || html`<span class="muted">（无标签）</span>`}</h2>
            ${data?.variant ? html`<${Chip} tone="accent" title=${[`条件套 ${data.variant.key || ''}`, data.variant.notes].filter(Boolean).join('：')}>${data.variant.title || data.variant.key}<//>` : null}
            ${old ? html`<${Chip} tone="muted" title=${`导入批次 #${row.superseded_by} 重新导入时被替换，只读`}>旧版本<//>` : null}
            ${row.deleted ? html`<${Chip} tone="bad">已删除<//>` : null}
            ${pending ? html`<${Chip} tone="warn">待更新<//>` : null}
            ${row.edited ? html`<${Chip} tone="accent" title=${row.origin_id ? '数据和流水线版本不同' : '人工新建或复制的反应'}>已修改<//>` : null}
            <div class="dh-nav">
              <button type="button" class="icon-btn" disabled=${nb?.prev == null} onClick=${() => go(nb.prev)}
                      title="上一条（[）" aria-label="上一条">${Icon.prev}</button>
              <button type="button" class="icon-btn" disabled=${nb?.next == null} onClick=${() => go(nb.next)}
                      title="下一条（]）" aria-label="下一条">${Icon.next}</button>
              <button type="button" class="icon-btn" onClick=${onClose} title="关闭，回到列表" aria-label="关闭">${Icon.close}</button>
            </div>
          </div>
          <div class="dh-row dh-context">
            <span class="dh-ctx-main">
              ${paper ? html`<a class="dh-paper" href=${href('papers', row.paper_id)} title=${paper.title || ''}>${paperShort(paper)}</a>` : null}
              ${src.figure ? html`<span class="dh-sep">·</span><span>${src.figure}</span>` : null}
              ${src.doc && src.page != null ? html`<span class="dh-sep">·</span><${Where} at=${{ doc: src.doc, page: src.page }} />` : null}
              ${row.layout ? html`<span class="dh-sep">·</span><span class="muted">${name(LAYOUT, row.layout)}</span>` : null}
            </span>
            ${row.block?.title ? html`
              <span class="dh-blockpart"><span class="dh-sep">·</span><span class="muted dh-block" title=${row.block.title}>${row.block.title}</span></span>` : null}
          </div>
          ${editing ? html`
            <div class="dh-row dh-tools dh-edit">
              <span class="edit-badge"><i></i>编辑中</span>
              <span class="dh-edit-base">基于第 ${edit.baseRev} 版</span>
              <span class="dh-edit-hint">点击反应式或来源块里的部分，在${showInspector ? '右侧' : '检查器里'}修改；<kbd>Ctrl</kbd>+<kbd>S</kbd> 保存</span>
              <div class="dh-actions">
                <button type="button" class="btn" onClick=${locate} title="打开 PDF 并跳到这条反应的条目">在 PDF 中定位</button>
              </div>
            </div>` : html`
            <div class="dh-row dh-tools">
              ${old ? html`<span class="dh-readonly muted">旧版本只读：审核状态 ${name(REVIEW_STATUS, row.review_status)}${
                row.review_note ? `，备注：${row.review_note}` : ''}</span>` : html`<${ReviewBar} row=${row} busy=${busy} onReview=${review} />`}
              <div class="dh-actions">
                ${old ? null : html`<button type="button" class="btn" disabled=${busy} onClick=${() => begin(row)} title="编辑这条反应的数据">编辑</button>`}
                <button type="button" class="btn" disabled=${busy} onClick=${copy}
                        title=${old ? '复制成当前数据里的一条新反应（人工），然后编辑它' : '复制成一条新的反应（人工），然后编辑它'}>复制</button>
                ${old ? null : row.deleted
                  ? html`<button type="button" class="btn" disabled=${busy} onClick=${() => setDialog('restore')}>恢复</button>`
                  : html`<button type="button" class="btn danger" disabled=${busy} onClick=${() => setDialog('delete')}>删除</button>`}
                <a class="btn" href=${exportOneUrl(id)} download=${`${row.rid}.json`} title="下载这条反应的导出 JSON">导出 JSON</a>
                <button type="button" class="btn" onClick=${locate} title="打开 PDF 并跳到这条反应的条目">在 PDF 中定位</button>
              </div>
            </div>`}
          <nav class="dtabs" role="tablist" aria-label="反应详情">
            ${TABS.map(([t, label]) => html`
              <button type="button" key=${t} role="tab" aria-selected=${tab === t ? 'true' : 'false'}
                      class=${cx('dtab', tab === t && 'active')} onClick=${() => setTab(t)}>
                ${label}${t === 'history' ? html`<span class="tab-count">${row.rev}</span>` : null}
                ${t === 'json' && editing ? html`<span class=${cx('tab-edit', draftPending && 'pending')}
                    title=${draftPending ? '有未应用的修改' : '可以编辑'}>${draftPending ? '未应用' : '可编辑'}</span>` : null}
              </button>`)}
          </nav>
        </header>

        ${editing ? html`
          <div class=${cx('edit-body', showInspector && 'with-inspector')}>
            <div class="edit-main">
              <div class="dbody">${banners}${content}</div>
            </div>
            ${showInspector ? html`
              <aside class="inspector-pane" aria-label="检查器">
                <${Inspector} working=${edit.working} selected=${edit.selected} docs=${row.documents} info=${info}
                              block=${blockState.data} problems=${problems} drawing=${drawing?.path || null}
                              onChange=${change} onSelect=${select} onDraw=${startDraw} onCancelDraw=${cancelDraw}
                              onTab=${setTab} reveal=${reveal} />
              </aside>` : null}
          </div>
          <${EditBar} ops=${ops} validation=${validation} problems=${problems} draftPending=${draftPending} saving=${saving}
                      comment=${comment} onComment=${setComment} onSave=${() => save()} onDiscard=${discard}
                      onUndo=${() => setEdit(undo)} onRedo=${() => setEdit(redo)} canUndo=${edit.past.length > 0}
                      canRedo=${edit.future.length > 0} onPick=${pickProblem} trayOpen=${trayOpen} onTray=${setTrayOpen}
                      onShowChanges=${() => setEditDialog('changes')} />`
          : html`<div class="dbody">${banners}${content}</div>`}
      </div>

      ${editDialog === 'changes' ? html`<${ChangesDialog} ops=${ops} working=${edit.working} onClose=${() => setEditDialog(null)} />` : null}
      ${editDialog === 'discard' ? html`
        <${DiscardDialog} count=${diffLines(ops).length} onClose=${() => setEditDialog(null)}
                          onConfirm=${() => { leave(); toast('已放弃修改'); }} />` : null}
      ${editDialog === 'since' ? html`
        <${DiffDialog} title=${`你开始编辑后的改动（第 ${edit.baseRev} 版 → 第 ${row.rev} 版）`} onClose=${() => setEditDialog(null)}
                       lead="别人（或另一个页面）在你编辑期间保存的改动。" empty="数据没有变化"
                       load=${() => getDiff(id, edit.baseRev, 'current')} names=${keyNames(row.data)} />` : null}
      ${editDialog?.conflict ? html`
        <${ConflictDialog} id=${id} baseRev=${edit.baseRev} current=${editDialog.conflict} ops=${ops} working=${edit.working}
                           busy=${saving} onReload=${reloadLatest} onOverwrite=${overwrite} onClose=${() => setEditDialog(null)} />` : null}
      ${dialog === 'delete' ? html`
        <${ConfirmDialog} title=${`删除 ${row.rid}`} confirm="删除" danger onClose=${() => setDialog(null)}
                          lead="删除只是做一个标记：列表默认不显示，导出不包含，历史都还在，随时可以恢复。"
                          onConfirm=${(comment) => run(() => deleteReaction(id, { base_rev: row.rev, comment }), `已删除 ${row.rid}`)} />` : null}
      ${dialog === 'restore' ? html`
        <${ConfirmDialog} title=${`恢复 ${row.rid}`} confirm="恢复" onClose=${() => setDialog(null)}
                          lead="恢复后这条反应重新出现在列表和导出里。"
                          onConfirm=${(comment) => run(() => restoreReaction(id, { base_rev: row.rev, comment }), `已恢复 ${row.rid}`)} />` : null}
      ${dialog === 'accept' ? html`
        <${ConfirmDialog} title="采用流水线新版本" confirm="采用" onClose=${() => setDialog(null)}
                          lead="用流水线的新版本替换现在的数据（人工改动会被覆盖，但都留在历史里，可以回退）。审核状态不变。"
                          onConfirm=${(comment) => run(() => acceptPending(id, { base_rev: row.rev, comment }), '已采用流水线新版本')} />` : null}
      ${dialog === 'dismiss' ? html`
        <${ConfirmDialog} title="忽略流水线新版本" confirm="忽略" onClose=${() => setDialog(null)}
                          lead="保留现在的数据。这个流水线版本以后不再提示；更新的版本出现时会再提示。"
                          onConfirm=${(comment) => run(() => dismissPending(id, { base_rev: row.rev, comment }), '已忽略流水线新版本')} />` : null}
      ${dialog === 'pending' ? html`
        <${DiffDialog} title=${`流水线新版本（导入 #${pending?.import_id ?? '?'}）与当前数据的差异`}
                       lead="每一行是：现在的值 → 流水线新版本里的值。"
                       empty="数据相同（只是流水线的记录变了）" onClose=${() => setDialog(null)}
                       load=${() => getDiff(id, 'current', 'pending')} names=${keyNames(row.data)}
                       footer=${html`
                         <button type="button" class="btn" onClick=${() => setDialog('dismiss')}>忽略</button>
                         <button type="button" class="btn primary" onClick=${() => setDialog('accept')}>采用新版本</button>`} />` : null}
    <//>`;
}
