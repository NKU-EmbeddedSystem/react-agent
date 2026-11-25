---
name: prose-reaction
description: Stage 2 for one reaction of a prose block of a chemistry paper (experiments reported in words: a paragraph, a reference note or endnote, a methods or SI procedure paragraph). Checks the reading of stage 1 for this reaction, reads its outcomes from the passage (with the measured values the SI gives for a result the passage states only in words) and looks the run up in the main text and the SI, in particular the amounts, the scale and what the passage leaves open. Use when a prompt points to a prose-passage reaction task file under work/<paper_id>/step2.
---

# Prose block: one reaction

Read `.agents/shared/extract-core.md` first: it holds the rules every extraction follows. This
skill says how to collect one reaction of a passage that reports experiments in words.

Stage 1 has read the passage: its compounds once (boxed where the paper draws that very compound),
every experiment with its own participants, steps, conditions (as stated, or from where a reference
leads), runs and results, and what the passage says that is no experiment of its own; then it listed
the reactions, one per run. You take one of those reactions. You do not decide again how many runs the
passage reports, which compounds take part, or what a reference leads to. Your part is to check that
reading for your reaction, read its outcomes, and add what the main text and the SI say about this run.

## Task file

- `template`: your experiment as a template: its participants (the compounds in their roles here,
  with their boxes where drawn), `steps`, `conditions` (stated, or taken from a reference with
  `stated_at`), `based_on` (the reference, when the experiment is given by one), `variants` (its
  runs), the `footnotes` it prints, the drawn `structures`, `default_yield_type`, `reading_guide` and
  `context`. Read `reading_guide` first.
- `entry`: your experiment: `statement` (its sentences, quoted), `descriptor`, `page`, `bbox`,
  `based_on`, `results` (every result the passage states for it, numbered from 1),
  `footnote_markers`.
- `reaction`: your reaction: `rid`, `results` (the numbers of your results in `entry.results`) with
  `results_text`, `variant` and `variant_title` (your run), `footnote_markers` with their texts in
  `footnotes`, `distinguishing` (set when the experiment reports more than one reaction), and
  `variables`.
- `protocol`: the template as it applies to your reaction (your run and footnotes merged): its steps
  with their participants, its conditions with where each comes from, and the participants and
  conditions your run does without.
- `other_reactions_of_entry`, `other_entries`: the other runs and experiments of the passage; not
  yours.
- `documents`, `paper`, `region`, `block`: as for stage 1. Every document is yours to read, the SI
  included, whatever the notes of the locate step say about the scope it searched.

Attached images: (1) the page around the passage with a point grid and your experiment's sentences
outlined in red, (2) a close-up of those sentences, (3) the general scheme the passage refers to when
it is on another page.

The text layer loses Greek letters, the middle dot and sub- and superscripts, and runs a note number
into the value or compound number before it: check every value you read against the image.

## 1. Check the reading

Before you use them, check against the passage and the places it refers to what concerns your
reaction:

- the compounds: the right ones for your run; a box only on the drawing of that very compound (not
  on a related one, not on a drawing that the passage changes in words);
- the roles: what reacts and what forms;
- the conditions: as stated; when they come from a reference, that the reference leads to the
  conditions stage 1 took (the right entry, the right procedure, the right earlier sentence);
- your run: what its variant changes is what the passage says it changes;
- your results are your run's: not those of another run of a "respectively" list, nor of a cited or
  restated experiment.

Where stage 1 is wrong, do not change your record to fit what you think: add an item to
`template_check` (target: a compound, participant, condition, structure or variant key, a footnote
marker, or 'steps', 'based_on', 'statement', 'results', 'default_yield_type'; what stage 1 says, what
you see, the evidence). Leave it empty when the reading is right.

## 2. `outcomes`

One outcome per value measured in your results, nothing from the other runs.

- `result`: the number of the experiment's result the value belongs to (one of `reaction.results`).
- `product_key`: the template key of the compound the value is measured on: a product or a
  by-product. Several products of one run each get their own outcome. A value stated for several
  products together: `product_key` the first of them, and `notes` say that it is the combined value.
  Null only when the result does not say which compound it is.
