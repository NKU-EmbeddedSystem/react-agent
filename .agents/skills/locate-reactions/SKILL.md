---
name: locate-reactions
description: Build the inventory of where reaction information lives in one chemistry paper from its preprocessed workspace work/<paper_id>, for the documents the prompt puts in scope (main text, SI or both); outputs regions (schemes/tables/figures/sections) split into reaction blocks with page bboxes. Use when asked to locate reactions or reaction regions for a paper workspace.
---

# Locate reactions

You locate and describe; you do not extract individual products or table rows (a later
step does that, one block at a time, using your output as its map).

## Scope

The prompt names the documents in scope: `main`, `si` or both. Regions, blocks and schemes
come only from those documents.

When `si` is not in scope, do not open it. `si_sections` is empty, and no region, scheme or
`related` entry refers to the SI. A main-text sentence that points to the SI ("see the SI for
details") is then neither a region nor a link; mention it in the `notes` of the region it
belongs to. Everything below about the SI applies only when it is in scope.

## Inputs (`work/<id>/`)

- `main/` and `si/`, each with:
  - `manifest.json`: per-page stats (`n_chars`, `image_coverage`, `n_drawings`), `sheets` index, `toc`.
  - `pages/pNNN.png`: full-page renders; `sheets/sheet_NN.png`: 20 thumbnails per image, page tag in red.
  - `text/pNNN.txt`, `blocks/pNNN.jsonl`, `words/pNNN.jsonl`: text layer with bboxes.
- `step1/caption_candidates.json`: caption-like text blocks found by a regex. Every candidate
  must appear in `caption_check`, mapped to a region or given a reason (e.g. "in-text reference").
- Page numbers are 1-based PDF page indices (as in file names), never printed labels like "S12".
- Every page number inside a region (`first_page`, `last_page`, `boxes[].page`, `blocks[].page`,
  `entries_first_page`, `entries_last_page`) refers to that region's own `doc`. A main-text block
  whose procedure or product data sit in the SI keeps its main-text page and box; the SI link is
  expressed only through `related` (`procedure_in`, `characterization_in`, `details_in`, `same_as`)
  pointing to the SI region or SI section.
- Coordinates are PDF points, origin top-left. Every bbox you output is `[x0, y0, x1, y1]` in points.

## Page tools

Run from the repo root as `.venv/bin/python -m pipeline.pagetools.<tool> ...` (see `.agents/worker-guide.md`).
They print the path of the image they write; view it with your image tool.

- `layout <ws> <doc> <page> [--gap 12] [--within BBOX] [--no-text]`: numbered blocks
  (G = vector/raster graphics, T = text) plus an annotated image. At the default gap a whole
  scheme or table body is usually one G block; with `--within <region bbox> --gap 4..8` it
  splits sub-panels. Union the blocks you need to get a box.
- `grid <ws> <doc> <page> [--clip BBOX]`: page or area with a point grid. Use it for
  raster figures and scanned pages, and to fine-tune boundaries (e.g. between panels).
- `crop <ws> <doc> <page> <BBOX>`: high-resolution crop. Look at it to confirm a box.
- `find_text <ws> <doc> <regex> [--words] [--pages A-B]`: search the text layer. Labels are
  often wrapped in punctuation ("(3aj,"), so search `3aj\b`, not `^3aj`.

## Workflow

1. **Main text.** Read the text and look at every page render. Understand the chemistry and the
   compound numbering. Every Scheme/Table/Figure becomes a region (included or not); so does a
   reaction reported only in prose (see Granularity for what counts).
2. **SI** (when in scope). Read the first pages (contents) and search for captions and section
   headings. Look at the contact sheets to classify pages (procedures, tables/schemes,
   characterization, spectra, scanned). Open full pages where needed. Fill `si_sections` so
   that every substantive page range belongs to a section (all spectra may be one section).
3. **Relate.** Link regions describing the same experiments. With the SI in scope, also link
   main and SI regions, and link regions to the SI sections holding their procedures and
   characterization data.
4. **Boxes.** Region box: caption + graphic/table body + footnotes when contiguous on a page
   (one box per page for multi-page regions; for long prose regions boxing the first page is
   enough). Block box: only the part of the body belonging to that block. Check every box with
   the `crop` tool before you finish.
5. **Answer** with the JSON object required by the output schema and nothing else.

## Granularity

- **Region**: one numbered Scheme/Table/Figure, or one SI (sub)section that describes reactions
  in prose (substrate syntheses, catalyst syntheses, derivatizations, extra control experiments).
- **Block**: the part of a region that shares one general reaction and one base set of
  conditions: panels A/B/C, sub-tables, each General Procedure. A region with one general
  reaction has one block.
- A prose region or block must carry its own extractable content: reactants and products, plus
  conditions or an outcome. A sentence that only mentions or points to experiments reported
  elsewhere (a figure, a table, the SI, or a cited paper such as "prepared according to the
  literature") is not a region or block; record the link in `related` or `notes` instead.
- Give every block its `layout`: what one entry prints (condition_table, product_scope,
  reactant_table, equation, prose, other; see `references/taxonomy.md`). It does not depend on
  `kind`.
- Do not list entries. Give `n_entries_est` and `labels_seen` as ranges ("3a–3am, 3aaa–3aal").
  Later steps check their reading against both, so read them from the image, never complete a
  series by its pattern:
  - When the letters run out, papers go on in different ways (5z → 5aa, 5ab, 5ac … or
    5z → 5aa, 5ba, 5ca …), and one figure may switch from one way to the other; a series may
    also skip letters, or change its number part in the middle of a figure.
  - A number can be printed twice (one compound from two substrates or two protocols, each
    with its own result), and entries can be unnumbered (unsuccessful substrates, drawings with
    a remark only).
  - Write each run as printed and where it breaks ("5a–5z, 5aa–5za, 5ab–5ap; 5k twice; four
    unnumbered unsuccessful substrates"), and count `n_entries_est` from those runs: one per
    printed number, each repeat and each unnumbered entry included.
- If one drawing reports yields under several protocols (e.g. [Fe] isolated / [Fe] in situ /
  [Ni] per product), keep one block and describe the variants in `conditions_text`/`notes`.
- If a block's entries are listed on other pages of the same document (e.g. an SI General
  Procedure whose substrates are characterized on later SI pages), set
  `entries_first_page`/`entries_last_page`; otherwise null. Never use them for cross-document links.

## General schemes

A general scheme is the drawn general or model reaction that the entries of a block follow:
the header of a scope scheme, the reaction above an optimization table, a numbered equation
in the text.

- List each one once under `schemes`, with its page and a box around the whole drawn
  reaction: all structures, arrows and the text on the arrows. A multi-step general scheme
  (several arrows in a row, e.g. acid → activated ester → product) is one scheme; box all of it.
- Give every block the `scheme_id` its entries follow. Blocks that follow the same general
  reaction share the id. A panel that draws its own general reaction gets its own scheme.
- The scheme may lie outside the block and outside the region (an equation on an earlier
  page), but it is in the same document as the block.
- `scheme_id` is null when every reaction of the block is drawn or described in full
  (mechanistic experiments, single procedures).

## Include or exclude

Include reactions performed in this work: optimization, scope (including failed, trace and ND
entries), mechanistic and control experiments with outcomes, applications (scale-up,
derivatization), preparation of substrates, reagents and catalysts.

Exclude, but keep the region and give `exclude_reason`: background and prior work, drug or
natural-product showcases, concept or graphical-abstract figures, proposed catalytic cycles,
X-ray structures, spectra, kinetic plots, Hammett/LFER plots and DFT without discrete reaction
outcomes. Single blocks can be excluded inside an included region.

## Pitfalls

- In vector schemes, labels, yields and conditions are usually outlined paths, not text. Read
  the image; the text layer only has captions and footnotes.
- Main-text tables often reappear in the SI with more entries and new numbering (Table 1 ⊂
  Table S1). Keep both regions and relate them (`subset_of`/`superset_of`/`same_as`).
- Footnotes change conditions for marked entries; copy them verbatim into `footnotes`.
- SI per-compound procedure and characterization paragraphs for main-text scope products are not
  new regions; point to them with `procedure_in` / `characterization_in`.
- Any other experiment the SI draws or describes on its own (optimization tables, control and
  mechanistic experiments, scale-up, derivatizations, substrate/catalyst syntheses) is its own
  SI region, with or without a caption, even when the main text shows the same experiment.
  Link such pairs with `same_as`, `details_in`, `subset_of` or `superset_of`.
- Scanned pages have no text layer: use the renders and the `grid` tool.

## IDs and labels

- `label`: only the numbered caption label as printed ("Scheme 2", "Table S1", "Supplementary
  Figure 3"); null when the region has no numbered caption. Section names go in `notes`.
- `region_id`: `<doc>:<slug>`, e.g. `main:scheme2`, `main:table1`, `si:table-s1`, `si:fig-s4`,
  `si:sec3-substrate-prep`.
- `block_id`: unique inside its region, e.g. `A`, `B`, `1`, `GP1`.
- `scheme_id`: `<doc>:<slug>`, e.g. `main:scheme2-general`, `main:eq1`, `si:gp1-scheme`.
- `section_id`: `si-sec:<n>`, e.g. `si-sec:3`. `related[].target_id` is a region_id or section_id.

See `references/taxonomy.md` for kind/layout/presentation/relation definitions with examples.
