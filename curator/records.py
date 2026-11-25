"""The stored form of a reaction and what the curator derives from it, as pure functions.

  normalize   the pipeline's record without its crop paths: that is what is stored (structure pictures are
              rendered from (doc, page, bbox) on demand, so a box moved in the editor needs no new file)
  summarize   the list columns of `reactions`: labels, yields, flags, thumbnail, search text, sort key
  validate    errors that block saving and warnings that do not, with a readable path each
  skeleton    the record a person starts from when adding a reaction by hand

No database and no PDF here: the caller passes the page tables of the paper's documents.
"""

from __future__ import annotations

import copy
import json
import math
import re

from .config import CURATOR_ORIGIN
from .db import plain_numbers
from .diff import render_path

RECORD_KEYS = ("reaction_id", "label", "kind", "variant", "conditions_given", "results", "inferences", "source",
               "steps", "conditions", "removed_conditions", "unresolved", "other_outcomes", "footnotes",
               "related", "notes", "issues")
LIST_KEYS = ("results", "inferences", "steps", "conditions", "removed_conditions", "unresolved",
             "other_outcomes", "footnotes", "related", "issues")
STR_KEYS = ("reaction_id", "label", "kind", "notes")
SOURCE_KEYS = ("doc", "page", "figure", "section", "caption", "region_id", "block_id", "entry_id",
               "reaction_id", "entry_bbox")

KNOWN = {  # enum values of the pipeline's schemas; anything else is a warning, never an error
    "participant_role": ("reactant", "intermediate", "product", "byproduct"),
    "participant_source": ("drawn", "derived", "text"),
    "condition_role": ("catalyst", "ligand", "reagent", "additive", "base", "solvent", "temperature", "time",
                       "atmosphere", "other"),
    "yield_type": ("isolated", "NMR", "GC", "HPLC", "LC", "analytical", "conversion", "other"),
    "kind": ("optimization", "substrate_scope", "mechanistic", "application", "substrate_prep", "catalyst_prep",
             "background", "mechanism_proposal", "characterization", "other"),
    "origin_prefix": ("base", "entry", "lookup", "footnote", "variant", "default", "stated", "curator"),
    "doc": ("main", "si"),
}

# Blank items for the editor, with every key the pipeline writes. A product also carries `outcomes: []`.
TEMPLATES = {
    "participant": {"key": "", "role": "reactant", "label": None, "text": None, "amount": None,
                    "amount_origin": CURATOR_ORIGIN, "amount_stated_at": None, "source": "text", "unknown": False,
                    "generic": False, "isolated": None, "page": None, "bbox": None, "variables": [], "basis": None,
                    "alternatives": [], "stated_at": None, "choice": None, "inferred": None},
    "condition": {"key": "", "role": "other", "text": "", "amount": None, "origin": CURATOR_ORIGIN,
                  "structure": None, "alternatives": [], "stated_at": None, "amount_stated_at": None,
                  "inferred": None, "value_missing": False},
    "outcome": {"yield": {"text": None, "value": None, "qualifier": None, "type": None,
                          "type_origin": CURATOR_ORIGIN},
                "selectivity": [], "footnote_markers": [], "notes": None, "stated_at": None},
    "step": {"step": 1, "description": "", "reactants": [], "products": [], "conditions": []},
}

FINDING_LABELS = {
    "yield_unspecified": "未明确产率", "conditions_unspecified": "未明确条件",
    "reference_unresolved": "引用未解析", "variables_missing": "变量信息缺失",
    "evidence_conflict": "存在矛盾", "condition_applicability": "条件适用性存疑", "other_review": "其他待核对",
}
FLAGS = ("inferred", "unresolved", "issues", "warned", *FINDING_LABELS, "auxiliary")
BBOX_TOLERANCE = 2.0  # pt a box may stick out of its page (trimmed boxes sit on the edge)


def normalize(record: dict) -> dict:
    """A deep copy without any `crop` key, at any depth."""
    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != "crop"}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node
    return strip(record)


# ----------------------------------------------------------------------------- reading malformed data safely

def _dict(x) -> dict:
    return x if isinstance(x, dict) else {}


def _items(obj, key) -> list[dict]:
    """The dict items of the list obj[key]; nothing if either is not what it should be."""
    value = obj.get(key) if isinstance(obj, dict) else None
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # an int beyond any float: not a number a page or a browser can hold
        return False


