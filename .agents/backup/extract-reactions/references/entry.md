# Entry mode

Extract one reaction: `reaction` in the task file. The block reader has decided what it is:
which of the entry's results are its own (`reaction.results_text`), under which protocol
(`reaction.variant`), with which footnotes, variables and printed changes
(`reaction.overrides`). `protocol` is the template as it applies to this reaction, with all
of that merged: its steps with their participants, and its conditions with where each comes
from. Use these as given. Start with `template.reading_guide` (how to read an entry of this
figure).

`entry` is the printed entry the reaction comes from, with what the block reader transcribed.
`other_reactions_of_entry` are the other reactions reported in the same entry (other results
printed next to yours, other labels of an R list): they are not yours. `other_entries` are the
rest of the block.

Attached images: (1) the block with a point grid and the entry outlined in red, (2) a
close-up of the entry with a finer grid.

Work in this order: read the entry (sections 1–3), then look the reaction up in the main text
and the SI (section 4), then add what you found.

## 1. Participants

List every reactant, intermediate and product of this reaction. Every participant of
`protocol.steps` takes part, so each is listed here (the pipeline checks this), plus any
compound that only this reaction has.

| situation | `source` | box |
|---|---|---|
| has its own drawing in the entry (a scope product, the reactants of a table row, both sides of an explicit equation) | `drawn` | its structure box, read from the close-up |
| no own drawing; the template participant is a specific compound (model substrate of an optimization table) | `drawn` | page and bbox of the template participant |
| no own drawing; the template participant is generic | `derived` | none; `basis` says why ("only the product is drawn; reactant follows from 1 + 2 → 3") |
| only named (also a template participant without a box, such as a reagent that reacts and is written on the arrow) | `text` | page and bbox of the name if easy, else null |

- Use the template key for a compound that corresponds to a template participant.
- A compound that the reaction's row puts in the place of a template participant is listed
  under that participant's key with what the entry prints: `text` and source `text`, or
  `drawn` with its own box.
- When the drawing is shared with the other reactions of the entry, list only the compounds
  of this reaction.
- `label`: the label printed for this specific compound ("3fa", "1a"); null if none.
- `text`: the name printed for this compound in the entry. Leave it null rather than copy the
  template's text.
- `variables`: attach each of `reaction.variables` to every participant whose drawing (own or
  generic) carries that symbol. Use only those; the pipeline adds the template defaults. A
  variable printed for this reaction that `reaction.variables` misses goes under `issues`.
- `amount`: only when printed for this reaction; otherwise null (the protocol amount applies).
- `isolated`: only for an intermediate whose isolation this entry states; otherwise null.

## 2. Drawn structures

For each item of `reaction.drawn_structures`, give its structure box under `structures`, with
the same key. Nothing else goes there; a drawn compound that the reaction does not mention
goes under `issues`.

## 3. Outcomes

One outcome per value measured in `reaction.results_text`. Results printed for the other
reactions of the entry are not yours.

- `yield_text` as printed ("42%", "<2%", "trace", "ND", ">98"); `yield_value` the number;
  `yield_qualifier` for "<", ">", "~", trace, ND (not detected), NR (no reaction).
- `yield_type` when stated for this result (column header, parenthesis, footnote); otherwise
  null and the template default applies. Conversions are outcomes with type `conversion`.
- `product_key`: the participant the result belongs to; null when there is one product or for
  a conversion.
- `selectivity`: d.r., e.r., ee, r.r., E/Z as printed.
- `footnote_markers`: the markers attached to this value.
- `notes`: what concerns this one value only.

An unsuccessful substrate without a drawn product gets an outcome with qualifier NR or
`other` and a note, and no product participant.

## 4. Look the reaction up

Now search the main text and the SI for what the paper says about this particular reaction
(`template.reading_guide` and `template.context` say where the block's reactions are
described). Search for its compound number or entry number, and for the name of its
substrate when you know it.

- List the passages that are about this reaction under `related`: document, page, the
  sentence or two quoted, and what they add. Nothing found is a valid result.
- Where a passage states something the reaction leaves open, put it into the record with
  `stated_at`: the one catalyst of an "A or B", an amount, a temperature, the scale, which
  alternative this reaction used (`overrides`); the name or number of a reactant that the
  figure does not draw (`text` or `label` of that participant, which keeps its `source`).
- Your `overrides` are for this only: every one has `stated_at`, or `inferred` true with the
  reasoning in `basis`. What the entry prints was settled by the block reader; if you read
  the entry differently, describe that under `issues`.
- Where a passage contradicts what the figure prints (another yield, another condition), keep
  the figure's value and describe the difference under `issues`.
- Stay with this reaction. What holds for the whole block is the template's business.
- Do not collect characterization data.

`inferred` is false for everything stated. Set it to true, with the reasoning in `basis`,
only for a change you conclude yourself; leaving that change out is usually better.

## 5. Notes and issues

- `notes`: anything else printed for this reaction ("from flurbiprofen", a CCDC number).
- `issues`: doubts a reviewer should look at (unreadable text, an ambiguous assignment, a
  contradiction between figure and text, a disagreement with the block reader's decision).

Never transcribe a structure into a name or SMILES, and do not guess values that are not
printed or stated.
