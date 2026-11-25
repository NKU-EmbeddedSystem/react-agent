// Who is editing. Every change the server records names its author; there are no accounts, so the
// name is asked for once and kept in this browser (localStorage `curator.author`).
//
// The dialog is the shell's (app.js registers itself with setPromptHost); without a host the
// browser's own prompt() is used, so ensureAuthor works on any page that imports this module.

const KEY = 'curator.author';
let memory = '';              // when localStorage is unavailable
let host = null;              // ({current, reason}) => Promise<string|null>
let asking = null;            // the open request: concurrent callers share it
const subscribers = new Set();

export function getAuthor() {
  try {
    return (localStorage.getItem(KEY) || '').trim();
  } catch {
    return memory;
  }
}

export function setAuthor(name) {
  const value = String(name || '').trim();
  memory = value;
  try {
    if (value) localStorage.setItem(KEY, value);
    else localStorage.removeItem(KEY);
  } catch { /* private mode: the name lasts until the page reloads */ }
  for (const fn of [...subscribers]) fn(value);
  return value;
}

// fn(name) after every change; returns the unsubscribe function.
export function onAuthor(fn) {
  subscribers.add(fn);
  return () => subscribers.delete(fn);
}

// A name set in another tab of this browser.
try {
  addEventListener('storage', (e) => {
    if (e.key === KEY || e.key === null) for (const fn of [...subscribers]) fn(getAuthor());
  });
} catch { /* not a browser */ }

export function setPromptHost(fn) {
  host = fn;
  return () => { if (host === fn) host = null; };
}

// Asks for a name (prefilled with the current one). Resolves the name, or null when cancelled.
export function askAuthor({ reason = null } = {}) {
  if (asking) return asking;
  const current = getAuthor();
  const ask = host
    ? host({ current, reason })
    : Promise.resolve(globalThis.prompt ? globalThis.prompt('编辑者（会记在每次修改里）', current) : null);
  asking = ask.then((name) => {
    const value = String(name || '').trim();
    return value ? setAuthor(value) : null;
  }, () => null).finally(() => { asking = null; });
  return asking;
}

// The name to record with a change: the stored one, else asked for. Null when the person cancels.
export async function ensureAuthor({ reason = null } = {}) {
  return getAuthor() || askAuthor({ reason: reason || '修改会记下编辑者的名字，请先填写。' });
}
