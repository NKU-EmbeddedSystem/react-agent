// The reaction list: a full table with filters when no reaction is open, a narrow column of one line
// per reaction next to the detail. Filters, sorting and the page live in the route's query, so a reload
// or Back keeps them; the selection for export is this view's own and survives paging.
import { html, useEffect, useMemo, useRef, useState } from '../lib/preact.js';
import { createReaction, getBlock, getFacets, getNeighbours, getPaper, listReactions, renderUrl } from '../lib/api.js';
import { useDebounced, useLoad, useOn } from '../lib/hooks.js';
import { emit } from '../lib/bus.js';
import { currentRoute, href, navigate, setQuery } from '../lib/router.js';
import { FLAG, KIND, LAYOUT, REVIEW_STATUS, REVIEW_TONE, clock, cx, name, stamp } from '../lib/format.js';
import { Chip, Dialog, Field, FlagChips, ReviewChip, ReviewDot } from '../components/common.js';
import { ExportDialog } from './exportdlg.js';
import { loadPapers, paperShort } from './papers.js';
import { FILTER_KEYS, FLAG_ORDER, REVIEW_ORDER, clearAll, docPage, filterParts, only, split } from './filters.js';

const PAGE = 100;

const FLAG_HINT = {
  inferred: '记录里有文献没有直接写出、由流水线推断的值',
  unresolved: '有没确定下来的成分、候选或二选一',
  issues: '记录里写了问题（issues）',
  warned: '流水线运行时报告了错误或警告',
};
// Filters next to the four flags: [label, query key, value, facet count key, hint].
const STATE_FILTERS = [
  ['已修改', 'edited', '1', 'edited', '数据和流水线版本不同，或是人工新建的'],
  ['被覆盖的旧版本', 'latest', '0', 'not_latest', '文献重新导入时被新结果替换掉的反应（只读，默认不显示）'],
];

// Loads whenever `key` changes and keeps the last answer on screen meanwhile (`stale`), so paging and
// filtering do not blank the table; `refresh` reloads the same key.
function useKept(loader, key, refresh) {
  const [state, setState] = useState({ data: null, error: null, key: null });
  useEffect(() => {
    let alive = true;
    loader().then((data) => alive && setState({ data, error: null, key }),
      (error) => alive && setState((s) => ({ data: s.key === key ? s.data : null, error, key })));
    return () => { alive = false; };
  }, [key, refresh]);
  return { ...state, stale: state.key !== key };
}

// ------------------------------------------------------------------ the view

