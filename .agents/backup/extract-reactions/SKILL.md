---
name: extract-reactions
description: Turn one located reaction block of a preprocessed chemistry paper into reaction records. The block reader ("inventory" task) reads the block with the paper's text and SI, writes the template its entries share and lists the entries, then spells out one entry per turn into the reactions it reports ("expand"); an "entry" task takes one of those reactions, boxes its compounds, reads its outcomes and looks it up in the text and SI. Use when a prompt points to a task file under work/<paper_id>/step2.
---

# Extract reactions

A block (a scheme panel, a table, a procedure) was located earlier. Here it becomes reaction
records. Structures are never turned into names or SMILES in this step: you point at each
drawing with a box. Everything printed as text (labels, yields, conditions, footnotes) you
transcribe.

## Task file

The prompt gives the path of a JSON task file:

- `mode`: `inventory` or `entry`. Read `references/<mode>.md` and follow it. The inventory
  session continues with one turn per entry; the prompt of the first of those turns tells you
  to read `references/expand.md`.
- `workspace`, `doc`: the paper workspace and the document (`main` or `si`) of this block.
- `documents`: every document of the paper, with its directory and page count.
- `paper`: reaction class and compound numbering of the paper.
- `region`: caption, verbatim footnotes and pages of the scheme/table/section the block is in.
- `block`: page, bbox, kind, and what the earlier step noted about it. When
  `entries_first_page`/`entries_last_page` are set, the block's entries are on those pages.
  `block.scheme` is the general scheme the block's entries follow (page, box, description),
  or null when the block has none.
- `scratch`: a private directory for your own temporary files.
- Entry mode adds `template`, `entry` (the printed entry and what the block reader transcribed
  from it), `reaction` (the one reaction you extract, as the block reader decided it),
  `protocol` (the template as it applies to that reaction), `other_reactions_of_entry` and
  `other_entries`. `template.reading_guide` is what the block reader wrote for you about this
  particular figure; read it first.

## The rule everything else follows

A general scheme, a table header or a general procedure summarises many experiments. A record
is one of them. Wherever the summary leaves more than one possibility, there is an **open
point**, and every record needs exactly one value for it, together with where that value
comes from.

**Find the open points.** They come in a few forms:

| the source prints | what is open | where it is recorded |
|---|---|---|
| two compounds for one position ("ester A or ester B") | which one reacts | `alternative_groups`; a `default`, a variant or the row of a reaction picks one with `use` |
| "A or B" for a condition, or inside a name ("Fe(acac)3 or FeCl3", "NHPI or TCNHPI ester") | which one was used | `alternatives` on that item, until something names the one |
| a range ("5–40 mol%", "0–25 °C") | the value | the value a footnote, the text or the SI gives per protocol or reaction; the range as printed only when nothing does |
| a variable group (R, X, Ar, M) | the group | `variables` of the reaction's row, `variable_defaults` of the block |
| a column or placeholder that changes per entry ("cat.", "additive") | each entry's value | a `per_entry` condition that the row of every reaction fills in |
| protocol labels ("[isolated]", "[in situ]", "[Fe]", "[Ni]", "Method B") | which protocol a result belongs to | `variants`, one per printed label |
| a pointer ("standard conditions", "see the SI") | the conditions | look them up (below); `conditions_given: false` when the paper has them nowhere |
| a compound of the reaction that the entry does not draw | its identity | the participant with `source: derived` |

**Give every value its source.** Exactly one of these holds for each value in a record:

- The block prints it (scheme, table, caption, footnotes): nothing to add.
- The paper states it elsewhere (main text, SI): set `stated_at` to the document and page,
  and say in `basis` what the passage says.
- It is your conclusion, by analogy with another protocol or from chemical knowledge: set
  `inferred` to true and give the reasoning in `basis`. Amounts and conditions are never
  carried from one protocol to another this way.
- The paper does not say and nothing sound can be concluded: leave it open (`alternatives`
  listed, null, `conditions_given: false`).

Two alternatives are never both recorded as if both were used.

