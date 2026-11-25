"""Conservative checks for printed variable assignments lost outside machine-readable cells.

This detects explicit `name = value` statements already transcribed by the model. It does not
infer chemistry, propagate variables to derived products, or recover omitted source text.
"""
from __future__ import annotations

import re

_ASSIGNMENT = re.compile(r"(?<![\w])([A-Za-z][A-Za-z0-9₀₁₂₃₄₅₆₇₈₉]*(?:['′])?)\s*=\s*([^;\n,]+)")
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def norm(value):
    return re.sub(r"\s+", "", value.translate(_SUBSCRIPTS)).replace("′", "'")


def assignments(text):
    for match in _ASSIGNMENT.finditer(text or ""):
        name, value = match.groups()
        # Rows often append results after a semicolon; strip only an unambiguous prose separator.
        value = re.split(r"\s+(?:and|with|yield|ee)\b", value, maxsplit=1)[0].strip()
        if value:
            yield name, value


def check(inv, resolve_cells):
    """Only inspect names the table declares or explicitly repeats across >=2 rows.

    Excludes prose quantities like 'yield = 80%' unless declared as variables. Exact values are
    compared after whitespace/subscript normalization. No fields are changed to make checks pass.
    """
    columns = {c["key"]: c for c in inv["columns"]}
    declared = {norm(c["variable_name"]) for c in columns.values()
                if c["kind"] == "variable" and c.get("variable_name")}
    defaults = inv["template"].get("variable_defaults", [])
    declared.update(norm(v["name"]) for v in defaults if v.get("name"))
    printed = []
    for row in inv["entries"]:
        texts = [row.get("descriptor", "")] + [c.get("text", "") for c in row["cells"]]
        printed.append(set((norm(k), norm(v)) for text in texts for k, v in assignments(text)))
    repeated = {}
    for row in printed:
        for key in {k for k, _ in row}:
            repeated[key] = repeated.get(key, 0) + 1
    names = declared | {k for k, n in repeated.items() if n >= 2 and k not in {"yield", "ee", "time", "temperature"}}
    errors = []
    for i, row in enumerate(inv["entries"], 1):
        encoded = set()
        cells = resolve_cells(inv, i)
        for key, cell in cells.items():
            col = columns[key]
            if col["kind"] != "variable" or not col.get("variable_name") or not cell["text"].strip():
                continue
            name, text = norm(col["variable_name"]), cell["text"].strip()
            values = list(assignments(text))
            value = norm(values[0][1]) if len(values) == 1 and norm(values[0][0]) == name else norm(text)
            encoded.add((name, value))
        # Defaults are explicit assignments, but a row-specific value must match, not be hidden by a default.
        explicit_names = {name for name, _ in encoded}
        encoded.update((norm(v["name"]), norm(v["value"])) for v in defaults
                       if v.get("name") and v.get("value") and norm(v["name"]) not in explicit_names)
        for name, value in sorted(printed[i - 1]):
            if name in names and (name, value) not in encoded:
                errors.append(f"variable contract: row {row.get('label') or i}: printed {name}={value} appears "
                              "only in prose/participant text or disagrees with its variable cell; encode it "
                              "in a variable column with explicit participant targets (do not guess propagation)")
    return errors
