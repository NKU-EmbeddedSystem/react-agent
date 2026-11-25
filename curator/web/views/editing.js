import { useEffect, useRef, useState } from '../lib/preact.js';
import { getInfo, validate } from '../lib/api.js';
import { describePath, keyNames } from '../lib/format.js';
import { getIn, parsePath, pathKey, setIn } from '../lib/paths.js';

// The editor's logic, apart from how it looks: what a path in a record is (header, step, participant,
// condition, outcome, source), blank items with fresh keys, the client-side diff of a working copy
// against the version it started from, validation messages tied back to the parts they are about,
// and boxes drawn into the data. The forms are in inspector.js, the save bar in editbar.js.

const isObj = (x) => x !== null && typeof x === 'object' && !Array.isArray(x);
export const list = (x) => (Array.isArray(x) ? x : []);
export const clone = (x) => (x === undefined ? undefined : structuredClone(x));

// ------------------------------------------------------------------ vocabularies and templates

// records.KNOWN and records.TEMPLATES, for when /api/info cannot be read (the server's win).
const FALLBACK = {
  known: {
    participant_role: ['reactant', 'intermediate', 'product', 'byproduct'],
    participant_source: ['drawn', 'derived', 'text'],
    condition_role: ['catalyst', 'ligand', 'reagent', 'additive', 'base', 'solvent', 'temperature', 'time',
      'atmosphere', 'other'],
    yield_type: ['isolated', 'NMR', 'GC', 'HPLC', 'LC', 'analytical', 'conversion', 'other'],
    kind: ['optimization', 'substrate_scope', 'mechanistic', 'application', 'substrate_prep', 'catalyst_prep',
      'background', 'mechanism_proposal', 'characterization', 'other'],
    doc: ['main', 'si'],
  },
  templates: {
    participant: { key: '', role: 'reactant', label: null, text: null, amount: null, amount_origin: 'curator',
      amount_stated_at: null, source: 'text', unknown: false, generic: false, isolated: null, page: null, bbox: null,
      variables: [], basis: null, alternatives: [], stated_at: null, choice: null, inferred: null },
    condition: { key: '', role: 'other', text: '', amount: null, origin: 'curator', structure: null, alternatives: [],
      stated_at: null, amount_stated_at: null, inferred: null, value_missing: false },
    outcome: { yield: { text: null, value: null, qualifier: null, type: null, type_origin: 'curator' },
      selectivity: [], footnote_markers: [], notes: null, stated_at: null },
    step: { step: 1, description: '', reactants: [], products: [], conditions: [] },
  },
};

let infoPromise = null;
// {known, templates}: the server's, read once per page.
export function editorInfo() {
  infoPromise ||= getInfo().then((i) => ({ known: { ...FALLBACK.known, ...(i?.known || {}) },
    templates: { ...FALLBACK.templates, ...(i?.templates || {}) } }), () => FALLBACK);
  return infoPromise;
}

export function useEditorInfo() {
  const [info, setInfo] = useState(FALLBACK);
  useEffect(() => {
    let alive = true;
    editorInfo().then((i) => alive && setInfo(i));
    return () => { alive = false; };
  }, []);
  return info;
}

// A key no participant, condition or structure of the record has: new1, new2, …
export function newKey(data, prefix = 'new') {
  const used = new Set();
  const visit = (x) => {
    if (Array.isArray(x)) x.forEach(visit);
    else if (isObj(x)) {
      if (typeof x.key === 'string') used.add(x.key);
      Object.values(x).forEach(visit);
    }
  };
  visit(data);
  let n = 1;
  while (used.has(`${prefix}${n}`)) n++;
  return `${prefix}${n}`;
}

// A blank item of `kind` for the list at `listPath` (role and outcomes follow the list it goes into).
export function blank(info, data, kind, listPath) {
  const t = clone(info.templates[kind] ?? FALLBACK.templates[kind]);
  if (kind === 'participant') {
    t.key = newKey(data);
    if (listPath[listPath.length - 1] === 'products') {
      t.role = 'product';
      t.outcomes = [];
    }
  } else if (kind === 'condition') {
    t.key = newKey(data);
  } else if (kind === 'step') {
    t.step = list(data?.steps).reduce((n, st) => Math.max(n, Number(st?.step) || 0), 0) + 1;
  }
  return t;
}

