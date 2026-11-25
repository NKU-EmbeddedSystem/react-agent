---
name: condition-table-reaction
description: Stage 2 for one reaction of a condition-table block of a chemistry paper (an optimization or screening table). Checks the table reading of stage 1 for this reaction, writes how its row changes the model reaction, reads its outcomes and looks the entry up in the main text and the SI. Use when a prompt points to a condition-table reaction task file under work/<paper_id>/step2.
---

# Condition table: one reaction

Read `.agents/shared/extract-core.md` first: it holds the rules every extraction follows. This
skill says how to collect one reaction of a condition table.

Stage 1 has read the table: the model reaction and what every row shares (the template), what
every column means (the columns), every row as printed cells, and which reactions each row
reports. You take one of those reactions. You do not decide again how many reactions the row
reports, nor what the table shares; you write what is particular to your reaction.

## Task file

- `template`: the model reaction and what every row shares: participants with their boxes,
  base conditions (a `per_entry` condition is a placeholder that every row fills in), legend
  `structures`, `footnotes` with their overrides, `variants`, `reading_guide`, `context`.
  Read `reading_guide` first.
- `columns`: every column with its `kind`, `target`, `unit`, `values`, `measures` and
  `blank_means`.
- `entry`: your row: `label`, `page`, `bbox` and `cells`. Each cell has the printed `text`, its
  `markers`, and for a drawn value its `structure_bbox` and the `structure_key` to use for it.
- `reaction`: your reaction: `rid`, `results` (your result cells) with `results_text`, `variant`
  and `variant_title`, `footnote_markers` with their texts in `footnotes`, `distinguishing` (set
  when the row reports more than one reaction), `variables`, `drawn_structures`.
- `protocol`: the template as it applies to your reaction before your row's changes: your
  variant and your footnotes are already merged in.
- `other_reactions_of_entry`, `other_entries`: the rest of the row and of the table; not yours.
- `documents`, `paper`, `region`, `block`: as for stage 1. Every document is yours to read, the
  SI included, whatever the notes of the locate step say about the scope it searched.

Attached images: (1) the block with a point grid and your row outlined in red, (2) a close-up of
your row with a finer grid, (3) the model reaction, when it is drawn on another page
(`template.scheme` says where; it is not always the table's own header).

## 1. Check the table reading

Before you use them, check against the images and the text what concerns your reaction: the
participants of the model reaction, the base conditions, the definitions of the columns your row
prints in, your footnotes, the legend labels your row cites. Where stage 1 is wrong, do not
change your record to fit what you think: add an item to `template_check` (target, what stage 1
says, what you see, the evidence). The reviewer and stage 1 correct the template. Leave
`template_check` empty when it is right.

## 2. `overrides`: how your row changes the model reaction

What your row prints, as changes to the template (extract-core: overrides). `text` says what an
item is: a compound's name, or for a temperature, time, atmosphere or solvent the value itself
with its unit. `amount` is only the quantity of a compound. A `per_entry` placeholder is filled
only by a replace that gives `text`.

- **Condition column**: `replace` its target.
  - `text`: the compound's name, or the value with the column's `unit` ("60" under "T (°C)"
    gives text "60 °C"; "8" under "t (h)" gives "8 h").
  - When the column's `values` list your printed value, write exactly what they say (its
    `text`, `amount`, `structure_key`) and give the printed value in `basis`. This is how a
    legend label ("C1"), an R group that selects a drawn catalyst, or a drawn ligand added as
    its salt is written. The pipeline checks it.
  - A legend label the `values` do not list gets the `structure_key` of that legend structure
    and its printed name as `text`.
  - A drawn value gets the cell's `structure_key`, and as `text` its printed label, or a short
    name when it has none ("ligand drawn in entry 3").
  - `amount` when the cell gives one, with the column's unit: "1.8 LiOtBu" under "base (equiv)"
    gives text "LiOtBu", amount "1.8 equiv".
  - A cell that prints an abbreviation a footnote or `reading_guide` resolves ("[Pd]" with
    footnote f: "[Pd] = Pd(AzePhos)Cl2"): `text` is the resolved name; give both in `basis`.
  - An empty cell, "–" or "none": what `blank_means` says, usually `remove`.
- **Amount column**: `replace` its target with only the `amount`: the cell with the column's
  unit ("0.3" under "TBAI (equiv)" gives amount "0.3 equiv"). Never `text`: the compound stays
  the same. An empty cell: what `blank_means` says. When your variant or a footnote swapped the
  column's target for another compound of its group (BMIDA instead of Bdan), the amount is that
  compound's.
- **Participant column, or a deviation that swaps a reactant** ("aryl-OTs instead of aryl-OTf"):
  `replace` that participant with the printed compound (`structure_key` when it is drawn).
