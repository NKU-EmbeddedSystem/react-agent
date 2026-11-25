import { useEffect, useRef, useState } from './preact.js';
import { on } from './bus.js';

// Loads `loader()` whenever `deps` change (the data is dropped first: it is something else now),
// and again, keeping what is shown, when `refresh` changes, every `interval` ms, and when the
// tab comes back into view. Nothing re-renders while the data stays the same.
export function useLoad(loader, deps, { refresh = null, interval = null } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const shown = useRef({ key: null, text: null });
  const key = JSON.stringify(deps);
  useEffect(() => {
    let alive = true;
    if (shown.current.key !== key) {
      shown.current = { key, text: null };
      setState({ data: null, error: null, loading: true });
    }
    const run = () => loader().then((data) => {
      if (!alive) return;
      const text = JSON.stringify(data);
      if (text === shown.current.text) return;
      shown.current.text = text;
      setState({ data, error: null, loading: false });
    }, (error) => alive && setState((s) => ({ data: s.data, error, loading: false })));
    run();
    const timer = interval ? setInterval(run, interval) : null;
    const onVisible = () => { if (!document.hidden) run(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      alive = false;
      if (timer) clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [key, refresh, interval]);
  return shown.current.key === key ? state : { data: null, error: null, loading: true };
}

// Calls fn(payload) on every bus `event` while mounted; always the latest fn, so no deps needed.
export function useOn(event, fn) {
  const latest = useRef(fn);
  latest.current = fn;
  useEffect(() => on(event, (payload) => latest.current(payload)), [event]);
}

function readStored(key, initial) {
  try {
    const raw = localStorage.getItem(key);
    return raw == null ? initial : JSON.parse(raw);
  } catch {
    return initial;
  }
}

// useState kept in localStorage under `key` (JSON); falls back to plain state when storage is blocked.
export function useStored(key, initial) {
  const [value, setValue] = useState(() => readStored(key, initial));
  const set = (next) => setValue((old) => {
    const v = typeof next === 'function' ? next(old) : next;
    try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* not kept */ }
    return v;
  });
  return [value, set];
}

// `value`, once it has stayed the same for `ms`.
export function useDebounced(value, ms = 300) {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return settled;
}