// ------------------------------------------------------------------ what a path is

// The selectable parts (reaction.js documents the same paths):
//   []  header · ['source'] · ['steps', i] · ['steps', i, 'reactants'|'products', j]
//   ['steps', i, 'conditions', j] · ['conditions', j] · ['steps', i, 'products', j, 'outcomes', k] · ['other_outcomes', k]
export function kindOf(path) {
  const p = path || [];
  if (!p.length) return 'header';
  if (p[0] === 'source' && p.length === 1) return 'source';
  if (p[0] === 'steps' && typeof p[1] === 'number') {
    if (p.length === 2) return 'step';
    if ((p[2] === 'reactants' || p[2] === 'products') && p.length === 4) return 'participant';
    if (p[2] === 'conditions' && p.length === 4) return 'condition';
    if (p[2] === 'products' && p[4] === 'outcomes' && p.length === 6) return 'outcome';
  }
  if (p[0] === 'conditions' && p.length === 2) return 'condition';
  if (p[0] === 'other_outcomes' && p.length === 2) return 'outcome';
  return null;
}

const HEADER_FIELDS = new Set(['label', 'kind', 'variant', 'conditions_given', 'notes', 'issues', 'results', 'steps',
  'other_outcomes']);

// The part a (resolved, index-only) path belongs to, for the inspector; null when only the JSON has a
// form for it (inferences, footnotes, related, …).
export function selectionFor(path) {
  const p = path || [];
  if (p[0] === 'steps' && typeof p[1] === 'number') {
    const side = p[2];
    if ((side === 'reactants' || side === 'products') && typeof p[3] === 'number') {
      if (side === 'products' && p[4] === 'outcomes' && typeof p[5] === 'number') return p.slice(0, 6);
      return p.slice(0, 4);
    }
    if (side === 'conditions' && typeof p[3] === 'number') return p.slice(0, 4);
    return p.slice(0, 2);
  }
  if ((p[0] === 'conditions' || p[0] === 'other_outcomes') && typeof p[1] === 'number') return p.slice(0, 2);
  if (p[0] === 'source') return ['source'];
  if (HEADER_FIELDS.has(p[0])) return [];
  return null;
}

// Whether the selection still points at something (after a JSON edit, an undo, a deletion).
export const exists = (data, path) => !path || !path.length || getIn(data, path) !== undefined;

// ------------------------------------------------------------------ diff (as curator/diff.py)

const keyed = (items) => {
  const keys = items.map((x) => (isObj(x) ? x.key : undefined));
  return keys.every((k) => typeof k === 'string') && new Set(keys).size === keys.length;
};

// [{op: add|remove|change|reorder, path, old, new}], with key-matched participants and conditions, like
// the server's: so the count and the list of changes in the save bar are the history line to come.
export function diff(old, nw, path = [], out = []) {
  if (isObj(old) && isObj(nw)) {
    for (const k of [...new Set([...Object.keys(old), ...Object.keys(nw)])].sort()) {
      if (!(k in nw)) out.push({ op: 'remove', path: [...path, k], old: old[k], new: null });
      else if (!(k in old)) out.push({ op: 'add', path: [...path, k], old: null, new: nw[k] });
      else diff(old[k], nw[k], [...path, k], out);
    }
  } else if (Array.isArray(old) && Array.isArray(nw)) {
    if (keyed(old) && keyed(nw)) {
      const before = new Map(old.map((x) => [x.key, x]));
      const after = new Map(nw.map((x) => [x.key, x]));
      for (const x of old) if (!after.has(x.key)) out.push({ op: 'remove', path: [...path, { key: x.key }], old: x, new: null });
      for (const x of nw) if (before.has(x.key)) diff(before.get(x.key), x, [...path, { key: x.key }], out);
      for (const x of nw) if (!before.has(x.key)) out.push({ op: 'add', path: [...path, { key: x.key }], old: null, new: x });
      const a = old.filter((x) => after.has(x.key)).map((x) => x.key);
      const b = nw.filter((x) => before.has(x.key)).map((x) => x.key);
      if (a.join('\u0000') !== b.join('\u0000')) out.push({ op: 'reorder', path, old: a, new: b });
    } else {
      for (let i = 0; i < Math.min(old.length, nw.length); i++) diff(old[i], nw[i], [...path, i], out);
      for (let i = nw.length; i < old.length; i++) out.push({ op: 'remove', path: [...path, i], old: old[i], new: null });
      for (let i = old.length; i < nw.length; i++) out.push({ op: 'add', path: [...path, i], old: null, new: nw[i] });
    }
  } else if (old !== nw) {
    out.push({ op: 'change', path, old, new: nw });
  }
  return out;
}