**Decide once, where it applies.** What concerns more than one entry (what a label or a
colour means, which alternative applies by default, what a footnote changes, what "standard
conditions" are) is decided by the block reader and written into the template. The block
reader then looks at every entry on its own and decides, with the template in mind, which
reactions the entry reports and how each differs from the template. The entry session boxes
what is drawn for its one reaction, reads its outcomes and adds what the paper says about that
reaction elsewhere; it does not re-decide the block or the row.

**Facts go into fields.** `notes`, `reading_guide` and `description` explain; the pipeline
does not read them. If you write that two drawings are alternatives, that a result starts from
another compound, or that a condition does not apply, the corresponding field has to say the
same (a group, a `use`, a `remove`).

## Read the paper, not only the picture

A figure is the authors' shorthand. What its labels, brackets and conventions mean, which
substrate the optimization used, what "in situ" involved, is explained in the running text
and in the SI. Do not work it out from the picture alone.

- Inventory mode reads what the paper says about the block; entry mode looks up its one
  reaction. The references say what to look for.
- Finding it: `find_text <ws> <doc> '<regex>'` lists the hits (search for the block's label,
  compound numbers, protocol names); then read `<dir>/text/pNNN.txt` of those pages. Look at
  `<dir>/pages/pNNN.png` when the passage is a drawing, a table or a scan. The first pages of
  an SI usually hold its table of contents.
- Page numbers are PDF page indices (as in the file names), never printed labels ("S16").
- Take from there what the block leaves open: the meaning of a label, which alternative
  applies, the conditions a pointer refers to, an amount, how yields were determined, the
  name or number of a starting material. Mark each with `stated_at`.
- Quote the passages you used (`context` in the template, `related` in an entry): the
  sentence or two that matter, shortened with "…".
- Characterization data (NMR, HRMS, melting points) and whole experimental write-ups are not
  collected in this step.
- When a passage contradicts what the block prints, the block's value stays in the record and
  the difference is described (`issues` of the entry, `notes` of the template).

## Conventions shared by both modes

**One reaction** is one specific set of reactants under one set of conditions, with its outcome.
An **entry** is what the block prints as one unit: a drawing with its label(s) and results, a
table row, a paragraph. An entry reports one reaction or several.

- A product label in a scope scheme is one reaction. An R list ("3b, R = Me, 64%") is one
  reaction per label; they share the drawing (one entry).
- A table row is one reaction, also when it reports several products, unless its results come
  from different experiments (below).
- Failed, trace and ND results are reactions. A substrate shown as unsuccessful is a reaction
  without a product.
- Several results printed for one entry are several reactions when anything that went into
  the flask differs: the reactants (another label, another value of R, another alternative),
  a condition ("rt: 40%, 60 °C: 80%"), or the protocol ("[Fe] 62%, [Ni] 66%"). They are one
  reaction with several outcomes when they measure the same experiment: an isolated and an
  NMR yield, a yield and an ee, two products of one run. Protocol labels that recur across
  the block are template `variants`.
- A sequence whose intermediates are not isolated, or are carried on crude with only an overall
  yield (one-pot activation then coupling, "1) … 2) …" over one arrow, "Step 1 / Step 2" of a
  procedure), is one reaction with numbered steps. When an intermediate is isolated and has
  its own yield, each step is its own reaction.

**Keys.** Participants (reactants, products, byproducts) use the compound label printed in the
general scheme ("1", "2", "3", "1a") or a short slug ("amine"). Conditions use short slugs
(`cat`, `ligand`, `additive-1`, `solvent`, `temp`, `time`). Keys are unique across the
participants and conditions of a template. Entry mode reuses the template key for the
corresponding compound.

**Steps.** A reaction is described as steps, each with the participants that react and the
participants that form: `A + B → C` is one step; `A → B`, then `B + C → D` are two, and B is
an `intermediate` (product of step 1, reactant of step 2; `isolated` says whether it was
isolated in between). Every condition of a sequence carries the number of its step.

Steps follow the way the paper presents the reaction, not its mechanism. Start a new step
only where the paper separates one: a second arrow, "then", "1) … 2) …", "Step 1 / Step 2",
reagents added after a stated time. What stands together on one arrow is one step, even when
the chemistry passes through a species that is not drawn (an organometallic reagent and a
metal salt that transmetalates it, printed on the same arrow: one step, and the salt is a
condition).

The pipeline leaves out a step whose reactants, or whose products, have all dropped out of a
record, together with the compounds that only that step needs. So a protocol that starts from
an isolated intermediate, or an entry that uses the other alternative, only has to say which
compound it uses.

**Reactant or condition.** What is drawn or written on an arrow is not automatically a
condition. Decide it step by step, from the product of that step as the paper draws or
names it:

- A compound that contributes atoms to that product is a `reactant` of the step, whatever the
  paper calls it: a coupling partner, an organometallic reagent, an acylating agent, an
  N-hydroxy compound that becomes part of an ester, a coupling agent when the product drawn
  is the active ester that contains part of it.
- A compound that makes the step go without ending up in its product is a condition:
  catalysts, ligands, bases, additives, dehydrating or coupling agents none of whose atoms
  are in the product (a carbodiimide in an esterification), solvents, temperature, time.

The same compound can be a reactant in one block and a condition in another. A reactant
that is drawn is a participant with its structure box (it is not listed under `structures`);
one that is only named is a participant without a box.

**Drawn conditions.** A catalyst, ligand, additive or reagent that is drawn (in a legend under
a table, beside the scheme, inside an entry) is listed under `structures`: key (its printed
label such as "C1" or "L3", else a short slug), printed label, printed name, page and structure
box. A condition or an override points to its drawing with `structure_key`. Compounds that are
only named in text have no structure and `structure_key` is null.

**Overrides** state how a footnote, a variant or one reaction differs from the template:
`{key, action, role, text, amount, structure_key, step, alternatives, basis, stated_at, inferred}`.

- `replace`: the non-null `text` / `amount` replace the item's values (for a participant, use
  `amount`, e.g. "0.6 mmol, 3.0 equiv"). When `text` names another compound, set
  `structure_key` to its drawing, or null if it is not drawn.
  Set `step` to move an item to another step, `alternatives` when the replacement is itself
  "A or B", and `role` only to change a participant's role (reactant to intermediate).