export function ReactionList({ route, compact }) {
  const [changes, setChanges] = useState(0);
  useOn('reaction:changed', () => setChanges((n) => n + 1));
  const filters = route.filters;
  const facetQuery = only(filters, FILTER_KEYS);
  const list = useKept(() => listReactions({ ...filters, limit: PAGE }), JSON.stringify(filters), changes);
  const facets = useKept(() => getFacets(facetQuery), JSON.stringify(facetQuery), changes);
  const papers = useKept(loadPapers, 'papers', 0);
  const [selected, setSelected] = useState(() => new Set());
  const [dialog, setDialog] = useState(null);   // 'export' | 'export-selected' | 'create'
  const [recent, setRecent] = useState(route.id);
  const root = useRef(null);
  const stepped = useRef(false);   // the last move was ↑/↓ in this list: its focus goes on with it
  const body = useRef(null);

  const rows = list.data?.rows || [];
  const total = list.data?.total ?? null;
  const offset = Number(filters.offset) || 0;
  // While the next page loads the previous one stays on screen: the pager describes the rows shown.
  const shownOffset = list.stale && list.key ? Number(JSON.parse(list.key).offset) || 0 : offset;
  const linkQuery = route.query.t ? { ...filters, t: route.query.t } : filters;
  const open = (id) => navigate('reactions', id, linkQuery);

  const papersById = useMemo(() => Object.fromEntries((papers.data || []).map((p) => [p.paper_id, p])), [papers.data]);
  const names = useMemo(() => ({
    paper: Object.fromEntries((papers.data || []).map((p) => [p.paper_id, paperShort(p)])),
    block: Object.fromEntries((facets.data?.block || []).map((b) => [String(b.value), b.label])),
    import: Object.fromEntries((facets.data?.import || []).map((i) => [String(i.value), `导入 #${i.value}`])),
  }), [papers.data, facets.data]);

  useEffect(() => { if (route.id != null) setRecent(route.id); }, [route.id]);

  // A new page or filter starts at the top, unless the open reaction is on it.
  useEffect(() => {
    if (body.current && !body.current.querySelector('.is-open')) body.current.scrollTop = 0;
  }, [list.key]);

  // Keep the open reaction in view (and, back in the table from the detail, the one last opened); when
  // the list had the focus, it moves to that row so ↑/↓ go on from there.
  const wasCompact = useRef(compact);
  useEffect(() => {
    const leaving = wasCompact.current && !compact;
    wasCompact.current = compact;
    const box = body.current;
    if (!box || !list.data || (!compact && !leaving)) return;
    const row = box.querySelector(compact ? '.is-open' : '.is-recent');
    if (!row) return;
    // (A step onto another page replaces the focused row, which leaves the focus on <body>.)
    const focused = document.activeElement;
    const inList = root.current?.contains(focused) && !focused.matches('input, select, textarea');
    const dropped = stepped.current && (!focused || focused === document.body);
    if (compact && (inList || dropped)) row.focus({ preventScroll: true });
    stepped.current = false;
    // Far out of view (just opened, or back from the detail): to the middle; a step: just into view.
    const a = row.getBoundingClientRect();
    const b = box.getBoundingClientRect();
    const away = a.bottom < b.top || a.top > b.bottom;
    row.scrollIntoView({ block: away ? 'center' : 'nearest' });
  }, [route.id, compact, list.key, !!list.data]);

  // 上一条 / 下一条 in the detail can step past this page: the page follows when the reaction now open
  // is the neighbour of the first or last row.
  const lastOpen = useRef(route.id);
  useEffect(() => {
    const before = lastOpen.current;
    lastOpen.current = route.id;
    if (route.id == null || before == null || !list.data || list.stale) return undefined;
    const ids = rows.map((r) => r.id);
    if (ids.includes(route.id)) return undefined;
    const at = ids.indexOf(before);
    const forward = at === ids.length - 1 && offset + ids.length < total;
    const back = at === 0 && offset > 0;
    if (!forward && !back) return undefined;
    let alive = true;
    getNeighbours(before, filters).then((n) => {
      if (!alive) return;
      if (forward && n.next === route.id) setQuery({ offset: offset + PAGE }, { replace: true });
      else if (back && n.prev === route.id) setQuery({ offset: offset - PAGE > 0 ? offset - PAGE : '' }, { replace: true });
    }, () => {});
    return () => { alive = false; };
  }, [route.id]);

  const onKeyDown = (e) => {
    if (!compact || (e.key !== 'ArrowDown' && e.key !== 'ArrowUp')) return;
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    if (e.target.closest('input, select, textarea, [contenteditable]')) return;
    const ids = rows.map((r) => r.id);
    if (!ids.length) return;
    e.preventDefault();
    const step = e.key === 'ArrowDown' ? 1 : -1;
    // The router's route, not this render's: a second key can come before the first step re-rendered.
    const openId = currentRoute().id;
    const at = ids.indexOf(openId);
    const target = at < 0 ? ids[step > 0 ? 0 : ids.length - 1] : ids[at + step];
    stepped.current = true;
    if (target != null) {
      open(target);
      return;
    }
    // Past the end of the page: the server knows the neighbour, and the page follows (above).
    getNeighbours(openId, filters).then((n) => {
      const id = step > 0 ? n.next : n.prev;
      if (id != null) open(id);
    }, () => {});
  };

  const toggle = (id) => setSelected((s) => {
    const next = new Set(s);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });
  const togglePage = (on) => setSelected((s) => {
    const next = new Set(s);
    for (const r of rows) {
      if (on) next.add(r.id);
      else next.delete(r.id);
    }
    return next;
  });

  const hasFilters = filterParts(filters).length > 0;
  let content;
  if (list.error && !list.data) {
    content = html`
      <div class="rl-msg bad">
        <p>反应列表读取失败：${list.error.message || String(list.error)}</p>
        ${hasFilters ? html`<button type="button" class="btn small" onClick=${() => setQuery(clearAll())}>清除筛选</button>` : null}
      </div>`;
  } else if (!list.data) {
    content = html`<div class="rl-msg">正在读取反应…</div>`;
  } else if (total === 0) {
    content = html`
      <div class="rl-msg">
        ${hasFilters ? html`
          <p>没有符合筛选条件的反应。</p>
          <button type="button" class="btn small" onClick=${() => setQuery(clearAll())}>清除筛选</button>` : html`
          <p>数据库里还没有反应。</p>
          <p class="muted">先运行 <code>python -m curator import</code> 导入流水线的结果。</p>`}
      </div>`;
  } else if (!rows.length) {
    content = html`
      <div class="rl-msg">
        <p>这一页没有反应。</p>
        <button type="button" class="btn small" onClick=${() => setQuery({ offset: '' })}>回到第一页</button>
      </div>`;
  } else if (compact) {
    content = html`<${CompactRows} rows=${rows} openId=${route.id} linkQuery=${linkQuery} />`;
  } else {
    content = html`
      <${Table} rows=${rows} query=${filters} linkQuery=${linkQuery} recent=${recent} papersById=${papersById}
                selected=${selected} onToggle=${toggle} onTogglePage=${togglePage} onOpen=${open} />`;
  }

  const head = compact
    ? html`<${CompactHead} query=${filters} facets=${facets.data} names=${names} />`
    : html`
      <${FullHead} query=${filters} facets=${facets.data} names=${names} total=${total} selected=${selected}
                   onExport=${() => setDialog('export')} onExportSelected=${() => setDialog('export-selected')}
                   onCreate=${() => setDialog('create')} onClearSelection=${() => setSelected(new Set())} />`;

  return html`
    <div class=${cx('rl', compact ? 'rl-compact' : 'rl-full')} ref=${root} onKeyDown=${onKeyDown}>
      ${head}
      <div class=${cx('rl-body', list.stale && list.data && 'is-stale')} ref=${body} tabindex="-1"
           aria-busy=${list.stale ? 'true' : 'false'}>
        ${content}
      </div>
      ${list.data && total > 0 ? html`<${Pager} total=${total} offset=${offset} from=${shownOffset} shown=${rows.length} compact=${compact} />` : null}
      ${dialog === 'export' ? html`
        <${ExportDialog} filter=${facetQuery} ids=${null} names=${names} onClose=${() => setDialog(null)} />` : null}
      ${dialog === 'export-selected' ? html`
        <${ExportDialog} filter=${null} ids=${[...selected]} names=${names} onClose=${() => setDialog(null)} />` : null}
      ${dialog === 'create' ? html`
        <${CreateDialog} query=${filters} papers=${papers.data || []} onClose=${() => setDialog(null)} />` : null}
    </div>`;
}

