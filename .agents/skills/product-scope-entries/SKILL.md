---
name: product-scope-entries
description: Stage 1 for a product-scope block of a chemistry paper (a substrate-scope scheme or table, one general reaction drawn once and entries that each draw one product with its compound number and results, while the reactants of an entry are not drawn and follow from the general reaction). Turn 1 reads the figure together with the paper's text and SI and writes the template, the fields of an entry and every entry as cells; turn 2 lists the reactions the figure reports, one handle each. Use when a prompt points to a product-scope task file under work/<paper_id>/step2.
---

# Product scope: read the figure, list its reactions

Read `.agents/shared/extract-core.md` first: it holds the rules every extraction follows (one
reaction, where each value comes from, overrides, keys, boxes). This skill says how to read a
product scope.

A product scope runs one general reaction, drawn or written once (an equation over the entries,
or a scheme or equation the caption or the text points to), on many substrates and shows what came
out. The general reaction has **positions**: the reactants, the product, and any by-product the
entries report a result for. Each **entry** is one drawn product with its **legend**, the text
printed with the drawing: its compound number, sometimes values of variable groups, its results,
footnote markers, remarks. An entry fills in the product; as a rule it prints nothing about its
reactants (at most the value of a group only a reactant carries, or a remark).

Words used below: the **caption** is the figure's caption with its footnotes; the **legend** is
the text of one entry; a **heading** is a title over a group of entries.

What an entry does not draw comes from elsewhere: the general reaction fixes it (a specific
compound, the same for every entry), or it **follows from the product by the general reaction**:
cut the product at the bond the reaction forms, and each piece, with the group the general reaction
shows there, is one reactant. Such a reactant is recorded as unknown (derived) and worked out later
from the drawing, not here. Write the figure so that this later step has everything it needs: the
product of every entry boxed, every position of every entry accounted for, and for every unknown
position which part of the product it is and how it follows.

**Read the figure as a table whose column heads are not printed.** The entries are its rows. The
kinds of things a legend prints (the drawing, the number, a variable value, the results, a remark)
are its columns: you set them up yourself (section 3, the *fields*) and then write every entry as
one cell per field. The schema and the messages of the pipeline use the table words: `columns` are
your fields, `entries` the rows, and "row 3" is your third entry.

This session has two turns:

1. **Turn 1** (now): understand the figure, write the template, the fields and every entry as cells.
2. **Turn 2** (the next prompt): go through the entries and list the reactions they report.

After you, one agent per reaction reads what is left of its entry (remarks, conditions, outcomes)
and looks its compound up in the text and the SI. It sees your template, your fields and its own
entry. The pipeline itself puts the drawing of an entry into the position its field points at and
applies the entry's compound number and variable values. Everything that concerns more than one
entry is therefore decided by you, here.

## Task file

The prompt gives the path of a JSON task file:

- `workspace`, `doc`, `documents`: the paper workspace, the document of the block, and every
  document of the paper with its directory and page count. All of them are yours to read, the SI
  included, whatever the notes of the locate step say about the scope it searched.
- `paper`: reaction class and compound numbering of the paper.
- `region`: caption, verbatim footnotes and pages of the scheme, table or figure.
- `block`: page, bbox, and what the locate step noted. `block.scheme` is the general scheme the
  entries follow (page, box, description), or null.
- `shared_participants`: when not null, the positions of this scheme as another block of the same
  figure already described them. Copy them into `template.participants` unchanged (same keys,
  labels, boxes and `generic`); you may add positions they lack.
- `text_layer`: when the figure's text is real text, the words of the block area as lines
  `y=… | word@x word@x …`. Legends of entries that stand side by side share a line (tell them
  apart by x), and atom labels of the drawings are mixed in. Null when the text is drawn or the
  figure is an image.
- `scratch`: a private directory for your own files.

Attached images: the block with a point grid; a second image shows the general scheme when it
lies outside the block; the last images, when the prompt announces them, are close-ups of the
block with the same point coordinates.

## Turn 1

### 1. Read in this order

