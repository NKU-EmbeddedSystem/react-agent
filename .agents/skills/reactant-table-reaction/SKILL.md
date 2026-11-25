---
name: reactant-table-reaction
description: Stage 2 for one reaction of a reactant-table block of a chemistry paper (a table whose rows give the reactants of one general reaction). Checks the table reading of stage 1 for this reaction, writes what is left to read in its row, reads its outcomes and looks the entry up in the main text and the SI, in particular the name and number of a product the table does not draw. Use when a prompt points to a reactant-table reaction task file under work/<paper_id>/step2.
---

# Reactant table: one reaction

Read `.agents/shared/extract-core.md` first: it holds the rules every extraction follows. This
skill says how to collect one reaction of a reactant table.

Stage 1 has read the table: the general reaction with its positions (the template), how each
position a row leaves unknown follows from the others (`template.derivations`), what every column
gives, every row as printed cells, and which reactions each row reports. You take one of those
reactions. You do not decide again how many reactions the row reports, nor what the table shares.

The pipeline has already applied the row's participant, variable and label cells: the compounds the
row draws or names sit in their positions, the variable values on the participants that carry
them, the compound numbers on their participants. What the row does not print and the header does
not fix is unknown (derived): it is worked out later from the reactants, never by you. Your part is
what needs reading: the condition cells, the outcomes, and what the main text and the SI say about
this entry.

## Task file

- `template`: the general reaction and what every row shares: participants (positions) with their
  boxes, base conditions, `derivations`, `shared_results`, legend `structures`, `footnotes` with
  their overrides, `variants`, `reading_guide`, `lookup_guide`, `context`. Read `reading_guide`
  first.
- `columns`: every column with its `kind`, `targets`, `unit`, `values`, `measures` and `blank_means`.
- `entry`: your row as printed (`label`, `page`, `bbox`, `cells`).
- `row_cells`: your row's cells as they apply to your reaction: a cell that repeats an earlier row
  shows that row's value (`from_row`), a drawing has its `structure_key`, and a participant,
  variable or label cell split between the reactions of the row shows only your part. Result cells
  are shown whole: your parts of them are in `reaction.results`.