// ------------------------------------------------------------------ heads

function FullHead({ query, facets, names, total, selected, onExport, onExportSelected, onCreate, onClearSelection }) {
  const active = filterParts(query, names).length > 0;
  return html`
    <div class="rl-head">
      <div class="rl-bar">
        <h1 class="rl-title">反应${total != null ? html`<span class="count">${total}</span>` : null}</h1>
        <${SearchBox} value=${query.q || ''} />
        <div class="rl-actions">
          <button type="button" class="btn" onClick=${onCreate} title="在一篇文献里手工新建一条反应">
            <svg width="11" height="11" viewBox="0 0 11 11" aria-hidden="true"><path d="M5.5 1v9M1 5.5h9" stroke="currentColor" stroke-width="1.5" /></svg>
            新建反应
          </button>
          <button type="button" class="btn" onClick=${onExport} disabled=${!total}
                  title="导出当前筛选出的所有反应（不只是这一页）">导出当前筛选（${total ?? 0}）</button>
        </div>
      </div>
      <div class="rl-filters">
        <${FilterSelects} query=${query} facets=${facets} names=${names} />
      </div>
      <div class="rl-chips">
        <div class="chip-group" role="group" aria-label="审核状态">
          <span class="chip-group-label">审核</span>
          <${StatusFilters} query=${query} facets=${facets} />
        </div>
        <div class="chip-group" role="group" aria-label="标记">
          <span class="chip-group-label">标记</span>
          <${FlagFilters} query=${query} facets=${facets} />
        </div>
        <${DeletedToggle} query=${query} facets=${facets} />
        ${active ? html`
          <button type="button" class="btn quiet small rl-clear" onClick=${() => setQuery(clearAll())}>清除筛选</button>` : null}
      </div>
      ${selected.size ? html`
        <div class="rl-selbar" role="status">
          <span>已选 <b>${selected.size}</b> 条</span>
          <button type="button" class="btn small primary" onClick=${onExportSelected}>导出选中（${selected.size}）</button>
          <button type="button" class="btn small quiet" onClick=${onClearSelection}>清除选择</button>
        </div>` : null}
    </div>`;
}