def _steps(data) -> list[dict]:
    return _items(data, "steps")


def participants(data) -> list[dict]:
    """Every participant of every step, in order."""
    return [p for st in _steps(data) for p in _items(st, "reactants") + _items(st, "products")]


def _conditions(data) -> list[dict]:
    return [c for st in _steps(data) for c in _items(st, "conditions")] + _items(data, "conditions")


def _name(p: dict) -> str:
    return _text(p.get("label")) or _text(p.get("text")) or _text(p.get("key")) or "?"


def _located(p: dict) -> bool:
    bbox = p.get("bbox")
    return _int(p.get("page")) and isinstance(bbox, list) and len(bbox) == 4 and all(map(_number, bbox))


def _condition(c: dict) -> str:
    """'text amount'; the amount once only where it repeats the text (equation blocks write a temperature
    or time as both: '60 °C', '60 °C')."""
    text, amount = _text(c.get("text")), _text(c.get("amount"))
    return text if amount == text else " ".join(filter(None, (text, amount)))


_PERCENT = re.compile(r"[<>≤≥~]?\s*\d+(?:\.\d+)?")


def _natural(value) -> str:
    """Digits zero-padded, so that 'scheme10' sorts after 'scheme9' and 'e001-10' after 'e001-9'."""
    return re.sub(r"\d+", lambda m: m.group().zfill(6), _text(value))


# ----------------------------------------------------------------------------- list columns

def summarize(data: dict, *, paper_id: str, pipeline_info: dict | None = None) -> dict:
    """The list columns of one reaction (stored in the same-named columns of `reactions`). Works on any
    input: an imported record is stored even when it does not validate."""
    d = _dict(data)
    src = _dict(d.get("source"))
    steps, parts, conds = _steps(d), participants(d), _conditions(d)

    reactants = " + ".join(_name(p) for p in _items(steps[0], "reactants")) if steps else ""
    products = " + ".join(_name(p) for p in _items(steps[-1], "products")) if steps else ""
    conditions = "; ".join(t for t in map(_condition, conds) if t)

    names = {p["key"]: _name(p) for p in parts if isinstance(p.get("key"), str)}
    outcomes = [(_name(p), o) for st in steps for p in _items(st, "products") for o in _items(p, "outcomes")]
    outcomes += [(names.get(o.get("participant_key"), "") if isinstance(o.get("participant_key"), str) else "", o)
                 for o in _items(d, "other_outcomes")]
    yields = []
    for name, o in outcomes:
        y = _dict(o.get("yield"))
        text = _text(y.get("text")) or _text(y.get("value"))
        if text:
            if _PERCENT.fullmatch(text):
                text += "%"  # a bare number in a yield column is a percentage ("12" → "12%")
            suffix = "（回收起始物）" if o.get("measurement_kind") == "recovered_starting_material" else ("（转化率）" if y.get("type") == "conversion" else "")
            line = f"{name} {text}".strip() + suffix
            if line not in yields:  # the same product and value in two alternative steps reads as one
                yields.append(line)

    flags = []
    if d.get("inferences") or any(p.get("inferred") for p in parts):
        flags.append("inferred")
    if d.get("unresolved") or any(x.get("undecided_with") or x.get("alternatives") for x in parts + conds):
        flags.append("unresolved")
    if d.get("issues"):
        flags.append("issues")
    info = _dict(pipeline_info)
    if info.get("errors") or info.get("warnings"):
        flags.append("warned")
    review = _dict(d.get("review"))
    open_findings = [f for f in _items(review, "findings") if f.get("status") == "open"]
    for code in FINDING_LABELS:
        if any(f.get("code") == code for f in open_findings):
            flags.append(code)
    if review.get("category") == "auxiliary":
        flags.append("auxiliary")

    thumb = None
    candidates = [p for st in reversed(steps) for p in _items(st, "products") if p.get("role") == "product"] + parts
    for p in candidates:
        if _located(p):
            thumb = {"doc": src.get("doc"), "page": p["page"], "bbox": p["bbox"]}
            break

    bits = [d.get("label"), d.get("reaction_id"), src.get("figure"), src.get("caption")]
    bits += [p.get(k) for p in parts for k in ("label", "text")]
    bits += [c.get(k) for c in conds for k in ("text", "amount")]
    bits += [_dict(d.get("variant")).get("title"), d.get("notes")]
    bits += (d.get("issues") if isinstance(d.get("issues"), list) else [])
    bits += (d.get("results") if isinstance(d.get("results"), list) else [])
    bits += [f.get("message") for f in open_findings]
    bits += [x.get("text") for x in _items(review, "definitions") + _items(review, "measurements")]
    search = " ".join(t for t in map(_text, bits) if t).casefold()

    pid = str(paper_id)
    page = src.get("page") if _int(src.get("page")) else None
    doc_order = {"main": 0, "si": 1}.get(src.get("doc"), 2) if isinstance(src.get("doc"), str) else 2
    sort_key = "|".join([pid.zfill(6) if pid.isdigit() else pid, str(doc_order),
                         f"{99999 if page is None else page:05d}",
                         _natural(src.get("region_id")), _natural(src.get("block_id")),
                         # A copy or a reaction made by hand has no pipeline id: after its entry's own ones.
                         _natural(src.get("entry_id")) or "~", _natural(src.get("reaction_id")) or "~"])

    def opt(value):
        return value if isinstance(value, str) else None

    return {"label": opt(d.get("label")), "kind": opt(d.get("kind")), "figure": opt(src.get("figure")),
            "doc": opt(src.get("doc")), "page": page, "entry_id": opt(src.get("entry_id")),
            "reactants": reactants, "products": products, "conditions": conditions, "yields": "; ".join(yields),
            "flags": " ".join(flags), "thumb": thumb, "search": search, "sort_key": sort_key}


