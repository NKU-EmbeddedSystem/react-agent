---
name: condition-table-entries
description: Stage 1 for a condition-table block of a chemistry paper (an optimization or screening table, one fixed model reaction whose entries change only conditions, as text cells, words or drawn catalysts/ligands). Turn 1 reads the table together with the paper's text and SI and writes the template, the columns and every row as cells; turn 2 lists the reactions the table reports, one handle each. Use when a prompt points to a condition-table task file under work/<paper_id>/step2.
---

# Condition table: read the table, list its reactions

Read `.agents/shared/extract-core.md` first: it holds the rules every extraction follows (one
reaction, where each value comes from, overrides, keys, boxes). This skill says how to read a
condition table.

A condition table runs one model reaction, drawn or written once (in a header equation, in the
scheme above the table, or in a scheme or equation the caption or the text points to), many times
with some conditions changed: another catalyst, ligand,
additive, base, solvent, temperature, time or amount, sometimes another reactant. A row prints
its change in columns, in words ("no NaI", "CoCl2 instead of Co(acac)2"), or as a drawing (a
ligand drawn for each entry with its yields underneath). A small results table under an
equation (catalyst loading vs. yield) is a condition table too.

This session has two turns:

1. **Turn 1** (now): understand the table, write the template, the columns and every row as cells.
2. **Turn 2** (the next prompt): go through the rows and list the reactions they report.

After you, one agent per reaction reads its row into conditions and outcomes. It sees your
template, your columns and its own row, nothing else of the table. Everything that concerns more
than one row is therefore decided by you, here.

## Task file

The prompt gives the path of a JSON task file:

- `workspace`, `doc`, `documents`: the paper workspace, the document of the block, and every
  document of the paper with its directory and page count. All of them are yours to read, the SI
  included, whatever the notes of the locate step say about the scope it searched.
- `paper`: reaction class and compound numbering of the paper.
- `region`: caption, verbatim footnotes and pages of the table or figure.
- `block`: page, bbox, and what the locate step noted. `block.scheme` is the general scheme the
  rows follow (page, box, description), or null.
- `shared_participants`: when not null, the participants of this scheme as a sibling block
  already described them. Copy them into `template.participants` unchanged (same keys and boxes).
- `text_layer`: when the table is real text, the lines of the text layer of the block area as
  `y=… | word@x word@x …`; null when the table is drawn or scanned.
- `scratch`: a private directory for your own files.

The attached image shows the block with a point grid; a second image shows the general scheme
when it lies outside the block.

## Turn 1

### 1. Read in this order

1. **The model reaction.** Find it first: the header equation; without one, what the caption, a
   footnote or the text points to ("the reaction of Scheme 1", "eq 2", "conditions as in Table 1");
   without a drawing at all, the reaction as the caption and the conditions footnote name it
   ("coupling of 4c with 6b"). `block.scheme` is what the locate step found for it; when that is
   null and the table has no header equation, follow the pointer yourself and look at the page it
   leads to. Then read it: which compounds react and which form, with their labels: the
   reactants, the product and every byproduct the table reports a yield for. Read the text over
   and under the arrow. A compound on the arrow that ends up in the product is a reactant
   (extract-core: reactant or condition).
2. **The caption and the conditions footnote** ("Reaction conditions: …", usually footnote a):
   scale, amounts, solvent and volume, temperature, time, atmosphere, and how the yields were
   determined. `region.caption` may be shortened: read the whole caption, with its panel
   descriptions and abbreviation lists, in `<dir>/text/pNNN.txt` of the block's page.
3. **The legend.** Catalysts or ligands drawn with labels (C1–C4, L1–L5, 5a–5d). It may be under
   the table, beside it, or in another figure or scheme: when cells cite labels you do not see,
   search for them with `find_text` in both documents and look at those pages. Box only drawings
   on pages of `doc`. A legend drawn in the other document (a main-text table whose ligands are
   drawn in the SI) gets no structures: the conditions keep their printed names, and `context`
   says where they are drawn.
4. **The columns**, one by one (section 3).
5. **Every footnote marker** of the table: what it says and where it is printed (an entry number,
   a cell, a column header, the title, the header reaction).
6. **Protocol labels** printed in cells ("[B]", "Method B"), or in the header under drawn
   alternatives ("[A] or [B]").
