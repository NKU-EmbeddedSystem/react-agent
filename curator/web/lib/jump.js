// Opening the PDF pane at a place: resolves the document id when only (paper, doc) is known, then
// emits `pdf:open` (the shell opens the pane, the pane scrolls and highlights).
import { emit } from './bus.js';
import { docIdOf } from './api.js';
import { DOC, name } from './format.js';

// at: {paperId?, doc?, docId?, page, bbox?, label?, boxes?}. Resolves true when the event went out.
export async function jumpTo(at) {
  if (!at) return false;
  let docId = at.docId ?? null;
  if (docId == null && at.paperId != null && at.doc) {
    try {
      docId = await docIdOf(at.paperId, at.doc);
    } catch {
      docId = null;
    }
  }
  if (docId == null) {
    const doc = name(DOC, at.doc);
    const what = !doc ? '这份文档' : /^[A-Za-z]/.test(doc) ? ` ${doc} 的 PDF` : `${doc}的 PDF`;
    emit('toast', { text: `打不开：找不到${what}`, tone: 'warn' });
    return false;
  }
  emit('pdf:open', { ...at, docId });
  return true;
}