function CompactHead({ query, facets, names }) {
  const [open, setOpen] = useState(false);
  const parts = filterParts(query, names).filter((p) => p.key !== 'q');
  return html`
    <div class="rl-head">
      <div class="rl-bar">
        <${SearchBox} value=${query.q || ''} />
        <button type="button" class=${cx('btn', open && 'on')} aria-expanded=${open} onClick=${() => setOpen(!open)}
                title=${open ? '收起筛选' : '展开筛选'}>
          筛选${parts.length ? html`<span class="badge">${parts.length}</span>` : null}
        </button>
      </div>
      ${open ? html`
        <div class="rl-panel">
          <${FilterSelects} query=${query} facets=${facets} names=${names} />
          <div class="chip-group" role="group" aria-label="审核状态">
            <span class="chip-group-label">审核</span>
            <${StatusFilters} query=${query} facets=${facets} />
          </div>
          <div class="chip-group" role="group" aria-label="标记">
            <span class="chip-group-label">标记</span>
            <${FlagFilters} query=${query} facets=${facets} />
          </div>
          <div class="rl-panel-foot">
            <${DeletedToggle} query=${query} facets=${facets} />
            ${parts.length ? html`<button type="button" class="btn quiet small" onClick=${() => setQuery(clearAll())}>清除筛选</button>` : null}
          </div>
        </div>` : parts.length ? html`
        <div class="rl-active">
          ${parts.map((p) => html`
            <button type="button" key=${p.key + p.text} class="chip removable" title="去掉这个筛选"
                    onClick=${() => setQuery(p.patch)}>${p.text}<span aria-hidden="true">×</span></button>`)}
        </div>` : null}
    </div>`;
}

// While typing, the query follows 300 ms after the last key (replacing the history entry); Enter applies
// at once, Esc clears.
function SearchBox({ value }) {
  const [text, setText] = useState(value);
  const settled = useDebounced(text, 300);
  const apply = (t) => {
    const v = t.trim();
    if (v !== (currentRoute().query.q || '')) setQuery({ q: v }, { replace: true });
  };
  useEffect(() => { setText((t) => (t.trim() === value ? t : value)); }, [value]);
  // Only while it is still what the box holds: a timer that fires just after Esc or Enter must not
  // bring an older search back.
  useEffect(() => { if (settled === text) apply(settled); }, [settled]);
  return html`
    <label class="rl-search">
      <svg width="13" height="13" viewBox="0 0 13 13" aria-hidden="true">
        <circle cx="5.6" cy="5.6" r="4.1" fill="none" stroke="currentColor" stroke-width="1.4" />
        <path d="m8.7 8.7 3.3 3.3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
      </svg>
      <input type="search" class="input" value=${text} placeholder="搜索标签、化合物、条件、图注…" aria-label="搜索反应"
             onInput=${(e) => setText(e.currentTarget.value)}
             onKeyDown=${(e) => {
               if (e.key === 'Enter') apply(e.currentTarget.value);
               else if (e.key === 'Escape' && text) { e.stopPropagation(); setText(''); apply(''); }
             }} />
    </label>`;
}

// ------------------------------------------------------------------ filter controls

function FacetSelect({ field, label, all, items, value, text, group }) {
  const chosen = split(value);
  const visible = (items || []).filter((o) => o.value != null && (o.count > 0 || chosen.includes(String(o.value))));
  const option = (o) => html`<option key=${o.value} value=${String(o.value)}>${text(o)}（${o.count}）</option>`;
  let options = visible.map(option);
  if (group) {
    const groups = new Map();
    for (const o of visible) groups.set(group(o), [...(groups.get(group(o)) || []), o]);
    if (groups.size > 1) {
      options = [...groups].map(([g, os]) => html`<optgroup key=${g} label=${g}>${os.map(option)}</optgroup>`);
    }
  }
  const multi = chosen.length > 1;
  const unknown = chosen.length === 1 && !visible.some((o) => String(o.value) === chosen[0]);
  const current = multi ? String(value) : chosen[0] || '';
  const shown = multi ? `${chosen.length} 项` : chosen.length ? (visible.find((o) => String(o.value) === chosen[0])
    ? text(visible.find((o) => String(o.value) === chosen[0])) : chosen[0]) : all;
  return html`
    <label class=${cx('fsel', chosen.length && 'on')} title=${`${label}：${shown}`}>
      <span class="fsel-label">${label}</span>
      <select value=${current} onChange=${(e) => setQuery({ [field]: e.currentTarget.value })}>
        <option value="">${all}</option>
        ${multi ? html`<option value=${current}>${chosen.length} 项</option>` : null}
        ${unknown ? html`<option value=${chosen[0]}>${chosen[0]}</option>` : null}
        ${options}
      </select>
    </label>`;
}

