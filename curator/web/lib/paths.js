// Paths into a record: arrays of keys and indexes (['steps', 0, 'reactants', 2, 'amount']). Every
// change returns a new object that shares what it did not touch, so a working copy can be compared
// with `===` and kept in Preact state. Pure module (runs under node).
//
// Diffs and validation messages address list items of participants and conditions by their key
// ({key: '1a'}, rendered "reactants[1a]"); resolvePath turns such a path into indexes.

export const getIn = (obj, path) => path.reduce((o, k) => (o == null ? undefined : o[k]), obj);

// Containers missing along the way are created: an array when the next key is a number.
export function setIn(obj, path, value) {
  if (!path.length) return value;
  const [k, ...rest] = path;
  const base = obj ?? (typeof k === 'number' ? [] : {});
  const copy = Array.isArray(base) ? base.slice() : { ...base };
  copy[k] = setIn(base[k], rest, value);
  return copy;
}

export const updateIn = (obj, path, fn) => setIn(obj, path, fn(getIn(obj, path)));

// Removes the list item or object key the path ends with.
export function removeAt(obj, path) {
  if (!path.length) return undefined;
  const parentPath = path.slice(0, -1);
  const last = path[path.length - 1];
  const parent = getIn(obj, parentPath);
  if (parent == null || typeof parent !== 'object') return obj;
  let copy;
  if (Array.isArray(parent)) {
    copy = parent.slice();
    copy.splice(last, 1);
  } else {
    copy = { ...parent };
    delete copy[last];
  }
  return parentPath.length ? setIn(obj, parentPath, copy) : copy;
}

// Inserts `value` into the list at `path` before `index` (null or past the end: appends).
export function insertAt(obj, path, index, value) {
  const list = getIn(obj, path);
  const arr = Array.isArray(list) ? list.slice() : [];
  const i = index == null ? arr.length : Math.max(0, Math.min(index, arr.length));
  arr.splice(i, 0, value);
  return setIn(obj, path, arr);
}

// Moves the item at `from` of the list at `path` to `to` (上移 / 下移).
export function moveAt(obj, path, from, to) {
  const list = getIn(obj, path);
  if (!Array.isArray(list) || from < 0 || from >= list.length || to < 0 || to >= list.length || from === to) return obj;
  const arr = list.slice();
  const [item] = arr.splice(from, 1);
  arr.splice(to, 0, item);
  return setIn(obj, path, arr);
}

// A stable string for a path (map keys, comparisons); 0 and '0' stay different.
export const pathKey = (path) => JSON.stringify(path);
export const samePath = (a, b) => !!a && !!b && pathKey(a) === pathKey(b);
export const isPrefix = (prefix, path) =>
  !!prefix && !!path && prefix.length <= path.length && pathKey(prefix) === pathKey(path.slice(0, prefix.length));

// As the server renders paths (diff.render_path): steps[0].reactants[1a].amount
export function renderPath(path) {
  let text = '';
  for (const seg of path || []) {
    if (seg && typeof seg === 'object') text += `[${seg.key}]`;
    else if (typeof seg === 'number') text += `[${seg}]`;
    else text += text ? `.${seg}` : String(seg);
  }
  return text;
}

// The inverse of renderPath. Bracketed parts come back as {key}: the server writes a key-addressed
// item as [key] and any other as [index], and only the data can tell which (resolvePath does).
export function parsePath(text) {
  const out = [];
  const re = /([^.[\]]+)|\[([^\]]*)\]/g;
  let m;
  while ((m = re.exec(String(text || ''))) !== null) {
    if (m[1] !== undefined) out.push(m[1]);
    else out.push({ key: m[2] });
  }
  return out;
}

// A path with {key} segments (from a diff or parsePath) as plain indexes into `obj`; null when a part
// does not exist. A leading 'data' of a diff path is dropped when `obj` has no such key.
export function resolvePath(obj, path) {
  const segs = [...(path || [])];
  if (segs[0] === 'data' && obj && typeof obj === 'object' && !('data' in obj)) segs.shift();
  const out = [];
  let cur = obj;
  for (const seg of segs) {
    if (cur == null || typeof cur !== 'object') return null;
    let k = seg;
    if (seg && typeof seg === 'object') {
      if (!Array.isArray(cur)) return null;
      k = cur.findIndex((x) => x && typeof x === 'object' && x.key === seg.key);
      if (k < 0 && /^\d+$/.test(String(seg.key))) k = Number(seg.key);
      if (k < 0 || k >= cur.length) return null;
    } else if (Array.isArray(cur)) {
      k = Number(seg);
      if (!Number.isInteger(k) || k < 0 || k >= cur.length) return null;
    } else if (!(k in cur)) {
      return null;
    }
    out.push(k);
    cur = cur[k];
  }
  return out;
}
