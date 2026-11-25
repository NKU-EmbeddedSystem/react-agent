---
name: reactant-table-entries
description: Stage 1 for a reactant-table block of a chemistry paper (one general reaction drawn once; each table row gives the reactant(s) of that reaction as drawings, names, compound numbers or variable groups, and the product usually follows from the general reaction without being drawn). Turn 1 reads the table together with the paper's text and SI and writes the template, the columns and every row as cells; turn 2 lists the reactions the table reports, one handle each. Use when a prompt points to a reactant-table task file under work/<paper_id>/step2.
---

# Reactant table: read the table, list its reactions

Read `.agents/shared/extract-core.md` first: it holds the rules every extraction follows (one
reaction, where each value comes from, overrides, keys, boxes). This skill says how to read a
reactant table.

A reactant table runs one general reaction, drawn or written once (a header equation, or a
scheme or equation the caption or the text points to), on many substrates. The general reaction
has **positions**: the reactants, the product, and any byproduct the table reports a result for.
A row fills in some of them with
specific compounds:

- drawn in a cell, named in a cell, or as a compound number whose drawing is elsewhere;
- as the values of variable groups (R, X, Ar) of a position drawn generically ("X = SMe", a column
  headed R);
- one drawing may serve several rows, each row giving its own value of a variable group.

What a row does not print comes from elsewhere: the header fixes it (a specific compound drawn
once for all rows), a default gives its variable groups, or it **follows from the other
participants by the general reaction**. The last case is usually the product: it is recorded as
unknown (derived) and worked out later from the reactants, not here. Write the table so that this
later step has everything it needs: every position of every row accounted for, and for every
unknown position the participants it follows from and how.

This session has two turns:

1. **Turn 1** (now): understand the table, write the template, the columns and every row as cells.
2. **Turn 2** (the next prompt): go through the rows and list the reactions they report.

After you, one agent per reaction reads what is left of its row (condition cells, outcomes) and
looks the entry up in the text and the SI. It sees your template, your columns and its own row.
The pipeline itself applies the participant, variable and label cells of a row to the positions
your columns point at. Everything that concerns more than one row is therefore decided by you,
here.

## Task file

The prompt gives the path of a JSON task file:

- `workspace`, `doc`, `documents`: the paper workspace, the document of the block, and every
  document of the paper with its directory and page count. All of them are yours to read, the SI
  included, whatever the notes of the locate step say about the scope it searched.
- `paper`: reaction class and compound numbering of the paper.
- `region`: caption, verbatim footnotes and pages of the table or figure.
- `block`: page, bbox, and what the locate step noted. `block.scheme` is the general scheme the
  rows follow (page, box, description), or null.
- `shared_participants`: when not null, the positions of this scheme as another table that follows
  it already described them. Copy them into `template.participants` unchanged (same keys and boxes).
- `text_layer`: when the table is real text, the lines of the text layer of the block area as
  `y=… | word@x word@x …`; null when the table is drawn or scanned.
- `scratch`: a private directory for your own files.

The attached image shows the block with a point grid; a second image shows the general scheme
when it lies outside the block.

## Turn 1

### 1. Read in this order