7. **The main text** that cites the table or its entries ("Table 1, entry 9", "entries 3–7"):
   which entry gives the standard conditions, what abbreviations mean, what the authors single out.
8. **The SI optimization section** (its table of contents says where): the procedure of this
   screening (scale, volumes, atmosphere, internal standard), and the conditions a placeholder in
   the header stands for ("metal salt", "additives", "conditions", "see SI"). Take a value from an
   SI procedure only when it is the procedure of this screening. The typical procedure of the
   substrate scope, a gram-scale run or another table is another protocol, even with the same
   reagents: its solvent, volume or atmosphere are not this table's (extract-core: the source of
   every value). The fuller SI table is a block of its own: do not take over its rows.

### 2. The template: what every row shares

The template has the fields of any block template (see the schema). For a condition table:

- `participants`: every compound that any row or protocol of the table makes react or form, not
  only those drawn in the header. A compound that reacts but is not drawn (the acid behind an
  ester made in situ, a reactant only a deviation names) is a participant without a box, with
  `stated_at` (extract-core: one reaction). The agents after you cannot add participants. They
  are specific compounds: `generic` false, unless a variable column gives one of their groups
  (an X column with Br/I). A byproduct whose yield the table reports has role `byproduct`.
  A model reaction drawn elsewhere on a page of `doc` gives the participants their boxes there.
  One drawn only in the other document, or only named, gives participants without boxes: their
  printed names or labels as `text`, and `context` says where the reaction is drawn or stated.
- `steps`: usually one step, with all reactants and all products and byproducts. A protocol that
  forms the starting material in the flask is a sequence. Rows say so in a protocol label, a
  deviation or a footnote ("in situ", "made in situ", "prepared in the flask"), for example an
  acid activated with a coupling agent and a base and then coupled: add the activation step, in
  which the acid reacts and the ester forms as an intermediate (`isolated` false).
  - When the other rows start from that same ester, isolated, it is one participant: those rows
    remove the acid, and the activation step drops out.
  - When they start from another compound (one activated ester, where the in-situ rows make
    another), the in-situ ester and that compound are alternatives for one position: one alternative
    group, with the compound of the unlabelled rows as its default, and the variant `use`s the
    ester. The acid belongs to the activation step and to no group. The pipeline drops a step whose
    products are all removed, so the activation step and its acid disappear wherever the ester is
    not used.
- `conditions`: every catalyst, ligand, reagent, additive, base, solvent, temperature, time and
  atmosphere that the header and the conditions footnote state for all rows, and those that any
  protocol needs (the coupling agent and the base of the in-situ activation); split name and
  amount ("CsF", "0.3 mmol, 1.2 equiv"). A value that comes from the text or the SI has
  `stated_at`.
  - A condition that a column gives row by row is one item with `per_entry` true. For a compound
    its `text` is the column header or the placeholder as printed ("cat.", "additive", "ligand",
    "base") and its `amount` the amount the header prints for it ("cat. (2.5 mol%)" gives text
    "cat.", amount "2.5 mol%"). For a temperature or time column its `text` is the header as
    printed ("T (°C)", "time"). Do not fill it with the value of the standard entry.
  - A condition whose amount alone changes row by row (a column "NaBr (equiv)", "cat. loading
    (mol%)") keeps its real name as `text` and is not per_entry: its amount column changes only
    the amount.
  - An amount found only in the SI for a per_entry condition goes on the template item, with
    `stated_at`.
  - A table of deviations ("change from the standard conditions") has the standard conditions as
    its base: everything the header and the footnote state. It needs no per_entry condition,
    unless it also has columns that give a condition row by row.
- `structures`: every drawn legend compound on a page of `doc`, with its printed label as key,
  its printed name as `text` and its box. A drawing that is a row's own cell (a ligand drawn for
  each entry) is that cell's `structure_bbox` (section 4), not a legend structure.
