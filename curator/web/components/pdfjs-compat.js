// Built-ins the vendored pdf.js (6.4.299) calls that some current browsers do not have yet:
// Map/WeakMap getOrInsert / getOrInsertComputed (the TC39 "upsert" methods; missing in Chrome 144)
// and Math.sumPrecise (the worker's font code). Without them pdf.js throws on its first event
// listener. Loaded before pdf.js in the page and, through pdfjs-worker.js, in its worker. A browser
// that has a method keeps its own.

function define(target, name, fn) {
  if (typeof target[name] === 'function') return;
  Object.defineProperty(target, name, { value: fn, writable: true, configurable: true, enumerable: false });
}

for (const Kind of [Map, WeakMap]) {
  define(Kind.prototype, 'getOrInsert', function getOrInsert(key, value) {
    if (this.has(key)) return this.get(key);
    this.set(key, value);
    return value;
  });
  define(Kind.prototype, 'getOrInsertComputed', function getOrInsertComputed(key, compute) {
    if (this.has(key)) return this.get(key);
    const value = compute(key);
    this.set(key, value);
    return value;
  });
}

// Compensated (Neumaier) summation: exact for the integer sizes pdf.js adds up, and far closer than
// a plain loop for anything else. An empty list gives -0, as the proposal says.
define(Math, 'sumPrecise', function sumPrecise(items) {
  let sum = -0;   // -0 + x is x for every x, so the first item needs no special case
  let carry = 0;
  for (const x of items) {
    if (typeof x !== 'number') throw new TypeError('Math.sumPrecise: every item must be a number');
    const t = sum + x;
    if (Number.isFinite(t)) carry += Math.abs(sum) >= Math.abs(x) ? (sum - t) + x : (x - t) + sum;
    sum = t;
  }
  return Number.isFinite(sum) && carry ? sum + carry : sum;
});