# ----------------------------------------------------------------------------- validation

def _seg(item, i):
    """How a list item is addressed in a path: by its key where it has one."""
    key = item.get("key") if isinstance(item, dict) else None
    return {"key": key} if isinstance(key, str) and key else i


class _Check:
    def __init__(self, docs, doc):
        self.docs = docs if isinstance(docs, dict) else {}
        self.doc = doc if isinstance(doc, str) and doc in self.docs else None
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.found: list[tuple[list, str]] = []  # (path, message) of each error

    def error(self, path, msg):
        self.errors.append(f"{render_path(path)}: {msg}" if path else msg)
        self.found.append((list(path), msg))

    def warn(self, path, msg):
        self.warnings.append(f"{render_path(path)}: {msg}" if path else msg)

    def known(self, path, value, vocabulary):
        if value not in KNOWN[vocabulary]:
            self.warn(path, f"'{value}' 不是已知的取值")

    def origin(self, path, value):
        if not isinstance(value, str) or value.split(":")[0] not in KNOWN["origin_prefix"]:
            self.warn(path, f"'{value}' 不是已知的来源")

    def page_count(self, doc):
        n = _dict(self.docs.get(doc)).get("page_count") if isinstance(doc, str) else None
        return n if _int(n) else None

    def page_size(self, page):
        pages = _dict(self.docs.get(self.doc)).get("pages")
        if isinstance(pages, list) and 1 <= page <= len(pages):
            size = pages[page - 1]
            if isinstance(size, list) and len(size) >= 2 and _number(size[0]) and _number(size[1]):
                return size[0], size[1]
        return None

    def located(self, path, obj, bbox_key="bbox"):
        """page and bbox of something drawn in the source document: a participant, a structure, the entry."""
        page, bbox = obj.get("page"), obj.get(bbox_key)
        size = None
        if page is not None:
            n = self.page_count(self.doc)
            if not _int(page) or page < 1:
                self.error(path + ["page"], "页码应为正整数")
            elif n is not None and page > n:
                self.error(path + ["page"], f"页码 {page} 超出文档 {self.doc} 的范围（1–{n}）")
            else:
                size = self.page_size(page)
        if bbox is None:
            return
        if not (isinstance(bbox, list) and len(bbox) == 4 and all(map(_number, bbox))):
            self.error(path + [bbox_key], "框应为 4 个有限数字 [x0, y0, x1, y1]")
        elif not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
            self.error(path + [bbox_key], "框应满足 x0 < x1 且 y0 < y1")
        elif page is None:
            self.error(path + [bbox_key], "有框但没有页码")
        elif size and (bbox[0] < -BBOX_TOLERANCE or bbox[1] < -BBOX_TOLERANCE
                       or bbox[2] > size[0] + BBOX_TOLERANCE or bbox[3] > size[1] + BBOX_TOLERANCE):
            self.error(path + [bbox_key], f"框超出页面范围（页面 {size[0]:g} × {size[1]:g} pt）")

    def structure(self, path, x):
        if x is None:
            return
        if not isinstance(x, dict):
            self.error(path, "应为对象或 null")
        else:
            doc = x.get("doc", self.doc)
            if "doc" in x and not isinstance(doc, str):
                self.error(path + ["doc"], "结构来源文档必须为文本")
                return
            if doc != self.doc:
                located = _Check(self.docs, doc)
                if doc not in self.docs:
                    located.error(path + ["doc"], "结构来源文档没有导入")
                located.located(path, x)
                self.errors.extend(located.errors)
                self.warnings.extend(located.warnings)
            else:
                self.located(path, x)

    def alternatives(self, path, obj):
        value = obj.get("alternatives")
        if value is None:
            return
        if not isinstance(value, list):
            self.error(path + ["alternatives"], "应为列表")
            return
        for i, a in enumerate(value):
            if isinstance(a, dict):
                self.structure(path + ["alternatives", i, "structure"], a.get("structure"))

    def ref(self, path, ref):
        """A place in the paper the record points at ({doc, page}): a warning when it is not there."""
        if ref is None:
            return
        if not isinstance(ref, dict):
            self.warn(path, "应为 {doc, page} 对象")
            return
        doc, page = ref.get("doc"), ref.get("page")
        n = self.page_count(doc)
        if not (isinstance(doc, str) and doc in self.docs):
            self.warn(path + ["doc"], f"文档 '{doc}' 没有导入")
        elif not _int(page) or page < 1:
            self.warn(path + ["page"], "页码应为正整数")
        elif n is not None and page > n:
            self.warn(path + ["page"], f"页码 {page} 超出文档 {doc} 的范围（1–{n}）")

    def unique(self, path, items):
        seen, reported = set(), set()
        for x in items:
            key = x.get("key") if isinstance(x, dict) else None
            if isinstance(key, str) and key:
                if key in seen and key not in reported:
                    self.error(path, f"key '{key}' 重复")
                    reported.add(key)
                seen.add(key)

    def key(self, path, obj):
        if not (isinstance(obj.get("key"), str) and obj.get("key")):
            self.error(path + ["key"], "缺少 key（应为非空字符串）")

    def outcome(self, path, o):
        if not isinstance(o, dict):
            self.error(path, "应为对象")
            return
        y = o.get("yield")
        if not isinstance(y, dict):
            self.error(path + ["yield"], "应为对象")
        else:
            if y.get("value") is not None and not _number(y.get("value")):
                self.error(path + ["yield", "value"], "应为数字或 null")
            if y.get("type") is not None:
                self.known(path + ["yield", "type"], y.get("type"), "yield_type")
            if y.get("type_origin") is not None:
                self.origin(path + ["yield", "type_origin"], y.get("type_origin"))
        self.ref(path + ["stated_at"], o.get("stated_at"))

    def participant(self, path, p):
        if not isinstance(p, dict):
            self.error(path, "应为对象")
            return
        self.key(path, p)
        if not isinstance(p.get("role"), str):
            self.error(path + ["role"], "缺少 role（应为字符串）")
        else:
            self.known(path + ["role"], p["role"], "participant_role")
        self.known(path + ["source"], p.get("source"), "participant_source")
        if p.get("source") == "drawn" and p.get("bbox") is None:
            self.warn(path, "标为画出的结构（drawn），但没有框")
        if p.get("amount_origin") is not None:
            self.origin(path + ["amount_origin"], p["amount_origin"])
        variables = p.get("variables")
        if isinstance(variables, list):
            for i, v in enumerate(variables):
                if isinstance(v, dict) and v.get("origin") is not None:
                    self.origin(path + ["variables", i, "origin"], v["origin"])
        for key in ("stated_at", "amount_stated_at"):
            self.ref(path + [key], p.get(key))
        if isinstance(p.get("choice"), dict):
            self.ref(path + ["choice", "stated_at"], p["choice"].get("stated_at"))
        self.located(path, p)
        self.alternatives(path, p)
        prep = p.get("preparation")
        if isinstance(prep, dict):
            for i, x in enumerate(_items(prep, "from")):
                self.located(path + ["preparation", "from", _seg(x, i)], x)
            for i, x in enumerate(_items(prep, "items")):
                self.structure(path + ["preparation", "items", i, "structure"], x.get("structure"))
        if "outcomes" in p:
            if not isinstance(p["outcomes"], list):
                self.error(path + ["outcomes"], "应为列表")
            else:
                for i, o in enumerate(p["outcomes"]):
                    self.outcome(path + ["outcomes", i], o)

    def condition(self, path, c):
        if not isinstance(c, dict):
            self.error(path, "应为对象")
            return
        self.key(path, c)
        if not isinstance(c.get("role"), str):
            self.error(path + ["role"], "缺少 role（应为字符串）")
        else:
            self.known(path + ["role"], c["role"], "condition_role")
        if not isinstance(c.get("text"), str):
            self.error(path + ["text"], "缺少 text（应为字符串）")
        self.origin(path + ["origin"], c.get("origin"))
        self.structure(path + ["structure"], c.get("structure"))
        self.alternatives(path, c)
        for key in ("stated_at", "amount_stated_at"):
            self.ref(path + [key], c.get(key))

    def conditions(self, path, items):
        for i, c in enumerate(items):
            self.condition(path + [_seg(c, i)], c)
        self.unique(path, items)