// ------------------------------------------------------------------ paths of diffs and messages

// A path with {key} segments (diff, validation message) walked through `data`: the indexes of the part
// that exists, and what is left of the path beyond it. A bracket is a key where an item has it, else
// an index (the server writes both as [..]).
export function locate(data, segs) {
  const path = [];
  let cur = data;
  let i = 0;
  for (; i < segs.length; i++) {
    const seg = segs[i];
    if (Array.isArray(cur)) {
      const want = isObj(seg) ? String(seg.key) : String(seg);
      let k = cur.findIndex((x) => isObj(x) && x.key === want);
      if (k < 0 && /^\d+$/.test(want) && Number(want) < cur.length) k = Number(want);
      if (k < 0) break;
      path.push(k);
      cur = cur[k];
    } else if (isObj(cur) && typeof seg === 'string' && seg in cur) {
      path.push(seg);
      cur = cur[seg];
    } else {
      break;
    }
  }
  return { path, rest: segs.slice(i) };
}

// The same path in words ("步骤 1 › 反应物 1a › 框"): list items by key where they have one, named by label.
export function pathWords(data, path, rest = []) {
  const segs = [];
  let cur = data;
  for (const seg of path) {
    const next = cur?.[seg];
    segs.push(typeof seg === 'number' && isObj(next) && typeof next.key === 'string' && next.key ? { key: next.key } : seg);
    cur = next;
  }
  for (const seg of rest) segs.push(isObj(seg) && /^\d+$/.test(String(seg.key)) ? Number(seg.key) : seg);
  return describePath(segs, keyNames(data));
}

// "steps[0].reactants[1a].bbox: 框超出页面范围" (records.validate) → its parts. target: the part the
// inspector shows it with (null: only in the JSON); field: the index path of the value it is about.
const MESSAGE = /^([A-Za-z_]\w*(?:\.[A-Za-z_]\w*|\[[^\]]*\])*): ([\s\S]*)$/;

export function parseProblem(text, data, tone) {
  const m = MESSAGE.exec(String(text));
  if (!m) return { text: String(text), tone, where: null, field: null, target: [], old: false };
  const { path, rest } = locate(data, parsePath(m[1]));
  const field = [...path, ...rest.map((s) => (isObj(s) && /^\d+$/.test(String(s.key)) ? Number(s.key) : isObj(s) ? s.key : s))];
  const old = m[2].endsWith('（原有问题）');
  return { text: m[2], tone, where: pathWords(data, path, rest), field, target: selectionFor(field), old };
}

export function parseProblems(state, data) {
  return [
    ...list(state?.errors).map((e) => parseProblem(e, data, 'bad')),
    ...list(state?.warnings).map((w) => parseProblem(w, data, 'warn')),
  ];
}

// Selection paths with changes since the edit started (pathKey set), for the marks in the equation.
export function changedParts(ops, data) {
  const out = new Set();
  for (const op of ops) {
    if (op.op === 'reorder') continue;
    const { path, rest } = locate(data, op.path);
    if (rest.length && op.op !== 'remove') continue;   // gone from the working copy
    const target = selectionFor(path);
    if (target) out.add(pathKey(target));
  }
  return out;
}

// ------------------------------------------------------------------ boxes