1. **The general reaction.** Find it: the equation over the entries; without one, what the
   caption, a footnote or the text points to ("the reaction of eq 1", "conditions as in Table 1");
   without a drawing at all, the reaction as the caption and the conditions footnote name it
   ("coupling of aryl halides with alkylzinc reagents"). `block.scheme` is what the locate step
   found for it; when that is null and the block has no equation of its own, follow the pointer
   yourself and look at the page it leads to. Then take its positions one by one:
   - which compounds react and which form, with their labels; a second arrow, "1) … 2) …" or
     "then" make it a sequence (section 2, `steps`);
   - for each, whether it is a specific compound (one structure for every entry) or generic (drawn
     with variable groups R, X, Ar, with a placeholder ring or chain, or named as a class);
   - which variable groups a generic drawing carries, and what a legend beside the general
     reaction says about them ("Y = A or B").

   The general reaction may be a **model reaction**: one example drawn with specific compounds.
   A position is then specific only when no entry shows another group in the part of the product
   that comes from it; one entry that does makes the position generic: the model compound is one
   instance of it, not the position, and its drawing is not the position's box, nor its number the
   position's label (section 2).
2. **Colours and marks.** A scope figure often draws the part that comes from one reactant in one
   colour and the part from the other in another, marks the bond that forms (bold, a dot on each
   atom), or colours what changes from entry to entry. Find what each colour and mark means: the
   general reaction usually uses the same colours, and the caption or the text may say. This is
   what tells which part of a product belongs to which reactant. The same product can be made
   from two different pairs of reactants, and then only the colours show which pair an entry used.
   Without colours, a heading that says which reactant a group varies tells it.
3. **How each reactant follows from the product** (`derivations`, section 2).
4. **The caption and the conditions footnote**: scale, amounts, solvent, temperature, time,
   atmosphere, and how the yields and selectivities were determined. A sentence such as "X = I
   unless noted otherwise" gives the default of a variable group. `region.caption` may be
   shortened: read the whole caption in `<dir>/text/pNNN.txt` of the block's page.
5. **The groups of entries.** Headings, panels, dividing lines: what each group varies (which
   reactant), what it holds fixed, and what its heading sets for the entries under it (a value of
   a variable group, a protocol, conditions, a footnote marker). The block may be one panel of a
   larger figure: the other panels are blocks of their own, but may share this general reaction.
6. **What one legend prints**: set up the fields (section 3). Look at several entries first, the
   most crowded ones included.
7. **Every footnote marker**: what it says and where it is printed (on a yield, on a compound
   number, on a heading, on the title, in the general reaction, or only in another panel).
8. **Several results in one legend**: results under protocol labels ("[A] 72% / [B] 55%"), under a
   condition ("rt: 40%; 60 °C: 80%"), under values of a reactant's group ("Br: 70% / Cl: 52%").
9. **The main text** about the figure and its compounds: which substrates failed, what a group
   shows, special cases (a product that forms by another path than the general one).
10. **The SI**: the general procedure of this scope (scale, volumes, atmosphere, how the reagents
    were made); the paragraphs that report the individual products, where they are, how one is
    matched to an entry (its compound number, its name) and whether they name the starting
    materials used; and where the SI lists or characterises the starting materials. Take a value
    from an SI procedure only when it is the procedure of this figure (extract-core: the source of
    every value). Where the general procedure contradicts what the figure prints, the figure's
    value stays; describe the difference in `notes` and quote the passage in `context`.

### 2. The template: what every entry shares

The template has the fields of any block template (see the schema). For a product scope:

