# Inventory mode

You are the block reader. In this turn you understand the block as a whole, write that
understanding down as the template, and list the entries. In the turns that follow, in this
same session, you will be shown one entry at a time and spell out the reactions it reports
(`references/expand.md`). After that, one agent per reaction boxes its compounds, reads its
outcomes and looks it up in the text and the SI; it sees only its entry plus what you wrote.
Do not spell out the entries in this turn.

The attached image shows the block with a point grid. Render more with the page tools as needed.

## 1. Understand the block

Read three things before writing anything:

1. The block itself, with its caption and footnotes.
2. The main text about it. Search for the block's label ("Table 1", "Figure 1B") and for its
   compound numbers, and read those paragraphs: they say what was optimized on which
   substrate, what a label or a colour means, which entries the authors single out and why.
3. The SI parts that define it, when the paper has an SI: the general procedures of the
   protocols the block names, the fuller version of the table ("Optimization details"),
   a graphical guide. Start from the SI's table of contents.

Then answer:

- What reaction is this, and in how many steps as the paper presents it? Which compounds
  react and which form in each step? Read the general scheme arrow by arrow.
- For each step: which of the things on its arrow end up in its product (reactants), and
  which do not (conditions)? See SKILL.md.
- What does one entry consist of: which structure is drawn (product only? both reactants?),
  where is its label, which numbers are yields and under which conditions, what do colours,
  brackets, prefixes and superscripts mean?
- What is said once for the whole block: panel title, legend, caption, footnotes ("[M = Zn]",
  "X = Br unless otherwise noted", "isolated yields").
- Where are the open points (SKILL.md)? For each one: what settles it, for the block as a
  whole and for each protocol?
- Do results come under several protocol labels? How do the protocols differ, in conditions
  and in the compounds they start from? Where does the paper give the conditions of each?
- Does the scheme show how a starting material was made, although the reported yields are for
  the later step only?

## 2. Template

