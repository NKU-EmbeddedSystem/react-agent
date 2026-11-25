---
name: equation-reaction
description: Stage 2 for one reaction of an equation block of a chemistry paper (whole reactions drawn as equations, each with its own starting materials, arrow text, products and results). Checks the reading of stage 1 for this reaction, reads its outcomes and looks its experiment up in the main text and the SI, in particular the amounts, the scale and what the equation gives only by reference. Use when a prompt points to an equation-block reaction task file under work/<paper_id>/step2.
---

# Equation block: one reaction

Read `.agents/shared/extract-core.md` first: it holds the rules every extraction follows. This
skill says how to collect one reaction of an equation block.

Stage 1 has read the block: its compounds once (with their boxes), and every equation with its own
participants, steps, conditions (as printed, or from where a reference leads), protocols and printed
results; then it listed the reactions each equation reports. You take one of those reactions. You do
not decide again how many reactions the equation reports, which compounds it draws, or what its
arrow text says. Your part is to check that reading for your reaction, read its outcomes, and add
what the main text and the SI say about this experiment.

## Task file

- `template`: your equation as a template: its participants (the compounds in their roles here,
  with their boxes), `steps`, `conditions` (printed, or taken from a reference with `stated_at`),
  `condition_pointer` (the reference, when the conditions are given by one), `variants`, the
  `footnotes` the equation prints, the drawn `structures`, `default_yield_type`, `reading_guide`
  and `context`. Read `reading_guide` first.
- `entry`: your equation: `label`, `page`, `bbox`, `descriptor`, `results` (every result the
  equation prints, numbered from 1), `footnote_markers`.
- `reaction`: your reaction: `rid`, `results` (the numbers of your results in `entry.results`) with
  `results_text`, `variant` and `variant_title`, `footnote_markers` with their texts in `footnotes`,
  `distinguishing` (set when the equation reports more than one reaction), and `variables` (values
  printed for your reaction, each with the participants that carry it).
- `protocol`: the template as it applies to your reaction (your variant and footnotes merged): its
  steps with their participants, its conditions with where each comes from, and the participants
  and conditions your reaction does without.
- `other_reactions_of_entry`, `other_entries`: the rest of the equation and of the block; not yours.
- `documents`, `paper`, `region`, `block`: as for stage 1. Every document is yours to read, the SI
  included, whatever the notes of the locate step say about the scope it searched.

Attached images: (1) the block with a point grid and your equation outlined in red, (2) a close-up
of your equation with a finer grid.

## 1. Check the reading

Before you use them, check against the images and the text what concerns your reaction:

- the boxes of your compounds hold the whole drawing and nothing of a neighbour; a compound that is
  only named or numbered has none;
- the roles: what reacts and what forms; an item of the arrow text that ends up in a drawn product
  is a participant, not a condition;
- the conditions as printed; when they come from a reference, that the reference leads to the
  conditions stage 1 took (the right table entry, the right procedure);
- your results are your reaction's: not those of another protocol, option or neighbouring arrow;
- your variant and what it changes; your variable values and the drawings they are on.

Where stage 1 is wrong, do not change your record to fit what you think: add an item to
`template_check` (target: a compound, participant, condition, structure or variant key, a footnote
marker, or 'steps', 'condition_pointer', 'results', 'default_yield_type'; what stage 1 says, what
you see, the evidence). Leave it empty when the reading is right.

## 2. `outcomes`

One outcome per value measured in your results, nothing from the other reactions of the equation.

- `result`: the number of the equation's result the value is read from (one of `reaction.results`).
- `product_key`: the template key of the compound the value is measured on: a product or a
  by-product. Several products of one run each get their own outcome. A value printed for several
  products together (the combined yield of a mixture): `product_key` the first of them, and `notes`
  say that it is the combined value of all of them. Null only when the result does not say which
  compound it is.
- A value measured on a starting material at the end (the amount recovered, its ee after the
  reaction): `product_key` that reactant, and `notes` say that it is the recovered starting
  material.
