---
name: product-scope-reaction
description: Stage 2 for one reaction of a product-scope block of a chemistry paper (a substrate-scope scheme or table whose entries each draw one product of a general reaction). Checks the reading of stage 1 for this reaction, writes what is left to read in its entry, reads its outcomes and looks the entry up in the main text and the SI, in particular the product's name and the starting materials its paragraph names. Use when a prompt points to a product-scope reaction task file under work/<paper_id>/step2.
---

# Product scope: one reaction

Read `.agents/shared/extract-core.md` first: it holds the rules every extraction follows. This
skill says how to collect one reaction of a product scope.

Stage 1 has read the figure as a table whose column heads are not printed: the general reaction
with its positions (the template), how each position an entry does not draw follows from the
product (`template.derivations`), the fields of an entry (`columns`: its drawing, its number,
variable values, results, remarks), every entry as cells, and which reactions each entry reports.
You take one of those reactions. You do not decide again how many reactions the entry reports,
nor what the figure shares. The task and the messages of the pipeline use the table words: a
"row" is an entry, a "column" a field. The **legend** of an entry is the text printed with its
drawing; the **caption** is the figure's caption with its footnotes.

The pipeline has already applied the entry's drawing, number and variable values: the drawn
product sits in its position with its compound number, the variable values on the participants
that carry them. The reactants the entry does not draw and the general reaction does not fix are
unknown (derived): they are worked out later from the product, never by you. Your part is what
needs reading: remarks and conditions printed in the legend, the outcomes, and what the main text
and the SI say about this compound.

## Task file

- `template`: the general reaction and what every entry shares: participants (positions) with
  their boxes, base conditions, `derivations`, `shared_results`, legend `structures`, `footnotes`
  with their overrides, `variants`, `reading_guide`, `lookup_guide`, `context`, and `scheme`
  (where the general reaction is drawn) with `general_reaction` (what it is). Read
  `reading_guide` first.
- `columns`: every field with its `kind`, `targets`, `unit`, `values`, `measures` and `blank_means`.
- `entry`: your entry as stage 1 wrote it (`label`, `page`, `bbox`, `descriptor`, `cells`,
  `lookup_hint`).
- `row_cells`: your entry's cells as they apply to your reaction: a cell that shares the value of
  an earlier entry shows that value (`from_row`), a drawing has its `structure_key`, and a
  participant or variable cell split between the reactions of the entry shows only your part.
  Result cells are shown whole: your parts of them are in `reaction.results`.
