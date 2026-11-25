# Worker guide

Extracts reaction data from chemistry papers. A Python driver (`python -m pipeline`) runs the
steps; Codex does the reading through the repo-local skills in `.agents/skills/`.

- Run Python with `.venv/bin/python` (PyMuPDF, Pillow, NumPy are installed there).
- `Data/` holds the source PDFs and `work/<paper_id>/{main,si}/` holds the preprocessed pages;
  treat both as read-only.
- Put your own temporary files (drafts of your answer too) in the scratch directory named in the
  task prompt, and write nothing else under `work/`: the task file and the results there belong
  to the pipeline, and your answer is your final message.
- Do the whole task yourself in this session: do not start sub-agents or hand work to other
  agents (`spawn_agent` and the other collaboration tools). The driver already runs many
  sessions side by side; waiting on sub-agents only makes a session run into its time limit.

## Page tools

`.venv/bin/python -m pipeline.pagetools.<tool> <ws> <main|si> <page> ...`, where `<ws>` is
`work/<paper_id>` and pages are 1-based PDF page indices. Boxes are `x0,y0,x1,y1` in PDF
points (origin top-left). Each tool prints the path of the PNG it writes (under
`work/<paper_id>/scratch/tools/`).

```
layout    <ws> <doc> <page> [--gap 12] [--within x0,y0,x1,y1] [--no-text] [--json]
grid      <ws> <doc> <page> [--clip x0,y0,x1,y1] [--step PT]
crop      <ws> <doc> <page> x0,y0,x1,y1 [--dpi 300] [--margin 4]
trim      <ws> <doc> <page> x0,y0,x1,y1
find_text <ws> <doc> <regex> [--words] [--pages A-B] [--case]
```

- `layout`: numbered graphic (G) and text (T) blocks of a page or of an area (`--within`).
- `grid`: page or area (`--clip`) with a labelled point grid, for reading coordinates.
- `crop`: high-resolution render of a box, for checking it.
- `trim`: shrink a box to the ink inside it.
- `find_text`: regex search over the text layer (blocks, or `--words`).