function FilterSelects({ query, facets, names }) {
  const f = facets || {};
  return html`
    <${FacetSelect} field="paper" label="文献" all="全部" items=${f.paper} value=${query.paper}
                    text=${(o) => `${o.value} · ${names.paper[o.value] || o.label}`} />
    <${FacetSelect} field="figure" label="图表" all="全部" items=${f.figure} value=${query.figure}
                    text=${(o) => o.value} />
    <${FacetSelect} field="block" label="块" all="全部" items=${f.block} value=${query.block}
                    text=${(o) => o.label} group=${(o) => `文献 ${o.paper_id}${names.paper[o.paper_id] ? ` · ${names.paper[o.paper_id]}` : ''}`} />
    <${FacetSelect} field="layout" label="版式" all="全部" items=${f.layout} value=${query.layout}
                    text=${(o) => name(LAYOUT, o.value)} />
    <${FacetSelect} field="kind" label="类型" all="全部" items=${f.kind} value=${query.kind}
                    text=${(o) => name(KIND, o.value)} />
    <${FacetSelect} field="import" label="导入批次" all="全部" items=${f.import} value=${query.import}
                    text=${(o) => `#${o.value} · ${stamp(o.label)}`} />`;
}

function FilterChip({ on, count, onClick, title, children }) {
  return html`
    <button type="button" class=${cx('filter', on && 'active')} aria-pressed=${on ? 'true' : 'false'}
            disabled=${!on && count === 0} title=${title || null} onClick=${onClick}>
      ${children}${count != null ? html`<span>${count}</span>` : null}
    </button>`;
}

function StatusFilters({ query, facets }) {
  const chosen = split(query.status);
  const counts = Object.fromEntries((facets?.status || []).map((s) => [s.value, s.count]));
  return REVIEW_ORDER.map((s) => {
    const on = chosen.includes(s);
    const next = on ? chosen.filter((x) => x !== s) : [...chosen, s];
    return html`
      <${FilterChip} key=${s} on=${on} count=${counts[s]} onClick=${() => setQuery({ status: next.join(',') })}>
        <i class=${cx('dot', REVIEW_TONE[s])}></i>${REVIEW_STATUS[s]}
      <//>`;
  });
}

