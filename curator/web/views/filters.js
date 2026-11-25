// The list's filters as words, and the query a batch export would take. Shared by the list, its
// export dialog and the pages that link into the list. No preact here.
import { DOC, FLAG, KIND, LAYOUT, REVIEW_STATUS, name } from '../lib/format.js';

export const REVIEW_ORDER = ['unreviewed', 'reviewed', 'problem', 'excluded'];
export const FLAG_ORDER = Object.keys(FLAG);

// Query keys that narrow the list (everything else is paging, sorting or the detail's own).
export const FILTER_KEYS = ['paper', 'figure', 'block', 'layout', 'kind', 'import', 'status', 'flag', 'edited',
  'pending', 'latest', 'deleted', 'q', 'ids', 'scope'];
export const PAGING_KEYS = ['offset', 'sort', 'order', 'limit'];

export const split = (value) => String(value ?? '').split(',').map((s) => s.trim()).filter(Boolean);

export function only(query, keys) {
  const out = {};
  for (const k of keys) if (query?.[k] != null && query[k] !== '') out[k] = query[k];
  return out;
}

// A patch that removes every filter (sorting stays).
export const clearAll = () => Object.fromEntries(FILTER_KEYS.map((k) => [k, '']));

// The active filters, one part per thing a person chose: {key, text, patch} where `patch` removes it.
// `names` resolves ids to words: {paper: id → text, block: pk → text, import: id → text}.
export function filterParts(query, names = {}) {
  const parts = [];
  const add = (key, text, patch) => parts.push({ key, text, patch: patch || { [key]: '' } });
  const listed = (key, fn) => {
    const values = split(query[key]);
    if (values.length) add(key, values.map(fn).join('、'));
  };
  listed('paper', (v) => `文献 ${names.paper?.[v] ? `${v} ${names.paper[v]}` : v}`);
  listed('figure', (v) => v);
  listed('block', (v) => names.block?.[v] || `块 #${v}`);
  listed('layout', (v) => name(LAYOUT, v));
  listed('kind', (v) => name(KIND, v));
  listed('import', (v) => names.import?.[v] || `导入 #${v}`);
  for (const s of split(query.status)) {
    const rest = split(query.status).filter((x) => x !== s);
    add('status', name(REVIEW_STATUS, s), { status: rest.join(',') });
  }
  for (const f of split(query.flag)) {
    const rest = split(query.flag).filter((x) => x !== f);
    add('flag', name(FLAG, f), { flag: rest.join(',') });
  }
  if (query.pending === '1') add('pending', '待更新');
  if (query.pending === '0') add('pending', '没有待更新');
  if (query.edited === '1') add('edited', '已修改');
  if (query.edited === '0') add('edited', '未修改');
  if (query.latest === '0') add('latest', '被覆盖的旧版本');
  if (query.latest === 'all') add('latest', '含被覆盖的旧版本');
  if (query.deleted === 'all') add('deleted', '含已删除');
  if (query.deleted === '1') add('deleted', '只看已删除');
  if (query.q) add('q', `搜索“${query.q}”`);
  if (query.ids) add('ids', `指定的 ${split(query.ids).length} 条`);
  return parts;
}

export const describeFilters = (query, names) => filterParts(query || {}, names).map((p) => p.text).join(' · ');

// The list query that selects what POST /api/export would write (export.select_ids): the filters, the
// chosen ids, without excluded and deleted reactions unless asked. Null when nothing can match.
export function exportQuery(filter, ids, { include_excluded = false, include_deleted = false } = {}) {
  const q = only(filter || {}, FILTER_KEYS);
  if (ids) q.ids = ids.join(',');
  if (!ids && !split(q.flag).includes('auxiliary')) q.scope = 'core';
  if (!include_excluded) {
    const statuses = (q.status ? split(q.status) : REVIEW_ORDER).filter((s) => s !== 'excluded');
    if (!statuses.length) return null;
    q.status = statuses.join(',');
  }
  if (include_deleted) {
    if (!q.deleted) q.deleted = 'all';
  } else {
    if (q.deleted === '1') return null;
    q.deleted = '0';
  }
  return q;
}

export const docPage = (doc, page) => [name(DOC, doc), page != null ? `p${page}` : ''].filter(Boolean).join(' ');
