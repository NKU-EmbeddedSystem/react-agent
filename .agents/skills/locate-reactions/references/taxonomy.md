# Taxonomy for regions, blocks and SI sections

## Region / block `kind`

| kind | meaning | typical forms |
|---|---|---|
| optimization | condition screening of one model reaction; entries are condition variants | "Optimization of reaction conditions" tables; tables whose rows are "change from the standard conditions"; SI screening tables (ligands, solvents, metal sources, additives) |
| substrate_scope | one general reaction applied to many substrates; entries are products, often drawn without their reactants | "Substrate scope" schemes/tables; tables with electrophile, nucleophile and yield columns |
| mechanistic | experiments run to probe the mechanism, with outcomes | radical trapping (TEMPO/BHT), radical clocks, control reactions, stoichiometric reactions, competition, KIE, radical probe tables |
| application | use of the method or its products | gram-scale runs, derivatization of products, late-stage functionalization, synthesis of a target |
| substrate_prep | synthesis of substrates or reagents, incl. organometallic reagents | SI "Synthesis of substrates", "Preparation of alkylzinc reagents", general procedures for starting materials |
| catalyst_prep | synthesis of catalysts, ligands, precatalysts | SI "Synthesis of catalysts/ligands"; well-defined complexes prepared for control experiments |
| background | prior work, motivation, drug examples, design concept | first scheme of many papers ("previous work / this work", bioactive molecules) |
| mechanism_proposal | proposed catalytic cycle or pathway without an experimental outcome | "Proposed mechanism", computed pathways |
| characterization | compound data only (no reaction) | rarely a region; usually an SI section |
| other | anything else; explain in notes | X-ray figures, kinetic plots, Hammett plots, EPR/NMR monitoring |

## `presentation`

- `vector_graphic`: drawn with vector paths. Text inside is usually outlined (not in the text layer).
- `raster_image`: embedded bitmap.
- `text_table`: table whose cells are real text.
- `prose`: reaction described in running text (typical for SI procedures).
- `scanned`: page is a scan without a text layer.

## Block `layout`

What one entry of the block prints. A later step picks its reading procedure by it, so decide
by what is drawn or written per entry, not by the purpose of the block (`kind`).

| layout | one entry is | typical forms |
|---|---|---|
| condition_table | one variant of a fixed model reaction: the same reactants and products for every entry, drawn once (in a header equation or the scheme above); entries change conditions (catalyst, ligand, additive, solvent, temperature, time, amounts) | optimization tables with columns such as cat./ligand/additive/solvent/yield; "deviation from the standard conditions" tables; a set of drawn ligands or catalysts, each with its yields under one model reaction; a small results table under a model equation (catalyst vs. yield) |
| product_scope | a drawn product with its label and results; the reactants follow from the general scheme | substrate-scope schemes; one product drawing with an "R = …" list; per-product comparisons of protocols or metals ([Fe]/[Ni], isolated/in situ) |
| reactant_table | a table row (or a line of a list under a general scheme) that gives the reactant(s) of the general reaction: drawn or named in its cells, as compound numbers, or as the values of variable groups (R, X); the product follows from the general reaction and is usually not drawn | "electrophile / nucleophile / yield" tables; a scope table that varies one reactant while the other is fixed in the header equation; a substrate column where a blank cell repeats the row above, sometimes with a partly filled product column; a "compound / R" table under a generic equation; one drawing with "X = H / OMe / Cl" serving several rows |
| equation | a whole reaction drawn on its own: reactants, an arrow with its conditions, products and results | control and radical-trap experiments, radical clocks, scale-up, derivatizations of a product, catalyst or reagent syntheses drawn as equations, short sequences |
| prose | a paragraph describing one reaction or one preparation | SI general and typical procedures, per-compound procedures, reactions reported only in running text |
| other | none of these | explain in `notes` |

- `layout` and `kind` are independent: an optimization can be a condition_table or a set of
  equations; a scope can be product_scope or reactant_table; a mechanistic block can be a
  condition_table (one model reaction run with different additives) or equations.
- Entries that each draw their product (with its label and results) are product_scope; table rows
  that give the reactants are reactant_table, even when some rows also draw the product.
- A table whose rows sometimes also change a reactant ("alkyl-I instead of alkyl-Br", an
  X = Br/I column) is still a condition_table when one model reaction is printed once for all rows.
- If a block mixes layouts, give the layout of most of its entries and say in `notes` what else
  it holds.

## `related[].relation` (from this region to the target)

- `subset_of` / `superset_of`: same experiments, one listing has more entries (a main-text optimization table vs. the full SI table).
- `same_as`: same experiments shown twice.
- `overlaps`: partially shared experiments.
- `details_in`: extra details for the same experiments (e.g. a fuller SI figure).
- `procedure_in`: the experimental procedure is in the target (usually an SI section).
- `characterization_in`: product data are in the target (usually an SI section).

## SI section `kind`

general_info (materials, instruments), optimization, general_procedure, reaction_procedures
(per-compound procedures), substrate_prep, catalyst_prep, application, mechanistic,
characterization, crystallography, spectra, computation, references, other.

The printed SI page labels ("S12") usually differ from PDF page indices (often by one because
of a cover page); always report PDF page indices.