- An ee, er or dr goes into `selectivity` of the yield of its product; a ratio between two products
  goes into `selectivity` with type other, on the outcome of the first of them, and both products
  keep their own yields.
- `yield_text` as printed ("58%", "trace", "n.d."); `yield_value` the number as a percentage;
  `yield_qualifier` for "<", ">", "~", trace, ND (also "not observed", "not detected"), NR.
- Detection data without a yield (calculated and found masses, a spectroscopic observation):
  `yield_text` and `yield_value` null, `yield_qualifier` other, and the data as printed in `notes`.
- A mass printed with a yield ("3.1 g, 68%"): the yield as the value, the mass in `notes`; so is a
  purity.
- `yield_type`: only when this value has a type of its own (a value the caption calls an NMR yield,
  a passage that says how it was determined); otherwise null, and the template's default applies.
- `footnote_markers`: the markers printed on this value; `notes`: what concerns this value only.
- An equation that prints no result for your reaction gets no outcomes. A yield only the text or the
  SI gives is not an outcome: it goes into `notes` and `related`.
- A result printed for an intermediate means that stage 1 should have made its steps separate
  equations: give the value `product_key` that intermediate, and say so in `template_check` (target
  'steps').

## 3. Look the experiment up

Start from `template.reading_guide` and `template.context`: find the paragraph of the SI (or the
sentences of the main text) that reports your experiment, by its product's number or name, or by the
section the SI gives experiments of this kind. A scanned page has no text layer: read its image.
When the paragraph reports several runs (other protocols, options, scales), take only the run that
is your reaction; the others go under `related`.

From that passage take, as `lookup` overrides with `stated_at`:

- **Amounts and the scale**: the amounts of the starting materials and reagents of your experiment
  ("0.30 mmol, 1.0 equiv", "45 mg"): a replace with only the `amount`. An amount the equation prints
  stays and the passage's values are added to it ("1.2 equiv (0.36 mmol)"); another amount is a
  contradiction (below).
- **What the equation leaves open or gives by reference**: the time, temperature, atmosphere,
  solvent volume, a loading: a replace of the template item of its kind, or an add with its role.
  Your experiment's own paragraph wins over conditions stage 1 took from a reference (the items with
  `stated_at` on the referred page): a replace with the paragraph's value, and the difference
  described under `issues`.
- **Names**: a compound the equation draws with variable groups or prints only as a number: a
  replace with its name as `text`. A name identifies the compound the equation shows, so it has to
  fit the drawing: compare the two; a name that plainly describes another compound is not taken
  (quote it under `related`, describe the mismatch under `issues`). A compound number the passage
  gives a compound the equation does not number goes under `labels`.
- **How the yields were determined**, when the passage says it for your experiment: the
  `yield_type` of those outcomes, with the passage under `related`.
- **The outcome of your run**, when the equation prints none and the text reports it: into `notes`,
  quoted under `related`.

List every passage you used under `related` (document, page, the sentence or two quoted, what it
adds). Nothing found is a valid result.

- What the equation prints is not open: a passage that gives another yield, another condition or
  another compound contradicts it. Keep the equation's value, describe the difference under
  `issues`, and add no lookup override for it.
- A procedure written for other experiments (the general procedure of the scope, another equation,
  a run on another scale) is another protocol: it fills nothing of yours (extract-core: the source
  of every value). The conditions a reference of your equation names are the exception, and stage 1
  has taken them already.
- Never work out a compound yourself: not from the drawing, and not by a number that merely
  resembles one of yours. Never turn a drawing into a name.

## 4. `notes` and `issues`

- `notes`: anything else printed for your reaction (a mass, a purity, detection data, an
  observation), and what the text reports about the outcome of your run when the equation prints
  none.
- `issues`: doubts a reviewer should look at: unreadable print, a result you could not place, a
  value that may belong to a neighbouring arrow, a disagreement with how stage 1 split the equation.

Your final message is only the JSON object required by the output schema.