1. **The general reaction.** Find it: the header equation; without one, what the caption, the
   footnotes or the text point to ("eq 1", "Scheme 1", "conditions of Table 1"); without a
   drawing at all, the reaction as the caption and the conditions footnote name it ("conjugate
   addition of thiols to enones"). Then take its positions one by one:
   - which compounds react and which form, with their labels;
   - for each, whether it is a specific compound (one structure for every row) or generic (drawn
     with variable groups R, X, Ar, with a placeholder such as "alkyl", or named as a class);
   - which variable groups a generic drawing carries, and what colours or highlights mark (often
     the part that changes from row to row, the same colour in a reactant and in the product);
   - whether the rows give it (a column), the header fixes it, or it follows from the others.

   The scheme the block points to may be a **model reaction**: one example of the general
   reaction drawn with specific compounds (the substrates of an optimization). Then a position
   that the rows vary is generic all the same: the model compound is one instance of it, not the
   position, and its drawing is not the position's box, nor its number the position's label
   (section 2). Keep as specific only the compounds that really are the same in every row, and
   leave out the model reaction's byproducts unless the table reports results for them.
2. **How each unknown position follows** (`derivations`, section 2).
3. **The caption and the conditions footnote**: scale, amounts (an amount the caption gives for
   one reagent, "1.3 equiv of the thiol", goes on that position), solvent, temperature, time,
   atmosphere, and how the yields were determined. `region.caption` may be shortened: read the
   whole caption in `<dir>/text/pNNN.txt` of the block's page.
4. **The columns**, one by one (section 3).
5. **Every footnote marker**: what it says and where it is printed (an entry number, a cell, a
   column header, the title, the header reaction).
6. **Protocol labels and values in parentheses**: a value in parentheses with its own footnote
   ("67 (71)c" with c: "on a 12 mmol scale") is a second experiment of the row, under that
   footnote; one in parentheses without a footnote is explained by the header or the caption.
7. **The main text** that cites the table or its entries: what it says about particular entries,
   failed substrates, abbreviations.
8. **The SI**: the general procedure of this table (scale, volumes, atmosphere, how the reagents
   were made), and the paragraphs that report the individual products, with their names, compound
   numbers, amounts and yields. Find where they are and how a paragraph is matched to a row: an
   entry reference ("Table 4, entry 6"), a compound number, or only the names of the reactants
   and the yield. Take a value from an SI procedure only when it is the procedure of this table
   (extract-core: the source of every value). A fuller SI table is a block of its own.

### 2. The template: what every row shares

The template has the fields of any block template (see the schema). For a reactant table:

- `participants`: one per position of the general reaction, plus every compound a footnote,
  protocol or row makes react or form in addition. Give the drawing of the general reaction as
  the box of each position it draws (`generic` true for a drawing with variable groups or a class
  name, and for every position a column gives; false only for a compound that is the same in every
  row). A position the general reaction only names has no box. In a model reaction (section 1,
  step 1) the drawing and number of a position the rows vary belong to one instance: the position
  then has no box, and its `label` is the number the paper gives the whole class ("4" where the
  text speaks of the aldehydes 4), else null, never the instance's number. The agents after you
  cannot add participants.
- `steps`: usually one step with all reactants and products.
- **A reagent made in the flask for some runs only** (a footnote or protocol label "made in situ"
  on some results): the reagent as the other rows use it and the reagent made in situ (an
  intermediate, `isolated` false) are two participants of one alternative group, with the
  reagent of the unmarked rows as its `default`. Add the step that makes the in-situ reagent from
  its precursors (they belong to that step only, in no group), and give the footnote or variant
  a `use` of the in-situ reagent. The pipeline drops a step whose products are all removed, so the
  extra step appears only in the runs under that footnote.
- `derivations`: one item per position that a row leaves unknown (usually the product):
  - `key`: the position; `from`: the participants it follows from;
  - `how`: one sentence saying which part of each of them ends up where, as the general reaction
    draws it: the bond that forms, the groups that leave ("the carbon that carries I bonds to the
    carbon that carries Sn; I and SnBu3 leave"), what a colour corresponds to, which variable group
    carries over ("R of the aldehyde is the R of the alcohol"). Describe; never name the structure.
  - A position that no column gives, but that some rows change visibly (the product drawn in those
    rows shows another ester group than the default), follows from the participants that show it
    (here the product and the other reactant): it is derived, not a default.
  - A generic position whose variable groups the row gives all of (a "substrate / Ar" table where
    Ar is the only variable of both drawings) is known: the generic drawing with those values, no
    derivation. A position the row's values define only in part (the product carries a group R
    from a variable column, but its other part comes from the reactant drawn in the row) keeps its
    derivation; its values are attached to it as well, and it stays unknown.
  - Every generic position that a row does not print needs either a derivation or variable
    values (a variable column, or `variable_defaults`). The pipeline checks this row by row.
- `variable_defaults`: the value of a variable group the rows do not print, when the paper states
  it ("R = cyclohexyl unless noted") or a fixed compound defines it, with the participant that
  carries it.
- `shared_results`: a result printed once for every row (">85% yield" under the header
  equation), verbatim. Each reaction reads it as its own outcome.
- `conditions`: everything the header and the conditions footnote state for all rows, split into
  name and amount; a value from the text or the SI has `stated_at`. A condition that a column gives
  row by row is one item with `per_entry` true (its `text` is the column header as printed); this
  is rare in a reactant table.
- `structures`: drawn legend compounds that are not positions (a catalyst drawn beside the table),
  with their printed labels as keys.
- `footnotes`: one item per marker of `region.footnotes`, with its verbatim text.
  - A footnote printed on the title, a column header or the header reaction concerns every row:
    write what it states into the template and give it no overrides.
  - A footnote printed in rows that changes an amount, a time, a temperature or the scale for the
    rows that carry it gets `overrides`.
  - A footnote that puts another reagent in the place of a position ("RCu(CN)Li (2 equiv) instead
    of R2CuLi") is a replace of that position with the new compound's name and amount.
  - A footnote that only says how a value was measured, or that a product was impure, has no
    overrides; say what it means in `notes`.
- `default_yield_type`: as the paper states it (isolated, NMR, GC, analytical against an internal
  standard); null when nothing says.
- `variants` and `alternative_groups`: as for any block (extract-core); every group needs a
  `default` for the rows that print no label.
- `reading_guide`: for the agents that each read one row: what every column means, how an empty
  cell reads, what colours and parentheses mean, which footnotes are printed where, and the
  pitfalls of this table.
- `lookup_guide`: where the main text and the SI report the individual entries and how a passage is
  matched to a row (section 1, step 8); '' when you found nothing.
- `context`: the passages of the main text and the SI you relied on, quoted, with what each settles.
- `scheme`: the area of the general reaction (`block.scheme` when given).

### 3. The columns

One item per printed column, in order, with a short unique `key` and the `header` as printed. A
column header often prints the generic formula of the position it gives ("R–X", "alkyl–SnBu3",
"ArSi(OR)3", "enone"): that is its target.

| kind | the column gives | `targets` |
|---|---|---|
| `entry_number` | the entry numbers | none |
| `participant` | the compound of one position, row by row: drawn, named, or a compound number | that position |
| `variable` | the value of a variable group ("R", "X = SMe") | every participant whose drawing (the general reaction's or the row's) carries the symbol; plus `variable_name` |
| `label` | the compound number of one position, row by row ("compound 9e" for the product) | that position |
| `condition` | which compound or value one condition has, row by row | the per_entry condition |
| `amount` | only the quantity of one compound, row by row | that condition or participant |
| `deviation` | a change from the standard conditions in words | none |
| `outcome` | measured results | none; `measures` instead |
| `other` | anything else; say what in `notes` | none |

- A participant column whose cells print compound numbers with the drawings elsewhere (another
  figure, a chart): resolve each number under `values` (its `structure_key` when it is drawn on a
  page of `doc`, else its name as `text`, with `basis`). The number becomes the participant's
  label.
- A variable column gives one group. A printed column that gives different groups in different
  rows ("X = SMe" in some rows, "R = Bn" in others) is one column item per group, with the
  same header: each has its own `variable_name` and targets, and its cell is '' in the rows that
  give the other group.
- `measures` (outcome columns): what one cell holds, in printed order, each with the participant it
  is measured on, the measure and the yield type the header or a footnote states. A "conversion to
  adduct" measured against an internal standard is the yield of that product (NMR or GC); only
  the consumption of a starting material is a conversion, measured on that reactant.
- `unit`, `values`, `blank_means`: as in a condition table. `blank_means` says how an empty cell
  of the column reads: "as in the row above", "not determined", "no product drawn".

### 4. The rows

`entries` lists every printed row, in reading order (a table printed in two halves side by side:
the left half top to bottom, then the right half).

- `label`: the entry number as printed, without footnote markers; null when rows are not numbered.
- `bbox`: the whole row with all its cells, including a drawing that serves it and the rows below.
- `cells`: one per column, in column order.
  - `text`: the cell as printed, without footnote markers; '' for an empty cell. For a drawn cell,
    the label printed with the drawing, or ''.
  - `markers`: the footnote markers printed in the cell (an entry number printed "2b" is text "2",
    markers ["b"]).
  - `structure_bbox`: the box of the drawing of one compound, without its label and without the
    neighbouring cell's drawing; null otherwise.
  - `same_as`: for an empty cell that repeats the value of an earlier row (a blank meaning "as
    above"), the number of that row in `entries` (1 = first); a chain of blanks may point at the
    row just above. When one drawing serves several rows, it belongs to the first of them; the
    others leave the cell empty with `same_as` that row, and give their own variable values in
    the variable column. An empty cell that means "none" or "not drawn" has `same_as` null.
- `lookup_hint`: where the paper reports this row's experiment (its SI paragraph), when you found
  it while reading section 1, step 8, with how you matched it; else null.
- `descriptor`: the row in short ("6; enone drawn; X = SMe; 71; 64").
- When `text_layer` is given, use it to transcribe exactly, and check every word against the image:
  the text layer misspells some labels ("Li" for "L1") and glues markers to the word before them.

### 5. Ignored areas

Inked parts of the block that are neither a row, the scheme, a participant nor a legend
structure: the title, column headers, rules, footnote text, and content of a neighbouring panel
that reaches into the block box.

### 6. Check before answering

- Every inked area inside the block box lies in a row box, the scheme box, a participant box, a
  structure box or an ignored box. The pipeline checks this and sends leftovers back.
- Every row has a cell for every column; every `same_as` points at an earlier row that prints the
  value (or repeats one that does).
- Every position of every row is printed by the row, fixed by the header, given by variable values,
  or covered by a derivation.
- Every marker in a cell is a footnote of the template; every footnote with overrides is printed in
  some row; every alternative group has a default.
- Compare the number of rows with `block.n_entries_est`.
- Reread `reading_guide` as if you saw one row and nothing else.

## Turn 2: the reactions

The next prompt asks you to go through the rows you wrote and list the reactions the table
reports, in row order. Answer with the schema of that turn.

- **One row is one reaction.** The several numbers of a row measure one experiment: a conversion
  and a yield, an analytical and an isolated yield, a yield and an ee.
- **Split a row only when it prints several experiments**, each with its own result:
  - a value in parentheses with its own footnote (another scale, a reagent made in situ), or two
    results each with a condition or protocol label. Each reaction gives, for the result cell, the
    `part` that is its own (copied exactly) and says in `distinguishing` what sets it apart;
  - two compounds or variable values printed together in one cell, each with its own result
    ("1b / 1c" with "70 / 65"). Each reaction also gives under `cells` its part of that cell.
- **One printed result for several runs** ("mean of three runs", runs that only the SI reports
  separately) is one reaction.
- **"A or B" with one result** is one reaction; the agent of the reaction records the alternatives.
- `entry`: the number of the row in your `entries` (1 = first).
- `results`: the outcome cells of the reaction; `part` null when the whole cell is its own. Every
  printed result belongs to exactly one reaction. A row whose result cells are all empty still has
  its reaction, with no results.
- `cells`: empty unless the row is split on a cell that prints two compounds or values.
- `variant`: the variant whose label is printed in this row for this reaction; null without a label.
- `footnote_markers`: the markers printed in the row that apply to this reaction: on the entry
  number, in its cells and on its own results. Never the markers of the title, a column header or
  the header reaction.
- `notes`: why a row was split, or what is unusual about it. Nothing for plain rows.
- `issues`: doubts a reviewer should look at.

Your final message in each turn is only the JSON object required by the output schema.
