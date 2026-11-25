// Boxes and the two coordinate frames. A bbox is [x0, y0, x1, y1] in PDF points in PyMuPDF's page.rect
// frame (origin top-left, the frame the pipeline wrote). A document page carries `to_pdf`, the matrix
// [a, b, c, d, e, f] that maps a page.rect point to PDF user space (origin bottom-left, the frame
// pdf.js viewports take): x' = a*x + c*y + e, y' = b*x + d*y + f. Pure module (runs under node).

// Smallest box around `boxes`, grown by `pad` and kept inside a page of `size` [w, h].
export function around(boxes, size, pad = 12) {
  const x0 = Math.max(0, Math.min(...boxes.map((b) => b[0])) - pad);
  const y0 = Math.max(0, Math.min(...boxes.map((b) => b[1])) - pad);
  const x1 = Math.min(size[0], Math.max(...boxes.map((b) => b[2])) + pad);
  const y1 = Math.min(size[1], Math.max(...boxes.map((b) => b[3])) + pad);
  return [x0, y0, x1, y1];
}

export const applyMatrix = (m, x, y) => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];

export function invertMatrix(m) {
  const [a, b, c, d, e, f] = m;
  const det = a * d - b * c;
  if (!det) throw new Error('matrix is not invertible');
  return [d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det];
}

// Both corners through m, then min/max again: a rotated page swaps or flips the axes.
function corners(m, [x0, y0, x1, y1]) {
  const [ax, ay] = applyMatrix(m, x0, y0);
  const [bx, by] = applyMatrix(m, x1, y1);
  return [Math.min(ax, bx), Math.min(ay, by), Math.max(ax, bx), Math.max(ay, by)];
}

// page.rect bbox → PDF user-space rect (for viewport.convertToViewportRectangle).
export const toUser = (m, bbox) => corners(m, bbox);

// PDF user-space rect (from viewport.convertToPdfPoint) → page.rect bbox.
export const fromUser = (m, rect) => corners(invertMatrix(m), rect);

const r1 = (v) => Math.round(v * 10) / 10 + 0;  // + 0 turns -0 into 0
export const round1 = (bbox) => bbox.map(r1);

export const normBox = ([x0, y0, x1, y1]) => [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)];
export const isBox = (b) => Array.isArray(b) && b.length === 4 && b.every(Number.isFinite) && b[0] < b[2] && b[1] < b[3];
