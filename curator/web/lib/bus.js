// A tiny event bus between parts of the page that do not render each other (the list, the detail,
// the PDF pane, the shell). Events and payloads (FRONTEND.md):
//   pdf:open          {docId, doc, paperId, page, bbox?, label?, boxes?: [{page, bbox, label, kind}]}
//   pdf:boxes         {docId, boxes}
//   draw:start        {doc, docId, label, onDone({page, bbox}), onCancel()}
//   draw:end          {}
//   toast             {text, tone: 'ok'|'warn'|'bad'}
//   reaction:changed  {id}
// No preact here, so the module also runs under node.

const listeners = new Map();

export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(fn);
  return () => listeners.get(event)?.delete(fn);
}

// Listeners run in the order they subscribed; one that throws does not stop the others.
export function emit(event, payload) {
  for (const fn of [...(listeners.get(event) || [])]) {
    try {
      fn(payload);
    } catch (e) {
      console.error(`bus ${event}:`, e);
    }
  }
}

export const toast = (text, tone = 'ok') => emit('toast', { text, tone });
