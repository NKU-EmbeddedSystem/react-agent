// Every call to the curator server (curator/server.py). Answers are the store's dicts as they are;
// failures throw ApiError {status, message, body} (body = the server's JSON: `error`, plus `current`
// on 409 and `errors`/`warnings` on 422). Mutations add `author` themselves and ask for a name first
// when none is set (ApiError(0, '未设置编辑者') if the person cancels).
import { ensureAuthor } from './author.js';

export class ApiError extends Error {
  constructor(status, message, body = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

const enc = encodeURIComponent;

// Keys of a route query that are the page's own, not filters of the API.
const UI_KEYS = new Set(['t', 'edit']);
const PAGING_KEYS = new Set(['offset', 'limit', 'sort', 'order']);

// A query string from a plain object: empty values dropped, lists comma-joined (the server's
// convention for several values), commas left readable.
export function qs(query, { drop = UI_KEYS } = {}) {
  const parts = [];
  for (const [k, v] of Object.entries(query || {})) {
    if (drop.has(k) || v == null || v === '' || v === false) continue;
    const value = Array.isArray(v) ? v.join(',') : v === true ? '1' : String(v);
    if (value === '') continue;
    parts.push(`${enc(k)}=${enc(value).replace(/%2C/gi, ',')}`);
  }
  return parts.join('&');
}

const withQuery = (url, query) => {
  const s = qs(query);
  return s ? `${url}?${s}` : url;
};

async function failure(res) {
  let body = null;
  try {
    body = await res.json();
  } catch { /* not JSON (a proxy, a crash): keep the status text */ }
  const message = (body && body.error) || `${res.status} ${res.statusText || '请求失败'}`;
  return new ApiError(res.status, message, body);
}

export async function request(method, url, body) {
  const init = { method, headers: { Accept: 'application/json' } };
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(url, init);
  } catch (e) {
    throw new ApiError(0, `连不上服务器：${e.message || e}`);
  }
  if (!res.ok) throw await failure(res);
  return res.status === 204 ? null : res.json();
}

const get = (url) => request('GET', url);

async function mutate(method, url, body = {}) {
  const author = await ensureAuthor();
  if (!author) throw new ApiError(0, '未设置编辑者');
  return request(method, url, { ...body, author });
}

// ------------------------------------------------------------------ documents (cached)
// doc_ids of a paper's documents never change once imported, so they are kept for the whole session.
// Filled from every answer that lists documents; detail answers also bring `pages` (sizes + to_pdf).

const docsByPaper = new Map();   // paperId → {doc: {doc_id, filename, page_count, pages?}}
const docsById = new Map();      // docId → {doc_id, paper_id, doc, filename, page_count, pages?}
const docsLoading = new Map();   // paperId → Promise

// documents: {doc: {...}} (reaction, paper) or [{doc, doc_id, ...}] (paper list).
export function rememberDocs(paperId, documents) {
  if (paperId == null || !documents) return;
  const pid = String(paperId);
  const list = Array.isArray(documents) ? documents : Object.entries(documents).map(([doc, d]) => ({ ...d, doc }));
  const known = { ...(docsByPaper.get(pid) || {}) };
  for (const d of list) {
    if (!d || d.doc_id == null || !d.doc) continue;
    const merged = { ...(known[d.doc] || {}), ...d };
    if (!d.pages && known[d.doc]?.pages) merged.pages = known[d.doc].pages;
    known[d.doc] = merged;
    docsById.set(String(d.doc_id), { ...merged, paper_id: pid });
  }
  docsByPaper.set(pid, known);
}

// {doc: {doc_id, filename, page_count, pages?}} of a paper.
export function paperDocs(paperId) {
  const pid = String(paperId);
  if (docsByPaper.has(pid)) return Promise.resolve(docsByPaper.get(pid));
  if (!docsLoading.has(pid)) {
    docsLoading.set(pid, getPaper(pid).then(() => docsByPaper.get(pid) || {})
      .finally(() => docsLoading.delete(pid)));
  }
  return docsLoading.get(pid);
}

export async function docIdOf(paperId, doc) {
  if (paperId == null || !doc) return null;
  return (await paperDocs(paperId))[doc]?.doc_id ?? null;
}

// What is known about a document by its id (synchronous; null if nothing has listed it yet).
export const docById = (docId) => docsById.get(String(docId)) || null;

// ------------------------------------------------------------------ reads

export const getInfo = () => get('/api/info');
export const getFacets = (query) => get(withQuery('/api/facets', query));
export const listReactions = (query) => get(withQuery('/api/reactions', query));
export async function getReaction(id) {
  const row = await get(`/api/reactions/${enc(id)}`);
  rememberDocs(row.paper_id, row.documents);
  return row;
}
export const getNeighbours = (id, query) => get(withQuery(`/api/reactions/${enc(id)}/neighbours`, query));
export const getHistory = (id) => get(`/api/reactions/${enc(id)}/history`);
export const getRevision = (id, rev) => get(`/api/reactions/${enc(id)}/revisions/${enc(rev)}`);
export const getDiff = (id, from, to = 'current') =>
  get(`/api/reactions/${enc(id)}/diff?from=${enc(from)}&to=${enc(to)}`);

export async function listPapers() {
  const papers = await get('/api/papers');
  for (const p of papers) rememberDocs(p.paper_id, p.documents);
  return papers;
}
export async function getPaper(pid) {
  const paper = await get(`/api/papers/${enc(pid)}`);
  rememberDocs(paper.paper_id, paper.documents);
  return paper;
}
export const getPaperHistory = (pid) => get(`/api/papers/${enc(pid)}/history`);
export const getBlock = (pk) => get(`/api/blocks/${enc(pk)}`);
export const listImports = () => get('/api/imports');

// The save checks without saving (no author needed).
export const validate = ({ paper_id, data, base_rev, id }) =>
  request('POST', '/api/validate', { paper_id, data, base_rev, id });

// ------------------------------------------------------------------ changes

const r = (id, tail = '') => `/api/reactions/${enc(id)}${tail}`;

export const updateReaction = (id, { base_rev, data, comment }) => mutate('PUT', r(id), { base_rev, data, comment });
export const reviewReaction = (id, { base_rev, status, note, comment }) =>
  mutate('POST', r(id, '/review'), { base_rev, status, note, comment });
export const revertReaction = (id, { base_rev, to_rev, comment }) =>
  mutate('POST', r(id, '/revert'), { base_rev, to_rev, comment });
export const copyReaction = (id, { comment } = {}) => mutate('POST', r(id, '/copy'), { comment });
export const createReaction = ({ paper_id, block_pk, entry_id, comment }) =>
  mutate('POST', '/api/reactions', { paper_id, block_pk, entry_id, comment });
export const deleteReaction = (id, { base_rev, comment }) => mutate('POST', r(id, '/delete'), { base_rev, comment });
export const restoreReaction = (id, { base_rev, comment }) => mutate('POST', r(id, '/restore'), { base_rev, comment });
export const acceptPending = (id, { base_rev, comment }) =>
  mutate('POST', r(id, '/pending/accept'), { base_rev, comment });
export const dismissPending = (id, { base_rev, comment }) =>
  mutate('POST', r(id, '/pending/dismiss'), { base_rev, comment });
export const updatePaper = (pid, { base_rev, fields, comment }) =>
  mutate('PUT', `/api/papers/${enc(pid)}`, { base_rev, fields, comment });

// ------------------------------------------------------------------ files

export const pdfUrl = (docId) => `/api/docs/${enc(docId)}/pdf`;

const tenth = (v) => Math.round(v * 10) / 10 + 0;

// A rendered PNG of a page, or of bbox ± pad on it (bbox null: the whole page). Values are rounded as
// the server rounds them, so equal pictures share one URL and the browser cache.
export function renderUrl(docId, page, bbox, { dpi = 150, pad = 2 } = {}) {
  let url = `/api/docs/${enc(docId)}/render?page=${enc(page)}`;
  if (bbox) url += `&bbox=${bbox.map(tenth).join(',')}&pad=${tenth(pad)}`;
  return `${url}&dpi=${Math.round(dpi)}`;
}

export const exportOneUrl = (id) => `/api/export/reactions/${enc(id)}.json`;

function filename(disposition, fallback) {
  const star = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(disposition || '');
  if (star) {
    try { return decodeURIComponent(star[1].trim()); } catch { /* fall through */ }
  }
  const plain = /filename\s*=\s*"([^"]+)"/i.exec(disposition || '');
  return plain ? plain[1] : fallback;
}

// Hands a Blob to the browser as a download.
export function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

// A batch export as a file download. filter: a route query (UI and paging keys are left out) or null;
// ids: reaction ids or null. Resolves {count, filename} once the download has been handed over.
export async function exportBatch({ filter = null, ids = null, format = 'jsonl', images = false,
  include_excluded = false, include_deleted = false } = {}) {
  const cleaned = filter ? Object.fromEntries(Object.entries(filter)
    .filter(([k, v]) => !UI_KEYS.has(k) && !PAGING_KEYS.has(k) && v != null && v !== '')) : null;
  let res;
  try {
    res = await fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filter: cleaned, ids, format, images, include_excluded, include_deleted }),
    });
  } catch (e) {
    throw new ApiError(0, `连不上服务器：${e.message || e}`);
  }
  if (!res.ok) throw await failure(res);
  const blob = await res.blob();
  const name = filename(res.headers.get('Content-Disposition'), `reactions.${format}`);
  saveBlob(blob, name);
  return { count: Number(res.headers.get('X-Export-Count') || 0), filename: name };
}