def _validate(data, docs) -> _Check:
    if not isinstance(data, dict):
        check = _Check(docs, None)
        check.error([], "记录应为一个 JSON 对象")
        return check
    src = data.get("source")
    check = _Check(docs, _dict(src).get("doc"))
    for key in RECORD_KEYS:
        if key not in data:
            check.error([key], "缺少字段")
    for key in LIST_KEYS:
        if key in data and not isinstance(data[key], list):
            check.error([key], "应为列表")
    for key in STR_KEYS:
        if data.get(key) is not None and not isinstance(data[key], str):
            check.error([key], "应为字符串或 null")
    if "conditions_given" in data and not isinstance(data["conditions_given"], bool):
        check.error(["conditions_given"], "应为 true 或 false")
    if data.get("variant") is not None and not isinstance(data["variant"], dict):
        check.error(["variant"], "应为对象或 null")
    if data.get("kind") is not None:
        check.known(["kind"], data["kind"], "kind")

    if "source" in data and not isinstance(src, dict):
        check.error(["source"], "应为对象")
    elif isinstance(src, dict):
        if check.doc is None:
            names = "、".join(sorted(check.docs)) or "无"
            check.error(["source", "doc"], f"文档 '{src.get('doc')}' 不是这篇文献的文档（{names}）")
        check.located(["source"], src, "entry_bbox")

    steps = data.get("steps")
    if isinstance(steps, list):
        if not steps:
            check.error(["steps"], "至少需要一个步骤")
        for i, st in enumerate(steps):
            path = ["steps", i]
            if not isinstance(st, dict):
                check.error(path, "应为对象")
                continue
            for key in ("reactants", "products", "conditions"):
                if not isinstance(st.get(key), list):
                    check.error(path + [key], "应为列表")
            for key in ("reactants", "products"):
                items = st.get(key) if isinstance(st.get(key), list) else []
                for j, p in enumerate(items):
                    check.participant(path + [key, _seg(p, j)], p)
                check.unique(path + [key], items)
            if isinstance(st.get("conditions"), list):
                check.conditions(path + ["conditions"], st["conditions"])
    if isinstance(data.get("conditions"), list):
        check.conditions(["conditions"], data["conditions"])

    part_keys = {p["key"] for p in participants(data) if isinstance(p.get("key"), str)}
    for i, o in enumerate(data.get("other_outcomes") if isinstance(data.get("other_outcomes"), list) else []):
        check.outcome(["other_outcomes", i], o)
        key = o.get("participant_key") if isinstance(o, dict) else None
        if key is not None and not (isinstance(key, str) and key in part_keys):
            check.warn(["other_outcomes", i, "participant_key"], f"'{key}' 不是任何参与物的 key")
    keys = part_keys | {c["key"] for c in _conditions(data) if isinstance(c.get("key"), str)}
    for i, key in enumerate(data.get("unresolved") if isinstance(data.get("unresolved"), list) else []):
        if not (isinstance(key, str) and key in keys):
            check.warn(["unresolved", i], f"'{key}' 不是任何参与物或条件的 key")
    for i, ref in enumerate(data.get("related") if isinstance(data.get("related"), list) else []):
        check.ref(["related", i], ref)
    review = data.get("review")
    if review is not None:
        if not isinstance(review, dict):
            check.error(["review"], "应为对象")
        else:
            ids = set()
            for i, e in enumerate(_items(review, "evidence")):
                path = ["review", "evidence", i]
                if not isinstance(e.get("id"), str) or not e["id"] or e["id"] in ids:
                    check.error(path + ["id"], "证据 ID 缺失或重复")
                ids.add(e.get("id"))
                check.ref(path, e)
                located = _Check(docs, e.get("doc"))
                located.located(path, e)
                check.errors.extend(located.errors)
                check.found.extend(located.found)
            for kind in ("findings", "definitions", "measurements"):
                for i, item in enumerate(_items(review, kind)):
                    if not set(item.get("evidence_ids") or []) <= ids:
                        check.error(["review", kind, i], "引用了不存在的证据")
            for i, finding in enumerate(_items(review, "findings")):
                if finding.get("code") not in FINDING_LABELS or finding.get("status") not in ("open", "resolved"):
                    check.error(["review", "findings", i], "问题类型或状态无效")
    return check