function FlagFilters({ query, facets }) {
  const chosen = split(query.flag);
  const counts = Object.fromEntries((facets?.flag || []).map((s) => [s.value, s.count]));
  return html`
    ${FLAG_ORDER.map((f) => {
      const on = chosen.includes(f);
      const next = on ? chosen.filter((x) => x !== f) : [...chosen, f];
      return html`
        <${FilterChip} key=${f} on=${on} count=${counts[f]} title=${FLAG_HINT[f]}
                       onClick=${() => setQuery({ flag: next.join(',') })}>${FLAG[f]}<//>`;
    })}
    ${STATE_FILTERS.map(([label, key, value, countKey, hint]) => {
      const on = query[key] === value;
      return html`
        <${FilterChip} key=${key} on=${on} count=${facets?.[countKey]} title=${hint}
                       onClick=${() => setQuery({ [key]: on ? '' : value })}>${label}<//>`;
    })}`;
}

function DeletedToggle({ query, facets }) {
  const on = query.deleted === 'all' || query.deleted === '1';
  return html`
    <label class="check rl-deleted" title="已删除的反应默认不显示；勾选后显示出来（划掉的行）">
      <input type="checkbox" checked=${on} onChange=${(e) => setQuery({ deleted: e.currentTarget.checked ? 'all' : '' })} />
      显示已删除${facets ? html`<span class="muted">${facets.deleted}</span>` : null}
    </label>`;
}

// ------------------------------------------------------------------ the table

const FIRST_DESC = new Set(['updated']);   // newest first is what one wants first

function SortTh({ col, label, cls, query, title }) {
  const active = query.sort === col;
  const order = active ? (query.order === 'desc' ? 'desc' : 'asc') : null;
  const cycle = FIRST_DESC.has(col) ? ['desc', 'asc'] : ['asc', 'desc'];
  const next = !active ? cycle[0] : order === cycle[0] ? cycle[1] : null;
  const patch = next ? { sort: col, order: next === 'asc' ? '' : 'desc' } : { sort: '', order: '' };
  const hint = next ? `按${label}${next === 'asc' ? '升序' : '降序'}排列` : '恢复印刷顺序';
  return html`
    <th class=${cls} aria-sort=${active ? (order === 'asc' ? 'ascending' : 'descending') : null}>
      <button type="button" class=${cx('th-sort', active && 'on')} title=${title ? `${title}；点击${hint}` : `点击${hint}`}
              onClick=${() => setQuery(patch)}>
        ${label}<i class="sort-mark" aria-hidden="true">${active ? (order === 'asc' ? '↑' : '↓') : '↕'}</i>
      </button>
    </th>`;
}

function Table({ rows, query, linkQuery, recent, papersById, selected, onToggle, onTogglePage, onOpen }) {
  const all = rows.every((r) => selected.has(r.id));
  const some = !all && rows.some((r) => selected.has(r.id));
  return html`
    <table class="rt">
      <thead>
        <tr>
          <th class="c-check">
            <input type="checkbox" checked=${all} indeterminate=${some} aria-label="全选本页" title="全选本页"
                   onChange=${(e) => onTogglePage(e.currentTarget.checked)} />
          </th>
          <${SortTh} col="id" label="编号" cls="c-rid" query=${query} />
          <${SortTh} col="paper" label="文献" cls="c-paper" query=${query} title="按文献，再按印刷顺序" />
          <${SortTh} col="figure" label="图表" cls="c-fig" query=${query} />
          <${SortTh} col="label" label="标签" cls="c-label" query=${query} />
          <th class="c-thumb">结构</th>
          <th class="c-rxn">反应物 → 产物</th>
          <${SortTh} col="yields" label="产率" cls="c-yield" query=${query} />
          <th class="c-cond">条件</th>
          <${SortTh} col="status" label="审核" cls="c-status" query=${query} />
          <th class="c-flags">标记</th>
          <${SortTh} col="updated" label="更新" cls="c-upd" query=${query} />
        </tr>
      </thead>
      <tbody>
        ${rows.map((r) => html`
          <${Row} key=${r.id} r=${r} link=${hrefOf(r.id, linkQuery)} recent=${r.id === recent}
                  paper=${papersById[r.paper_id]} checked=${selected.has(r.id)} onToggle=${onToggle} onOpen=${onOpen} />`)}
      </tbody>
    </table>`;
}

const hrefOf = (id, query) => href('reactions', id, query);

// The thumbnail box is about 76×40 px inside. A structure drawn small in the PDF is rendered at a higher
// dpi so that it fills the box (72 dpi at least, 144 at most, in steps of 24 so that neighbours share
// renders); the 2x source is for high-density screens.
function thumbDpi(bbox) {
  const w = bbox[2] - bbox[0] + 4;
  const h = bbox[3] - bbox[1] + 4;
  const fit = 72 * Math.min(76 / w, 40 / h);
  return Math.max(72, Math.min(144, Math.round(fit / 24) * 24));
}

function Thumb({ thumb }) {
  if (!thumb || thumb.doc_id == null || !thumb.bbox || thumb.page == null) {
    return html`<span class="thumb none" aria-hidden="true"></span>`;
  }
  const dpi = thumbDpi(thumb.bbox);
  const lo = renderUrl(thumb.doc_id, thumb.page, thumb.bbox, { dpi });
  const hi = renderUrl(thumb.doc_id, thumb.page, thumb.bbox, { dpi: dpi * 2 });
  return html`
    <span class="thumb"><img loading="lazy" decoding="async" src=${lo} srcset=${`${lo} 1x, ${hi} 2x`} alt="产物结构" /></span>`;
}

function Row({ r, link, recent, paper, checked, onToggle, onOpen }) {
  const click = (e) => {
    if (e.defaultPrevented || e.target.closest('a, input, button, label')) return;
    if (window.getSelection()?.toString()) return;   // selecting text to copy is not a click on the row
    onOpen(r.id);
  };
  const yields = ownYields(r);
  return html`
    <tr class=${cx('rt-row', recent && 'is-recent', r.deleted && 'is-deleted', checked && 'is-checked')} onClick=${click}>
      <td class="c-check">
        <input type="checkbox" checked=${checked} aria-label=${`选择 ${r.rid}`} onChange=${() => onToggle(r.id)} />
      </td>
      <td class="c-rid"><a class="rid-link" href=${link}>${r.rid}</a></td>
      <td class="c-paper" title=${paper ? `${paper.paper_id} · ${paper.title || ''}` : null}>
        <span class="cell-main">${r.paper_id}</span><span class="cell-sub">${paperShort(paper)}</span>
      </td>
      <td class="c-fig">
        <span class="cell-main">${r.figure || '—'}</span><span class="cell-sub">${docPage(r.doc, r.page)}</span>
      </td>
      <td class="c-label">
        <b class="rt-label">${r.label || '—'}</b>
        ${r.kind ? html`<span class="cell-sub sub-kind">${name(KIND, r.kind)}</span>` : null}
        <span class="cell-sub sub-fig">${r.figure || docPage(r.doc, r.page)}</span>
      </td>
      <td class="c-thumb"><${Thumb} thumb=${r.thumb} /></td>
      <td class="c-rxn" title=${`${r.reactants || '—'} → ${r.products || '—'}${r.conditions ? `\n条件：${r.conditions}` : ''}`}>
        <span class="clamp">${r.reactants || '—'}<span class="arrow"> → </span>${r.products || '—'}</span>
      </td>
      <td class="c-yield" title=${r.yields || null}>
        ${yields.length ? html`<span class="clamp">${yields.map((y, i) => html`<span key=${i} class="yield-line">${y}</span>`)}</span>`
          : html`<span class="muted-dash">—</span>`}
      </td>
      <td class="c-cond" title=${r.conditions || null}><span class="clamp">${r.conditions || '—'}</span></td>
      <td class="c-status"><${ReviewChip} status=${r.review_status} /></td>
      <td class="c-flags"><span class="flag-chips"><${RowFlags} r=${r} /></span></td>
      <td class="c-upd" title=${`${stamp(r.updated_at)} · ${r.updated_by || ''}`}>
        <span class="cell-main">${clock(r.updated_at)}</span><span class="cell-sub">${r.updated_by || ''}</span>
      </td>
    </tr>`;
}

// The yields as printed parts; the product label is left out when every part names the reaction's own
// label ("3a 87%" on reaction 3a), which is the case of most scope entries.
function ownYields(r) {
  const parts = (r.yields || '').split('; ').filter(Boolean);
  const prefix = r.label ? `${r.label} ` : null;
  return prefix && parts.length && parts.every((y) => y.startsWith(prefix)) ? parts.map((y) => y.slice(prefix.length)) : parts;
}

function RowFlags({ r }) {
  return html`
    ${r.deleted ? html`<${Chip} tone="muted">已删除<//>` : null}
    ${r.pending ? html`<${Chip} tone="warn" title="流水线有新版本，等待采用或忽略">待更新<//>` : null}
    <${FlagChips} flags=${r.flags} />
    ${r.edited ? html`<${Chip} tone="accent" title="数据和流水线版本不同，或是人工新建的">已修改<//>` : null}
    ${!r.in_latest ? html`<${Chip} tone="muted" title=${r.superseded_by != null ? `导入批次 #${r.superseded_by} 重新导入时被替换，只读` : '最近一次导入里没有这条反应'}>旧版本<//>` : null}`;
}

