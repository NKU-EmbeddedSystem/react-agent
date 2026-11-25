---
name: equation-entries
description: Stage 1 for an equation block of a chemistry paper (whole reactions drawn as equations, each with its own starting materials, arrows with the conditions over and under them, products and results; one equation or a few, an arrow of a figure whose arrows start from one compound, or a sequence over several arrows). Turn 1 reads the block together with the paper's text and SI and writes the compounds once and every equation with its own participants, steps, conditions, variants and results; turn 2 lists the reactions the equations report, one handle each. Use when a prompt points to an equation-block task file under work/<paper_id>/step2.
---

# Equation block: read the equations, list their reactions

Read `.agents/shared/extract-core.md` first: it holds the rules every extraction follows (one
reaction, where each value comes from, overrides, keys, boxes). This skill says how to read a block
of equations.

An equation block draws whole reactions. Each **equation** shows its own starting materials, one or
more arrows with what is written over and under them, its products and its results. Unlike a table
or a scope figure, the equations of a block share no general reaction: every equation is read on its
own, and it takes nothing from the other equations except compounds that are the very same drawing.

Words used below: the **arrow text** is what is printed over and under an arrow; a **reference** is
arrow text that gives conditions by pointing elsewhere ("standard conditions", "conditions of
Table 2", "as above", a key such as "(ii)" that the caption explains, a protocol label); the
**caption** is the caption of the figure with its footnotes.

The block you get may be:

- one equation;
- several equations, one under another or side by side;
- one or more arrows of a figure whose arrows all start from (or lead to) one compound drawn in the
  middle. Each arrow is an equation, and the compound in the middle is one compound that all of
  them use. Other arrows of the same figure may be blocks of their own: what of them reaches into
  your block box is an ignored area, not an equation of yours;
- a sequence over several arrows, possibly branching (section 4).

This session has two turns:

1. **Turn 1** (now): understand the block, write its compounds once and every equation.
2. **Turn 2** (the next prompt): go through the equations and list the reactions they report.

After you, one agent per reaction checks your reading of its equation, reads its outcomes and looks
its experiment up in the main text and the SI. It sees its equation as you wrote it (as a template),
its results and the other equations in short. It cannot add compounds or protocols, and it adds
only what the experiment's own passage states that the equation leaves open (amounts, a time, a
temperature): everything the equation prints, and every reference it makes, is yours to write here.

## Task file

The prompt gives the path of a JSON task file:

- `workspace`, `doc`, `documents`: the paper workspace, the document of the block, and every
  document of the paper with its directory and page count. All of them are yours to read, the SI
  included, whatever the notes of the locate step say about the scope it searched.
- `paper`: reaction class and compound numbering of the paper.
- `region`: caption, verbatim footnotes and pages of the scheme or figure.
- `block`: page, bbox, and what the locate step noted about the block (its title, the number of
  entries it estimated).
- `shared_participants`: null for this kind of block.
- `text_layer`: when the block's text is real text, its words as lines `y=… | word@x word@x …`;
  arrow text above and below an arrow are separate lines, and atom labels of the drawings are mixed
  in. Null when the text is drawn or the figure is an image.
- `scratch`: a private directory for your own files.

Attached images: the block with a point grid; the further images, when the prompt announces them,
are close-ups of the block with the same point coordinates.

## Turn 1

### 1. Read in this order

1. **The equations.** Find each one: where it starts, its arrows, where it ends. For each arrow:
   the compounds on its two sides and what is drawn or written over and under it. A second arrow,
   or "1) … 2) …" or "then" over one arrow, makes a sequence (section 4).
2. **The arrow text, item by item.** Decide for each item whether it is a participant or a
   condition (extract-core: reactant or condition). On an arrow, these are participants:
   - a coupling partner or an organometallic reagent written as a formula or a name;
   - a reagent a fragment of which the drawn product shows (a group it transfers, a ring built
     with it);
   - a trapping or labelling agent when a drawn product or by-product contains it; when nothing
     drawn contains it, it is an additive;
   - a generic formula ("Ar–X", "R–M") whose group the drawn product shows: a participant with
     `generic` true. Which compound it was is named later from the text or the SI, never worked
     out by you.

   Everything else is a condition: catalyst, ligand, base, additive, solvent, temperature, time,
   atmosphere. A catalyst, ligand or additive that is drawn is a structure (section 2).
3. **References.** Arrow text that gives conditions by reference: follow each one (section 5)
   before you write conditions.
4. **The results.** What is printed for each equation: the yield of each product, ratios, ee, er,
   dr, "n.d." or "not observed", masses and scale, purity, a value measured on a starting material
   at the end, detection data (calculated and found masses) without a yield, time points. Find
   which compound each belongs to and, when several are printed, which protocol, option or
   condition each was measured under.
