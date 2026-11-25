"""What changed between two JSON values, as a list of operations a person can read.

Each operation is {"op": "add"|"remove"|"change"|"reorder", "path": [...], "old": .., "new": ..}. A path is
a list of dict keys, list indexes and {"key": k} segments: lists of participants and conditions are
matched by their `key`, so inserting a reactant shows up as one addition instead of every later reactant
"changing". Moving items around is one `reorder` of the list (old and new key order). Numbers compare by
value (126 is 126.0), booleans are not numbers. The revision log stores these lists next to each
snapshot, and the UI translates the paths.
"""

from __future__ import annotations


def diff(old, new, path=()) -> list[dict]:
    out: list[dict] = []
    _diff(old, new, list(path), out)
    return out


def _keyed(items: list) -> bool:
    keys = [x.get("key") if isinstance(x, dict) else None for x in items]
    return all(isinstance(k, str) for k in keys) and len(set(keys)) == len(keys)


def _diff(old, new, path: list, out: list) -> None:
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new), key=str):
            if k not in new:
                out.append({"op": "remove", "path": path + [k], "old": old[k], "new": None})
            elif k not in old:
                out.append({"op": "add", "path": path + [k], "old": None, "new": new[k]})
            else:
                _diff(old[k], new[k], path + [k], out)
    elif isinstance(old, list) and isinstance(new, list):
        if _keyed(old) and _keyed(new):
            before = {x["key"]: x for x in old}
            after = {x["key"]: x for x in new}
            for x in old:
                if x["key"] not in after:
                    out.append({"op": "remove", "path": path + [{"key": x["key"]}], "old": x, "new": None})
            for x in new:
                if x["key"] in before:
                    _diff(before[x["key"]], x, path + [{"key": x["key"]}], out)
            for x in new:
                if x["key"] not in before:
                    out.append({"op": "add", "path": path + [{"key": x["key"]}], "old": None, "new": x})
            common_old = [x["key"] for x in old if x["key"] in after]
            common_new = [x["key"] for x in new if x["key"] in before]
            if common_old != common_new:
                out.append({"op": "reorder", "path": path, "old": common_old, "new": common_new})
        else:
            for i in range(min(len(old), len(new))):
                _diff(old[i], new[i], path + [i], out)
            for i in range(len(new), len(old)):
                out.append({"op": "remove", "path": path + [i], "old": old[i], "new": None})
            for i in range(len(old), len(new)):
                out.append({"op": "add", "path": path + [i], "old": None, "new": new[i]})
    elif (old != new or type(old) is not type(new)) and not (_number(old) and _number(new) and old == new):
        # 1 and True are different values in a record; 126 and 126.0 are not: a browser sends 126.0
        # back as 126 (as db.canonical_json hashes it).
        out.append({"op": "change", "path": path, "old": old, "new": new})


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def render_path(path) -> str:
    """["data", "steps", 0, "reactants", {"key": "1a"}, "amount"] -> "data.steps[0].reactants[1a].amount"."""
    text = ""
    for seg in path:
        if isinstance(seg, dict):
            text += f"[{seg.get('key')}]"
        elif isinstance(seg, int) and not isinstance(seg, bool):
            text += f"[{seg}]"
        else:
            text += f".{seg}" if text else str(seg)
    return text