- `participants`: the participants as the pipeline builds them from your row: for each its `source`
  (drawn, text, derived), `state` (cell: the row prints it; fixed: a specific header compound;
  variables: the generic drawing with variable values; unknown: to be derived; swapped: a footnote
  or protocol put another compound there), box, variables (those printed for your reaction; the
  template's defaults are added to the record), label and `basis`.
- `cannot_derive`: unknown participants whose derivation needs something your row does not give.
  The pipeline adds them to the record's issues itself.
- `reaction`: your reaction: `rid`, `results` (your result cells, with your `part` of each) with
  `results_text`, `variant` and `variant_title`, `footnote_markers` with their texts in
  `footnotes`, `distinguishing` (set when the row reports more than one reaction), `variables`,
  `drawn_structures`; `reaction_cells` gives your part of a cell the row was split on.
- `protocol`: the template as it applies to your reaction, with your variant, your footnotes and
  your row's compounds merged in.
- `other_reactions_of_entry`, `other_entries`: the rest of the row and of the table; not yours.
- `documents`, `paper`, `region`, `block`: as for stage 1. Every document is yours to read, the SI
  included, whatever the notes of the locate step say about the scope it searched.

Attached images: (1) the block with a point grid and your row outlined in red, (2) a close-up of
your row with a finer grid, (3) the general reaction, when it is on another page.

## 1. Check the table reading

Before you use them, check against the images and the text what concerns your reaction:

- that each drawing or name of your row sits in the position its column points at (the reactant
  the column header names, not its partner), and that a repeated cell repeats the right row;
- the variable values of your row and the participants they are on;
- the positions marked unknown: that your row indeed does not print them, and that the derivation
  says which participants they follow from;
- the header participants, the base conditions, your footnotes, a legend label your row cites.

Where stage 1 is wrong, do not change your record to fit what you think: add an item to
`template_check` (target, what stage 1 says, what you see, the evidence). Leave it empty when the
reading is right.

## 2. `overrides`: what is left to read in your row

Never write an override that names, draws or removes a participant that a participant, variable or
label cell of your row gives: the pipeline has applied it (a name you find in the text or the SI
goes into `lookup`; a disagreement with the cell into `template_check`). Never fill in a participant
whose `state` is unknown or variables either: it is worked out later; only a name a passage prints
for it may be added, as a lookup with `stated_at`. An amount for such a participant (an amount
column, an amount the text gives) is fine. What remains, as changes to the template (extract-core:
overrides):

- **Condition column**: `replace` its target with the printed value (`text`: the compound's name,
  or the value with the column's `unit`; `amount` when the cell gives one). When the column's
  `values` list the printed value, write exactly what they say. An empty cell, "–" or "none":
  what `blank_means` says, usually `remove`.
- **Amount column**: `replace` its target with only the `amount` (the cell with the column's unit),
  also when the target is a participant your row draws.
- **Deviation column**: change only what it names, matched to the template item of the same kind
  ("no X": remove X; "X instead of Y": replace Y; "−30 °C": replace the temperature).
- **Your row reports several reactions** (`reaction.distinguishing` is set) and what sets yours
  apart is a condition: write it on the template item of its kind. When the row was split on a cell
  that prints two compounds (`reaction_cells` is not empty), the pipeline has already used your part.
- **Your footnotes win**: `protocol` shows what they set; leave that out, and describe a conflict
  under `issues`.
- A choice your row makes between alternatives of the template: `use`.

Most rows of a reactant table need no override at all.

## 3. `outcomes`

One outcome per value measured in your result cells (`reaction.results`, your parts), nothing from
other rows or from the other reactions of your row.

- `column`: the outcome column the value is printed in; null for a result of
  `template.shared_results` (printed once for the whole table), which is yours too.
- `measure`: which of the column's `measures` the value is (1 = first); required when the column has
  more than one, else null.
- `product_key`: the product the value belongs to (the measure gives it), also when that product is
  unknown (derived). Null for a conversion of a starting material.
- An ee, er or dr goes into `selectivity` of its product's yield, never into an outcome of its own.
- `yield_text` as printed ("72", "(64)", ">99", "n.d.", "trace"); `yield_value` the number as a
  percentage; `yield_qualifier` for "<", ">", "~", trace, ND, NR.
- `yield_type`: only when this value has a type of its own (a footnote that names the method);
  otherwise null, and the column and the template's default apply.
- `footnote_markers`: the markers printed on this value; `notes`: what concerns this value only.

## 4. Look the entry up

This is where the identity of an undrawn product usually is. Start from `entry.lookup_hint` when
stage 1 found the passage, else from `template.lookup_guide`: find the paragraph of the main text or
the SI that reports your entry (by its entry reference, by its compound number, or by the names of
its reactants together with its yield). A scanned page has no text layer: read its image.

From that passage take:

- **The product's name**: a `lookup` replace of the product with `text` (the name as printed) and
  `stated_at`. It stays derived: a name identifies the compound, it does not draw it.
- **The product's compound number**, when the row prints none: under `labels`, with `stated_at`.
- **The reactants' names and amounts** as the passage gives them: `lookup` replaces with `text`
  and `amount` (a name keeps the drawing of the row). The same for the scale, a reagent's amount
  or a condition the table leaves open.
- **Several runs of the same entry** (repeated runs whose mean the table prints, runs under two
  protocols): each run's values under `related` and in `notes`; they are not separate reactions,
  and the table's value stays the outcome.
- **Which general procedure** the passage says was used: under `related`.

List every passage you used under `related` (document, page, the sentence or two quoted, what it
adds). Nothing found is a valid result.

- What the table prints is not open: a passage that gives another yield or another compound for it
  contradicts the table. Keep the table's value, describe the difference under `issues`, and add no
  lookup override for it.
- A procedure written for other experiments (another table, a gram-scale run) is another protocol:
  it fills nothing of yours (extract-core: the source of every value).
- Never work out the product yourself, never write a name for it that no passage prints, and never
  turn a drawing into a name.

## 5. `notes` and `issues`

- `notes`: anything else printed for this reaction.
- `issues`: doubts a reviewer should look at: unreadable print, a value you could not place, a
  disagreement with how stage 1 split the row. Do not repeat `cannot_derive`: the pipeline adds it.

Your final message is only the JSON object required by the output schema.