_NOWHERE = object()


def _at(root, path):
    """The value at a path of the validator's (dict keys, list indexes, {"key": k} items); _NOWHERE if
    there is none."""
    node = root
    for seg in path:
        if isinstance(seg, dict) and isinstance(node, list):
            node = next((x for x in node if isinstance(x, dict) and x.get("key") == seg.get("key")), _NOWHERE)
        elif isinstance(seg, int) and isinstance(node, list) and 0 <= seg < len(node):
            node = node[seg]
        elif isinstance(seg, str) and isinstance(node, dict) and seg in node:
            node = node[seg]
        else:
            return _NOWHERE
        if node is _NOWHERE:
            return _NOWHERE
    return node


def _identity(root, path, msg):
    """An error apart from where it is: its message, its field and the object that holds the field
    (without that object's key). The same problem keeps it when its step moves up because an earlier
    one was deleted, or its participant's key is renamed."""
    if not path:
        return None
    holder = _at(root, path[:-1])
    if holder is _NOWHERE:
        return None
    if isinstance(holder, dict):
        holder = {k: v for k, v in holder.items() if k != "key"}
    try:
        text = json.dumps(plain_numbers(holder), ensure_ascii=False, sort_keys=True, default=repr)
    except (TypeError, ValueError, RecursionError):
        return None
    return msg, json.dumps(path[-1], ensure_ascii=False, default=repr), text