- `footnotes`: one item per marker of `region.footnotes`, with its verbatim text.
  - A footnote printed on the title, on a column header or in the header reaction concerns every
    row. No reaction carries its marker (turn 2), so overrides on it would never be applied:
    write what it states into the template's participants, conditions or `default_yield_type`,
    and give it no overrides. The footnote with the base conditions is one of these.
  - A footnote printed in rows that changes conditions or amounts for the rows that carry it gets
    `overrides` ("CoBr2 (8 mol %)" on the catalyst amount, "at 60 °C" on the temperature). A
    compound it swaps in keeps the amount of the one it replaces unless the footnote gives one.
  - Such a footnote may replace what a column gives for its row (the cell prints "MnCl2" and
    footnote e says "MnBr2 instead"). Write the override, and say in `reading_guide` how a cell
    under that footnote reads: the footnote wins for what it sets.
  - A footnote that names what a cell abbreviates ("[Ni] = Ni(Cy-PyIm)Br2"), says how yields
    were measured, or defines an abbreviation has no overrides; say what it means in `notes`.
    The agent of the reaction writes the resolved name into its row.
- `default_yield_type`: how the yields of the table were determined, as the paper states it
  ("determined by 1H NMR" is NMR, "isolated yields" is isolated, a GC yield against an internal
  standard is GC; measured on the crude against an internal standard without naming the method:
  analytical). Null when nothing says.
- `variants`: one per protocol label printed in cells, as for any block (extract-core). Rows
  without a label run the template. A label printed only in the header, under drawn
  alternatives, names the protocol of the unlabelled rows: that protocol is the template, it gets
  no variant, and the group's `default` picks its compound.
- `alternative_groups`: every group needs a `default` for the rows that print no label (with
  `stated_at`, or inferred with your reasoning). The pipeline checks this.
- `reading_guide`: for the agents that each read one row: what every column means, what an
  empty cell or "–" means, which footnotes are printed where and how a cell reads under them,
  what abbreviations and brackets mean, and the pitfalls of this table (a row printed over two
  lines, two halves side by side, a value in parentheses, a drawing whose label is printed under it).
- `context`: the passages of the main text and the SI you relied on, quoted, with what each settles.
- `scheme`: the area of the model reaction: `block.scheme` when given, else where you found it
  on a page of `doc`; null when it is not drawn in `doc`.

### 3. The columns

One item per printed column, in order, with a short unique `key` and the `header` as printed. A
table printed in two halves side by side has its columns once: list the columns of one half; the
rows of both halves use them (section 4).

| kind | the column gives | `target` |
|---|---|---|
| `entry_number` | the entry numbers | null |
| `condition` | which compound or value one condition has, row by row: catalyst, ligand, additive, base, solvent, temperature, time, atmosphere | the per_entry condition of the template |
| `amount` | only the quantity of one compound, row by row: a loading, equivalents, a concentration | the condition or participant whose amount it gives |
| `participant` | a reactant or product row by row (a substrate column, a column of swapped compounds) | the template participant it replaces |
| `variable` | the value of a variable group of a participant (an "X" column with Br/I) | that participant; plus `variable_name` |
| `deviation` | the change from the standard conditions in words | null |
| `outcome` | measured results | null; `measures` instead |
| `other` | anything else; say what in `notes` | null |

- `unit`: the unit of the column's bare numbers ("mol%", "equiv", "°C", "h", "M"), as the
  header, a footnote or the text gives it; null when the cells carry their units or are not
  numbers. Give where the text states it in `notes` when the header does not print it.
- `values`: what a printed value stands for when it is not written as printed. One item per
  distinct printed value, with the `text`, `amount` or `structure_key` it is written as, and the
  `basis`:
  - a legend label ("C1" is Co(Mes-PDI)Cl2, drawn as C1: text "Co(Mes-PDI)Cl2", structure_key "C1");
  - an R group that selects a drawn catalyst ("Tripp" in an "Ar" column: the catalyst drawn with
    that group, its name and structure_key). Such a column is a condition column on the catalyst,
    not a variable column: variable columns give groups of reactants and products;
  - a drawn ligand that was added as its salt (the NHC drawn, its HBF4 salt weighed in: text
    "ICy·HBF4").
  Leave `values` empty when every value is written as printed.
- `measures` (outcome columns only): what one cell holds, in printed order, each with the
  participant it is measured on, the measure (yield, conversion, ee, er, dr, other) and the
  yield type the header or a footnote states. A cell "15/6/41" under "4b/4b′/2b′ (yield, %)"
  holds three yields: of 4b, of 4b′, of 2b′. A conversion is measured on the reactant consumed.
  A cell "85 (92)" under "yield (ee) (%)" holds a yield and an ee of the same product.
