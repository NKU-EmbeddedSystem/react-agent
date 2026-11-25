# Expand: one entry per turn

After the template turn, every turn of your session shows you one entry: its id, its box, how
you described it in your list, and a close-up with the entry outlined in red. Spell out the
reactions this entry reports. Answer about this entry only.

The template you wrote stays as it is. Use its keys, variants, footnotes and alternative
groups. If this entry shows that the template is wrong somewhere, describe that under `issues`.

Look at the close-up first. When something is too small or unclear, use the page tools
(`.agents/worker-guide.md`): `crop` of the entry box for a sharper picture, `find_text --words` within the
page for small print.

Work in this order; the output fields come in the same order.

## 1. `printed`

Transcribe everything printed for this entry, in reading order: labels, variable assignments
("R = Me"), every result with the protocol label and the footnote markers printed with it,
conditions or remarks printed with it. Copy; do not interpret. Structures are drawn, not
printed text: leave them out.

## 2. `results`

Every result printed for the entry, one item each: a yield, a conversion, a ratio, "n.d.",
"NR", "trace". Copy it with what identifies it: "[in situ] [Fe] 71%", "78% b", "3fa: 64%". A
selectivity printed together with a yield ("85%, 3:1 d.r.") may stay one item. Empty when the
entry prints no result.

## 3. `reasoning`

Before writing rows, decide how many reactions the entry reports (SKILL.md, One reaction). Go
through the results by number and ask for each: does it come from the same reactants, under
the same conditions and protocol, as another one? Then the two measure one experiment and
belong to one reaction. If anything that went into the flask differs, they are different
reactions. Write down the decision and why, naming the results by their numbers, and what you
take from the template (which variant a label stands for, which alternative a protocol uses).

## 4. `rows`

One row per reaction.

- `label`: the printed label of the compound or entry the reaction is reported under.
- `results`: the numbers of its results in `results` (1 = first). Every result belongs to
  exactly one row.
- `variant`: the key of the template variant whose label is printed with these results; null
  when they are printed without a protocol label. Do not move a result to a variant with
  another label.
- `footnote_markers`: the markers printed on this reaction's label or results. A marker on the
  label of the whole entry applies to every row of the entry.
- `variables`: variable groups printed as text for this reaction ("R = Me", "X = Cl"). Do not
  work a variable out from the drawing.
- `overrides`: how this reaction differs from the template once its variant and footnotes are
  applied, as printed in this entry. Do not repeat what those already say.
  - Each cell of a column the template gives entry by entry (`per_entry`): `replace` with the
    printed text (and `structure_key` when the compound is drawn), or `remove` for an empty
    cell, "–" or "none".
  - A row of deviations ("FeCl3 instead of Fe(acac)3", "without LiCl", "60 °C") names only what
    changes. Match each named thing to the template item of the same kind (a ligand replaces
    the ligand, a solvent the solvent, a metal salt the metal source) and leave the rest.
  - A condition printed with the result: a temperature under the structure, "(2 equiv)", an
    additive over the arrow of a control experiment.
  - The alternative this reaction uses (`use`), when neither its variant nor the group's
    default settles it, or when the entry says otherwise. Give the basis, and `stated_at` or
    `inferred` as SKILL.md says.
  - In a sequence, give added or changed conditions their `step`.
  - A condition the entry leaves open ("Pd(OAc)2 or Pd2(dba)3" with one result) keeps the
    printed text and gets `alternatives`.
  - For a variant with `conditions_given` false, add no conditions that the paper does not
    give for this reaction.
- `drawn_structures`: a catalyst, ligand or additive that is drawn only inside this entry and
  that an override names: its key, printed label and name. The agent of the reaction takes
  its box. A compound of the template's legend is referred to by its template structure key
  instead.

## 5. `issues`

Doubts a reviewer should look at: unreadable print, a result you could not place with
certainty, a point where the entry and the template disagree.

## What the pipeline checks

- Every result is in exactly one row.
- Variants and footnote markers exist in the template.
- After template, variant, footnotes and the row are merged, every reaction is left with
  exactly one participant of each alternative group, and every `per_entry` condition has a
  value.
- Two rows of the entry with the same label, protocol, footnotes, changes and variables are
  one reaction; give it one row with all its results.