- **A value the passage states**: `yield_text` as printed ("64%", "<5%", "traces"), `yield_value`
  the number as a percentage, `yield_qualifier` for "<", ">", "~" ("ca.", "about", "nearly"),
  trace ("traces of", "trace amounts"), ND for a product that was looked for and not found ("not
  detected", "not observed", "no product", "essentially no coupling"), NR for a reaction that did not
  take place at all ("no reaction", "did not proceed", "no conversion", "the starting material was
  recovered unchanged").
- **A conversion** keeps its value, with `yield_type` conversion ("complete conversion": value 100).
  A "conversion to P" has `product_key` P; a conversion of a starting material, or one the passage
  gives without saying of what, has `product_key` the reactant consumed, and `notes` say so.
- **A result stated only in words** ("the yield was poor", "the coupling was suppressed", "had no
  effect on the yield"): look for the measured value of this very run in the SI (a table row, the
  run's paragraph) or elsewhere in the paper (a table the passage cites). When you find it, the
  outcome is that value, with `stated_at` where it is printed and the passage's words in `notes`: one
  outcome per product the passage's result speaks about, each with that `result` number. A value the
  source gives for a product the passage does not mention is not an outcome (quote it under
  `related`). When nothing gives a value, the outcome is the words: `yield_text` the words as printed,
  `yield_value` null, `yield_qualifier` the one that fits (trace, ND, NR) or other.
- When the value you find is an entry of a table, figure or scheme of the main text that reports this
  very run, record it as said, and add a `template_check` item (target 'statement') saying that the
  passage restates that entry.
- When a participant or a condition of your reaction is a class ("tertiary alkyl bromides", "most
  bidentate phosphines"), no single member's row is your run: its value is not your outcome and its
  name not your compound's name. Quote the members' rows under `related`; the outcome is the passage's
  words.
- `stated_at` stays null for a value the passage states. When the passage states a number, that
  number is the outcome: a different value elsewhere is described under `issues`, never written in
  its place.
- **A value measured on a starting material** at the end (the amount recovered, its ee, the share
  that decomposed): `product_key` that reactant, and `notes` say what was measured; `yield_value` only
  for the percentage recovered, else null with qualifier other. An ee or er of the recovered material
  goes into `selectivity` of that outcome.
- **An ee, er or dr** goes into `selectivity` of the yield of its product; a ratio between two
  products goes into `selectivity` with type other, on the outcome of the first of them.
- **Detection without a yield** (a species observed by MS or NMR, a product identified but not
  quantified): `yield_text` and `yield_value` null, `yield_qualifier` other, and what was observed in
  `notes`.
- A mass printed with a yield ("1.2 g, 68%"): the yield as the value, the mass in `notes`; so is a
  purity.
- `yield_type`: only when this value has a type of its own (the passage or the SI says how it was
  measured: "by GC", "isolated"); otherwise null, and the template's default applies.
- `footnote_markers`: the markers printed on this value; `notes`: what concerns this value only.
- A run for which the passage states no result gets no outcomes; what the SI says about it goes into
  `notes` and `related`.

## 3. Look the run up

Start from `template.reading_guide` and `template.context`: find where the SI (or the main text)
reports your run: its paragraph, or its row in a table of control or additional experiments, by the
compound numbers or names, the additive or condition that sets the run apart, or the section the SI
gives experiments of this kind. A scanned page has no text layer: read its image. When a paragraph or
table reports several runs, take only yours; the others go under `related`.

From that report take, as `lookup` overrides with `stated_at`:

- **Amounts and the scale** of your run ("0.50 mmol, 1.0 equiv", "45 mg"): a replace with only the
  `amount`. An amount the passage states stays and the report's values are added to it; another
  amount is a contradiction (below).
- **What the passage leaves open or gives by reference**: the time, temperature, atmosphere, solvent
  volume, a loading: a replace of the template item of its kind, or an add with its role. The order of
  addition, premixing, the work-up and the analysis are not conditions: quote them under `related`
  when they matter. Your run's
  own report wins over conditions stage 1 took from a reference (the items with `stated_at` on the
  referred page): a replace with the report's value, and the difference described under `issues`.
- **Names**: a compound the passage gives only by number or by a description: a replace with its name
  as `text`, when the report names exactly this compound. A name has to fit what the passage says (and
  the drawing, when the compound has a box); a name that plainly describes another compound is not
  taken (quote it under `related`, describe the mismatch under `issues`). A compound number the report
  gives a compound that has none goes under `labels`.
- **How the yields were determined**, when the report says it for your run: the `yield_type` of those
  outcomes, with the report under `related`.

List every passage you used under `related` (document, page, the sentence or two quoted, what it
adds). Nothing found is a valid result.

- What the passage states is not open: a report that gives another yield, another condition or
  another compound contradicts it. Keep the passage's value, describe the difference under `issues`,
  and add no lookup override for it.
- A procedure written for other experiments (the general procedure of the scope, another run, a run
  on another scale) is another protocol: it fills nothing of yours (extract-core: the source of every
  value). Two exceptions: the conditions a reference of your experiment names, which stage 1 has taken
  already; and a procedure your run's own report says it follows (a table or section of control
  experiments "following General Procedure 4", a paragraph "according to GP2"): it is part of that
  report, so take its amounts, scale and conditions as lookup with `stated_at` on the procedure's
  page, the report's own values winning over it.
- Never work out a compound yourself: not from a drawing, not from a description, and not by a number
  that merely resembles one of yours. Never turn a drawing into a name.

## 4. `notes` and `issues`

- `notes`: anything else stated for your run (an observation, a colour change, a mass, a purity), and
  what the SI says about a run for which the passage states no result.
- `issues`: doubts a reviewer should look at: unreadable print, a result you could not place, a
  value that may belong to another run, a reference that may lead elsewhere, a disagreement with how
  stage 1 split the passage.

Your final message is only the JSON object required by the output schema.
