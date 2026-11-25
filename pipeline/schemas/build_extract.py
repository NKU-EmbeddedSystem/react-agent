"""Single source of the Step 2 output schemas.

Run `python -m pipeline.schemas.build_extract` after editing; it rewrites next to this file
extract_inventory.schema.json, extract_expand.schema.json and extract_entry.schema.json (the
generic skill extract-reactions, kept in .agents/backup), ctable_entries.schema.json,
ctable_handles.schema.json and ctable_reaction.schema.json (the two skills for condition tables),
rtable_entries.schema.json, rtable_handles.schema.json and rtable_reaction.schema.json (the two skills
for reactant tables), pscope_entries.schema.json, pscope_handles.schema.json and
pscope_reaction.schema.json (the two skills for product scopes), eqn_entries.schema.json,
eqn_handles.schema.json and eqn_reaction.schema.json (the two skills for equation blocks), and
prose_entries.schema.json, prose_handles.schema.json and prose_reaction.schema.json (the two skills
for prose passages).
The schemas follow the strict structured-output rules Codex needs: every property
is required, objects are closed, optional values are nullable.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

COND_ROLES = ["catalyst", "ligand", "reagent", "additive", "base", "solvent", "temperature", "time",
              "atmosphere", "other"]
PART_ROLES = ["reactant", "intermediate", "product", "byproduct"]
# "analytical": measured on the crude mixture (e.g. against an internal standard), method not stated.
YIELD_TYPES = ["isolated", "NMR", "GC", "HPLC", "LC", "analytical", "conversion", "other"]

S, N, B, I = {"type": "string"}, {"type": "number"}, {"type": "boolean"}, {"type": "integer"}
BBOX = {"type": "array", "items": N, "description": "[x0, y0, x1, y1] in PDF points"}
NBBOX = {"type": ["array", "null"], "items": N, "description": "[x0, y0, x1, y1] in PDF points, or null"}
STEP = {"type": ["integer", "null"],
        "description": "Number of the step (template.steps) this condition belongs to; null for a single-step reaction"}
STRUCTURE_KEY = {"type": ["string", "null"],
                 "description": "Key of the drawn structure (`structures`) this refers to; null if it is not drawn"}


def nullable(kind: str, **extra) -> dict:
    return {"type": [kind, "null"], **extra}


def enum(values, null: bool = False, **extra) -> dict:
    if null:
        return {"type": ["string", "null"], "enum": [*values, None], **extra}
    return {"type": "string", "enum": list(values), **extra}


def obj(props: dict, **extra) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(props),
            "properties": props, **extra}


def arr(items: dict, **extra) -> dict:
    return {"type": "array", "items": items, **extra}


def reworded(schema: dict, descriptions: dict) -> dict:
    """A copy of `schema` with other descriptions: {path: text}. A path names the properties from
    the top, joined by dots ("entries.cells.same_as"); arrays on the way are stepped into."""
    out = copy.deepcopy(schema)
    for path, text in descriptions.items():
        node = out
        for name in path.split("."):
            # The builders share small dicts (S, BBOX), and a deep copy keeps them shared: every node
            # on the way gets a dict of its own, so that only the named property changes.
            while node.get("type") == "array":
                node["items"] = dict(node["items"])
                node = node["items"]
            node["properties"] = dict(node["properties"])
            node["properties"][name] = dict(node["properties"][name])
            node = node["properties"][name]
        node["description"] = text
    return out


STATED_AT = {
    "type": ["object", "null"], "additionalProperties": False, "required": ["doc", "page"],
    "properties": {"doc": {"type": "string", "enum": ["main", "si"]}, "page": I},
    "description": "Where the paper states this when the block itself (its scheme, table, caption, footnotes) "
                   "does not print it: document and page of the passage. Null when the block prints it, and "
                   "for an inferred item",
}

ALTERNATIVES = arr(
    obj({"text": S, "structure_key": STRUCTURE_KEY}),
    description="The options when the source says 'A or B' without saying which one was used "
                "here (at least two); empty when the item is definite")

PASSAGE = obj({
    "doc": {"type": "string", "enum": ["main", "si"]}, "page": I,
    "text": {**S, "description": "The passage, quoted (shortened with … where long)"},
    "about": {**S, "description": "What it says about the block or reaction, and what you took from it"},
})

DEFS = {
    "override": obj({
        "key": {**S, "description": "Key of the template participant/condition to change, or a new key for action=add"},
        "action": enum(["replace", "remove", "add", "use"],
                       description="use: of the alternatives of an `alternative_groups` entry, this one applies "
                                   "(the others of its group drop out)"),
        "role": enum(COND_ROLES + PART_ROLES, null=True,
                     description="New role. Required for action=add (a condition role). For replace, set it "
                                 "only to change a participant's role (e.g. to intermediate); else null"),
        "text": nullable("string"),
        "amount": nullable("string"),
        "structure_key": STRUCTURE_KEY,
        "step": STEP,
        "alternatives": ALTERNATIVES,
        "basis": {**S, "description": "Where this change is stated, e.g. 'footnote b', 'row cell: additive'; "
                                      "for an inferred change, the reasoning"},
        "stated_at": STATED_AT,
        "inferred": {**B, "description": "False for a change the paper states. True when it is your own conclusion "
                                         "(by analogy with another protocol, from chemical knowledge); `basis` "
                                         "then gives the reasoning"},
    }),
    "structure": obj({
        "key": {**S, "description": "Printed label of the drawn compound (C1, L3) or a short slug"},
        "label": nullable("string"),
        "text": nullable("string", description="Printed name, if any"),
        "page": I, "bbox": BBOX,
    }),
}

# The template a block reader writes: what every entry of the block shares.
TEMPLATE = obj({
    "general_reaction": {**S, "description": "One sentence describing the reaction shared by the block"},
    "reading_guide": {**S, "description": "Guidance written for the agents that will each extract one entry of this "
                                          "block: how an entry is laid out, what every printed element means (label, each "
                                          "number, colours, brackets, superscripts), what is drawn per entry and what "
                                          "follows from the scheme, and the pitfalls of this particular figure"},
    "scheme": {"type": ["object", "null"], "additionalProperties": False, "required": ["page", "bbox"],
               "properties": {"page": I, "bbox": BBOX},
               "description": "Area of the general scheme / header (structures, arrows, text over the arrows); null if none"},
    "participants": arr(obj({
        "key": S, "role": enum(PART_ROLES),
        "label": nullable("string"), "text": nullable("string"), "amount": nullable("string"),
        "generic": {**B, "description": "True if the drawing has variable groups (R, X, Ar, dashed rings) or stands for a compound class"},
        "isolated": nullable("boolean", description="For an intermediate: whether it was isolated before the next step; null otherwise"),
        "page": nullable("integer"), "bbox": NBBOX,
        "alternatives": ALTERNATIVES,
        "stated_at": STATED_AT,
    })),
    "alternative_groups": arr(obj({
        "keys": arr(S, description="Keys of the participants the source offers for one position ('A or B'), at least two"),
        "default": nullable("string", description="The one that applies to a result reported without a variant; "
                                                  "null when every result comes under a variant that chooses"),
        "basis": {**S, "description": "What decides the default: where the paper says it, or your reasoning"},
        "stated_at": STATED_AT,
        "inferred": {**B, "description": "True when the paper does not say which one applies and the default is your conclusion"},
    }), description="Positions of the reaction for which the source draws or names alternatives. Every record "
                    "ends up with exactly one participant of each group"),
    "steps": arr(obj({
        "n": {**I, "description": "1, 2, ... in reaction order"},
        "description": {**S, "description": "What happens in this step, e.g. 'activation of the acid to the redox-active ester'"},
        "reactants": arr(S, description="Keys of the participants that react in this step"),
        "products": arr(S, description="Keys of the participants formed in this step"),
    }), description="The reaction as steps: one for a single-step reaction, several for a sequence. "
                    "An intermediate is a product of one step and a reactant of a later one"),
    "conditions": arr(obj({
        "key": S, "role": enum(COND_ROLES), "text": S, "amount": nullable("string"),
        "structure_key": STRUCTURE_KEY, "step": STEP, "alternatives": ALTERNATIVES,
        "stated_at": STATED_AT,
        "per_entry": {**B, "description": "True when the block gives this condition entry by entry (a column of "
                                          "an optimization table): `text` is the header or placeholder as "
                                          "printed ('cat.', 'additive') and every entry states its own value"},
    }), description="The base conditions: what the scheme and the conditions footnote state for every entry"),
    "structures": arr({"$ref": "#/$defs/structure"},
                      description="Drawn compounds that are not participants: catalysts, ligands, additives, "
                                  "reagents (e.g. a legend of catalysts C1-C6 under a table)"),
    "footnotes": arr(obj({"marker": S, "text": {**S, "description": "Verbatim footnote text for this marker"},
                          "overrides": arr({"$ref": "#/$defs/override"}), "notes": S})),
    "preparations": arr(obj({
        "participant_key": {**S, "description": "The starting material (a template participant) that was made beforehand"},
        "description": {**S, "description": "What the block shows about how it was made, e.g. 'esterification of the acid'"},
        "from_participants": arr(S, description="Keys of the template participants it was made from; may be empty"),
        "items": arr(obj({
            "role": enum(["reactant", *COND_ROLES]),
            "text": nullable("string", description="Printed name; null for a compound that is only drawn"),
            "amount": nullable("string"),
            "structure_key": STRUCTURE_KEY,
        }), description="The other compounds and conditions of that preparation, as printed or drawn"),
        "basis": {**S, "description": "Where the block shows it, e.g. 'first arrow of the general scheme'"},
    }), description="How a starting material was made, when the block shows it but the reported results do "
                    "not include that step (an activated ester isolated before the reaction the yields "
                    "refer to). Usually empty"),
    "variable_defaults": arr(obj({"name": S, "value": S, "participant_key": nullable("string"), "basis": S})),
    "default_yield_type": enum(YIELD_TYPES, null=True, description="Only when the document states it; else null"),
    "variants": arr(obj({
        "key": S, "title": S,
        "conditions_given": {**B, "description": "False when the paper (main text and SI) does not give the "
                                                 "conditions of this protocol. Nothing of the base conditions "
                                                 "or amounts then carries over"},
        "overrides": arr({"$ref": "#/$defs/override"}),
        "notes": {**S, "description": "E.g. where the paper points to for the conditions of this protocol"},
    })),
    "context": arr(PASSAGE, description="The passages outside the block that you relied on to understand it: "
                                        "where the main text discusses it, and the parts of the SI that define "
                                        "what it leaves open (general procedures, the fuller table)"),
})

INVENTORY = obj({
    "template": TEMPLATE,
    "entries": arr(obj({
        "label": nullable("string", description="Label printed for the entry (compound label, entry number); null if none"),
        "page": I, "bbox": BBOX,
        "descriptor": {**S, "description": "What is printed for the entry, in short, e.g. '3; [isolated] [Fe] 81% c; "
                                           "[in situ] [Fe] 71%; [Ni] 85%'"},
    }), description="Every entry of the block in reading order: what is printed as one unit (a drawing with its "
                    "label and results, a table row, a paragraph). An entry may report several reactions; they are "
                    "told apart later, one entry at a time"),
    "ignored": arr(obj({"page": I, "bbox": BBOX, "reason": S})),
    "notes": S,
}, **{"$defs": DEFS})

EXPAND = obj({
    "printed": {**S, "description": "Everything printed for this entry, transcribed in reading order: labels, variable "
                                    "assignments ('R = Me'), each result with the protocol label and footnote markers "
                                    "printed with it, conditions printed with it"},
    "results": arr(S, description="Each result printed for this entry, verbatim with what identifies it: "
                                  "'[in situ] [Fe] 71%', '78% b', 'n.d.', '3:1 d.r.'. Empty when the entry prints none"),
    "reasoning": {**S, "description": "How many reactions (experiments) this entry reports and why: which results come "
                                      "from the same reactants under the same conditions (one reaction, several "
                                      "measurements) and which differ in a reactant, a condition or the protocol"},
    "rows": arr(obj({
        "label": nullable("string", description="Label of the compound or entry this reaction is reported under"),
        "results": arr(I, description="Numbers of this reaction's results in `results` (1 = first)"),
        "variant": nullable("string", description="Key of the template variant (protocol) this reaction was run "
                                                  "under; null when it comes under no protocol label"),
        "footnote_markers": arr(S, description="Markers printed on this reaction's label or results"),
        "variables": arr(obj({"name": S, "value": S}),
                         description="Variable groups printed as text for this reaction ('R = Me', 'X = Cl')"),
        "drawn_structures": arr(obj({"key": S, "label": nullable("string"), "text": nullable("string")}),
                                description="Catalysts, ligands, additives drawn only inside this entry that an "
                                            "override refers to; their boxes are taken later. Usually empty"),
        "overrides": arr({"$ref": "#/$defs/override"},
                         description="How this reaction differs from the template and its variant, as printed in "
                                     "this entry: row cells, a condition printed with it, the alternative it uses, "
                                     "the value of each per-entry condition"),
    }), description="One row per reaction reported in this entry"),
    "issues": arr(S, description="Doubts a reviewer should look at"),
}, **{"$defs": DEFS})

# One measured value of a reaction.
OUTCOME = obj({
    "product_key": nullable("string"),
    "yield_text": nullable("string"),
    "yield_value": nullable("number"),
    "yield_qualifier": enum(["<", ">", "~", "trace", "ND", "NR", "other"], null=True),
    "yield_type": enum(YIELD_TYPES, null=True),
    "selectivity": arr(obj({"type": enum(["dr", "er", "ee", "rr", "E/Z", "other"]), "text": S})),
    "footnote_markers": arr(S),
    "notes": nullable("string"),
})

ENTRY = obj({
    "participants": arr(obj({
        "key": S, "role": enum(PART_ROLES),
        "label": nullable("string"), "text": nullable("string"), "amount": nullable("string"),
        "source": enum(["drawn", "text", "derived"]),
        "isolated": nullable("boolean", description="For an intermediate: whether it was isolated; null otherwise"),
        "page": nullable("integer"), "bbox": NBBOX,
        "variables": arr(obj({"name": S, "value": S}),
                         description="The reaction's variables (task: reaction.variables) that this compound's drawing carries"),
        "basis": nullable("string"),
        "stated_at": {**STATED_AT, "description": "Where the paper gives the name or number in `text`/`label` for this "
                                                  "reaction when the entry itself does not print it (found in the "
                                                  "main text or the SI); else null"},
    })),
    "structures": arr({"$ref": "#/$defs/structure"},
                      description="Boxes of the compounds listed under reaction.drawn_structures, with the same keys; "
                                  "usually empty"),
    "outcomes": arr(OUTCOME, description="The results of this reaction (task: reaction.results), one per measured value"),
    "overrides": arr({"$ref": "#/$defs/override"},
                     description="What the main text or the SI states for this reaction that the template and the "
                                 "reaction leave open; every one has stated_at (or is inferred)"),
    "related": arr(PASSAGE, description="What the main text and the SI say about this particular reaction, outside "
                                        "the block; empty when nothing was found"),
    "notes": S,
    "issues": arr(S),
}, **{"$defs": DEFS})


# ------------------------------------------------------------ condition tables
# Stage 1 (skill condition-table-entries): turn 1 reads the table (CTABLE_ENTRIES), turn 2 lists
# its reactions (CTABLE_HANDLES). Stage 2 (skill condition-table-reaction): one reaction (CTABLE_REACTION).

COLUMN_KINDS = ["entry_number", "condition", "amount", "participant", "variable", "deviation", "outcome", "other"]
MEASURES = ["yield", "conversion", "ee", "er", "dr", "other"]

# The template of condition and reactant tables: TEMPLATE, except that their validators require a
# default for every alternative group. A copy, so that the generic path's schemas do not change.
TABLE_TEMPLATE = reworded(TEMPLATE, {
    "alternative_groups.default": ("The one that applies to a result reported without a variant; required for "
                                   "every group, also when every result carries a label"),
})

CTABLE_COLUMN = obj({
    "key": {**S, "description": "Short slug, unique among the columns: 'entry', 'cat', 'ligand', 'solvent', 'yield'"},
    "header": {**S, "description": "The header as printed, footnote markers left out; '' when the column has none"},
    "kind": enum(COLUMN_KINDS, description=(
        "entry_number: the entry numbers. condition: which compound or which value one condition has in each row "
        "(catalyst, ligand, additive, base, solvent, temperature, time, atmosphere), possibly with its amount. "
        "amount: only the quantity of one compound row by row (a loading, equivalents, a concentration). "
        "participant: which reactant or product each row has. variable: the value of a variable group (X, R) of a "
        "participant. deviation: the change from the standard conditions in words. outcome: measured results. "
        "other: anything else (say what in notes)")),
    "target": nullable("string", description=(
        "condition: key of the template condition the column gives row by row (that condition has per_entry true). "
        "amount: key of the template condition or participant whose amount it gives. participant, variable: key of "
        "the template participant. Otherwise null")),
    "variable_name": nullable("string", description="variable: the symbol the cells give a value for ('X', 'R'); else null"),
    "unit": nullable("string", description=(
        "The unit of the column's bare numbers ('mol%', 'equiv', '°C', 'h', 'M') as the header, a footnote or the "
        "text gives it; null when the cells carry their units or are not numbers")),
    "values": arr(obj({
        "printed": {**S, "description": "A value as printed in the column's cells, footnote markers left out"},
        "text": nullable("string", description="What it is written as: the compound's name, or the value with its unit; null to keep the printed text"),
        "amount": nullable("string", description="The amount it stands for, when the printed value gives one; else null"),
        "structure_key": STRUCTURE_KEY,
        "stated_at": STATED_AT,
        "basis": {**S, "description": "What says so: the legend, the header, a footnote, a passage"},
    }), description=(
        "What printed values of this column stand for, when that is not the printed text itself: a legend label "
        "(C1 is Co(Mes-PDI)Cl2, drawn as C1), an R group that selects a drawn catalyst, a drawn ligand that was "
        "added as its salt. One item per distinct printed value it applies to; empty when every value is written "
        "as printed")),
    "measures": arr(obj({
        "participant_key": nullable("string", description=(
            "Template participant the value belongs to: the product or byproduct of a yield, ee, er or dr; the "
            "reactant of a conversion; null when the table does not say")),
        "measure": enum(MEASURES),
        "yield_type": enum(YIELD_TYPES, null=True, description=(
            "For a yield: how it was determined, as the header or a footnote states; null when nothing says")),
    }), description=("outcome: what one cell holds, in printed order (a cell '27/15/40' under '6b/6b′/4b′ (yield, %)' "
                     "holds three yields). Empty for the other kinds")),
    "blank_means": nullable("string", description=(
        "What an empty cell, '–' or 'none' means in this column ('no additive', 'the standard conditions', "
        "'not determined'); null if the column has none")),
    "notes": S,
})

CTABLE_CELL = obj({
    "column": {**S, "description": "Key of the column the cell belongs to"},
    "text": {**S, "description": ("The cell as printed, footnote markers left out ('' for an empty cell); when one cell "
                                  "holds several values with different markers, each marker stays after its value "
                                  "('78% b, 75% c')")},
    "markers": arr(S, description="Footnote markers printed in the cell (an entry number printed '2b' gives text '2', markers ['b'])"),
    "structure_bbox": {**NBBOX, "description": "When the value is a drawing (a ligand or catalyst drawn for this row): "
                                               "the box of that drawing; else null"},
})

CTABLE_ENTRIES = obj({
    "template": TABLE_TEMPLATE,
    "columns": arr(CTABLE_COLUMN, description="Every column of the table, in printed order"),
    "entries": arr(obj({
        "label": nullable("string", description="Entry number as printed, footnote markers left out; null when rows are not numbered"),
        "page": I, "bbox": BBOX,
        "descriptor": {**S, "description": "The row in short, e.g. '5; MnCl2; –; 87; 52/18/3; c'"},
        "cells": arr(CTABLE_CELL, description="One cell for every column, in column order; text '' for an empty cell"),
    }), description=("Every printed row in reading order. A result printed with the header reaction (the standard "
                     "conditions) is a row too")),
    "ignored": arr(obj({"page": I, "bbox": BBOX, "reason": S})),
    "notes": S,
}, **{"$defs": DEFS})

CTABLE_HANDLES = obj({
    "reactions": arr(obj({
        "entry": {**I, "description": "Number of the row in `entries` (1 = first) the reaction is printed in"},
        "results": arr(obj({
            "column": {**S, "description": "Key of an outcome column"},
            "part": nullable("string", description=(
                "null when the whole cell belongs to this reaction; else the part of the cell text that does, copied exactly")),
        }), description="The result cells of this reaction"),
        "variant": nullable("string", description="Key of the template variant whose label is printed for this reaction; null without a label"),
        "footnote_markers": arr(S, description=(
            "Markers printed in the row (on the entry number or in a cell) that apply to this reaction; never those of "
            "the title or of a column header")),
        "distinguishing": nullable("string", description=(
            "Only when the row reports more than one reaction: what sets this one apart, as printed ('COMU', '60 °C'); else null")),
    }), description="Every reaction of the table in row order: one per row, unless a row reports several experiments"),
    "notes": arr(obj({"entry": I, "text": S}), description="Why a row was split, or what is unusual about it; nothing for plain rows"),
    "issues": arr(S, description="Doubts a reviewer should look at"),
})

CTABLE_OUTCOME = obj({**OUTCOME["properties"],
                      "column": {**S, "description": "Key of the outcome column the value is printed in"},
                      "measure": nullable("integer", description=(
                          "Which of the column's `measures` the value is (1 = first); required when the column "
                          "has more than one, else null"))})

CTABLE_REACTION = obj({
    "template_check": arr(obj({
        "target": {**S, "description": ("What you checked: a template participant, condition or structure key, a column "
                                        "key, a footnote marker, or 'steps' / 'scheme' / 'default_yield_type'")},
        "stage1": {**S, "description": "What the table reading says"},
        "seen": {**S, "description": "What the page or the text shows instead"},
        "evidence": {**S, "description": "Where: the printed cell, header or footnote, or a passage (doc and page)"},
    }), description="Where the table reading (template, columns) is wrong for this reaction; empty when it is right"),
    "overrides": arr({"$ref": "#/$defs/override"}, description=(
        "How this reaction differs from the template as its row prints it: each condition cell (replace with the "
        "printed value, or remove when the cell is empty), each change a deviation names, a participant the row replaces")),
    "outcomes": arr(CTABLE_OUTCOME, description="One per measured value in this reaction's result cells"),
    "lookup": arr({"$ref": "#/$defs/override"}, description=(
        "What the main text or the SI states about this entry that the table leaves open; each has stated_at or is inferred")),
    "related": arr(PASSAGE, description="What the main text and the SI say about this entry; empty when nothing was found"),
    "notes": S,
    "issues": arr(S, description="Doubts a reviewer should look at"),
}, **{"$defs": DEFS})

# ------------------------------------------------------------ reactant tables
# Stage 1 (skill reactant-table-entries): turn 1 reads the table (RTABLE_ENTRIES), turn 2 lists its
# reactions (RTABLE_HANDLES). Stage 2 (skill reactant-table-reaction): one reaction (RTABLE_REACTION).
# Built next to the condition-table objects, not by changing them: TEMPLATE, CTABLE_COLUMN and the
# others stay as they are, so the schemas of the other paths (and the hashes of their results) do
# not change.

RTABLE_TEMPLATE = obj({
    **TABLE_TEMPLATE["properties"],
    "derivations": arr(obj({
        "key": {**S, "description": "A template participant that the rows do not print (usually the product)"},
        "from": arr(S, description="Keys of the participants it follows from by the general reaction"),
        "how": {**S, "description": ("One sentence: which part of each of those participants ends up where, as the "
                                     "general reaction shows it (the bond that forms, the groups that leave, what a "
                                     "coloured or highlighted part corresponds to). Never a name of the structure")},
    }), description=("The participants a row leaves unknown and how each follows from the others by the general "
                     "reaction; they are recorded as derived, to be worked out later")),
    "shared_results": arr(S, description=("Results printed once for every row (e.g. '>85% yields' under the header "
                                          "equation), verbatim; empty when the rows print their own")),
    "lookup_guide": {**S, "description": ("Where the main text and the SI report the individual entries of this table "
                                          "(per-compound paragraphs, a fuller table) and how a passage is matched to "
                                          "a row (an entry reference, a compound number, the reactant names with the "
                                          "yield); '' when nothing was found")},
})

RTABLE_COLUMN_KINDS = ["entry_number", "participant", "variable", "label", "condition", "amount", "deviation",
                       "outcome", "other"]

RTABLE_COLUMN = obj({
    **{k: v for k, v in CTABLE_COLUMN["properties"].items() if k not in ("kind", "target")},
    "kind": enum(RTABLE_COLUMN_KINDS, description=(
        "entry_number: the entry numbers. participant: which compound one position of the general reaction has in "
        "each row (drawn, named, or a compound number). variable: the value of a variable group (R, X) of the "
        "position(s) whose drawing carries it. label: the compound number of one position, row by row. condition: "
        "which compound or value one condition has in each row. amount: only the quantity of one compound row by "
        "row. deviation: a change from the standard conditions in words. outcome: measured results. other: anything "
        "else (say what in notes)")),
    "targets": arr(S, description=(
        "participant, label: the one template participant (position) the column gives. variable: every template "
        "participant whose drawing carries the symbol. condition: the one template condition the column gives row by "
        "row (per_entry true). amount: the one template condition or participant whose amount it gives. Empty for "
        "the other kinds")),
})

RTABLE_CELL = obj({
    **CTABLE_CELL["properties"],
    "structure_bbox": {**NBBOX, "description": "When the value is a drawing (a reactant, a product or a catalyst drawn "
                                               "in this row's cell): the box of that one drawing; else null"},
    "same_as": nullable("integer", description=(
        "When the cell prints nothing because it repeats the value above it (a blank meaning 'as above', or the "
        "rows that one drawing serves): the number of the row in `entries` (1 = first) whose cell it repeats; the "
        "cell's text is then '' and structure_bbox null. Null otherwise")),
})

RTABLE_ENTRIES = obj({
    "template": RTABLE_TEMPLATE,
    "columns": arr(RTABLE_COLUMN, description="Every column of the table, in printed order"),
    "entries": arr(obj({
        "label": nullable("string", description="Entry number as printed, footnote markers left out; null when rows are not numbered"),
        "page": I, "bbox": BBOX,
        "descriptor": {**S, "description": "The row in short, e.g. '6; drawn chloride; R = CF3; 81; 77'"},
        "cells": arr(RTABLE_CELL, description="One cell for every column, in column order; text '' for an empty cell"),
        "lookup_hint": {
            "type": ["object", "null"], "additionalProperties": False, "required": ["doc", "page", "note"],
            "properties": {"doc": {"type": "string", "enum": ["main", "si"]}, "page": I,
                           "note": {**S, "description": "How the passage was matched to this row"}},
            "description": "Where the paper reports this row's experiment (e.g. its SI paragraph), when you found it; else null",
        },
    }), description="Every printed row in reading order"),
    "ignored": arr(obj({"page": I, "bbox": BBOX, "reason": S})),
    "notes": S,
}, **{"$defs": DEFS})

RTABLE_HANDLES = obj({
    "reactions": arr(obj({
        **CTABLE_HANDLES["properties"]["reactions"]["items"]["properties"],
        "cells": arr(obj({
            "column": {**S, "description": "Key of a participant or variable column"},
            "part": {**S, "description": "The part of that cell's text that is this reaction's own, copied exactly"},
        }), description=("Only when the row reports several reactions that differ in a compound or a variable value "
                         "printed together in one cell ('4c / 4d', 'R = Et, iPr'): this reaction's part of that cell. "
                         "Empty otherwise")),
    }), description="Every reaction of the table in row order: one per row, unless a row reports several experiments"),
    "notes": CTABLE_HANDLES["properties"]["notes"],
    "issues": CTABLE_HANDLES["properties"]["issues"],
})

RTABLE_OUTCOME = obj({**CTABLE_OUTCOME["properties"],
                      "column": nullable("string", description=(
                          "Key of the outcome column the value is printed in; null for a result of "
                          "template.shared_results"))})

RTABLE_REACTION = obj({
    "template_check": reworded(CTABLE_REACTION, {
        "template_check.target": ("What you checked: a template participant, condition, structure or variant key, "
                                  "a column key, a footnote marker, or 'steps' / 'scheme' / 'default_yield_type'"),
    })["properties"]["template_check"],
    "overrides": arr({"$ref": "#/$defs/override"}, description=(
        "How this reaction differs from the template beyond what the pipeline applies from the row's participant, "
        "variable and label cells: each condition or amount cell, each change a deviation names, what sets this "
        "reaction apart when its row reports several. Usually empty")),
    "outcomes": arr(RTABLE_OUTCOME, description="One per measured value of this reaction"),
    "lookup": arr({"$ref": "#/$defs/override"}, description=(
        "What the main text or the SI states about this entry that the table leaves open (the product's name, the "
        "reactants' names and amounts, the scale); each has stated_at or is inferred")),
    "labels": arr(obj({
        "key": {**S, "description": "A participant of this reaction"},
        "label": {**S, "description": "Its compound number as the passage prints it ('5a')"},
        "stated_at": {**STATED_AT, "description": "Where the passage is"},
    }), description=("Compound numbers the main text or the SI gives this reaction's participants where the row prints "
                     "none (the product's number in its SI paragraph); empty when none is found")),
    "related": CTABLE_REACTION["properties"]["related"],
    "notes": S,
    "issues": arr(S, description="Doubts a reviewer should look at"),
}, **{"$defs": DEFS})

# ------------------------------------------------------------ product scopes
# Stage 1 (skill product-scope-entries) and stage 2 (skill product-scope-reaction). A product scope
# is read as a table whose header is not printed: the entries (one drawn product each) are the
# rows, the kinds of things an entry prints are the columns. The objects have the structure of the
# reactant-table ones, so the same logic runs on both; only the descriptions (which are prompts)
# speak of entries and fields.

PSCOPE_ENTRIES = reworded(RTABLE_ENTRIES, {
    "template.derivations": (
        "The participants an entry does not draw (the reactants, as a rule) and how each follows from those it "
        "does draw by the general reaction; they are recorded as derived, to be worked out later"),
    "template.derivations.key": (
        "A template participant the entries do not draw: usually a reactant; the product when some entries draw "
        "a reactant instead; a by-product the entries only number"),
    "template.derivations.from": "Keys of the participants it follows from by the general reaction (for a reactant: the product)",
    "template.derivations.how": (
        "One sentence. For a reactant: which part of the product it is and what stands at the bond the reaction "
        "forms, as the general reaction shows it (where the product is cut, which coloured or highlighted part "
        "belongs to it, which group of the general reaction sits at the cut). For a by-product or an intermediate: "
        "how it forms from the participants in `from`. For the product of entries that draw a reactant: the bond "
        "that forms. Never a name of the structure"),
    "template.participants.generic": (
        "True for the product and every position the entries vary (drawn with variable groups, as a placeholder, "
        "as a class, or as one example of a model reaction); false only for a compound that is the same in every "
        "entry and that the figure identifies (drawn once without variable groups, or named or numbered)"),
    "template.alternative_groups.default": (
        "The one that applies to a result reported without a variant; required for every group, also when every "
        "result carries a label"),
    "template.shared_results": ("Results printed once for every entry (e.g. '>95% yield in every case' under the "
                                "general reaction), verbatim; empty when the entries print their own"),
    "template.lookup_guide": (
        "Where the main text and the SI report the individual entries of this figure (per-compound paragraphs), "
        "how a passage is matched to an entry (its compound number, its name), whether those paragraphs name the "
        "starting materials, and where the SI lists or characterises the starting materials; '' when nothing was found"),
    "columns": ("The fields of an entry: one item per kind of thing the entries print (the drawing, the compound "
                "number, a variable group, the results, a remark). Nothing prints a header for them: set them up "
                "from the entries"),
    "columns.key": "Short slug, unique among the fields: 'product', 'label', 'R', 'X', 'yield', 'remark'",
    "columns.header": "'' as a rule (a figure prints no header); the header as printed when the entries stand under column heads",
    "columns.kind": (
        "participant: the drawing of the entry, i.e. the compound of the position it shows (the product, as a "
        "rule). label: the compound number printed with the drawing, for the position it numbers. entry_number: "
        "the entry number, when entries are numbered instead of their compounds. variable: the value of a variable "
        "group (R, n, X) printed in the entry's legend. outcome: measured results. deviation: a change of "
        "conditions that concerns the whole entry ('at 45 °C', 'on a larger scale'). condition, amount: a "
        "condition, or only an amount, that every entry prints for itself. other: remarks and anything else (say "
        "what in notes)"),
    "columns.targets": (
        "participant, label: the one template participant (position) the field gives. variable: the participants "
        "whose drawing carries the symbol: the product for a symbol drawn in the entry's own drawing, a reactant "
        "for a symbol that only the general reaction's reactant carries (a leaving group). condition: the one "
        "template condition the field gives entry by entry (per_entry true). amount: the one template condition or "
        "participant whose amount it gives. Empty for the other kinds"),
    "columns.variable_name": "variable: the symbol the entries give a value for ('R', 'X'); else null",
    "columns.measures": (
        "outcome: what the result of an entry holds, in printed order ('74% (68%)' under a caption that explains "
        "the parenthesis holds an analytical and an isolated yield of the product; '85%, 92% ee' a yield and an "
        "ee). Empty for the other kinds"),
    "columns.blank_means": ("What it means when an entry prints nothing for this field ('no remark'); null as a rule. "
                            "A default of a variable group goes into template.variable_defaults, never only here"),
    "columns.values": ("What a printed value of this field stands for when that is not the printed text itself (a "
                       "compound number whose drawing is elsewhere); empty as a rule"),
    "entries": ("Every entry of the figure in reading order, one per printed compound number: a drawing with a "
                "list of compounds gives one entry per compound, a number printed on two result lines gives two"),
    "entries.label": "The compound number (or entry number) printed for the entry, footnote markers left out; null when it prints none",
    "entries.bbox": ("The whole entry, its drawing with its legend (the text printed with it), [x0, y0, x1, y1] "
                     "in PDF points; entries that share one drawing have the same box"),
    "entries.descriptor": "The entry in short, e.g. '5b; drawing shared with 5a; R = OMe; 70%'",
    "entries.cells": "One cell for every field, in field order; text '' when the entry prints nothing for it",
    "entries.cells.column": "Key of the field the cell belongs to",
    "entries.cells.text": (
        "What the entry prints for this field, footnote markers left out ('' when nothing): the compound number, "
        "the value of the variable ('Me'; several values that each have their own result as 'A / B'), the results "
        "as printed (when several results carry different markers, each marker stays after its value: "
        "'72% c / 55%'), the remark. '' for the drawing itself"),
    "entries.cells.markers": "Footnote markers printed on this part of the entry (on the compound number, on a yield)",
    "entries.cells.structure_bbox": (
        "For the drawing of the entry: the box of that one drawing, without its legend and without neighbouring "
        "drawings; null for every other field and for an entry that shares the drawing of an earlier one"),
    "entries.cells.same_as": (
        "When the entry prints nothing for this field because it shares the value of an earlier entry (the drawing "
        "that serves a list of compounds, a group heading that sets one value for the entries under it): the number "
        "of that entry in `entries` (1 = first); the cell's text is then '' and structure_bbox null. Null otherwise"),
    "entries.lookup_hint": ("Where the paper reports this entry's experiment (the SI paragraph of its compound), "
                            "when you found it; else null"),
    "entries.lookup_hint.note": "How the passage was matched to this entry",
})

PSCOPE_HANDLES = reworded(RTABLE_HANDLES, {
    "reactions": "Every reaction of the figure in entry order: one per entry, unless an entry reports several experiments",
    "reactions.entry": "Number of the entry in `entries` (1 = first) the reaction is printed in",
    "reactions.results": "The result cells of this reaction",
    "reactions.results.column": "Key of an outcome field",
    "reactions.variant": (
        "Key of the template variant this reaction runs: the one whose label is printed with its results or heads "
        "its group of entries, or the one a rule printed in the figure assigns to it (say so in notes); null "
        "without a label or rule"),
    "reactions.footnote_markers": (
        "Markers printed in the entry (on the compound number or on its results) that apply to this reaction; "
        "never those of the title or of the general reaction"),
    "reactions.distinguishing": (
        "Every reaction of an entry that reports more than one: what sets it apart, as printed ('[B]', '60 °C', "
        "'on a larger scale', 'Cl'); null for an entry that reports one reaction"),
    "reactions.cells": (
        "Only when the entry reports several reactions that differ in a variable value (or a compound) printed "
        "together in one field ('Br / Cl'): this reaction's part of that cell. Empty otherwise"),
    "reactions.cells.column": "Key of a participant or variable field",
    "notes": ("Why an entry was split, how a variant was assigned to an entry that prints no label, or what is "
              "unusual about it; nothing for plain entries"),
})

PSCOPE_REACTION = reworded(RTABLE_REACTION, {
    "template_check": ("Where the reading of stage 1 (template, fields, this entry's cells and boxes) is wrong for "
                       "this reaction; empty when it is right"),
    "template_check.target": ("What you checked: a template participant, condition, structure or variant key, a "
                              "field key, a footnote marker, or 'steps' / 'scheme' / 'derivations' / "
                              "'default_yield_type'"),
    "template_check.stage1": "What the reading says",
    "template_check.evidence": "Where: the entry as printed, the general reaction, a footnote, or a passage (doc and page)",
    "overrides": (
        "How this reaction differs from the template beyond what the pipeline applies from the entry's drawing, "
        "number and variable values: a condition or amount the entry prints, what sets this reaction apart when "
        "its entry reports several, a remark of the entry that says what a reactant was (a replace of that reactant "
        "with the remark as text). Usually empty"),
    "outcomes.column": "Key of the outcome field the value is printed in; null for a result of template.shared_results",
    "lookup": (
        "What the main text or the SI states about this entry that the figure leaves open (the product's name; the "
        "starting materials its paragraph names, with their amounts; the scale; a value the figure gives as a "
        "range); each has stated_at or is inferred"),
    "labels": ("Compound numbers the main text or the SI gives this reaction's participants where the entry "
               "prints none (the number of a starting material named in the product's paragraph); empty when none "
               "is found"),
    "labels.label": "Its compound number as the passage prints it ('1b')",
})

# ------------------------------------------------------------ equation blocks
# Stage 1 (skill equation-entries): turn 1 reads the equations (EQN_ENTRIES), turn 2 lists their
# reactions (EQN_HANDLES). Stage 2 (skill equation-reaction): one reaction (EQN_REACTION). Every
# equation draws a whole reaction of its own, so the equations share no template: the compounds are
# listed once for the block (a drawing that several equations use is one compound), and every
# equation carries the fields of a template itself. New objects, built next to the others, so that
# the schemas of the other layouts do not change.

EQN_COMPOUND = obj({
    "key": {**S, "description": ("Short key, unique in the block: the compound number as printed ('21', '21a'), else a "
                                 "slug ('trap-adduct', 'aryl-halide'). One drawing is one compound, with one key in "
                                 "every equation it serves")},
    "label": nullable("string", description="The compound number printed with the drawing or the name; null if none"),
    "text": nullable("string", description=("The name or formula the block prints for it ('Ar–X', a reagent's name); "
                                            "null when the block prints none (names of drawn compounds are looked up "
                                            "later)")),
    "generic": {**B, "description": "True if the drawing or formula has variable groups (R, X, Ar) or stands for a class"},
    "page": nullable("integer"),
    "bbox": {**NBBOX, "description": ("The drawing of this one compound on a page of `doc`, without its label and "
                                      "results; null when it is not drawn there as a structural formula (only named, "
                                      "only numbered with its drawing elsewhere, shown as a crystal-structure picture)")},
    "stated_at": {**STATED_AT, "description": ("For a compound the block does not draw: where the paper draws or names it "
                                               "when that is outside the block (a number whose drawing is in another "
                                               "figure); null for a drawn compound")},
})

EQN_PARTICIPANT = obj({
    "key": {**S, "description": "Key of the compound (`compounds`)"},
    "role": enum(PART_ROLES),
    "amount": nullable("string", description=("The amount printed for it in this equation ('1.5 equiv', '0.5 mmol', "
                                              "'2.0 g, 10 mmol'); null if none")),
    "isolated": nullable("boolean", description="For an intermediate: whether it was isolated before the next step; null otherwise"),
    "alternatives": ALTERNATIVES,
    "stated_at": {**STATED_AT, "description": ("Null as a rule: an amount the block does not print is looked up later, "
                                               "for the experiment itself")},
})

EQN_POINTER = {
    "type": ["object", "null"], "additionalProperties": False, "required": ["printed", "refers_to", "found", "stated_at"],
    "properties": {
        "printed": {**S, "description": ("The reference as printed ('standard conditions', 'conditions of Table 2', "
                                         "'(iii)', a protocol label)")},
        "refers_to": {**S, "description": ("What it refers to, as you found it: the conditions of which table entry, "
                                           "scheme or procedure; or 'outside the paper' for a reference to other work")},
        "found": {**B, "description": ("True when the paper itself gives the conditions it refers to: they are then "
                                       "written into this equation's conditions with stated_at. False when it gives "
                                       "them nowhere")},
        "stated_at": {**STATED_AT, "description": "Where the paper gives those conditions; null when found is false"},
    },
    "description": ("Set when the conditions of the equation are given by a reference instead of being printed over "
                    "or under its arrows (in full or in part); null when they are printed"),
}

EQN_CONDITION = obj({**{k: v for k, v in TEMPLATE["properties"]["conditions"]["items"]["properties"].items()
                        if k != "per_entry"},
                     "step": {**STEP, "description": ("Number of the step (the equation's `steps`) this condition "
                                                      "belongs to; null for a single-step equation")}})

EQN_EQUATION = obj({
    "label": nullable("string", description="Label printed for the equation (a letter, an equation number); null if none"),
    "page": I,
    "bbox": {**BBOX, "description": ("The whole equation: its compounds, arrows, the text over and under them and its "
                                     "results")},
    "descriptor": {**S, "description": "The equation in short, e.g. '7 + 8 → 9; standard conditions; 9, 62%'"},
    "general_reaction": {**S, "description": "One sentence: what the equation does"},
    "results": arr(S, description=("Every result printed for the equation, verbatim with what identifies it ('9, 62%', "
                                   "'10, not detected', '84% ee', '3:1 d.r.', '1.2 g, 70%', '(A) 45%'); empty when "
                                   "it prints none")),
    "footnote_markers": arr(S, description=("Every footnote marker printed in the equation (on a compound number, a "
                                            "condition or a result)")),
    "participants": arr(EQN_PARTICIPANT, description=("The compounds that react or form in this equation, each with "
                                                      "its role here")),
    "steps": reworded(TEMPLATE, {
        "steps": ("The equation as steps: one for a single arrow, several for a sequence. An intermediate is a "
                  "product of one step and a reactant of a later one"),
    })["properties"]["steps"],
    "conditions": arr(EQN_CONDITION, description=(
        "The equation's conditions: what is printed over and under its arrows, what a key on an arrow stands for, "
        "and what a reference leads to (with stated_at)")),
    "condition_pointer": EQN_POINTER,
    "alternative_groups": TABLE_TEMPLATE["properties"]["alternative_groups"],
    "preparations": TEMPLATE["properties"]["preparations"],
    "variable_defaults": TEMPLATE["properties"]["variable_defaults"],
    "default_yield_type": TEMPLATE["properties"]["default_yield_type"],
    "variants": reworded(TEMPLATE, {
        "variants": ("The protocols under which this equation reports results side by side (protocol labels, "
                     "the options of an 'A or B' that each have their own result, listed catalysts or reagents), and "
                     "the runs of optional items that have their own result or that the text names; empty when there "
                     "are none"),
    })["properties"]["variants"],
})

EQN_ENTRIES = obj({
    "reading_guide": {**S, "description": ("Guidance for the agents that each collect one reaction of this block: how "
                                           "the equations are laid out, what each printed element means, and the "
                                           "pitfalls of this block")},
    "compounds": arr(EQN_COMPOUND, description=(
        "Every compound that reacts or forms in an equation of the block, once: a drawing several equations use (a "
        "starting material at the centre of several arrows) is one compound")),
    "structures": arr({"$ref": "#/$defs/structure"}, description=(
        "Drawn compounds that are not participants: a catalyst, ligand or additive drawn over an arrow")),
    "footnotes": reworded(TEMPLATE, {
        "footnotes": ("One item per marker of region.footnotes; its overrides apply to the reactions whose equation "
                      "prints the marker, and use the keys of those equations"),
    })["properties"]["footnotes"],
    "context": TEMPLATE["properties"]["context"],
    "equations": arr(EQN_EQUATION, description="Every equation of the block, in reading order"),
    "ignored": arr(obj({"page": I, "bbox": BBOX, "reason": S})),
    "notes": S,
}, **{"$defs": DEFS})

EQN_HANDLES = obj({
    "reactions": arr(obj({
        "entry": {**I, "description": "Number of the equation in `equations` (1 = first) the reaction is printed in"},
        "results": arr(I, description=("Numbers of this reaction's results in the equation's `results` (1 = first); "
                                       "empty when the equation prints none")),
        "variant": nullable("string", description="Key of the equation's variant this reaction runs; null when it has none"),
        "footnote_markers": arr(S, description="Markers of the equation that apply to this reaction"),
        "distinguishing": nullable("string", description=(
            "Only when the equation reports more than one reaction: what sets this one apart, as printed; else null")),
        "variables": arr(obj({
            "name": S, "value": S,
            "participant_keys": arr(S, description="The participants of the equation whose drawing carries the symbol"),
        }), description="Values of variable groups printed for this reaction ('X = Cl'); empty as a rule"),
    }), description="Every reaction of the block in equation order: one per equation, unless an equation reports several experiments"),
    "notes": arr(obj({"entry": I, "text": S}), description="Why an equation was split, or what is unusual about it; nothing for plain equations"),
    "issues": arr(S, description="Doubts a reviewer should look at"),
})

EQN_OUTCOME = obj({
    **OUTCOME["properties"],
    "product_key": nullable("string", description=(
        "Key of the compound the value is measured on: a product or by-product of this reaction; a reactant only for "
        "a starting material recovered at the end (say so in notes); an intermediate only for a result printed for it "
        "(say so in template_check); null when the result does not say")),
    "result": {**I, "description": ("Number of the equation's result the value is read from (entry.results, 1 = first): "
                                    "one of reaction.results")},
})

EQN_REACTION = obj({
    "template_check": reworded(CTABLE_REACTION, {
        "template_check": ("Where the reading of stage 1 (the compounds and their boxes, this equation's participants, "
                           "steps, conditions, variants, results) is wrong for this reaction; empty when it is right"),
        "template_check.target": ("What you checked: a compound, participant, condition, structure or variant key, a "
                                  "footnote marker, or 'steps' / 'condition_pointer' / 'results' / 'default_yield_type'"),
        "template_check.stage1": "What the reading says",
        "template_check.evidence": "Where: the equation as printed, a footnote, or a passage (doc and page)",
    })["properties"]["template_check"],
    "outcomes": arr(EQN_OUTCOME, description="One per measured value in this reaction's results"),
    "lookup": arr({"$ref": "#/$defs/override"}, description=(
        "What the main text or the SI states about this experiment that the equation leaves open (the amounts and "
        "the scale, the time, temperature or atmosphere, the name of a compound the equation only numbers or draws "
        "with variable groups); each has stated_at or is inferred")),
    "labels": reworded(RTABLE_REACTION, {
        "labels": ("Compound numbers the main text or the SI gives this reaction's participants where the equation "
                   "prints none; empty when none is found"),
    })["properties"]["labels"],
    "related": arr(PASSAGE, description="What the main text and the SI say about this experiment; empty when nothing was found"),
    "notes": S,
    "issues": arr(S, description="Doubts a reviewer should look at"),
}, **{"$defs": DEFS})

# ------------------------------------------------------------ prose passages
# Stage 1 (skill prose-entries): turn 1 reads the passage (PROSE_ENTRIES), turn 2 lists its reactions
# (PROSE_HANDLES). Stage 2 (skill prose-reaction): one reaction (PROSE_REACTION). Experiments reported in
# words: the structure of the equation schemas, with experiments in place of equations, compounds drawn
# (if at all) where the paper draws them, a reference to the reaction or conditions an experiment is based
# on, and what the passage says that is no experiment of its own. New objects again, so that the other
# schemas do not change.

PROSE_COMPOUND = obj({
    "key": {**S, "description": ("Short key, unique in the passage: the compound number ('3a', '7'), else a slug "
                                 "('aryl-bromide', 'coupling-product'). One compound has one key in every "
                                 "experiment it takes part in")},
    "label": nullable("string", description=("The compound number the passage gives it, or for a compound taken from "
                                             "a reaction the passage refers to, the number the paper gives it there; "
                                             "null if none")),
    "text": nullable("string", description=("The name, formula or description the passage gives it ('4-bromoanisole', "
                                            "'PhMgBr', 'a tertiary alkyl bromide', 'the cross-coupling product'), or for a "
                                            "compound taken from a reaction the passage refers to, the name printed there "
                                            "(then with stated_at); null when only a number is given")),
    "generic": {**B, "description": "True for a description of a class of compounds or a formula with variable groups"},
    "page": nullable("integer"),
    "bbox": {**NBBOX, "description": ("Where the paper draws this very compound on a page of `doc` (a numbered compound "
                                      "of a scheme, table or figure), without its number and results; null when it is "
                                      "only named or described, drawn only in the other document, or a changed version "
                                      "of a drawn compound")},
    "stated_at": {**STATED_AT, "description": ("Where the paper gives the number or name in label/text when the passage "
                                               "gives neither (a compound of the reaction the passage refers to); null "
                                               "when the passage prints it")},
})

PROSE_PARTICIPANT = reworded(EQN_PARTICIPANT, {
    "amount": "The amount the passage gives for it in this experiment ('1.5 equiv', '0.25 mmol'); null if none",
    "stated_at": "Null as a rule: an amount the passage does not give is looked up later, for the run itself",
})

PROSE_POINTER = {
    **EQN_POINTER,
    "properties": {
        "printed": {**S, "description": ("The reference as printed ('standard conditions', 'the model coupling of Table "
                                         "3', 'conditions B of Scheme 2', 'under otherwise identical conditions', a note "
                                         "'same conditions as in Scheme 2, method A')")},
        "refers_to": {**S, "description": ("What it refers to, as you found it: which table entry, scheme, procedure or "
                                           "earlier experiment of the passage; or 'outside the paper' for other work")},
        "found": {**B, "description": ("True when the paper gives the reaction or conditions it refers to: what you took "
                                       "from there is written into this experiment's participants and conditions with "
                                       "stated_at. False when it gives them nowhere")},
        "stated_at": {**STATED_AT, "description": "Where the paper gives what it refers to; null when found is false"},
    },
    "description": ("Set when the passage gives the experiment by reference to another reaction or set of conditions, in "
                    "full or in part; null when it states them"),
}

PROSE_CONDITION = reworded(EQN_CONDITION, {
    "step": "Number of the step (the experiment's `steps`) this condition belongs to; null for a single-step experiment",
})

PROSE_EXPERIMENT = obj({
    "label": nullable("string", description="A label the passage prints for the experiment (rare); null if none"),
    "page": I,
    "bbox": {**BBOX, "description": ("The sentences that report the experiment; where they begin when they run over a "
                                     "column or page break")},
    "statement": {**S, "description": ("The sentences that report the experiment, quoted in full and as printed (joined "
                                       "across a column or page break)")},
    "descriptor": {**S, "description": "The experiment in short, e.g. '12 + 13 → 14; standard conditions without CuI; 35%'"},
    "general_reaction": {**S, "description": "One sentence: what the experiment does"},
    "results": arr(S, description=("Every result the passage states for the experiment, verbatim with what identifies it "
                                   "('22% conversion of 12', '71% of 14 in dioxane', 'no coupling product was detected', "
                                   "'the recovered 12 had lost its ee'); empty when it states none")),
    "footnote_markers": arr(S, description=("Every marker printed in the experiment's sentences of a note that concerns "
                                            "it (a footnote, or a reference note that gives conditions, says how a value "
                                            "was measured or reports a run); a number that only cites other work is no "
                                            "marker")),
    "participants": arr(PROSE_PARTICIPANT, description=("The compounds that react or form in this experiment, each with "
                                                        "its role here")),
    "steps": reworded(TEMPLATE, {
        "steps": ("The experiment as steps: one as a rule, several where the passage separates stages ('then', a "
                  "sequence). An intermediate is a product of one step and a reactant of a later one"),
    })["properties"]["steps"],
    "conditions": arr(PROSE_CONDITION, description=(
        "The experiment's conditions: what the passage states, and what a reference leads to (with stated_at)")),
    "based_on": PROSE_POINTER,
    "alternative_groups": TABLE_TEMPLATE["properties"]["alternative_groups"],
    "preparations": TEMPLATE["properties"]["preparations"],
    "variable_defaults": TEMPLATE["properties"]["variable_defaults"],
    "default_yield_type": TEMPLATE["properties"]["default_yield_type"],
    "variants": reworded(TEMPLATE, {
        "variants": ("The runs of this experiment that differ only in a condition (an added or omitted reagent, another "
                     "solvent, catalyst or time point), each with what it changes; empty when the experiment is one run"),
    })["properties"]["variants"],
})

PROSE_ENTRIES = obj({
    "reading_guide": {**S, "description": ("Guidance for the agents that each collect one reaction of this passage: what "
                                           "each experiment is, where its conditions come from, where the SI reports it "
                                           "and how to match it, and the pitfalls of this passage")},
    "compounds": arr(PROSE_COMPOUND, description=(
        "Every compound that reacts or forms in an experiment of the passage, once")),
    "structures": arr({"$ref": "#/$defs/structure"}, description=(
        "Drawn compounds that are not participants: a catalyst, ligand or additive the passage names whose drawing is "
        "on a page of `doc`")),
    "footnotes": reworded(TEMPLATE, {
        "footnotes": ("One item per marker of region.footnotes, and one per note of the page foot, the reference list or "
                      "the end of the article whose marker an experiment prints and that concerns it, with its verbatim "
                      "text; its overrides apply to the reactions whose experiment prints the marker, and use the keys of "
                      "those experiments"),
    })["properties"]["footnotes"],
    "context": TEMPLATE["properties"]["context"],
    "experiments": arr(PROSE_EXPERIMENT, description="Every experiment the passage reports, in reading order"),
    "set_aside": arr(obj({
        "text": {**S, "description": "The statement, quoted (shortened with … where long)"},
        "reason": {**S, "description": ("Why it is no experiment of this passage: the result of other work, a restatement "
                                        "of an entry printed elsewhere (which), an analytical measurement, a proposal, a "
                                        "general procedure")},
    }), description="What the passage reports that is no experiment of its own; empty when there is nothing of the kind"),
    "notes": S,
}, **{"$defs": DEFS})

PROSE_HANDLES = reworded(EQN_HANDLES, {
    "reactions": ("Every reaction of the passage in experiment order: one per experiment, or one per run of an "
                  "experiment that has variants"),
    "reactions.entry": "Number of the experiment in `experiments` (1 = first)",
    "reactions.results": ("Numbers of this reaction's results in the experiment's `results` (1 = first); empty when it "
                          "states none"),
    "reactions.variant": "Key of the experiment's variant (run) this reaction is; null when it has none",
    "reactions.footnote_markers": "Markers of the experiment that apply to this reaction",
    "reactions.distinguishing": ("Only when the experiment reports more than one reaction: what sets this one apart, as "
                                 "the passage says it; else null"),
    "reactions.variables.participant_keys": "The participants of the experiment that carry the symbol",
    "notes": "Why an experiment was split, or what is unusual about it; nothing for plain experiments",
})

PROSE_OUTCOME = obj({
    **EQN_OUTCOME["properties"],
    "result": {**I, "description": ("Number of the experiment's result the value belongs to (entry.results, 1 = first): "
                                    "one of reaction.results")},
    "stated_at": {**STATED_AT, "description": ("Null when the passage gives the value. When the passage states the result "
                                               "only in words and the SI (or another place of the paper) reports the "
                                               "measured value of this very run: where (document and page); the "
                                               "passage's words then go into notes")},
})

PROSE_REACTION = obj({
    "template_check": reworded(CTABLE_REACTION, {
        "template_check": ("Where the reading of stage 1 (the compounds and their boxes, this experiment's participants, "
                           "steps, conditions, reference, runs, results) is wrong for this reaction; empty when it is right"),
        "template_check.target": ("What you checked: a compound, participant, condition, structure or variant key, a "
                                  "footnote marker, or 'steps' / 'based_on' / 'statement' / 'results' / "
                                  "'default_yield_type'"),
        "template_check.stage1": "What the reading says",
        "template_check.evidence": "Where: the passage as printed, a footnote, or another passage (doc and page)",
    })["properties"]["template_check"],
    "outcomes": arr(PROSE_OUTCOME, description="One per measured value of this reaction's results"),
    "lookup": arr({"$ref": "#/$defs/override"}, description=(
        "What the main text or the SI states about this run that the passage leaves open (the amounts and the scale, "
        "the time, temperature or atmosphere, the name of a compound the passage only numbers or describes); each has "
        "stated_at or is inferred")),
    "labels": reworded(RTABLE_REACTION, {
        "labels": ("Compound numbers the main text or the SI gives this reaction's participants where the passage and "
                   "stage 1 give none; empty when none is found"),
        "labels.label": "The compound number as the report in the main text or the SI prints it ('5a')",
        "labels.stated_at": "Where that report is",
    })["properties"]["labels"],
    "related": arr(PASSAGE, description="What the main text and the SI say about this run; empty when nothing was found"),
    "notes": S,
    "issues": arr(S, description="Doubts a reviewer should look at"),
}, **{"$defs": DEFS})

SCHEMAS = {"extract_inventory": INVENTORY, "extract_expand": EXPAND, "extract_entry": ENTRY,
           "ctable_entries": CTABLE_ENTRIES, "ctable_handles": CTABLE_HANDLES, "ctable_reaction": CTABLE_REACTION,
           "rtable_entries": RTABLE_ENTRIES, "rtable_handles": RTABLE_HANDLES, "rtable_reaction": RTABLE_REACTION,
           "pscope_entries": PSCOPE_ENTRIES, "pscope_handles": PSCOPE_HANDLES, "pscope_reaction": PSCOPE_REACTION,
           "eqn_entries": EQN_ENTRIES, "eqn_handles": EQN_HANDLES, "eqn_reaction": EQN_REACTION,
           "prose_entries": PROSE_ENTRIES, "prose_handles": PROSE_HANDLES, "prose_reaction": PROSE_REACTION}


def main() -> None:
    for name, schema in SCHEMAS.items():
        path = HERE / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(path.name)


if __name__ == "__main__":
    main()
