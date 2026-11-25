// The pdf.js worker (a module worker, GlobalWorkerOptions.workerSrc), with the built-ins it needs
// installed first: imports run in order, so pdfjs-compat.js is done before the worker sets itself up.
import './pdfjs-compat.js';
import '../vendor/pdfjs/build/pdf.worker.min.mjs';