def validate(data: dict, docs: dict, base: dict | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings) of a record, each a Chinese message after a readable path. Errors block saving.

    docs: {doc: {"page_count": int, "pages": [[w, h, rotation, matrix], ...]}} of the reaction's paper.
    base: the data the edit started from; an error it already had (the pipeline left it) becomes a
    warning marked （原有问题）, so it does not block an unrelated change. "Already had": the same message
    at the same place, or the same problem of an unchanged object that has moved (_identity)."""
    check = _validate(data, docs)
    errors, warnings = check.errors, check.warnings
    if base is not None and errors:
        old = _validate(base, docs)
        texts = set(old.errors)
        identities = {_identity(base, path, msg) for path, msg in old.found} - {None}
        before = [e in texts or _identity(data, path, msg) in identities
                  for e, (path, msg) in zip(errors, check.found)]
        warnings = warnings + [f"{e}（原有问题）" for e, was in zip(errors, before) if was]
        errors = [e for e, was in zip(errors, before) if not was]
    return errors, warnings


def skeleton(*, source: dict | None = None, kind: str | None = None) -> dict:
    """A record with nothing in it but where it comes from: one empty step."""
    s = _dict(source)
    src = {k: s.get(k) for k in SOURCE_KEYS}
    src["doc"] = src["doc"] or "main"
    src["reaction_id"] = None
    return {"reaction_id": None, "label": None, "kind": kind, "variant": None, "conditions_given": True,
            "results": [], "inferences": [], "source": src, "steps": [copy.deepcopy(TEMPLATES["step"])],
            "conditions": [], "removed_conditions": [], "unresolved": [], "other_outcomes": [], "footnotes": [],
            "related": [], "notes": "", "issues": []}