- `blank_means`: what an empty cell, "–" or "none" means in that column ("no catalyst", "no
  additive", "the standard conditions", "not determined").
- **A drawn variable** (ligands or catalysts drawn one per entry, each with its yields): the
  drawing is the cell of a condition column whose target is the per_entry condition (the ligand);
  its printed label is the cell text and its box is `structure_bbox`. The yields printed with it
  are the cell of an outcome column.
- **A small table under an equation**: its header row gives the columns; the equation is the
  header reaction.

### 4. The rows

`entries` lists every printed row, in reading order. A table printed in two halves side by side:
the left half top to bottom, then the right half.

- A result printed with the header reaction (the standard conditions, e.g. "5 (64%, 61%)") is a
  row too, before the others. Its cells: the results, and '' for a deviation column.
- `label`: the entry number as printed, without footnote markers; null when rows are not numbered.
- `bbox`: the whole row with all its cells. For a drawn entry: the drawing with its label and its
  results.
- `cells`: one per column, in column order.
  - `text`: the cell as printed, without footnote markers. Keep it whole ("88 (80)/7/1",
    "1.3 NaOtBu", "68 : 32"); do not split values or convert units. An empty cell is ''.
  - `markers`: the footnote markers printed in the cell. An entry number printed "6c" is text
    "6", markers ["c"]. When one cell holds several values that carry different markers, also
    leave each marker after its value in the text ("64% b, 61% c").
  - `structure_bbox`: only for a drawn value; null otherwise. The box holds the whole drawing:
    the pipeline warns when ink runs to an edge of a box.
- `descriptor`: the row in short ("6; CoBr2; –; 95; 52/31/3; c").
- When `text_layer` is given, use it to transcribe exactly, and check every word against the
  image: the text layer misspells some labels ("Li" for "L1", "lc" for "1c") and glues markers to
  the word before them ("6c", "Trippb", "1,2-DCEd").

### 5. Ignored areas

Inked parts of the block that are neither a row, the scheme, a participant nor a legend
structure: the title, column headers, rules and dividers, footnote text, names printed under
legend drawings, and content of a neighbouring panel that reaches into the block box. A tinted
background is not ink.

### 6. Check before answering

- Every inked area inside the block box lies in a row box, the scheme box, a participant box, a
  structure box or an ignored box. The pipeline checks this and sends leftovers back.
- Every row has a cell for every column. Every per_entry condition has its condition column.
  Every marker in a cell is a footnote of the template; every footnote with overrides is printed
  in some row.
- Every alternative group has a default.
- Compare the number of rows with `block.n_entries_est`.
- Reread `reading_guide` as if you saw one row and nothing else: would you read it correctly?

## Turn 2: the reactions

The next prompt asks you to go through the rows you wrote and list the reactions the table
reports, in row order. Answer with the schema of that turn.

- **One row is one reaction.** The several numbers of a row measure one experiment: a conversion
  and yields, the yields of several products, an analytical and an isolated yield, a yield and
  an ee or er.
- **Split a row only when it reports several experiments**: one cell with two results, each with
  its own label or condition ("rt: 40, 60 °C: 80", "[Pd] 58 / [Cu] 47"), or a row that prints two
  conditions each with its result. Each of its reactions gives, for that cell, the `part` of the
  cell text that is its own (copied exactly) and says in `distinguishing` what sets it apart.
- **"A or B" with one result** ("Pd(OAc)2 or Pd2(dba)3 | <5") is one reaction; the agent of the
  reaction records the alternatives.
- `entry`: the number of the row in your `entries` (1 = first).
- `results`: the outcome cells of the reaction; `part` null when the whole cell is its own. Every
  printed result belongs to exactly one reaction. A row whose result cells are all empty still
  has its reaction, with no results.
- `variant`: the variant whose label is printed in this row for this reaction; null without a
  label. A row that prints a variant's label runs that variant, and a row without one runs the
  template. The pipeline checks the label against the row.
- `footnote_markers`: the markers printed in the row, on the entry number or in any of its cells,
  that apply to this reaction. Never the markers of the title, a column header or the header
  reaction: those concern the whole table and live in the template.
- `notes`: why a row was split, or what is unusual about it. Nothing for plain rows.
- `issues`: doubts a reviewer should look at.

Your final message in each turn is only the JSON object required by the output schema.
