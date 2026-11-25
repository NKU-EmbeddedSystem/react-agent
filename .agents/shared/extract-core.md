# Shared rules for extracting reactions

Every Step 2 skill follows these rules. There is one pair of skills per block layout (a stage 1
that reads the block and lists its reactions, a stage 2 that collects one reaction); the skill of
the layout says how to read its kind of block, this file says what a record is and where each of
its values comes from.

Structures are never turned into names or SMILES: a drawing is pointed at with a box. Everything
printed as text (labels, yields, conditions, footnotes) is transcribed.

## One reaction

One reaction is one specific set of reactants under one set of conditions, with its outcome.

- Failed, trace and ND results are reactions. A substrate shown as unsuccessful is a reaction
  without a product.
- Several results printed for one entry are several reactions when anything that went into the
  flask differs: the reactants, a condition ("rt: 40%, 60 °C: 80%"), the protocol ("[Fe] 62%,
  [Ni] 66%"). They are one reaction with several outcomes when they measure the same experiment:
  an analytical and an isolated yield, a yield and an ee, the yields of several products of one run.
- A sequence whose intermediates are not isolated, or are carried on crude with only an overall
  yield, is one reaction with numbered steps (an "in situ" activation of an acid, then the
  coupling of the ester it gives). When an intermediate is isolated and has its own yield, each
  step is its own reaction.
- A compound that reacts is a participant even when the block does not draw it (the acid behind
  an "in situ" ester, named only in the text or the SI): it has no box and gets `stated_at`.

## The source of every value

A general scheme, a table header or a general procedure summarises many experiments; a record is
one of them. Wherever the summary leaves more than one possibility there is an open point, and
every record needs exactly one value for it, together with where that value comes from.

| the source prints | what is open | where it is recorded |
|---|---|---|
| two compounds for one position ("ester A or ester B") | which one reacts | `alternative_groups`; a `default`, a variant or the reaction picks one with `use` |
| "A or B" for a condition ("Fe(acac)3 or FeCl3") | which one was used | `alternatives` on that item, until something names the one |
| a range ("5–40 mol%") | the value | the value a footnote, the text or the SI gives; the range as printed only when nothing does |
| a variable group (R, X, Ar) | the group | the reaction's `variables`; `variable_defaults` of the template |
| a column or placeholder that changes per entry ("cat.", "additive") | each entry's value | a `per_entry` condition that every reaction fills in |
| protocol labels ("[in situ]", "[Ni]", "Method B") | which protocol a result belongs to | `variants`, one per printed label |
| a pointer ("standard conditions", "see the SI") | the conditions | look them up; `conditions_given: false` when the paper has them nowhere |

Exactly one of these holds for each value of a record:

- The block prints it (scheme, table, caption, footnotes): nothing to add.
- The paper states it elsewhere (main text, SI): `stated_at` gives document and page, and `basis`
  says what the passage says.
- It is your conclusion, by analogy or from chemical knowledge: `inferred` is true and `basis`
  gives the reasoning. Amounts and conditions are never carried from one protocol to another this
  way. A procedure written for other experiments (another table, the typical procedure of the
  scope, a gram-scale run) is another protocol, even when it uses the same reagents.
- The paper does not say and nothing sound can be concluded: it stays open (`alternatives`
  listed, null, `conditions_given: false`).

Two alternatives are never both recorded as if both were used.

**Decide once, where it applies.** What concerns more than one reaction (what a label, a colour,
a column or a footnote means, which alternative applies by default, what the standard conditions
are) is decided in stage 1 and written into the template. Stage 2 takes one reaction as stage 1
listed it; it does not re-decide the block. Where it sees that stage 1 got something wrong, it
says so in the field its skill gives for that, and keeps the template's value.

**Facts go into fields.** `notes`, `reading_guide` and `description` explain; the pipeline does
not read them. When you write that two drawings are alternatives, that a condition does not
apply or that a result belongs to another compound, the corresponding field has to say the same.

## The images the pipeline attaches

The block, scheme, close-up and complete-page images are rendered with a labelled grid: blue
numbers along the top and red numbers along the left are PDF points, and the label says which
page and document. Read coordinates from that grid, not from the pixel size of the image.

Candidate overlays are different: they come from a deterministic vector clustering and carry only
red numbered boxes, with no coordinate grid. Their exact PDF-point boxes are in the
`candidates.json` named in the prompt. A candidate may merge neighbouring structures, include a
neighbouring label or miss an atom label, so it is a proposal, not an answer. Check it with `grid`,
`layout` or `crop` before using a box, choose the candidate that matches the structure, and never
copy a candidate box without looking at the crop. Do not estimate PDF coordinates from the pixels
of a candidate overlay.

## Read the paper, not only the picture

A figure is the authors' shorthand. What its labels, brackets and conventions mean, which
substrate an optimization used, what "standard conditions" are, is explained in the running text
and in the SI.

- `find_text <ws> <doc> '<regex>'` lists the hits (search for the block's label, entry numbers,
  compound numbers, abbreviations); then read `<dir>/text/pNNN.txt` of those pages. Look at
  `<dir>/pages/pNNN.png` when the passage is a drawing, a table or a scan. The first pages of an
  SI usually hold its table of contents.
- Page numbers are PDF page indices (as in the file names), never printed labels ("S16").
- Quote the passages you use: the sentence or two that matter, shortened with "…".
- Characterization data (NMR, HRMS, melting points) and whole experimental write-ups are not collected.
- When a passage contradicts what the block prints, the block's value stays in the record and the
  difference is described (`issues`, `notes`).

## Keys and steps

- Participants (reactants, products, byproducts, intermediates) use the compound label printed in
  the block ("1a", "3a′") or a short slug ("amine"). Conditions use short slugs (`cat`, `ligand`,
  `additive`, `solvent`, `temp`, `time`). Keys are unique across the participants and conditions
  of a template.
- A reaction is described as steps, each with the participants that react and those that form:
  `A + B → C` is one step. Start a new step only where the paper separates one (a second arrow,
  "then", "1) … 2) …"). What stands together on one arrow is one step.

## Reactant or condition

Decide step by step, from the product of that step as the paper draws or names it:

- A compound that contributes atoms to that product is a reactant of the step, whatever the paper
  calls it (a coupling partner, an organometallic reagent, an acylating agent).
- A compound that makes the step go without ending up in its product is a condition: catalysts,
  ligands, bases, additives, solvents, temperature, time, atmosphere.

A reactant that is drawn is a participant with its structure box. A catalyst, ligand or additive
that is drawn (a legend under a table, a drawing beside the scheme, a drawing in an entry) is a
structure with its box; a condition points to it with `structure_key`. Compounds only named in
text have no structure, and `structure_key` is null.

## Overrides

An override states how a footnote, a variant or one reaction differs from the template:
`{key, action, role, text, amount, structure_key, step, alternatives, basis, stated_at, inferred}`.

- `replace`: the non-null `text` / `amount` replace the item's values. `text` says what the item
  is: a compound's name, or for a temperature, time, atmosphere or solvent the value itself with
  its unit ("60 °C", "16 h"). `amount` is only the quantity of a compound ("10 mol%", "1.5 equiv").
  When `text` names another compound, set `structure_key` to its drawing, or null if it is not
  drawn. `role` only to change a participant's role; `alternatives` when the replacement is itself
  "A or B". A `per_entry` placeholder is filled only by a replace that gives `text`.
- `remove`: the item is absent ("no LiCl", an empty cell), or a participant takes no part.
- `add`: a new condition; give `role` (a condition role) and `text`, plus `amount` if printed.
  Compounds that react or form are participants, not added conditions.
- `use`: of the participants of an alternative group, this one applies; the others drop out.
- `basis`: where the change is printed ("footnote c", "cell cat.: C1", "deviation: no LiCl"),
  what the passage at `stated_at` says, or the reasoning of an inferred change.
- `stated_at`, `inferred`: the source of the change, as above. At most one of them is set; both
  are empty for what the block prints.

The pipeline applies them in this order: template, variant, footnotes, what the reaction's entry
prints, what the main text or the SI states about the reaction. A later layer wins. A name found
in the main text or the SI identifies the compound the block shows: it keeps the item's drawing
(its `structure_key` may stay null) and is not a change of compound.

## Boxes and text

- Boxes are `[x0, y0, x1, y1]` in PDF points on a page of `doc`, origin top-left. The attached
  images carry a point grid; read coordinates from them. A drawing in the other document (a legend
  of the main-text table drawn in the SI) gets no box: name the compound, leave `structure_key`
  null, and say in `context` where it is drawn.
- A structure box holds the drawing of one compound: leave out its label, its yield and
  neighbouring drawings where you can. Draw it slightly generous: the pipeline shrinks every box
  to the ink inside it.
- Text is copied as printed (names, amounts, units, ranges). Footnote superscripts go into the
  marker fields, not into the text. Do not normalise names or convert units.

## Tools

The page tools are described in `.agents/worker-guide.md`. Reach for them when the attached images are not
enough: `grid --clip <area>` for a finer grid, `crop` to check a box or read small print,
`layout --within <area> --gap 3` for box proposals in vector drawings, `find_text --words` for
the exact text of an area.

Your final message is the JSON object required by the output schema and nothing else.