- `participants`: one per position of the general reaction, plus every compound a footnote, a
  protocol or an entry makes react or form in addition. The agents after you cannot add
  participants. `key` and `label` are those of the general reaction ("1", "3"); `text` the name
  or formula it prints for the position ("R–M", "alkene"), or null; `amount` as printed.
  - The product and every reactant the entries vary are `generic` true; the box of each is its
    drawing in the general reaction, and its `label` the number printed there. A position the
    general reaction prints only as a formula or a name has no box. In a model reaction (section
    1, step 1) that drawing and number belong to one instance: the position then has no box, and
    its `label` is the number the paper gives the whole class ("1" where the text speaks of the
    bromides 1), else null, never the instance's number.
  - A reactant is specific (`generic` false) only when the figure holds it fixed and says which
    compound it is: the general reaction draws it as one compound without variable groups (and,
    for a model reaction, no entry shows another group in its part), or a heading or the caption
    names or numbers it ("with 2a"). Its box is where the paper draws that very compound on a page
    of `doc`; without such a drawing it has no box, its number as `label` and its name as `text`.
  - A reactant that merely looks the same across the drawings, without the paper saying so, stays
    generic: it follows from each product like the others.
  - Other panels of the figure may follow the same general reaction and take your positions
    unchanged. Look at the whole figure before you call a position specific, and keep it generic
    when another panel varies it.
  - A by-product whose yield or number the entries print is a participant with role `byproduct`.
    First decide whether it changes with the entries: it does when it forms from a reactant the
    entries vary; it does not when it forms only from compounds the general reaction fixes (a
    product of a fixed reagent alone, such as its homo-coupling product). One that does not change
    is specific when the paper draws that very compound somewhere without variable groups, or
    names it: its box is that drawing when it lies on a page of `doc`, else it has no box and its
    name goes in `text` with `stated_at`; it needs no derivation, even when the general reaction
    draws it with variable groups. A drawing with variable groups is never the box of a specific
    compound. Every other by-product is generic and gets a derivation.
- `steps`: one step with all reactants and products when the general reaction is one arrow. Start
  a new step only where the figure separates one (a second arrow; "1) … 2) …" or "then" over an
  arrow): reagents that the general procedure premixes before the substrate is added (a metal salt
  with the organometallic reagent, a base with the nucleophile) do not make a step of their own.
  The cases of a sequence:
  - **Every entry is a sequence** (two arrows; "1) … 2) …" or "then" over one arrow): one step per
    stage, the intermediate as a participant (role `intermediate`, `isolated` false), and every
    condition with the number of its `step`. The yield an entry prints is that of the final
    product over the whole sequence.
  - **Some results only have an extra step** (a protocol label or footnote "in situ", "prepared
    in the flask"): the compound the other results start from and the one made in the flask (an
    intermediate, `isolated` false) are two participants of one alternative group, with the
    compound of the unmarked results as its `default`. Add the step that makes the in-flask
    compound from its precursors (they belong to that step only, in no group), with that step's
    reagents and conditions as template conditions carrying its `step`; the variant or footnote
    `use`s the in-flask compound. The pipeline drops a step whose reactants or whose products are
    all removed, together with what only that step needs, so the extra step appears only where
    it is used.
  - **An intermediate that is isolated and has its own yield**: each step is its own reaction.
    Write both steps, the intermediate with `isolated` true, and one variant per step: the variant
    of the first step `remove`s the final product and gives the intermediate the role `product`
    (a yield is recorded only on a product); the variant of the second `remove`s the reactants
    that only the first step uses and gives the intermediate the role `reactant`. A number and a
    yield the entries print for the intermediate get fields of their own (a `label` field that
    targets it, an outcome field whose measure is on it). Turn 2 gives each result the variant of
    its step.
  - **The general reaction shows how a starting material was made, but the yields do not include
    that step** (an activated compound prepared and isolated beforehand): that arrow goes into
    `preparations`, not into `steps`. Its `items` name what it was made with; the compound it was
    made from goes into `items` too when nothing else makes it a participant. When it is a
    participant anyway (a reactant of a step another protocol runs), point at it with
    `from_participants` instead, never both.
  - One figure can combine these (the same first arrow is a preparation for one protocol and a
    step for another): write each protocol as its case requires. The precursors are then
    participants of the in-flask step, so the preparation of the isolated compound lists them in
    `from_participants`, and its `items` keep only the reagents of that arrow.
