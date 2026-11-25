import { useEffect, useState } from './preact.js';

// Hash routes. The query after `?` holds the list's filters, so a reload or Back keeps them; `t` is
// the detail tab and `edit=1` opens a reaction in edit mode.
//   #/?paper=1&status=unreviewed&q=3a&sort=label&order=asc&offset=100   the reactions
//   #/r/<id>?<same filters>&t=reaction|block|history|json                 one reaction next to the list
//   #/papers, #/papers/<paper_id>, #/imports
//
// useRoute() → {page: 'reactions'|'papers'|'imports', id, query, tab, edit, filters, hash, key}
//   id: a number for reactions (R000123 and 123 both work), the paper id string for papers, else null;
//   query: every parameter as a string (several values of one filter are comma-joined);
//   filters: query without `t` and `edit`, what the list, facets and neighbours take.
// The same hash gives the same route object, so it can be an effect dependency.

const UI_KEYS = new Set(['t', 'edit']);
// Changing any other key moves the list back to its first page.
const KEEPS_OFFSET = new Set(['offset', 't', 'edit']);

const enc = (s) => encodeURIComponent(s).replace(/%2C/gi, ',');
function dec(s) {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

function clean(value) {
  if (value == null || value === false) return '';
  if (Array.isArray(value)) return value.filter((v) => v != null && v !== '').join(',');
  return value === true ? '1' : String(value);
}

function toQuery(query) {
  return Object.entries(query || {})
    .map(([k, v]) => [k, clean(v)])
    .filter(([, v]) => v !== '')
    .map(([k, v]) => `${enc(k)}=${enc(v)}`)
    .join('&');
}

export function href(page = 'reactions', id = null, query = null) {
  let path;
  if (page === 'papers') path = id != null && id !== '' ? `/papers/${enc(id)}` : '/papers';
  else if (page === 'imports') path = '/imports';
  else path = id != null && id !== '' ? `/r/${enc(id)}` : '/';
  const q = toQuery(query);
  return `#${path}${q ? `?${q}` : ''}`;
}

function reactionId(text) {
  const m = /^r?(\d+)$/i.exec(text || '');
  return m ? Number(m[1]) : text || null;
}

function parse(hash) {
  const raw = (hash || '').replace(/^#/, '');
  const cut = raw.indexOf('?');
  const parts = (cut < 0 ? raw : raw.slice(0, cut)).split('/').filter(Boolean).map(dec);
  const query = {};
  for (const [k, v] of new URLSearchParams(cut < 0 ? '' : raw.slice(cut + 1))) {
    if (v === '') continue;
    query[k] = query[k] ? `${query[k]},${v}` : v;
  }
  let page = 'reactions';
  let id = null;
  if (parts[0] === 'papers') [page, id] = ['papers', parts[1] ?? null];
  else if (parts[0] === 'imports') page = 'imports';
  else if (parts[0] === 'r' && parts[1]) id = reactionId(parts[1]);
  const filters = Object.fromEntries(Object.entries(query).filter(([k]) => !UI_KEYS.has(k)));
  // key: the canonical address (the browser may encode a typed hash differently), used to compare routes.
  return { page, id, query, tab: query.t || null, edit: query.edit === '1', filters, hash: `#${raw}`,
    key: href(page, id, query) };
}

// ------------------------------------------------------------------ current route + guards

let current = parse(location.hash);
const subscribers = new Set();
const guards = new Set();

// guard(fn): fn(next, current) returns a message to confirm before leaving (a string), or nothing.
// The editor uses it for unsaved changes; it sees every route change, including Back and links.
export function guard(fn) {
  guards.add(fn);
  return () => guards.delete(fn);
}

function allowed(next) {
  for (const fn of [...guards]) {
    const message = fn(next, current);
    if (message && !confirm(typeof message === 'string' ? message : '有未保存的修改，确定离开吗？')) return false;
  }
  return true;
}

function publish(next) {
  current = next;
  for (const fn of [...subscribers]) fn(next);
}

// Links, Back and typed addresses (navigate() publishes its route itself, so its own hashchange finds
// nothing new).
addEventListener('hashchange', () => {
  const next = parse(location.hash);
  if (next.key === current.key) return;
  if (!allowed(next)) {
    // Stay: put the old address back without another hashchange.
    history.replaceState(history.state, '', current.key);
    return;
  }
  publish(next);
});

export const currentRoute = () => current;

export function useRoute() {
  const [route, setRoute] = useState(current);
  useEffect(() => {
    subscribers.add(setRoute);
    if (route !== current) setRoute(current);
    return () => subscribers.delete(setRoute);
  }, []);
  return route;
}

// navigate(page, id, query) or navigate('#/papers'); replace(...) does not add a history entry.
function go(args, replacing) {
  const target = typeof args[0] === 'string' && args[0].startsWith('#') ? args[0] : href(...args);
  const next = parse(target);
  if (next.key === current.key) return false;
  if (!allowed(next)) return false;
  if (replacing) location.replace(next.key);
  else location.hash = next.key;
  // The new route goes out at once, not on the hashchange that follows: whatever reads the route right
  // after (a second key press before the page has re-rendered) already sees where it is going.
  publish(next);
  return true;
}

export const navigate = (...args) => go(args, false);
export const replace = (...args) => go(args, true);

// Merges `patch` into the current query (empty values remove a key); changing a filter or the sort
// drops `offset`. {replace: true} for changes made while typing.
export function setQuery(patch, { replace: replacing = false } = {}) {
  const next = { ...current.query };
  let resetOffset = false;
  for (const [k, v] of Object.entries(patch || {})) {
    const value = clean(v);
    if ((next[k] ?? '') !== value && !KEEPS_OFFSET.has(k)) resetOffset = true;
    if (value === '') delete next[k];
    else next[k] = value;
  }
  if (resetOffset && !('offset' in (patch || {}))) delete next.offset;
  return go([current.page, current.id, next], replacing);
}

// The current list query of the reactions page, for links back to the list from elsewhere.
let lastList = current.page === 'reactions' ? current.filters : {};
subscribers.add((r) => { if (r.page === 'reactions') lastList = r.filters; });
export const listHref = () => href('reactions', null, lastList);