// ------------------------------------------------------------------ the narrow column

function CompactRows({ rows, openId, linkQuery }) {
  return html`
    <ul class="crows" aria-label="反应">
      ${rows.map((r) => html`
        <li key=${r.id}>
          <a class=${cx('crow', r.id === openId && 'is-open', r.deleted && 'is-deleted')} href=${hrefOf(r.id, linkQuery)}
             aria-current=${r.id === openId ? 'true' : null}
             title=${[r.rid, r.label, r.figure, r.yields, name(REVIEW_STATUS, r.review_status)].filter(Boolean).join(' · ')}>
            <${ReviewDot} status=${r.review_status} />
            <span class="crow-id">${r.rid}</span>
            <span class="crow-main"><b>${r.label || '—'}</b><span class="crow-fig">${r.figure || ''}</span>
              ${r.pending ? html`<i class="crow-mark" title="待更新"></i>` : null}</span>
            <span class="crow-yield">${ownYields(r).join('; ')}</span>
          </a>
        </li>`)}
    </ul>`;
}

// offset: the page asked for (the buttons go on from it); from: the offset of the rows on screen.
function Pager({ total, offset, from, shown, compact }) {
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const page = Math.floor(offset / PAGE) + 1;
  const a = shown ? from + 1 : 0;
  const b = from + shown;
  const go = (o) => setQuery({ offset: o > 0 ? o : '' });
  return html`
    <div class="rl-foot">
      <span class="rl-range">${compact ? `第 ${a}–${b} 条，共 ${total} 条` : `共 ${total} 条，第 ${a}–${b} 条`}</span>
      ${pages > 1 ? html`
        <div class="pager">
          <button type="button" class="btn small" disabled=${page <= 1} onClick=${() => go(offset - PAGE)}
                  aria-label="上一页" title="上一页">‹${compact ? '' : ' 上一页'}</button>
          <span class="pager-n">${page} / ${pages}</span>
          <button type="button" class="btn small" disabled=${page >= pages} onClick=${() => go(offset + PAGE)}
                  aria-label="下一页" title="下一页">${compact ? '' : '下一页 '}›</button>
        </div>` : null}
    </div>`;
}

// ------------------------------------------------------------------ 新建反应

const entryText = (e, n) => {
  const desc = e.descriptor ? ` — ${e.descriptor.length > 48 ? `${e.descriptor.slice(0, 47)}…` : e.descriptor}` : '';
  return `${e.eid}${e.label ? ` · ${e.label}` : ''}${desc}${n ? `（已有 ${n} 条）` : '（库里没有）'}`;
};