- `derivations`: one item per generic position that the entries do not draw. A specific compound
  the general reaction fixes needs none: do not write one, and do not make the compound generic to
  fit one.
  - For each generic reactant: `key` the reactant, `from` the product, and `how`: one sentence
    saying which part of the product it is and what stands at the bond the reaction forms, named
    by its symbol or class as the general reaction shows it ("the part drawn in blue, with the
    halogen X on the carbon of the new bond", "the other part, with the boron group on its carbon
    of the new bond", "…, with the metal M on that carbon"). Do not write out the rest of the
    reagent's formula or its exact form (how many groups the metal carries, which ester): the
    position's box shows the drawn form, and a protocol, a footnote or the SI that uses another
    form names it in the participant's text, for which your sentence must still hold. Describe;
    never name the structure. A reactant that carries a variable group (a leaving group with its
    default) needs its item all the same: the group is one part of it, not the compound.
  - A by-product the entries only number follows from the reactant it is made of (`from` that
    reactant; `how` says how it forms from it): the chain product → reactant → by-product is fine.
  - An intermediate of a sequence follows from the product (`from` the product); the starting
    material of the first step then follows from the intermediate.
  - A compound that takes part only under one protocol (the compound made in the flask, its
    precursors) needs its item too: the pipeline requires one for every generic position the
    entries do not draw.
  - When some entries draw a reactant instead of the product (substrates shown as unsuccessful),
    add the forward item too: `key` the product, `from` the reactants, `how` the bond that forms.
    The pipeline requires it.
  - Write steps and derivations so that they hold under every protocol and every footnote, not only
    the default one.
- `variable_defaults`: the value of a variable group the entries do not print, when the paper
  states it ("X = I unless noted otherwise"), with the participant that carries it; and what the
  heading of the block's one group sets. A default lives only here (never only in a field's
  `blank_means`). A symbol that a legend of the general reaction defines as one of a few groups
  ("Y = A or B") and that each entry or result names is a variable of its reactant: its field
  gives the value, and it gets a default only when the paper names one.
- `shared_results`: a result printed once for every entry, verbatim; usually empty.
- `conditions`: everything the general reaction and the conditions footnote state for all
  entries, split into name and amount; a value from the text or the SI has `stated_at`.
  - The scale the caption or the footnote gives ("0.25 mmol scale") is the amount of the limiting
    reactant: "0.25 mmol, 1 equiv" on that participant. A number printed in front of a compound of
    the general reaction ("3 R–Nu") is its amount, with the unit the caption or the SI gives
    ("3 equiv"), else as printed.
  - An amount that only the SI gives for a compound the figure prints (a solvent volume, the
    equivalents of a reagent) goes on that template item with `stated_at`; the item keeps its
    printed name.
  - A condition the general reaction prints as a range and the footnote as one value has the
    footnote's value. A range or an "A or B" that the entries settle one by one stays open: the
    range as printed, "A or B" as `alternatives` on the item (extract-core: the source of every
    value).
  - A condition is `per_entry` only when every entry prints its own value for it and you give it
    a `condition` field; this is rare in a scope.
- `structures`: drawn compounds that are not positions (a catalyst or ligand drawn beside the
  general reaction), with their printed labels as keys.