// What the box of a selected part is: where its page and bbox live in the record, and its name.
export function drawTarget(data, path) {
  const kind = kindOf(path);
  if (kind === 'source') {
    return { kind, pagePath: ['source', 'page'], bboxPath: ['source', 'entry_bbox'],
      label: `条目 ${data?.source?.entry_id || ''}`.trim() };
  }
  const x = getIn(data, path);
  if (!x) return null;
  if (kind === 'participant') {
    return { kind, pagePath: [...path, 'page'], bboxPath: [...path, 'bbox'], label: x.label || x.text || x.key || '成分' };
  }
  if (kind === 'condition') {
    return { kind, pagePath: [...path, 'structure', 'page'], bboxPath: [...path, 'structure', 'bbox'],
      label: `${x.structure?.label || x.text || x.key || '条件'} 的结构` };
  }
  return null;
}

// The data with a drawn box written into the part at `path` (a condition gets a structure if it had none;
// a participant known only by name becomes a drawn one).
export function applyBox(data, path, { page, bbox }) {
  const t = drawTarget(data, path);
  if (!t) return data;
  if (t.kind === 'condition' && !isObj(getIn(data, [...path, 'structure']))) {
    const c = getIn(data, path);
    return setIn(data, [...path, 'structure'], { key: c.key || newKey(data), label: null, page, bbox, text: c.text || null });
  }
  let next = setIn(setIn(data, t.pagePath, page), t.bboxPath, bbox);
  if (t.kind === 'participant' && getIn(next, [...path, 'source']) === 'text') next = setIn(next, [...path, 'source'], 'drawn');
  return next;
}

// ------------------------------------------------------------------ live validation

const IDLE = { status: 'idle', errors: [], warnings: [], message: null, seen: false };

// POST /api/validate for the working copy, 500 ms after it last changed. The last answer stays shown
// while the next is on its way (status 'checking'); `setServer` takes a 422's lists.
export function useValidation({ editing, working, row, baseRev }) {
  const [state, setState] = useState(IDLE);
  const seq = useRef(0);
  useEffect(() => {
    if (!editing || !working || !row) {
      seq.current++;
      setState(IDLE);
      return undefined;
    }
    const n = ++seq.current;
    setState((s) => ({ ...s, status: 'checking' }));
    const t = setTimeout(() => {
      validate({ paper_id: row.paper_id, data: working, base_rev: baseRev, id: row.id }).then(
        (res) => { if (seq.current === n) setState({ status: 'done', errors: list(res?.errors), warnings: list(res?.warnings), message: null, seen: true }); },
        (e) => { if (seq.current === n) setState((s) => ({ ...s, status: 'failed', message: e.message || String(e) })); },
      );
    }, 500);
    return () => clearTimeout(t);
  }, [editing, working, row?.id, baseRev]);
  const setServer = (body) => {
    seq.current++;
    setState({ status: 'done', errors: list(body?.errors), warnings: list(body?.warnings), message: null, seen: true });
  };
  return { ...state, setServer };
}

// ------------------------------------------------------------------ undo

const COALESCE_MS = 1200;

// The edit state's next value after a change: the working copy before it goes on the undo stack, unless
// the change continues the previous one (typing into one field is one step to undo).
export function pushHistory(s, working, coalesce) {
  if (working === s.working) return s;
  const now = Date.now();
  const same = coalesce && s.lastKey === coalesce && now - (s.lastAt || 0) < COALESCE_MS;
  const past = same ? s.past : [...s.past.slice(-99), s.working];
  return { ...s, working, past, future: [], lastKey: coalesce || null, lastAt: now };
}

export function undo(s) {
  if (!s.past.length) return s;
  return { ...s, working: s.past[s.past.length - 1], past: s.past.slice(0, -1), future: [s.working, ...s.future],
    lastKey: null, selected: exists(s.past[s.past.length - 1], s.selected) ? s.selected : [] };
}

export function redo(s) {
  if (!s.future.length) return s;
  return { ...s, working: s.future[0], past: [...s.past, s.working], future: s.future.slice(1), lastKey: null,
    selected: exists(s.future[0], s.selected) ? s.selected : [] };
}

