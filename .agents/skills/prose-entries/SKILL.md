---
name: prose-entries
description: Stage 1 for a prose block of a chemistry paper (experiments reported in words: a paragraph of the running text, a reference note or endnote, a paragraph of the methods or of an SI procedure section; nothing drawn in the block, conditions mostly given by reference to another reaction plus what was changed). Turn 1 reads the passage together with the paper's text and SI and writes the compounds once and every experiment with its own participants, steps, conditions, runs and results, and sets aside what is no experiment of the passage; turn 2 lists the reactions, one handle each. Use when a prompt points to a prose-passage task file under work/<paper_id>/step2.
---

# Prose block: read the experiments of a passage, list their reactions

Read `.agents/shared/extract-core.md` first: it holds the rules every extraction follows (one
reaction, where each value comes from, overrides, keys, boxes). This skill says how to read
experiments that a paper reports in words.

A prose block is a **passage**: sentences that report what was done and what came of it. Nothing is
drawn in it. Its compounds are numbers the paper defines in a scheme, table or figure elsewhere,
names, descriptions of a class ("a secondary alkyl iodide"), or a drawn compound changed in words
("the substrate of entry 4 with a methyl group in place of the ester"). Its conditions are mostly
given by a reference ("under the standard conditions", "the model coupling of Table 3", "conditions B
of Scheme 2") plus what was changed: a reagent added or left out, another solvent or catalyst, a time
point, another scale. One passage often reports several runs of one set-up side by side, and it mixes
what this paper did with discussion, results of other work and restatements of results printed
elsewhere.

Words used below: an **experiment** is one set-up this passage reports (reactants and conditions),
with one run or several **runs** that differ only in a condition; a **reference** is wording that gives
reactants or conditions by pointing elsewhere; a **note** is a footnote or reference note whose marker
(often a superscript number) is printed in the passage.

The block you get may be:

- a paragraph of the running text, or part of one (`other_blocks` are the other blocks of the region:
  their sentences are not yours);
- a reference note or an endnote that reports an experiment;
- a paragraph of the methods, or of an SI procedure section;
- a general procedure whose experiments are listed on later pages (`block.entries_first_page` and
  `block.entries_last_page` are set; section 8);
- a passage that starts before or runs on beyond the block box: into the next column or onto a later
  page (`passages`, and the further images the prompt announces). The experiment is the whole
  statement, wherever it is printed.

This session has two turns:

1. **Turn 1** (now): understand the passage, write its compounds once, every experiment it reports,
   and what it says that is no experiment of its own.
2. **Turn 2** (the next prompt): go through the experiments and list the reactions they report.

After you, one agent per reaction checks your reading of its experiment, reads its outcomes and looks
the run up in the main text and the SI. It sees its experiment as you wrote it (as a template), its
results and the other experiments in short. It cannot add compounds, runs or references, and it adds
only what the run's own report states that the passage leaves open (amounts, a scale, a time, the name
of a compound the passage only numbers or describes, the measured value of a result the passage states
only in words): everything the passage says, and every reference it makes, is yours to write here.

## Task file

The prompt gives the path of a JSON task file:

- `workspace`, `doc`, `documents`: the paper workspace, the document of the block, and every
  document of the paper with its directory and page count. All of them are yours to read, the SI
  included, whatever the notes of the locate step say about the scope it searched.
- `paper`: reaction class and compound numbering of the paper.
- `region`: caption (if any), verbatim footnotes and pages of the region the block belongs to.
- `block`: page, bbox, and what the locate step noted about the block (its title, the number of
  entries it estimated, the pages its entries are listed on, if elsewhere). `block.scheme` is the
  general scheme the locate step linked, when there is one: often the reaction the passage refers to.
- `block_text`: the text of the block box, from the text layer.
- `passages`: every box of the region with its page, bbox and text, `this_block` true for the boxes
  that overlap your block. Use them to find where a sentence starts or ends. A box with `this_block`
  true may hold more than your block: your sentences are those inside the block box, plus the parts of
  them the box cuts; the region's other sentences are context.
- `other_blocks`: the other blocks of the region (id, title, page, bbox, layout).
- `blocks_of_paper`: every other block the paper's experiments are read in (reference, document,
  figure or table label, title, page, layout). An experiment printed in one of them is read there.
- `shared_participants`, `text_layer`: null for this kind of block.
- `scratch`: a private directory for your own files.