- `footnotes`: one item per marker of `region.footnotes`, with its verbatim text.
  - A footnote printed on the title or in the general reaction concerns every entry: write what
    it states into the template and give it no overrides.
  - A footnote printed in entries that changes an amount, a time, a temperature, a catalyst or
    the scale for the entries that carry it gets `overrides`.
  - A footnote printed on a heading concerns the entries of that group: it gets `overrides`, and
    its marker goes into a cell of every entry of the group (the field of the heading, section 4;
    also where that cell is a `same_as`, since markers are not inherited).
  - A marker that this block never prints (it marks results of another panel of the same figure)
    is listed with its text and no overrides; say in `notes` that this block does not print it,
    and never write its content into the template. A footnote that defines a protocol label is
    written into that label's variant.
  - A footnote that says another class of reactant was used ("the chloride was used", "from the
    iodide") is a replace of that reactant with the name as `text`; the reactant stays unknown.
    When the class is the value of a variable group of that reactant, the entries carrying the
    marker give that value in the group's field instead.
  - A footnote or variant that puts another reactant into the step that makes a compound in the
    flask changes that compound too, when the replaced reactant gives part of it (another
    activating agent gives another activated compound): give the in-flask compound a replace as
    well, with `text` saying what it then is, `inferred` true and the reasoning in `basis`. It
    stays unknown and keeps its derivation.
  - A footnote that only says how a value was measured, or that a product was impure, has no
    overrides; say what it means in `notes`.
- `default_yield_type`: as the paper states it (isolated, NMR, GC, analytical against an internal
  standard); null when nothing says.
- `variants`: one per protocol under which results are printed side by side.
  - One variant per printed label, with the label as `title`. A combination of labels printed with
    one result ("[P] [A]") is one variant with that combination as its title; a result that
    carries fewer labels than its neighbours is a variant of its own, titled as printed.
  - A variant says which compounds it starts from (`use` for a member of an alternative group,
    `remove` for a participant that takes no part) and what it changes in the conditions.
  - A heading that sets a protocol or conditions for its group is a variant, titled as the heading
    prints it; turn 2 gives the entries of the group that variant.
  - Several sets of conditions that the general reaction assigns by the kind of substrate
    ("conditions A for aryl, conditions B for alkyl substrates") are variants too, titled as
    printed.
  - `conditions_given` is false when neither the figure, the text nor the SI gives the conditions
    of a protocol; a pointer to the SI is not enough to decide it: look there first.
- `alternative_groups`: as for any block (extract-core); every group needs a `default` (for the
  results that print no label), also when every result carries a label.
- `reading_guide`: for the agents that each read one entry: how a legend is laid out, what every
  field means, which symbols belong to the entry's own drawing and which to a reactant, what the
  colours and parentheses mean, which footnotes are printed where, and the pitfalls of this
  figure (a legend that stands closer to the neighbour's drawing than to its own, entries that
  share a drawing, a second result line).
- `lookup_guide`: where the main text and the SI report the individual products and how a
  paragraph is matched to an entry; whether those paragraphs name the starting materials; where
  the SI lists the starting materials. '' when you found nothing.
- `context`: the passages of the main text and the SI you relied on, quoted, with what each settles.
- `scheme`: the area of the general reaction: `block.scheme` when given, else where you found it
  on a page of `doc`; null when it is not drawn in `doc`.

### 3. The fields of an entry

`columns` lists the fields: one item per kind of thing the legends print, with a short unique
`key` ("product", "label", "R", "X", "yield", "remark"). `header` is '' unless the figure prints
column heads.

| kind | the field holds | `targets` |
|---|---|---|
| `participant` | the drawing of the entry | the position it shows: the product |
| `label` | the compound number printed with the drawing | the position it numbers |
| `entry_number` | the entry number, when entries are numbered ("entry 5") instead of their compounds | none |
| `variable` | the value of a variable group printed in the legend ("R = Me", "n = 2", "X = Cl") | see below; plus `variable_name` |
| `outcome` | the results | none; `measures` instead |
| `deviation` | a change of conditions that concerns the whole entry ("at 45 °C", "on a 2 mmol scale", "3 equiv of the base") | none |
| `condition`, `amount` | a condition, or only an amount, that every entry prints for itself | the per_entry condition; the condition or participant |
| `other` | remarks ("from the cyclic bromide", "derived from <a natural product>", a deposition number) and anything else; say what in `notes` | none |

- **Whose variable it is.** Decide it for every symbol:
  - A symbol drawn in the entry's own drawing (an "R" on a ring, an "n" on a chain, an "Ar" that
    the legend spells out) is a group of that drawing: its field targets the product only. It
    may look like a symbol of the general reaction and mean something else (the general
    reaction's R a whole substituent, the entry's R one group on its ring): it is the entry's.
  - A symbol that only a reactant of the general reaction carries and that leaves no trace in the
    product (a leaving group X, the metal or boron group) targets that reactant, also though the
    legend prints it under a product.
  - The same symbol on drawings of different positions (an R on the product drawings, an R on
    the drawing of a substrate shown as unsuccessful) is one field per position, each with its
    own key and target.
  - A field gives one group. Its cells hold only values ("Me", "R = Me"), never the result
    printed after them.