- `general_reaction`: one sentence.
- `reading_guide`: your guidance to the agents that will extract the single reactions,
  specific to this figure. Say how an entry is laid out and what each printed element means, what they
  have to take from the scheme because it is not drawn in the entry, and what is easy to get
  wrong here (entries sharing a drawing, a yield that belongs to a neighbour, a default that
  some entries override). Say where in the main text and the SI the single reactions of this
  block are described (for example "the SI lists each product under its number from page 30
  on, naming the general procedure used"), so that they can look theirs up. Write it so that
  someone who sees one entry and nothing else of the figure reads it correctly.
- `context`: the passages of the main text and the SI that you relied on, each with document,
  page, the quoted sentence or two, and what it settles.
- `steps`: the reaction as numbered steps, each with the keys of the participants that react
  and of those that form. One step for a single-step reaction.
- `scheme`: the general scheme of the block. When the task gives `block.scheme`, that is it:
  use its page and box, and describe all of it, every step of a multi-step scheme included.
  When `block.scheme` is null, use a header or model reaction drawn inside the block if there
  is one, else null.
- `shared_participants` in the task, when present, are the participants of this scheme as a
  sibling block already described them. Copy them into `participants` with the same keys and
  boxes; add further participants only for compounds this block needs in addition.
- `participants`: each compound of the general or model reaction, with role, printed label,
  printed name (`text`), amount as printed ("0.2 mmol", "0.4 mmol, 2.0 equiv"), and the page
  and structure box of its drawing (null when it is not drawn). `generic` is true when the
  drawing has variable groups (R, X, Ar, dashed rings) or stands for a class of compounds.
  - The general scheme may sit outside the block (an equation in the text, a scheme above
    another table); it is then shown in a second attached image.
  - In a sequence, include the intermediates (role `intermediate`, with `isolated`).
  - A reactant drawn or written on an arrow is a participant too (page and box null when it
    is only named).
  - A compound that reacts but that the block does not show at all (the acid behind an
    "in situ" ester, named only in the text or the SI) is a participant without a box, with
    `stated_at`.
  - A reaction scale printed for the block ("0.1 mmol") is the amount of the limiting
    reactant: "0.1 mmol, 1 equiv".
  - `alternatives`: when the name itself leaves a choice ("NHPI or TCNHPI ester") and there is
    one drawing for both.
  - List every compound that any protocol of the block needs. Every participant appears in
    `steps`.
- `alternative_groups`: one group for each position where the paper draws or names separate
  compounds as alternatives ("A or B" side by side). List their keys. Every participant of
  the group appears in `steps` at that position.
  - `default`: the one that applies to a result reported without a variant, with what decides
    it: `stated_at` when the text or the SI says so ("optimization was carried out with ester
    1"), `inferred` with your reasoning when the paper does not say.
  - A protocol that always uses one of them picks it in its variant with a `use` override.
  - `default` may be null when the choice changes from entry to entry and each entry shows
    which one it uses; the row of every such reaction then picks one.
  - The pipeline checks that every reaction is left with exactly one of them, and tells you
    here which protocols leave the choice to the rows.
- `conditions`: one item per catalyst, ligand, reagent, additive, solvent, temperature, time
  and atmosphere that the scheme and the "Reaction conditions" footnote state for every
  entry; split name and amount ("ZnCl2", "0.2 mmol, 1.0 equiv"). Set `structure_key` when
  the compound is drawn, `step` in a sequence, `alternatives` when the paper leaves a
  choice open ("Fe(acac)3 or FeCl3"), and `stated_at` when the value comes from the text or
  the SI instead of the block.
  A condition the block gives entry by entry (a column of an optimization table, a reagent
  printed under each product) is one item with `per_entry` true and the header or
  placeholder as printed in `text` ("cat.", "additive"); keep an amount the scheme prints
  for it. The entries state the values. Do not fill it with the value of a best or
  "standard" entry.
- `structures`: every drawn compound that is not a participant: the catalysts or ligands of
  a legend (C1–C6, L1–L8), a catalyst drawn over the arrow, a reagent drawn for a
  preparation. One structure box each; the label and name printed with it go into `label`
  and `text`. Include the ones that only some entries use. A legend may sit outside the
  block (below the table, in another figure of the same document).
- `preparations`: for a starting material that the block shows being made although the
  reported results do not include that step (an activated ester that was isolated first, and
  the yields are for its coupling). Name the participant, the participants it was made from
  (`from_participants`), and the other compounds and conditions on that arrow as `items`: a
  compound that ends up in the starting material has role `reactant`, the others their
  condition role; a drawn one points to its `structures` entry. That preparation is then not
  a step of the reaction. Leave the list empty when the block shows nothing of the kind.
- `footnotes`: one item per marker of `region.footnotes`, with the verbatim text of that
  marker. Put what it changes about amounts or conditions into `overrides`; everything else
  (how yields or d.r. were determined, defaults) into `notes`. The footnote that defines the
  base conditions has no overrides.
- `variable_defaults`: what is stated once for a variable group, in a footnote ("X = Br unless
  otherwise noted"), a panel title ("[M = Zn]") or a legend: its name, its value and the
  participant that carries it.
- `default_yield_type`: the yield type the paper states for the block; null when it states
  none. A yield measured on the crude mixture against an internal standard, without the
  method being named, is `analytical`.
- `variants`: the protocols under which results are reported side by side (see SKILL.md),
  each with its overrides relative to the base conditions.
  - One variant per printed label, with the label as `title`. A label that is printed
    without a prefix ("[Fe]" next to "[isolated] [Fe]" and "[in situ] [Fe]") is a variant of
    its own. What you take it to mean is marked `inferred` unless the paper says it.
  - A variant says which compounds it starts from: `use` for a member of an alternative
    group, `remove` for a participant that takes no part, `role` to change a role.
  - `conditions_given` is false when neither the block, the main text nor the SI gives the
    conditions of the protocol. Nothing of the base conditions and amounts is then taken
    over for it: list in `overrides` only what the paper does state about this protocol.
    When the SI has the protocol (a general procedure), `conditions_given` is true and the
    overrides carry its conditions with `stated_at`.
  - Leave `variants` empty if there are none.

For a procedure written in prose, the participants are the compounds or compound classes it
names and the conditions come from the text.

For an optimization table, the participants are the model substrates and products, and each
row is a reaction. The base conditions are what the scheme above the table and the conditions
footnote state for all rows. Every column the table varies is a `per_entry` condition named
by its header. A table that lists deviations from stated standard conditions ("none",
"without LiCl", "FeCl2 instead of C1") has those standard conditions as its base.

## 3. Entries

List every entry (SKILL.md: what the block prints as one unit) in reading order: printed
`label` (compound label or entry number; null if none), `page`, entry box, and `descriptor`:
the text printed for it, in short (label, results with their protocol labels, footnote
markers, annotations such as "X = Cl"). Do not split an entry here, even when it reports
several reactions (results under several protocol labels, an R list under one drawing): that
is the work of the following turns, one entry at a time.

When `block.entries_first_page` is set (for example the compounds made by a general
procedure, each with its own paragraph on later pages), go through those pages and list one
entry per paragraph that belongs to this block, with the box of the paragraph.

## 4. Ignored areas

Inked parts of the block that are neither an entry, the scheme nor a drawn structure: panel
titles, column headers, dividers, text legends, crystal-structure pictures, footnote text, and
content of a neighbouring panel that reaches into the block box.

## 5. Check before answering

- Every inked area inside the block box lies in an entry box, the scheme box, a participant
  box, a structure box or an ignored box. The pipeline checks this and sends leftovers back.
- Compare your count with `block.n_entries_est`; recount if they differ much.
- Every compound drawn or written on an arrow of the scheme is accounted for: as a
  participant, a base condition, an override of a variant or footnote, or an item of a
  preparation.
- Every open point of the block has its field, and everything you explain in
  `reading_guide` or a note about who reacts and under which conditions is also expressed
  there.
- Every value that is not printed in the block has `stated_at` or `inferred`.
- Reread `reading_guide` as if you saw only one entry: would you extract it correctly?
- In a crowded block, look at a crop of the most crowded boxes.