- **Variable column** (LG = OMs/OTs): write nothing. The pipeline attaches the value
  (`reaction.variables`) to its participant, which keeps its drawing.
- **Deviation column**: change only what it names, matched to the template item of the same
  kind; leave the rest.
  - "none", "–", empty: no change.
  - "no X": `remove` X. "X instead of Y": `replace` Y with X; leave `amount` null to keep Y's
    amount unless the cell prints another. "CPME": `replace` the solvent.
  - "2.5 mol% [Pd]": `replace` the amount of the catalyst. "−15 °C": `replace` the
    temperature with text "−15 °C".
  - "8 mol% [Pd] (no ligand)": the catalyst amount, and `remove` the ligand.
  - "MeOH (0.1 equiv) added", "under O2 (balloon)": `add` (an additive, an atmosphere) or
    `replace` the template item of that kind.
  - Something the template has no item for: `add` it with a condition role.
- **A protocol label printed in your row** ("[one-pot]", "Method B") is your variant
  (`reaction.variant_title`); `protocol` already applies it. Write no override for the label.
- **Your footnotes win.** A footnote printed in your row may set what a column gives (the cell
  prints "MnCl2", footnote e: "MnBr2 instead"). `protocol` shows it already applied: leave out of
  your overrides what the footnote sets, write only what it leaves open, and describe a conflict
  under `issues`. The pipeline checks this.
- **Your row reports several reactions** (`reaction.distinguishing` is set): what sets yours
  apart is one of your changes, unless your variant already makes it. Write it on the template
  item of its kind: "60 °C" gives replace temp text "60 °C"; "COMU" gives a replace or add of
  the coupling agent. `other_reactions_of_entry` shows the others.
- A choice your row makes between alternatives of the template: `use`.
- `basis`: where your row prints it ("cell ligand: L2", "deviation: no TBAI").

After your overrides every per_entry condition has your row's value (a replace with `text`) or
is removed, and every alternative group has one member left. The pipeline checks this.

## 3. `outcomes`

One outcome per yield or conversion in your result cells (`reaction.results`), nothing from
other rows or from the other reactions of your row.

- `column`: the outcome column the value is printed in. `measure`: which of that column's
  `measures` the value is (1 = first); required when the column has more than one, else null.
- `product_key`: the product or byproduct the value belongs to; the measure gives it. Null for a
  conversion.
- A conversion has `yield_type` "conversion" and `product_key` null.
- An ee, er or dr belongs to a yield: put it into `selectivity` of that yield's outcome, whether
  it is printed in the same cell ("85 (92)") or in a column of its own. It is never an outcome of
  its own. A "–" there (not determined) gives nothing.
- `yield_text` as printed ("73", "(66)", ">95", "n.d.", "<5", "trace"); `yield_value` the number
  as a percentage (0–100); `yield_qualifier` for "<", ">", "~", trace, ND (not detected), NR (no
  reaction). Any other number (a TON, a ratio): keep `yield_text`, set `yield_value` null and say
  what it is in `notes`.
- `yield_type`: only when this value has a type of its own (an isolated yield in parentheses, a
  value with a footnote that names the method); otherwise null, and the column and the
  template's default apply.
- What a yield is based on, when the paper says ("based on 4c"): in `notes`.
- `footnote_markers`: the markers printed on this value itself.
- `notes`: what concerns this one value only.

## 4. Look the entry up

Search the main text for the table's entry number ("entry 5", "entries 3–7", "Table 1") and the
SI for the fuller version of the table or the procedure of this experiment
(`template.context` says where they are). When the rows are not numbered, search for what your
row prints (the ligand or catalyst label, a distinctive value) and look at the fuller SI table.

- List what you find under `related`: document, page, the sentence or two quoted, what it adds.
  Nothing found is a valid result.
- Where a passage states something the table leaves open for your reaction (the amount of a
  catalyst, the time, the scale, which of "A or B"), add an override to `lookup` with `stated_at`.
  `inferred` with your reasoning only when you conclude it yourself; leaving it out is usually
  better. A name found this way for a drawn compound keeps its drawing (extract-core: overrides).
- What the table prints is not open. In a table of deviations, everything the deviation does not
  name is printed by the table: the header's value. A passage that gives another value for it
  (another ligand amount, another solvent) contradicts the table.
- Where a passage contradicts the table (another yield, another condition), keep the table's
  value, describe the difference under `issues`, and add no lookup override.
- A procedure written for other experiments (the typical procedure of the scope, a gram-scale
  run) is another protocol: it fills nothing of yours (extract-core: the source of every value).

## 5. `notes` and `issues`

- `notes`: anything else printed for this reaction.
- `issues`: doubts a reviewer should look at: unreadable print, a value you could not place, a
  disagreement with how stage 1 split the row.

Your final message is only the JSON object required by the output schema.