5. **The caption and its footnotes**: keys of the arrows, general remarks (how the yields were
   determined, averages of runs), what each footnote says and where its marker is printed.
   `region.caption` may be shortened: read the whole caption in `<dir>/text/pNNN.txt` of the
   block's page.
6. **The main text** around the block: what each experiment shows, how it was run (the text often
   says which conditions were used, which combinations were tested and what was observed).
7. **The SI**: the paragraph of each experiment. Start from its table of contents (sections for
   mechanistic or control experiments, transformations of products, scale-up, preparations), and
   find how a paragraph is matched to an equation (the product's number or name, the section title).
   Say where they are in `reading_guide` and quote what you used in `context`: the agents after
   you take the amounts and the details of each experiment from there.

### 2. `compounds`: every compound once

- One item per compound that reacts or forms in an equation of the block: drawn, named, or printed
  only as a number.
- One drawing is one compound with one key, also when several equations use it (the compound in the
  middle of a set of arrows; the product of one equation that the next one starts from). Never list
  the same drawing twice. When the paper draws one compound twice under the same number, the
  compound has the box of its first drawing in reading order, and the other drawing is an ignored
  area.
- `key`: the compound number as printed; else a short slug ("trap-adduct", "aryl-halide"). Keys of
  conditions are short slugs too; a compound and a condition of one equation never share a key.
- `label`, `text`: the number and the name or formula as the block prints them; null when it prints
  none. Never a name you work out from a drawing, and not one you find in the text or the SI for a
  drawn compound: names of drawn compounds are looked up later for each experiment, where they are
  checked against the drawing. `generic` true for a drawing or a formula with variable groups or for a
  compound class.
- `bbox`: the drawing of that one compound on a page of `doc`, without its number, its results and
  the arrow text, and without a neighbour's atoms. Draw it slightly generous; the pipeline trims it
  to the ink. No box (`page` and `bbox` null) for:
  - a compound only named (a reagent written over the arrow): its name in `text`;
  - a compound printed only as a number whose drawing is elsewhere (another panel, another figure):
    its number in `label`, and `stated_at` where the paper draws or names it when that is outside
    the block (a drawn compound has no `stated_at`). Never a box of another block;
  - a product shown only as a crystal-structure picture (balls and sticks): that is not a structural
    formula; the picture is an ignored area;
  - an intermediate that a sequence over one arrow forms without drawing it: a `text` only when the
    paper names it.
- `structures`: drawn compounds that are not participants (a catalyst or ligand drawn over an
  arrow), each with its box and printed label; a condition points to it with `structure_key`.

### 3. `equations`

One item per equation, in reading order. Each arrow from the compound in the middle of a set of
arrows is one equation; equations drawn one under another are separate equations, also when they
share a drawing. One drawing with a variable group whose results are printed for several values
("X = S: 81%; X = NBn: 74%") is one equation: its drawings are generic compounds, each drawn once,
and turn 2 gives every value its reaction. Never split a drawing into one equation per value, and
never box a drawing that is not there.

- `label`: as printed (the letter of an arrow, an equation number); null if none. Never compose one
  ("a, X = S") from other printed text.
- `bbox`: the whole equation: its compounds, arrows, arrow text and results. Equations that share
  the compound in the middle overlap there.
- `descriptor`: the equation in short ("21 + 22 → 23; standard conditions; 23, 58%").
- `general_reaction`: one sentence saying what it does.
- `results`: every result printed for the equation, verbatim, with what identifies it (the product's
  number, a protocol label, a condition): one item per printed result. "23, 58%" and "23, 61% (B)"
  are two results; a yield printed with its ee ("23, 58%, 90% ee") is one. Detection data of a
  product is a result of that product. Empty when nothing is printed.
- `footnote_markers`: every marker printed anywhere in the equation.
- `participants`: the compounds of this equation, each with its role here (a compound can be the
  product of one equation and a reactant of another), and `amount` as printed for it in this
  equation ("1.2 equiv" under the drawing, a number in front of it, "2.0 g, 10 mmol"); null when the
  equation prints none. The amounts of the experiment are looked up later from its own paragraph
  (section 5), so a participant's `stated_at` stays null.
- `steps`, `conditions`, `condition_pointer`, `variants`, `alternative_groups`, `preparations`,
  `variable_defaults`, `default_yield_type`: sections 4 to 6.

### 4. Steps and sequences

One step per arrow, and one per numbered stage on an arrow ("1) … 2) …", "then"). What stands
together on one arrow is one step (extract-core: keys and steps). The cases of a sequence:

- **Stages on one arrow, the intermediate not drawn**: one equation with one step per stage; the
  intermediate is a compound without a box, role `intermediate`, `isolated` false, and every
  condition carries the number of its `step`. The yield printed is that of the final product over
  the whole sequence.
- **Several arrows, the intermediates drawn without results of their own**: one equation; each
  drawn intermediate is a compound with its box and role `intermediate`, with `isolated` as the
  text or the SI says (null when nothing says).
- **An intermediate with a result of its own** (a yield printed for it): each part that has its own
  result is an equation of its own. The intermediate is the product of one and a reactant of the
  next: one compound, used by both.
- **Branches**: a sequence that splits after common steps into several final products gives one
  equation per final product, each with all its steps, the common ones included (the same
  compounds, the same conditions). When the common part has a result of its own, it is an equation
  of its own, and the branches start from its product.
- **An arrow that makes a catalyst, ligand or additive that another equation uses** (as a
  condition): an equation of its own, with the results printed for it or none. In the equation that
  uses it, it is a condition whose `text` is its number or name and whose `structure_key` is null
  (its drawing is the compound of the other equation).
- **An arrow that makes a reagent which then reacts and ends up in the product** (a reagent made on
  one arrow and consumed on the next): a stage of the sequence, by the cases above: the
  reagent is an intermediate of one equation, unless the paper isolates it and prints a result of
  its own for it. `preparations` stays empty as a rule.

### 5. Conditions and references

- `conditions`: one item per catalyst, ligand, reagent, additive, base, solvent, temperature, time
  and atmosphere, name and amount split ("5 mol%"), the `step` in a sequence, `structure_key` when
  drawn.
- **Printed on the arrow**: as printed.
- **A key on the arrow** that the caption explains ("(ii)"): the caption's text for that key, as
  printed. The caption is part of the block: no `stated_at`.
- **A reference to conditions the paper gives elsewhere** ("standard conditions", "conditions of
  Table 2", "as for compound 23", "as above"): find what it refers to: the conditions the text calls
  standard (as a rule the optimized entry of a table or the general procedure of the scope), or the
  entry, scheme or procedure it names. Then:
  - `condition_pointer`: `printed` as printed, `refers_to` what you found, `found` true, `stated_at`
    where those conditions are printed;
  - copy those conditions into `conditions`, each with `stated_at` of where they are printed: the
    catalyst, ligand and additives with their loadings, the solvent, temperature, time, atmosphere;
  - amounts of the starting materials and the scale are not taken from there: an experiment of this
    kind often runs on another scale, and the agent of the reaction takes them from the
    experiment's own paragraph. An amount the equation prints stays;
  - what the equation prints beside the reference (an added reagent, another temperature) is
    printed: it replaces the referred item of its kind or is added, without `stated_at`;
  - when the experiment's own SI paragraph gives other conditions than the referred ones, say so in
    `notes`; the agent of the reaction writes the paragraph's values.
- **A reference that leads outside the paper** (to other work), or one the paper never resolves:
  `found` false, `stated_at` null; write only what the equation prints, and say in `notes` what is
  missing. When this concerns one protocol of the equation only, that protocol's variant has
  `conditions_given` false.
- **Protocol labels without conditions** ("[A]", a metal in brackets, "method B"): one variant per
  label; its conditions from where the paper defines the protocol, with `stated_at`; when the paper
  defines it nowhere, `conditions_given` false. Such a variant starts from nothing (no condition and
  no amount of the equation carries over), so it states again, as replace overrides, what the
  equation prints for that protocol (a reagent's amount, a temperature on its arrow).
- **"A or B" for a condition, or a range**: as extract-core says (`alternatives`, the value the text
  gives).
- **Optional items that make several runs** (an item marked "with or without", an amount written
  "none or n equiv", several such items on one arrow):
  - the equation prints a result for each run, or the text names the runs (below): write the
    equation with the items as the first run uses them, without `alternatives`; that run's variant
    needs no overrides, and every other run's variant `remove`s an item it does without or
    `replace`s its amount;
  - the equation prints a result for each run: each run is a variant;
  - it prints one result for all of them: one reaction, the choices stay open (`alternatives` on the
    items), and what the text says about the separate runs goes into `notes`;
  - it prints no result and the text names the runs that were done: one variant per run it names,
    titled as the text describes it; each is a reaction without results. When the text does not
    tell the runs apart either, it is one reaction with the choices open.

### 6. Several results, protocols and variables

- Results told apart by a **protocol label**: one variant per label, with the label as `title`.
- An **"A or B" over the arrow with a result for each** ("trace (A); 35% (B)"): one variant per
  option, titled as printed. The equation as you wrote it runs the first option, and its variant
  needs no overrides. For each other option, by the kind of the first one:
  - the first option is a condition (a solvent, a base, a temperature): `replace` it with the other
    option, its name or value and amount;
  - the first option is a participant that ends up in a drawn by-product, and the main product does
    not contain it: `remove` that participant and every drawn by-product that contains it, and `add`
    the other option as a condition with its role and amount, unless the text says the other option
    ends up in a product too;
  - the first option ends up in the step's only product (or in the main product): the other option
    does the same, so it is a participant: `replace` the first option with the other one (its name
    and amount), and `replace` the product with the one the other option gives: the name the paper
    gives it (with `stated_at`), or else a short description such as "the product with B, not
    drawn", `inferred` true and the reasoning in `basis`. Never remove the only product of a step;
    the pipeline rejects a protocol that does.
- **Catalysts or reagents listed with a result each** ("with catalyst A: 71%; with catalyst B:
  65%"): one variant per listed item, replacing the condition of its kind (`replace` with its name,
  and `structure_key` when it is drawn).
- Results told apart by **values of a variable group** ("X = S: 81%; X = NBn: 74%"): no variant;
  turn 2 gives each reaction its values and the participants that carry the symbol.
- **Several products of one run** (a direct and a rearranged product, a product and a by-product, a
  ratio of isomers): one reaction with several results.
- `alternative_groups`: two compounds drawn or named for one position ("ester A or ester B"). Every
  compound of a group is a participant and stands in `steps` at that position, beside the others;
  the pipeline keeps the one a reaction uses and drops the rest. Every group needs a `default` (the
  compound of the results that print no option), with `stated_at` or `inferred` and the reasoning; a
  variant picks its own member with `use`.
- `variable_defaults`: a value stated once for a variable group ("Y = OMe unless noted"): one item
  per participant whose drawing carries the symbol (the same participants turn 2 names for a printed
  value).
- `default_yield_type`: as the caption, a footnote or the text states it for the equation; null when
  nothing says.

### 7. Footnotes

- `footnotes`: one item per marker of `region.footnotes`, with its verbatim text.
- A footnote printed in an equation that changes something for it gets `overrides`, with the keys of
  that equation; give the same kind of item the same key in every equation that prints the marker
  (`temp`, `solvent`). When one of those equations has no item of that kind, write the change as an
  `add` with its role: it replaces the item where one exists and adds it where none does.
- A footnote of the title or the caption concerns every equation: write what it states into the
  equations and give it no overrides.
- A footnote that only says how a value was measured, or what a result means, has no overrides; say
  what it means in `notes`.

### 8. Ignored areas

Inked parts of the block that are neither an equation, a compound nor a structure: titles and panel
letters, footnote text, photographs of an apparatus or a product, work-up flowcharts,
crystal-structure pictures, schematic arrows that summarise a sequence without compounds, plots,
proposals drawn beside the experiments, a second drawing of a compound already boxed, and what of
another block reaches into the block box (another arrow of the same figure, a neighbouring panel).

### 9. Guide, passages, notes

- `reading_guide`: for the agents that each collect one reaction: how the equations are laid out,
  what each result means, where the conditions of each equation come from, where the SI describes
  each experiment and how a paragraph is matched to it, and the pitfalls of this block (a result
  printed nearer to a neighbouring arrow, a value measured on a starting material, a product only
  numbered here).
- `context`: the passages of the main text and the SI you relied on, quoted, with what each settles.
- `notes`: what concerns the block and no field takes.

### 10. Check before answering

- Every inked area inside the block box lies in an equation box, a compound box, a structure box or
  an ignored box. The pipeline checks this and sends leftovers back.
- Every compound is listed once and takes part in an equation; every participant of an equation is
  one of the compounds and appears in its steps.
- Every item of every arrow text is accounted for: a participant, a condition, or a change a variant
  makes.
- Every reference is followed: found, with where; or found false.
- Every printed result is in the `results` of exactly one equation.
- No box cuts its drawing or takes in a neighbour's.

## Turn 2: the reactions

The next prompt asks you to go through the equations you wrote and list the reactions the block
reports, in equation order. Answer with the schema of that turn.

- **One equation is one reaction**, unless it prints the results of several experiments: other
  protocols, the options of an "A or B", the listed catalysts or reagents, the values of a variable
  group (section 6), or the runs the text names (section 5). Several products of one run, a yield
  with its ee, the detection data of a product of the same run: one reaction.
- `entry`: the number of the equation in your `equations` (1 = first).
- `results`: the numbers of this reaction's results in the equation's `results`. Every printed
  result belongs to exactly one reaction. An equation that prints no result still has its reaction
  (or one per run the text names), with no results.
- `variant`: the variant of this reaction; null when it has none.
- `footnote_markers`: the markers of the equation that apply to this reaction: those on its own
  results and compounds, and those on the arrow text it runs.
- `distinguishing`: for every reaction of an equation that reports several, what sets it apart, as
  printed; else null.
- `variables`: the values of variable groups printed for this reaction ("X = S"), each with every
  participant of the equation whose drawing carries the symbol (as a rule the reactant and the
  product that show it); empty otherwise.
- `notes`: why an equation was split. `issues`: doubts a reviewer should look at.

Your final message in each turn is only the JSON object required by the output schema.