- `participants`: the participants as the pipeline builds them from your entry: for each its
  `source` (drawn, text, derived), `state` (cell: the entry draws or prints it; fixed: a specific
  compound of the general reaction; variables: the generic drawing with variable values; unknown:
  to be derived; swapped: a footnote or protocol put another compound there), box, variables
  (those printed for your reaction; the template's defaults are added to the record), label and
  `basis`. For the compounds of your reaction, this list counts.
- `cannot_derive`: unknown participants whose derivation needs something your entry does not give.
  The pipeline adds them to the record's issues itself.
- `reaction`: your reaction: `rid`, `results` (your result cells, with your `part` of each) with
  `results_text`, `variant` and `variant_title`, `footnote_markers` with their texts in
  `footnotes`, `distinguishing` (set when the entry reports more than one reaction), `variables`,
  `drawn_structures`; `reaction_cells` gives your part of a cell the entry was split on.
- `protocol`: the template as it applies to your reaction, with your variant and your footnotes
  merged in (its conditions count; the compound the entry draws shows there only as a stub).
- `other_reactions_of_entry`, `other_entries`: the rest of the entry and of the figure; not yours.
- `documents`, `paper`, `region`, `block`: as for stage 1. Every document is yours to read, the SI
  included, whatever the notes of the locate step say about the scope it searched.

Attached images: (1) the block with a point grid and your entry outlined in red, (2) a close-up of
your entry with a finer grid, (3) the general reaction, when it is drawn on another page. When it
is drawn in no image, `template.scheme` says where, and `template.general_reaction` and
`template.context` what it is. Entries that share one drawing share the box: yours is the one
`entry` describes (its label, its descriptor, its cells).

## 1. Check the reading

Before you use them, check against the images and the text what concerns your reaction:

- the box of your product holds the whole drawing and nothing of a neighbour (a cut ring, a
  neighbour's atom or label inside it);
- the compound number and the results are those of your entry: in a crowded figure a legend can
  stand closer to the neighbouring drawing than to its own;
- the variable values of your entry and the participants they are on: a symbol of the entry's own
  drawing on the product, a symbol that only a reactant carries on that reactant;
- the positions marked unknown: your entry indeed does not draw them, and the derivation names
  the part of the product (the colour, the side of the new bond) they are;
- the participants of the general reaction, the base conditions, your footnotes, your variant.
  When your variant was assigned by a rule of the general reaction and not by a printed label,
  check that your product is of the kind the rule names.

Where stage 1 is wrong, do not change your record to fit what you think: add an item to
`template_check` (target: a participant, condition, structure, field, footnote marker or variant
key, or 'steps', 'scheme', 'derivations', 'default_yield_type'; what stage 1 says, what you see,
the evidence). Leave it empty when the reading is right.

## 2. `overrides`: what is left to read in your entry

Never write an override that names, draws or removes the participant your entry draws: the
pipeline has applied it (a name you find in the text or the SI goes into `lookup`; a disagreement
with the drawing or the number into `template_check`). Never fill in a participant whose `state`
is unknown or variables either: it is worked out later. What remains, as changes to the template
(extract-core: overrides):

- **A deviation printed in the legend** ("at 45 °C", "48 h", "5 mol% of the catalyst"): change only
  what it names, on the template item of its kind.
- **A scale printed in the legend** ("on a 2 mmol scale"): `replace` the limiting reactant with
  only the `amount` ("2 mmol, 1 equiv"). **An amount printed for one compound** ("3 equiv of the
  base"): `replace` that compound with only the `amount`. Both are allowed for an unknown reactant
  too; in a sequence give the `step`.
- **A remark that says what a reactant was** ("from the cyclic bromide", "from the Z isomer"):
  `replace` that reactant with the remark as `text`, in the printed words (the whole remark, or
  whole words of it), and nothing else. The reactant stays unknown; the remark tells the later
  step that the general derivation does not give it. A remark about where the substrate comes
  from ("derived from <a natural product>") is not the reactant: it goes into `notes`.
- **Your entry reports several reactions** (`reaction.distinguishing` is set) and what sets yours
  apart is a condition: write it on the template item of its kind. When the entry was split on a
  variable value (`reaction_cells` is not empty), the pipeline has already used your part.
- **Your footnotes win**: `protocol` shows what they set; leave that out, and describe a conflict
  under `issues`.
- A choice your entry makes between alternatives of the template: `use`.
- In a sequence, give a changed or added condition its `step`.

Most entries of a product scope need no override at all.

## 3. `outcomes`

One outcome per value measured in your result cells (`reaction.results`, your parts), nothing from
other entries or from the other reactions of your entry.

- `column`: the outcome field the value is printed in; null for a result of
  `template.shared_results` (printed once for the whole figure), which is yours too.
- `measure`: which of the field's `measures` the value is (1 = first); required when the field has
  more than one, else null. Read every measure the field lists from your part of the cell.
- `product_key`: the template key of the compound the value belongs to (the measure gives it):
  your product, or the by-product for its yield, also when that by-product is unknown (derived).
  It is a key of the template ("3"), never the compound number of your entry.
- When your variant is the first step of a sequence whose intermediate is isolated, the entry's
  drawing (the final product) takes no part in your reaction: your product is the intermediate,
  also when it is unknown, and the yield printed for it is yours.
- An ee, er or dr goes into `selectivity` of its product's yield, never into an outcome of its own.
- `yield_text` as printed ("85%", "(68%)", ">99", "trace", "n.d."); `yield_value` the number as a
  percentage ("0%" is the value 0 with no qualifier); `yield_qualifier` for "<", ">", "~", trace,
  ND, NR.
- A substrate shown as unsuccessful: `yield_text` what is printed for it, no value, the qualifier
  NR (or other), `product_key` the product's key, and a note.
- `yield_type`: only when this value has a type of its own (the value in parentheses that the
  caption calls isolated, a footnote that names the method); otherwise null, and the field and
  the template's default apply.
- `footnote_markers`: the markers printed on this value; `notes`: what concerns this value only.

## 4. Look the entry up

Start from `entry.lookup_hint` when stage 1 found the passage, else from `template.lookup_guide`:
find the paragraph of the SI (or the sentence of the main text) that reports your compound, by
its compound number or by its name. A scanned page has no text layer: read its image. When the
same compound number stands in the figure more than once (another pair of reactants, another set
of conditions), or the paragraph reports several runs (other protocols, scales or reagents), take
only the run that is your reaction; the others go under `related`.

From that passage take:

- **The product's name**: a `lookup` replace of the product with `text` (the name as printed) and
  `stated_at`. It keeps its drawing: a name identifies the compound the entry draws, so it has to
  fit that drawing. Compare the two (the ring or chain, the groups, their positions); a name that
  plainly describes another compound (a group on another position, another ring, a group missing
  or extra) is not taken: quote it under `related`, describe the mismatch under `issues`, and never
  write a name of your own in its place. The rest of the paragraph stays yours when its compound
  number and its run match your entry.
- **The starting materials, as far as this passage names them** ("prepared from 1b and 2a
  following general procedure A", "with <compound> (41 mg, 0.20 mmol)"): for each, a `lookup`
  replace of that reactant with its name as `text` and `stated_at`; a compound number the passage
  gives it goes under `labels`. A number may be followed to the paragraph where the paper defines
  that number, and the name printed there is stated (its `stated_at` is that paragraph). Only a
  compound's name or number counts: a descriptive phrase ("the corresponding bromide") is not a
  name. The reactant stays derived: a name identifies it, it does not draw it.
- **Amounts**: an amount the passage gives for a starting material or a reagent is added to what
  the figure prints for it, which stays: "1.5 equiv (0.30 mmol, 45 mg)". When the passage gives
  another amount than the figure prints, that is a contradiction (below), not an addition.
- **What the figure leaves open**: a value it prints as a range (the scale, the amount of a
  catalyst or reagent, a temperature), the one of an "A or B", and a scale or a condition it does
  not print at all: `lookup` replaces with `stated_at`. A condition the template took from a
  general procedure (not from the figure) that your compound's paragraph states otherwise: the
  paragraph's value is your experiment's (a `lookup` replace with `stated_at`); describe the
  difference under `issues`.
- **Which general procedure** the passage says was used: under `related`. When your variant was
  assigned by a rule and the passage names another procedure, say so in `template_check`.
- **Several runs of the same entry** (two experiments averaged in the figure): each run's values
  under `related` and in `notes`; they are not separate reactions, and the figure's value stays
  the outcome.
- A main-text sentence about a group of entries counts for yours only when it plainly includes it
  (names your compound or a range of numbers that contains it); quote it under `related`.

List every passage you used under `related` (document, page, the sentence or two quoted, what it
adds). Nothing found is a valid result.

- What the figure prints is not open: a passage that gives another yield, another condition or
  another compound for it contradicts the figure. Keep the figure's value, describe the difference
  under `issues`, and add no lookup override for it.
- A procedure written for other experiments (another figure, a gram-scale run) is another
  protocol: it fills nothing of yours (extract-core: the source of every value).
- Never work out a reactant yourself: not from the drawing, not by picking from the SI's list of
  starting materials the one that fits your product, and not by a number that merely resembles
  your compound's. Only what a passage states about your compound's experiment goes into the
  record. Never turn a drawing into a name.

## 5. `notes` and `issues`

- `notes`: anything else printed for this reaction (where the substrate comes from, a deposition
  number, a remark on purity): copy every remark of your legend here unless it went into an
  override.
- `issues`: doubts a reviewer should look at: unreadable print, a result you could not place, a
  legend that may belong to the neighbouring drawing, a disagreement with how stage 1 split the
  entry. Do not repeat `cannot_derive`: the pipeline adds it.

Your final message is only the JSON object required by the output schema.