- `remove`: the item is absent ("no LiCl", an empty additive cell), or a participant takes no
  part.
- `add`: a new condition; give `role` and `text`, plus `amount`, `step` and `structure_key` if
  available. Compounds that react or form are participants, not added conditions.
- `use`: of the participants of an alternative group, this one applies; the others drop out.
  A `text` or `amount` given with it is applied as well.
- `basis`: where the change is printed ("footnote c", "row cell: cat.", "over the arrow"),
  what the passage at `stated_at` says, or the reasoning of an inferred change.
- `stated_at`, `inferred`: the source of the change, as described above. At most one of them
  is set; both are empty for what the block prints.

The pipeline applies them in the order base, variant, footnotes, the row of the reaction
(what its entry prints), then what the entry session found in the text or the SI.

**Boxes** are `[x0, y0, x1, y1]` in PDF points on a page of `doc`.

- Structure box: the drawing of one compound. Leave out its label, its yield and neighbouring
  structures where you can. A little intrusion is fine as long as the structure dominates.
  Draw the box slightly generous: the pipeline shrinks every box to the ink inside it.
- Entry box: everything printed for that one entry: its drawing(s) with their labels and
  results, or its table row, or its paragraph.

**Text** is copied as printed (names, amounts, units, ranges). Footnote superscripts go into
`footnote_markers`, not into the text. Do not normalise names or convert units.

**Tools** are described in `.agents/worker-guide.md`. The attached images already carry a point grid; read
coordinates from them. Reach for a tool when that is not enough: `grid --clip <area>` for a
finer grid, `crop` to check a box you are unsure about, `layout --within <area> --gap 3` for
box proposals in vector drawings.

Your final message is the JSON object required by the output schema and nothing else.