function CreateDialog({ query, papers, onClose }) {
  const one = (v) => (split(v).length === 1 ? split(v)[0] : '');
  const [pid, setPid] = useState(one(query.paper) || papers[0]?.paper_id || '');
  const [blockPk, setBlockPk] = useState(one(query.block));
  const [eid, setEid] = useState('');
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const paper = useLoad(() => (pid ? getPaper(pid) : Promise.resolve(null)), [pid]);
  const block = useLoad(() => (blockPk ? getBlock(blockPk) : Promise.resolve(null)), [blockPk]);
  const blocks = paper.data?.blocks || [];
  const entries = block.data?.view?.entries || [];
  const perEntry = useMemo(() => {
    const n = {};
    for (const r of block.data?.reactions || []) if (!r.deleted && r.entry_id) n[r.entry_id] = (n[r.entry_id] || 0) + 1;
    return n;
  }, [block.data]);

  // A block (and so an entry) of another paper is no choice once the paper changes.
  useEffect(() => {
    if (paper.data && blockPk && !blocks.some((b) => String(b.block_pk) === String(blockPk))) setBlockPk('');
  }, [paper.data]);
  useEffect(() => { setEid(''); }, [blockPk]);

  const submit = async (e) => {
    e.preventDefault();
    if (!pid || busy) return;
    setBusy(true);
    setError(null);
    try {
      const row = await createReaction({ paper_id: pid, block_pk: blockPk ? Number(blockPk) : null, entry_id: eid || null,
        comment: comment.trim() || null });
      emit('reaction:changed', { id: row.id });
      emit('toast', { text: `已新建 ${row.rid}`, tone: 'ok' });
      onClose();
      navigate('reactions', row.id, { ...query, edit: '1' });
    } catch (err) {
      setBusy(false);
      setError(err.status === 0 && err.message === '未设置编辑者' ? '没有填写编辑者，反应没有新建。' : err.message);
    }
  };

  return html`
    <${Dialog} title="新建反应" width=${540} onClose=${onClose} closeOnBackdrop=${false}
               footer=${html`
                 <button type="button" class="btn" onClick=${onClose}>取消</button>
                 <button type="submit" form="create-form" class="btn primary" disabled=${!pid || busy}>
                   ${busy ? '正在新建…' : '新建并编辑'}</button>`}>
      <form id="create-form" class="create-form" onSubmit=${submit}>
        <p class="dialog-lead">新反应是一条空记录，来源按所选的块和条目预先填好，建好后直接进入编辑。</p>
        <${Field} label="文献">
          <select class="select" value=${pid} onChange=${(e) => setPid(e.currentTarget.value)}>
            ${papers.map((p) => html`<option key=${p.paper_id} value=${p.paper_id}>${p.paper_id} · ${paperShort(p)} — ${p.title || ''}</option>`)}
          </select>
        <//>
        <${Field} label="来源块" hint=${blocks.length ? '可不选：不属于任何块的反应' : null}>
          <select class="select" value=${blockPk} disabled=${!paper.data} onChange=${(e) => setBlockPk(e.currentTarget.value)}>
            <option value="">${paper.data ? '不指定' : '正在读取…'}</option>
            ${blocks.map((b) => html`
              <option key=${b.block_pk} value=${String(b.block_pk)}>
                ${b.figure || b.region_id} / ${b.block_id}${b.title ? ` ${b.title}` : ''} · ${name(LAYOUT, b.layout)}（${b.reactions} 条）${b.in_latest ? '' : ' · 不在最新导入'}
              </option>`)}
          </select>
        <//>
        <${Field} label="条目" hint=${blockPk ? '可不选；括号里是库里已有的反应数' : '先选来源块'}>
          <select class="select" value=${eid} disabled=${!blockPk || !block.data} onChange=${(e) => setEid(e.currentTarget.value)}>
            <option value="">${blockPk && !block.data ? '正在读取…' : '不指定'}</option>
            ${entries.map((x) => html`<option key=${x.eid} value=${x.eid}>${entryText(x, perEntry[x.eid])}</option>`)}
          </select>
        <//>
        <${Field} label="说明" hint="可不填，会记在这条反应的第一个版本上">
          <input class="input" value=${comment} maxlength="500" placeholder="例如：流水线漏掉的条目"
                 onInput=${(e) => setComment(e.currentTarget.value)} />
        <//>
        ${error ? html`<p class="form-error" role="alert">${error}</p>` : null}
      </form>
    <//>`;
}