- A condition printed in front of one of several results of a legend ("60 °C: 80%") stays in the
  result cell; a `deviation` field is for a change that concerns the whole entry.
- A by-product the entries number ("6a: 12%" under the product's line) has a `label` field of its
  own, targeting the by-product, listed after the product's label field.
- A remark that says what a reactant was ("from the cyclic bromide") belongs in an `other` field,
  copied exactly: the agent of the reaction writes it onto that reactant. Several such remarks
  that tell the results of one legend apart go into that field together, in printed order ("from
  the E isomer / from the Z isomer"), and stay in the result cell as well.
- `measures` (outcome fields): what the result of an entry holds, in printed order, each with the
  participant it is measured on, the measure and the yield type the caption or a footnote states.
  "74% (68%)" where the caption says the value in parentheses is isolated holds two yields of the
  product; "85%, 92:8 er" a yield and an er of the product. A result line of its own for another
  compound (the by-product's yield) is a second outcome field.
- `unit`, `values`, `blank_means`: as in a table; usually null and empty.
- A setting that a heading fixes for its group (a value of a variable group, a marker) is a field
  of its own (section 4).

### 4. The entries

`entries` lists one entry per compound the figure reports, in reading order (group by group, line
by line, left to right).

- **One entry per printed compound number.** A drawing that serves a list of compounds ("5a, R =
  H, 78%; 5b, R = OMe, 70%; …") gives one entry per compound.
- A result that runs the default of a reactant's variable group, while another result of the same
  compound prints a value of that group ("5k, 62%" and "5k, X = Cl, 41%", on two lines or on one),
  is an entry of its own: these entries share the drawing (`same_as`) and the box; a number
  printed once goes in the first of them and the others' number cells are `same_as` it; the entry
  of the default result leaves the group's field empty, the other has the value. Results that
  each print a value of the group stay together in one entry ("Br: 70% / Cl: 52%", below), and so
  do results told apart by a protocol label or a condition; turn 2 splits them.
- A list of values under one drawing without compound numbers ("R = A, B, C"), with one result or
  one heading for all of them, gives one entry per value as well: the first with the drawing, the
  others `same_as` it, each with its own value and the shared result repeated in its outcome cell.
- `label`: the compound number as printed (the entry number where entries are numbered), without
  footnote markers; null when the entry prints none.
- `bbox`: the whole entry: its drawing and its legend. Entries that share one drawing have the
  same box.
- `cells`: one per field, in field order.
  - The drawing: text '', and `structure_bbox` the box of this one compound, without its legend
    and without a neighbour's atoms. When part of the drawing stands beside its own legend so that
    no rectangle holds the whole drawing without some of the legend, hold the whole drawing and
    take in as little of the legend as you can. An entry that shares the drawing of an earlier
    entry leaves the cell empty with `same_as` that entry (its number in `entries`, 1 = first).
  - The compound number, the variable value, the remark: as printed, without footnote markers;
    '' when the entry prints none.
  - The results: as printed, footnote markers left out. When one legend prints several results,
    keep them in the cell in printed order with what identifies each, and a marker that belongs
    to one of them stays after its value ("[A] 72% c / [B] 55%").
  - When the results of a legend are told apart by values of a reactant's variable group ("Br:
    70% / Cl: 52%"), the values go into that group's field ("Br / Cl") and the results into the
    outcome field ("70% / 52%"), in the same order; turn 2 gives each reaction its part of both.
  - `markers`: the footnote markers printed on that part of the entry.
- A setting that a heading fixes (section 3): the first entry of the group has the heading's
  value (and marker) in that field, the others `same_as` it and repeat the marker.
- **An entry that draws a reactant instead of the product** (a substrate shown as unsuccessful):
  its drawing is the cell of a `participant` field that targets that reactant (a field of its
  own, empty in the other entries), and the compound number printed with it goes into a `label`
  field that targets that reactant. Its product cell is empty: the product stays in the record as
  an unknown position (it follows from the reactants by the forward derivation). What is printed
  as its result, often only the heading of its group, goes into the outcome cell of every such
  entry. An entry that draws both a reactant and its product has both drawings, each in its field.
- A deposition number printed under a crystal-structure picture goes into the `other` field of
  the entry whose compound it shows; the picture itself is an ignored area.
- `lookup_hint`: where the paper reports this entry's compound (its SI paragraph), when you found
  it while reading section 1, step 10; else null.
- `descriptor`: the entry in short ("5b; drawing shared with 5a; R = OMe; 70%").
- When `text_layer` is given, use it to transcribe numbers and markers exactly, and check every
  word against the image. Without it, read small print from the close-ups (or render your own
  with `crop`), not from the overview.

### 5. Ignored areas

Inked parts of the block that are neither an entry, the scheme, a participant nor a legend
structure: the title, headings, dividing lines, footnote text, crystal-structure pictures,
photographs, lists of features, and content of a neighbouring panel that reaches into the block box.

### 6. Check before answering

- Every inked area inside the block box lies in an entry box, the scheme box, a participant box, a
  structure box or an ignored box. The pipeline checks this and sends leftovers back.
- Every entry has a cell for every field; every `same_as` points at an earlier entry that prints
  the value (or repeats one that does); entries with the same box share the drawing by `same_as`.
- Every position of every entry is drawn by the entry, fixed by the general reaction, or covered
  by a derivation.
- Every marker in a cell is a footnote of the template; every footnote with overrides is printed in
  some entry; every alternative group has a default.
- No structure box cuts its drawing or takes in a neighbour's.
- Compare the number of entries with `block.n_entries_est`.
- Reread `reading_guide` as if you saw one entry and nothing else.

## Turn 2: the reactions

The next prompt asks you to go through the entries you wrote and list the reactions the figure
reports, in entry order. Answer with the schema of that turn.

- **One entry is one reaction.** The several numbers of a legend measure one experiment: a yield
  and an ee, er or dr; an analytical and an isolated yield; the yields of the product and of a
  by-product.
- **Split an entry only when it prints several experiments**, each with its own result:
  - results under protocol labels: each reaction gives, for the result cell, the `part` that is
    its own (copied exactly) and its `variant`. Two results printed after one label are two
    reactions of that variant: each gives its own result as `part`;
  - results under values of a reactant's variable group: each reaction gives its part of the
    result cell and, under `cells`, its part of that group's cell, at the same position;
  - results under a condition ("60 °C: 80%", "on a larger scale: 75%", "with another ligand:
    62%"): each gives its part; the reaction without such a remark runs the template;
  - a yield for an isolated intermediate and one for the product: each with the variant of its step.

  Every reaction of a split entry says in `distinguishing` what sets it apart, as printed.
- **One printed result for several runs** ("average of two runs") and **"A or B" with one result**
  are one reaction.
- `entry`: the number of the entry in your `entries` (1 = first).
- `results`: the outcome cells of the reaction; `part` null when the whole cell is its own. Every
  printed result belongs to exactly one reaction. An entry that prints no result still has its
  reaction, with no results.
- `variant`: the variant whose label is printed with this reaction's results, or heads the group
  the entry stands in; null without a label. When the general reaction assigns sets of conditions
  by the kind of substrate and the entry prints no label, give the variant the rule assigns to
  what the drawing shows, and say in `notes` that it is your reading of the drawing.
- `footnote_markers`: the markers that apply to this reaction: those on its compound number and on
  its own results, and the marker of the heading its group stands under. Never the markers of the
  title or the general reaction.
- `notes`: why an entry was split, or how a variant was assigned. Nothing for plain entries.
- `issues`: doubts a reviewer should look at.

Your final message in each turn is only the JSON object required by the output schema.