Attached images: the block with a point grid; its general scheme when that lies elsewhere; images of
the region's boxes that belong to no block (where the passage starts or runs on), when the prompt
announces them.

The text layer loses Greek letters (an "a" or "b" for α or β), the middle dot ("ZnCl2 TMEDA"), and sub-
and superscripts: a note number printed after a value or a compound number runs into it ("71% of 5.12" can
be compound 5 and note 12; "(entry 6)14" is entry 6 and note 14). Check every number, every compound
number and every marker against the image of the page before you use it.

## Turn 1

### 1. Read in this order

1. **The passage.** Find where the block's sentences start and end. A sentence cut by the block box
   is read whole: back to its start, on to its end (in `passages`, in the next column, on the next
   page: `<dir>/text/pNNN.txt` and `<dir>/pages/pNNN.png`). A sentence that runs from your block into
   another block of the region belongs to the block that holds its result (when each holds a part of
   it, the one where it ends); the other block reads it as context and puts its own part under
   `set_aside`, naming that block.
2. **The sentences around it**: what "this reaction", "the same conditions", "under these
   conditions", "the catalyst" refer to; which experiment a "respectively" list goes with.
3. **The notes.** For every marker printed in the passage, its text: `region.footnotes`, a footnote
   at the foot of the page, or the note in the reference list. A note may give conditions ("same
   conditions as in Scheme 2, method A"), say how a value was measured, or report an experiment of its
   own. When your block is itself a note or an endnote, find where its marker is printed in the text
   (`find_text`): that sentence, and the one before it, is what its references ("under otherwise
   identical conditions", "the same reaction") point to.
4. **What the passage refers to**: the table entry, scheme, figure, general procedure or earlier
   experiment that a reference names. Read it there, with its own footnotes.
5. **The SI**: its table of contents first (sections for control or mechanistic experiments,
   additional experiments, scale-up, preparations), then the table or the paragraph that reports the
   runs of this passage. Say where they are in `reading_guide` and quote what you used in `context`.
6. **Check against the image**: numbers, compound numbers, markers, Greek letters.

### 2. What is an experiment

An experiment is a set-up this paper reports in the passage, with specific reactants and conditions.

- Failed, trace and qualitative results are experiments ("no product was detected", "the yield was
  poor").
- A failure stated for a class of substrates ("substrates bearing a free amine gave no product") is
  one experiment: its reactant is a compound with `generic` true and the class as `text`, without a
  box.
- A result stated for a class of catalysts, ligands, additives or solvents (a screen summed up in one
  sentence: "most bidentate phosphines gave low yields") is likewise one run: the condition's `text`
  is the class as printed, and its members are not listed as runs. Say in `reading_guide` where the SI
  lists them.
- A preparation of a specific compound (named or numbered) is an experiment, also when the passage
  gives no result.
- A new run of something printed elsewhere is an experiment: the same entry on another scale, at
  another time point, with a reagent added or left out.

Not experiments of the passage; each goes under `set_aside`, quoted, with the reason:

- results of other work: cited results, "it has been reported", "we have previously shown";
- a restatement of an experiment that is an entry of one of the `blocks_of_paper`: the same
  reactants and the same conditions as that entry, whether the passage repeats its result as a number
  or describes it in words ("dropped", "was suppressed"). Name the block and the entry in the reason.
  (That block owns the reaction; reading it twice would count it twice.) A table or paragraph of the
  SI that reports this passage's runs (control experiments, additional runs) and is not one of the
  `blocks_of_paper` is where the agent of each reaction reads its values: it is no reason to set a run
  aside;
- an experiment that a note reports (beyond conditions or how a value was measured) when your block
  only prints the note's marker: it is read where the note is printed ("reported in note 14"), unless
  your block is that note;
- analytical measurements that are not the outcome of a reaction (impurity levels, spectroscopic
  parameters, a kinetic order), and mechanistic proposals or interpretations;
- a general procedure written for "the appropriate" or "a" substrate that is used for many
  experiments (those are read where they are reported: a scope figure, a table, the paragraphs of
  section 8);
- what only points to experiments reported elsewhere ("see the SI for further examples").

A passage that reports no experiment of its own has no experiments and says what it reports instead
under `set_aside`.

### 3. One experiment or several

- **Runs that differ only in a condition** (a reagent added or left out that ends up in no product
  of the run, another solvent, catalyst, ligand, temperature, amount or time point, another scale):
  one experiment, one variant per run (section 6). The set-up you write is the first run as the
  passage states it; every other run's variant says what it changes. Runs the passage names one by one
  ("with either A or B", "A, B and C each gave …") are variants also when it states one result for all
  of them (section 7).
- **Runs that differ in a reactant**: separate experiments. A compound they share is one compound,
  listed once. A run that adds a reagent which reacts (a reactant by section 5, such as a trapping
  agent whose adduct the passage names) differs in a reactant.
- **"respectively"**: "4 and 5 were obtained in 70 and 64% yield, respectively" pairs each value
  with its run or product, one by one. Check that the counts match.
- **Several products of one run**, a yield with its ee, a conversion with a yield: one run, several
  results.
- **The same run reported twice** in the passage (first in short, then in detail): one experiment.
- **A sequence**: stages the passage separates ("then", a crude intermediate carried on, one pot) are
  steps of one experiment, and each condition carries its `step`. An intermediate the passage does not
  isolate is a compound with role `intermediate`, `isolated` false, and a `text` only when the passage
  names it. A stage with a result of its own (an intermediate isolated with a yield) is an experiment
  of its own; the intermediate is one compound, the product of one experiment and a reactant of the
  next. `preparations` stays empty as a rule.

### 4. `compounds`: every compound once

- One item per compound that reacts or forms in an experiment of the passage, also one only
  described.
- `key`: the compound number as the paper prints it; else a short slug ("aryl-bromide",
  "coupling-product"). A compound and a condition of one experiment never share a key.
- `label`: the compound number the passage gives it; for a compound taken from a reaction the passage
  refers to (section 6), the number the paper gives it there. A field the paper gives nothing for is
  null, never an empty string.
- `text`: the name, formula or description the passage gives it ("4-bromoanisole", "PhMgBr",
  "a tertiary alkyl bromide", "the homocoupling product"); for a compound taken from a reaction the
  passage refers to, the number or name printed there, with `stated_at`. Never a name you work out from
  a drawing, and never one from a report of the run (its SI paragraph, its characterization data):
  names are looked up later, for each run, and checked there. `generic` true for a class or a formula
  with variable groups.
- `stated_at`: where the paper gives the number or name in `label`/`text` when the passage gives
  neither (a compound of the reaction the passage refers to); null when the passage prints it.
- `bbox`: where the paper draws **this very compound** on a page of `doc` (a numbered compound of a
  scheme, a table entry, a figure), without its number and results; the general scheme image and the
  page images with `grid` give the coordinates. No box (`page` and `bbox` null) for:
  - a compound that is only named or described;
  - a compound drawn only in the other document (say in `context` where it is drawn);
  - a changed version of a drawn compound ("entry 4 with a methyl in place of the ester"): that is
    another compound, not the drawing; describe it in `text`;
  - a drawing of a class or of a related compound that is not this one.
- `structures`: a catalyst, ligand or additive the passage names whose drawing is on a page of `doc`
  (a numbered complex drawn in a scheme): its box and label; a condition points to it with
  `structure_key`.
- A compound that forms or reacts in one experiment of the passage and is a catalyst, ligand or
  additive of another is one compound, boxed once, and not a structure. In the experiment that uses
  it, it is a condition whose `text` is its number or name and whose `structure_key` is null.

### 5. Reactant or condition, and the product

- Decide by extract-core (reactant or condition). A reagent the product contains is a reactant; an
  additive, a trapping agent whose adduct nobody names, a catalyst or a base is a condition.
- **A product the passage does not name** ("the coupling proceeded in 64% yield", "the corresponding
  alcohol was obtained"): a compound without a box whose `text` says what the passage calls it ("the
  cross-coupling product of 12 and 13"). Its name is looked up later. When the experiment runs the
  reaction a reference leads to with its reactants unchanged, the product is that reaction's product:
  its number as the paper gives it there (`stated_at`) and a box on its drawing, as for the reactants
  (section 6).
- **A run that gives no product** ("no reaction", "decomposition"): write the product the run was
  meant to give, as the passage or the reaction it refers to has it, also for a substrate or a class
  the passage reports as unsuccessful (for a class: a compound without a box, `generic` true, its
  `text` what the passage calls it). This is how a passage's failed run is written: extract-core's
  "reaction without a product" applies here only when nothing names or implies the product.
- **What forms instead**: by-products, species observed by a spectroscopic method, a starting
  material recovered or converted. A compound the passage names as formed is a product or by-product
  of its run; a value on a starting material stays on that reactant (section 7).

### 6. Conditions and references

- `conditions`: one item per catalyst, ligand, reagent, additive, base, solvent, temperature, time
  and atmosphere, name and amount split ("10 mol%", "2.0 equiv"), the `step` in a sequence,
  `structure_key` when drawn.
- **Stated in the passage**: as stated, without `stated_at`.
- **A reference to another reaction or set of conditions** ("under the standard conditions", "the
  model coupling of Table 3", "conditions of entry 6", "under otherwise identical conditions", a note
  "same conditions as in Scheme 2"): find what it refers to: the conditions the paper calls standard (as
  a rule the optimized entry of a table or the general procedure of the scope), or the entry, scheme,
  procedure or earlier sentence it names. Then:
  - `based_on`: `printed` as printed, `refers_to` what you found, `found` true, `stated_at` where it
    is printed;
  - copy its conditions into `conditions`, each with `stated_at` of where it is printed: catalyst,
    ligand and additives with their loadings, solvent, temperature, time, atmosphere;
  - when the passage gives the reactants by the reference too ("the model coupling", "the coupling
    of entry 5"), take them (and the product, section 5) from there: compounds with the number (else
    the name) the paper gives them there, `stated_at` when the passage prints neither number nor name,
    a box on their drawing;
  - amounts of the starting materials and the scale are not taken from there: a run of this kind
    often has its own, and the agent of the reaction takes them from the run's own report;
  - what the passage states beside the reference (a reagent added, another solvent, a time) is
    stated: it replaces the referred item of its kind or is added, without `stated_at`; what it
    leaves out ("in the absence of the ligand") is a `remove` in the variant of that run, or simply
    not written when no run has it.
- **A reference to an earlier experiment of the same passage** ("the same reaction in THF"): a run
  of that experiment, its variant.
- **A reference that leads outside the paper**, or one the paper never resolves: `found` false,
  `stated_at` null; write only what the passage states, and say in `notes` what is missing. When this
  concerns one run only, that run's variant has `conditions_given` false. Such a variant starts from
  nothing (no condition and no amount of the set-up carries over), so it states again, as `replace`
  overrides, everything the passage states for that run.
- **A run given by a reference of its own** ("under conditions B"): its variant writes what that
  reference leads to as overrides, each with `stated_at`.
- **Nothing given and nothing referred to** ("the coupling of 12 with 13 failed"): write what is
  stated, and nothing else, and say in `reading_guide` that the conditions are to be looked for in the
  run's own report. An earlier sentence that sets up the conditions of a series of runs is a reference
  by context: follow it as above, with `printed` the sentence's words.
- **"A or B" for a condition, or a range**: as extract-core says (`alternatives`, the value the text
  gives).
- **The runs of an experiment** (section 3): one variant per run, titled as the passage describes the
  run ("in toluene", "without CuI", "after 5 min"). The set-up runs the first run, so its variant has
  no overrides; every other variant `replace`s, `add`s or `remove`s what its run changes.
  `alternatives` are for one run whose condition the paper leaves open (it names A or B and does not
  say which was used); runs the passage names one by one are variants (section 3).

### 7. Results

- `results`: every result the passage states for the experiment, verbatim, with what identifies it
  (the product, the run): "71% of 5 in dioxane", "<5% of 5", "no conversion of 12", "the ee of the
  recovered 12 was unchanged", "a signal at m/z 412 assigned to the adduct". One item per stated
  result: a yield with its ee is one, the yields of two products are two, the same product in two runs
  is two.
- Qualitative results are results ("the yield dropped sharply", "only traces of 5", "the reaction was
  completely suppressed").
- A result stated jointly for several runs the passage names ("neither A nor B had any effect on the
  yield") is written once per run, each naming its run ("no effect on the yield (with A)", "… (with
  B)"), so that every run's reaction carries it.
- Conversions, values measured on a starting material at the end (recovered, its ee, the share that
  decomposed) and observations of species without a yield are results.
- A value the passage does not state is not a result of yours, even when the SI gives it: the agent
  of the reaction reads it there for the result the passage states in words.
- `default_yield_type`: as the passage, a note or the text it refers to states it for the experiment
  ("by GC", "isolated"); null when nothing says.

### 8. Procedure sections

When the block is a general procedure whose experiments are listed on later pages
(`block.entries_first_page`..`entries_last_page`), the experiments are the paragraphs that follow
this procedure there, one per compound prepared ("Following GP2, 12 (0.50 mmol) and … gave 14 (88 mg,
71%)"): those that name it, or that stand under its heading until the next procedure starts. A
paragraph that follows another procedure is left out (that procedure's block reads it), not set aside.

- each paragraph is an experiment: its `page` and `bbox` where it is printed, `statement` its
  sentences (the procedure, not the characterization data), `based_on` the general procedure
  (`found` true, `stated_at` its page), the procedure's conditions copied with `stated_at`, and what
  the paragraph states (its amounts, another temperature) as stated;
- a paragraph that reports an experiment that is an entry of one of the `blocks_of_paper` (the
  procedure of a scope entry) goes under `set_aside`, naming the block and the entry: that block owns
  the reaction;
- the procedure itself is not an experiment.

A general procedure without listed experiments has no experiments (section 2).

### 9. Footnotes

- `footnotes`: one item per marker of `region.footnotes`, and one per note an experiment prints that
  concerns it (a footnote at the foot of the page, a note of the reference list or an endnote that
  gives conditions, says how a value was measured or reports a run), with the marker as printed and its
  verbatim text. Every marker in an experiment's `footnote_markers` is one of them.
- A number that only cites other work is no marker: it goes into neither `footnote_markers` nor
  `footnotes`. Neither is the marker of a note that reports another experiment of its own (that
  experiment is read where the note is printed, section 2), nor, when your block is a note, the note's
  own number: it is no marker and no `label` of the experiments the note reports.
- A note printed in an experiment that changes something for it gets `overrides`, with the keys of
  that experiment; give the same kind of item the same key in every experiment that prints the
  marker. When one of those experiments has no item of that kind, write the change as an `add` with
  its role.
- A note that gives the conditions of the experiment by reference is followed like any reference
  (section 6): `based_on` and the copied conditions; the note keeps no overrides.
- A note that only says how a value was measured, or what a result means, has no overrides; say what
  it means in `notes`.

### 10. Guide, passages, notes

- `reading_guide`: for the agents that each collect one reaction: what each experiment and run is,
  where its conditions come from, where the SI reports its runs and how a paragraph or a table row is
  matched to it, and the pitfalls (a value on a starting material, a note number that looks like a
  digit, a result stated only in words that an SI table gives in numbers).
- `context`: the passages of the main text and the SI you relied on, quoted, with what each settles.
- `set_aside`: section 2.
- `notes`: what concerns the passage and no field takes.

### 11. Check before answering

- Every sentence of the block that reports what was done or found is in the `statement` of an
  experiment or under `set_aside`; discussion that reports nothing is neither.
- Every compound is listed once and takes part in an experiment; every participant of an experiment
  is one of the compounds and appears in its steps.
- Every reference is followed: found, with where; or found false.
- Every stated result is in the `results` of exactly one experiment (a joint result once per run it
  names), and every run has its variant.
- Every box is the drawing of that very compound, in `doc`.

## Turn 2: the reactions

The next prompt asks you to go through the experiments you wrote and list the reactions the passage
reports, in experiment order. Answer with the schema of that turn.

- **One run is one reaction**: an experiment without variants is one reaction; one with variants is
  one reaction per variant. Several products of one run, a yield with its ee, a conversion with a
  yield: one reaction.
- `entry`: the number of the experiment in your `experiments` (1 = first).
- `results`: the numbers of this reaction's results in the experiment's `results`. Every stated
  result belongs to exactly one reaction. A run without a stated result still has its reaction, with
  no results (the pipeline warns about it, so that a reviewer can check it).
- `variant`: the variant of this reaction; null when it has none.
- `footnote_markers`: the markers of the experiment that apply to this reaction. A note printed in the
  experiment's sentences applies to every run it concerns, wherever in the sentence it stands: a note
  on the set-up (its conditions, how a reagent was added) to every run of the experiment, a note on
  one run's result or condition to that run only.
- `distinguishing`: for every reaction of an experiment that reports several, what sets it apart, as
  the passage says it; else null.
- `variables`: values of variable groups stated for this reaction ("R = Me"), each with the
  participants that carry the symbol; empty as a rule.
- `notes`: why an experiment was split. `issues`: doubts a reviewer should look at.

Your final message in each turn is only the JSON object required by the output schema.
