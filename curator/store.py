"""Reading and changing the curator database: the queries behind the API and every mutation.

Every change of a reaction goes through `apply_state`: load the row, build the new state
({data, review_status, review_note, deleted}), diff it against the current one; no difference, no
write; otherwise append revision rev+1 (full snapshot plus the diff), then update the row and its list
columns (`records.summarize`). The person-facing mutations first check the `base_rev` the client
started from, so two editors cannot overwrite each other unnoticed: `Conflict` carries the current
version. No HTTP here: problems are the exceptions below, which the server maps to status codes.
Query parameters arrive as strings, as they come from a query string.
"""

from __future__ import annotations

import re

from . import db, records
from .config import REVIEW_STATUSES, display_id
from .diff import diff


class StoreError(Exception):
    pass


class NotFound(StoreError):
    pass


class BadRequest(StoreError):
    pass


class Conflict(StoreError):
    """The row changed since the client loaded it; `current` is what it is now (get_reaction/get_paper)."""

    def __init__(self, current: dict):
        super().__init__(f"已被他人修改，现在是第 {current.get('rev')} 版")
        self.current = current


class Invalid(StoreError):
    def __init__(self, errors: list, warnings: list):
        super().__init__("数据有错误，没有保存")
        self.errors, self.warnings = list(errors), list(warnings)


# A person made the change: the reaction is `touched` and a re-import no longer overwrites it.
PERSON_ACTIONS = ("edit", "review", "revert", "copy", "create", "delete", "restore")
# Columns the importer may set next to a change of state (apply_state(extra=...)).
EXTRA_COLUMNS = ("pipeline_sha", "pipeline_info", "pending_data", "pending_sha", "pending_import",
                 "first_import", "last_import", "in_latest", "block_pk", "origin_id")
LIST_COLUMNS = ("id, paper_id, block_pk, origin_id, figure, label, layout, kind, doc, page, reactants, products,"
                " conditions, yields, review_status, flags, thumb, deleted, data_sha, pipeline_sha, pending_sha,"
                " in_latest, superseded_by, rev, updated_at, updated_by")
PAPER_FIELDS = ("title", "authors", "journal", "year", "doi", "note")  # what a person may edit
PAPER_COLUMNS = ("paper_id", *PAPER_FIELDS, "meta_origin", "rev", "created_at", "updated_at", "updated_by")
# "已修改": made by hand, or its data is not the pipeline version it was last brought in line with.
EDITED_SQL = "(origin_id IS NULL OR data_sha IS NOT pipeline_sha)"
SORTS = {"id": ("id",), "paper": ("sort_key",), "figure": ("figure",), "label": ("label",), "page": ("doc", "page"),
         "yields": ("yields",), "status": ("review_status",), "updated": ("updated_at",)}
DEFAULT_LIMIT, MAX_LIMIT = 100, 1000
# figure / layout / kind not set: the facet option and the filter value that selects it
NONE_VALUE, NONE_LABEL = "~", "（无）"


# ----------------------------------------------------------------------------- small helpers

def _author(author) -> str:
    if not isinstance(author, str) or not author.strip():
        raise BadRequest("请填写编辑者")
    return author.strip()


INT64 = range(-2 ** 63, 2 ** 63)  # what SQLite can bind; a larger Python int raises OverflowError there


def _int(value, what: str) -> int:
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip(), re.ASCII):
        text = value.strip()
        value = int(text) if len(text.lstrip("-").lstrip("0")) <= 19 else None  # int() of 5000 digits fails
        if value is None:
            raise BadRequest(f"{what} 超出范围：{text[:24]}…")
    if isinstance(value, int) and not isinstance(value, bool):
        if value not in INT64:
            raise BadRequest(f"{what} 超出范围：{value}")
        return value
    raise BadRequest(f"{what} 应为整数：{value!r}")


def _parse_id(value) -> int | None:
    """A reaction id as given: 123, "123" or "R000123"; None if it is none (or too large to be one)."""
    if isinstance(value, str):
        text = value.strip()
        text = text[1:] if text[:1] in ("R", "r") else text
        value = int(text) if re.fullmatch(r"\d+", text, re.ASCII) and len(text.lstrip("0")) <= 19 else None
    if isinstance(value, int) and not isinstance(value, bool) and value in INT64:
        return value
    return None


def _reaction_id(value) -> int:
    rid = _parse_id(value)
    if rid is None:
        raise NotFound(f"没有反应 {value}")
    return rid


def _json(value):
    """A value for a JSON column: dicts and lists are dumped, the rest is stored as it is."""
    return db.dumps(value) if isinstance(value, (dict, list)) else value


def _row(conn, rid: int):
    row = conn.execute("SELECT * FROM reactions WHERE id = ?", (rid,)).fetchone()
    if row is None:
        raise NotFound(f"没有反应 {display_id(rid)}")
    return row


def _update(conn, rid: int, cols: dict) -> None:
    conn.execute(f"UPDATE reactions SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?",
                 [*cols.values(), rid])


def _summary(conn, paper_id: str, block_pk, data, pipeline_info) -> dict:
    """The list columns of a reaction; `layout` is its block's."""
    if isinstance(pipeline_info, str):
        pipeline_info = db.loads(pipeline_info)
    cols = records.summarize(data, paper_id=paper_id, pipeline_info=pipeline_info)
    cols["thumb"] = _json(cols["thumb"])
    block = conn.execute("SELECT layout FROM blocks WHERE block_pk = ?", (block_pk,)).fetchone() \
        if block_pk is not None else None
    cols["layout"] = block["layout"] if block else None
    return cols


def _paper_key(paper_id: str):
    return (0, int(paper_id), "") if paper_id.isdigit() else (1, 0, paper_id)


def _block_key(b):
    """Blocks in printed order: paper, main text before SI, page, then region and block with their numbers
    compared as numbers (scheme9 before scheme10)."""
    def natural(text):
        return re.sub(r"\d+", lambda m: m.group().zfill(6), text or "")
    return (_paper_key(b["paper_id"]), {"main": 0, "si": 1}.get(b["doc"], 2),
            b["page"] if b["page"] is not None else 99999, natural(b["region_id"]), natural(b["block_id"]))


STATE_KEYS = ("data", "review_status", "review_note", "deleted")


def state_of(row) -> dict:
    """The state a reaction revision snapshots."""
    return {"data": db.loads(row["data"]), "review_status": row["review_status"],
            "review_note": row["review_note"], "deleted": bool(row["deleted"])}


def snapshot_state(snapshot: dict) -> dict:
    """The state in a reaction revision's snapshot, without what else it keeps (`dismissed`)."""
    return {k: snapshot[k] for k in STATE_KEYS if k in snapshot}


def docs_for(conn, paper_id: str) -> dict:
    """{doc: {doc_id, page_count, pages}} of a paper: what records.validate checks pages and boxes against."""
    return {r["doc"]: {"doc_id": r["doc_id"], "page_count": r["page_count"], "pages": db.loads(r["pages"])}
            for r in conn.execute("SELECT doc, doc_id, page_count, pages FROM documents WHERE paper_id = ?",
                                  (paper_id,))}


# ----------------------------------------------------------------------------- primitives

def insert_reaction(conn, *, paper_id, block_pk, origin_id, data, action, author, comment=None, import_id=None,
                    copied_from=None, pipeline_sha=None, pipeline_info=None, touched=False,
                    review_status="unreviewed") -> int:
    """A new reaction at rev 1 with its first revision; returns its id."""
    author = _author(author)
    if review_status not in REVIEW_STATUSES:
        raise BadRequest(f"未知的审核状态：{review_status}")
    data = records.normalize(data)
    with db.write(conn):
        now = db.now_iso()
        cols = {"paper_id": paper_id, "block_pk": block_pk, "origin_id": origin_id, "copied_from": copied_from,
                "data": db.dumps(data), "data_sha": db.sha_json(data), "rev": 1, "review_status": review_status,
                "review_note": None, "deleted": 0, "touched": int(bool(touched)), "first_import": import_id,
                "last_import": import_id, "in_latest": 1, "pipeline_sha": pipeline_sha,
                "pipeline_info": _json(pipeline_info), "created_at": now, "updated_at": now, "updated_by": author,
                **_summary(conn, paper_id, block_pk, data, pipeline_info)}
        rid = conn.execute(f"INSERT INTO reactions ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                           list(cols.values())).lastrowid
        db.insert_revision(conn, entity="reaction", entity_id=rid, rev=1, action=action, author=author,
                           snapshot={"data": data, "review_status": review_status, "review_note": None,
                                     "deleted": False},
                           diff=[], comment=comment, import_id=import_id, created_at=now)
    return rid


def apply_state(conn, row_id, new_state: dict, *, action, author, comment=None, import_id=None, base_rev=None,
                target_rev=None, extra: dict | None = None, force: bool = False,
                kept: dict | None = None) -> int | None:
    """Move a reaction to `new_state`. Returns the new rev, or None when nothing changed (and not `force`);
    `extra` columns are written either way, and with them the list columns (pipeline_info feeds `warned`).
    `kept`: more to keep in the revision's snapshot beside the state (a dismissed pipeline version)."""
    author = _author(author)
    extra = dict(extra or {})
    if set(extra) - set(EXTRA_COLUMNS):
        raise ValueError(f"not a column apply_state may set: {sorted(set(extra) - set(EXTRA_COLUMNS))}")
    with db.write(conn):
        row = _row(conn, row_id)
        old = state_of(row)
        new = {"data": records.normalize(new_state["data"]), "review_status": new_state["review_status"],
               "review_note": new_state.get("review_note"), "deleted": bool(new_state.get("deleted"))}
        changes = diff(old, new)
        info = extra["pipeline_info"] if "pipeline_info" in extra else row["pipeline_info"]
        block_pk = extra.get("block_pk", row["block_pk"])
        extra_cols = {k: _json(v) for k, v in extra.items()}
        if not changes and not force:
            if extra:
                _update(conn, row["id"], {**extra_cols, **_summary(conn, row["paper_id"], block_pk, old["data"], info)})
            return None
        rev = row["rev"] + 1
        now = db.now_iso()
        db.insert_revision(conn, entity="reaction", entity_id=row["id"], rev=rev, action=action, author=author,
                           snapshot={**new, **(kept or {})}, diff=changes, comment=comment, import_id=import_id,
                           base_rev=row["rev"] if base_rev is None else base_rev, target_rev=target_rev,
                           created_at=now)
        _update(conn, row["id"], {
            "data": db.dumps(new["data"]), "data_sha": db.sha_json(new["data"]), "rev": rev,
            "review_status": new["review_status"], "review_note": new["review_note"], "deleted": int(new["deleted"]),
            "touched": 1 if action in PERSON_ACTIONS else row["touched"], "updated_at": now, "updated_by": author,
            **_summary(conn, row["paper_id"], block_pk, new["data"], info), **extra_cols})
    return rev


# ----------------------------------------------------------------------------- reactions: queries

def _doc_ids(conn) -> dict:
    """(paper_id, doc) → doc_id, for the thumbnails of list rows (rendered by document id)."""
    return {(d["paper_id"], d["doc"]): d["doc_id"]
            for d in conn.execute("SELECT doc_id, paper_id, doc FROM documents").fetchall()}


def _thumb(r, doc_ids: dict | None):
    thumb = db.loads(r["thumb"])
    if thumb and doc_ids is not None:
        thumb["doc_id"] = doc_ids.get((r["paper_id"], thumb.get("doc")))
    return thumb


def _list_row(r, doc_ids: dict | None = None) -> dict:
    return {"id": r["id"], "rid": display_id(r["id"]), "paper_id": r["paper_id"], "block_pk": r["block_pk"],
            "origin_id": r["origin_id"], "figure": r["figure"], "label": r["label"], "layout": r["layout"],
            "kind": r["kind"], "doc": r["doc"], "page": r["page"], "reactants": r["reactants"],
            "products": r["products"], "conditions": r["conditions"], "yields": r["yields"],
            "review_status": r["review_status"], "flags": (r["flags"] or "").split(), "thumb": _thumb(r, doc_ids),
            "deleted": bool(r["deleted"]), "edited": r["origin_id"] is None or r["data_sha"] != r["pipeline_sha"],
            "pending": r["pending_sha"] is not None, "in_latest": bool(r["in_latest"]),
            "superseded_by": r["superseded_by"], "rev": r["rev"],
            "updated_at": r["updated_at"], "updated_by": r["updated_by"]}


def _import_ref(conn, import_id, paper_id) -> dict | None:
    """An import batch as a reaction's provenance: when, from where, at which commit, the paper's steps."""
    if import_id is None:
        return None
    i = conn.execute("SELECT import_id, started_at, finished_at, work_dir, repo_commit, repo_dirty, author, options"
                     " FROM imports WHERE import_id = ?", (import_id,)).fetchone()
    if i is None:
        return None
    p = conn.execute("SELECT steps FROM import_papers WHERE import_id = ? AND paper_id = ?",
                     (import_id, paper_id)).fetchone()
    return {**dict(i), "options": db.loads(i["options"]), "steps": db.loads(p["steps"]) if p else None}


PIPELINE_WRITES = ("import", "reimport", "accept_import")  # the actions that set the data to a pipeline version


def data_import(conn, rid: int) -> int | None:
    """The import whose pipeline version the reaction's data is, or was edited from: back from the newest
    revision past edits, reviews and dismissals (a revert continues at the revision it restored) to the
    one that wrote pipeline data. None for a reaction made by hand or copied."""
    revs = {r["rev"]: r for r in conn.execute("SELECT rev, action, import_id, target_rev FROM revisions"
                                              " WHERE entity = 'reaction' AND entity_id = ?", (str(rid),))}
    rev = max(revs, default=None)
    while rev in revs:
        r = revs[rev]
        if r["action"] in PIPELINE_WRITES:
            return r["import_id"]
        if r["action"] in ("copy", "create"):
            return None
        target = r["target_rev"] if r["action"] == "revert" else None
        rev = target if target is not None and target < rev else rev - 1
    return None


def get_reaction(conn, rid) -> dict:
    rid = _reaction_id(rid)
    r = _row(conn, rid)
    data = db.loads(r["data"])
    pending = None
    if r["pending_sha"] is not None:
        pending = {"import_id": r["pending_import"], "sha": r["pending_sha"],
                   "diff": diff(data, db.loads(r["pending_data"]), ("data",))}
    paper = conn.execute("SELECT paper_id, title, authors, journal, year, doi FROM papers WHERE paper_id = ?",
                         (r["paper_id"],)).fetchone()
    documents = {d["doc"]: {"doc_id": d["doc_id"], "filename": d["filename"], "page_count": d["page_count"],
                            "pages": db.loads(d["pages"])}
                 for d in conn.execute("SELECT doc, doc_id, filename, page_count, pages FROM documents"
                                       " WHERE paper_id = ? ORDER BY doc", (r["paper_id"],))}
    block = conn.execute("SELECT block_pk, region_id, block_id, slug, figure, layout, kind, title, doc, page"
                         " FROM blocks WHERE block_pk = ?", (r["block_pk"],)).fetchone() \
        if r["block_pk"] is not None else None
    return {**_list_row(r), "data": data, "review_note": r["review_note"], "touched": bool(r["touched"]),
            "copied_from": r["copied_from"], "first_import": r["first_import"], "last_import": r["last_import"],
            "pipeline_info": db.loads(r["pipeline_info"]), "pending": pending, "created_at": r["created_at"],
            "paper": dict(paper) if paper else None, "documents": documents,
            "block": dict(block) if block else None,
            # An old version: the import that replaced its paper's reactions (it is read-only since)
            "superseded": _import_ref(conn, r["superseded_by"], r["paper_id"]),
            "provenance": {"first_import": _import_ref(conn, r["first_import"], r["paper_id"]),
                           "last_import": _import_ref(conn, r["last_import"], r["paper_id"]),
                           # the import the data comes from (last_import may only have offered a version)
                           "data_import": _import_ref(conn, data_import(conn, rid), r["paper_id"])}}


def _values(params: dict, key: str) -> list[str]:
    value = params.get(key)
    if isinstance(value, (list, tuple)):
        value = ",".join(str(v) for v in value)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def filter_clause(params: dict | None) -> tuple[str, list]:
    """The filters of `params` as an SQL condition on `reactions` (no WHERE) and its arguments. Deleted
    reactions are left out unless `deleted` says otherwise; sort and paging keys are ignored here."""
    params = params or {}
    clauses: list[str] = []
    args: list = []

    def isin(column, values):
        clauses.append(f"{column} IN ({', '.join('?' * len(values))})")
        args.extend(values)

    def one(key, allowed):
        values = _values(params, key)
        if len(values) > 1 or (values and values[0] not in allowed):
            raise BadRequest(f"{key} 的取值不对：{params.get(key)!r}")
        return values[0] if values else None

    if _values(params, "paper"):
        isin("paper_id", _values(params, "paper"))
    for key in ("figure", "layout", "kind"):  # the column of the same name; NONE_VALUE: not set
        values = _values(params, key)
        if values:
            named = [v for v in values if v != NONE_VALUE]
            either = [f"{key} IN ({', '.join('?' * len(named))})"] if named else []
            if len(named) < len(values):
                either.append(f"{key} IS NULL OR {key} = ''")
            clauses.append(f"({' OR '.join(either)})")
            args.extend(named)
    if _values(params, "block"):
        isin("block_pk", [_int(v, "block") for v in _values(params, "block")])
    if _values(params, "status"):
        unknown = [v for v in _values(params, "status") if v not in REVIEW_STATUSES]
        if unknown:
            raise BadRequest(f"未知的审核状态：{', '.join(unknown)}")
        isin("review_status", _values(params, "status"))
    for flag in _values(params, "flag"):
        if flag not in records.FLAGS:
            raise BadRequest(f"未知的标记：{flag}")
        clauses.append("(' ' || flags || ' ') LIKE ?")
        args.append(f"% {flag} %")
    scope = one("scope", ("core", "all"))
    if scope == "core":
        clauses.append("(' ' || flags || ' ') NOT LIKE '% auxiliary %'")
    edited = one("edited", ("0", "1"))
    if edited is not None:
        clauses.append(EDITED_SQL if edited == "1" else f"NOT {EDITED_SQL}")
    pending = one("pending", ("0", "1"))
    if pending is not None:
        clauses.append("pending_sha IS NOT NULL" if pending == "1" else "pending_sha IS NULL")
    # Current reactions only, unless asked: the old versions a re-import of their paper replaced are an archive.
    latest = one("latest", ("0", "1", "all")) or "1"
    if latest != "all":
        clauses.append(f"in_latest = {int(latest)}")
    deleted = one("deleted", ("0", "1", "all")) or "0"
    if deleted != "all":
        clauses.append(f"deleted = {int(deleted)}")
    if _values(params, "import"):
        ids = [_int(v, "import") for v in _values(params, "import")]
        marks = ", ".join("?" * len(ids))
        clauses.append(f"(first_import IN ({marks}) OR last_import IN ({marks}))")
        args.extend(ids + ids)
    q = params.get("q")
    for token in (q.split() if isinstance(q, str) else []):
        token = token.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("search LIKE ? ESCAPE '\\'")
        args.append(f"%{token}%")
    if _values(params, "ids"):
        ids = [_parse_id(v) for v in _values(params, "ids")]
        if None in ids:
            raise BadRequest(f"ids 的取值不对：{params.get('ids')!r}")
        isin("id", ids)
    return " AND ".join(clauses) or "1", args


def _order(params: dict) -> str:
    sort = params.get("sort") or None
    order = params.get("order") or "asc"
    if order not in ("asc", "desc"):
        raise BadRequest(f"order 的取值不对：{params.get('order')!r}")
    if sort is not None and sort not in SORTS:
        raise BadRequest(f"不能按 {sort!r} 排序")
    columns = list(SORTS[sort]) if sort else []
    columns += [c for c in ("sort_key", "id") if c not in columns and "id" not in columns]
    return ", ".join(f"{c} {order.upper()}" for c in columns)


def _paging(params: dict) -> tuple[int, int]:
    offset = _int(params.get("offset") or 0, "offset")
    limit = _int(params.get("limit") or DEFAULT_LIMIT, "limit")
    if offset < 0 or limit < 0:
        raise BadRequest("offset 和 limit 不能是负数")
    return offset, min(limit, MAX_LIMIT)


def list_reactions(conn, params: dict) -> dict:
    params = params or {}
    where, args = filter_clause(params)
    order = _order(params)
    offset, limit = _paging(params)
    total = conn.execute(f"SELECT count(*) FROM reactions WHERE {where}", args).fetchone()[0]
    rows = conn.execute(f"SELECT {LIST_COLUMNS} FROM reactions WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                        [*args, limit, offset]).fetchall()
    doc_ids = _doc_ids(conn)
    return {"total": total, "rows": [_list_row(r, doc_ids) for r in rows]}


def neighbours(conn, rid, params) -> dict:
    """The reactions before and after `rid` in the list as filtered and sorted by `params`. The reaction
    itself counts as part of the list even when an edit has just taken it out of the filter."""
    rid = _reaction_id(rid)
    params = params or {}
    where, args = filter_clause(params)
    row = conn.execute(f"SELECT prev, next FROM (SELECT id, lag(id) OVER w AS prev, lead(id) OVER w AS next"
                       f" FROM reactions WHERE ({where}) OR id = ? WINDOW w AS (ORDER BY {_order(params)}))"
                       f" WHERE id = ?", [*args, rid, rid]).fetchone()
    if row is None:
        raise NotFound(f"没有反应 {display_id(rid)}")
    return {"prev": row["prev"], "next": row["next"]}


def facets(conn, params: dict) -> dict:
    """What the filter bar offers, with counts. Each facet is counted under all the other filters but its
    own, so its options stay visible after one is picked:
      {total, paper|figure|block|layout|kind|import: [{value, count, label?...}],
       status|flag: [{value, count}], edited, pending, not_latest, deleted: int}
    `flag` counts what adding that flag to the current ones would leave. Reactions without a figure,
    layout or kind are the option NONE_VALUE (label NONE_LABEL), a value the filter takes back."""
    params = dict(params or {})

    def count(**override) -> int:
        p = {k: v for k, v in params.items() if k not in override}
        p.update({k: v for k, v in override.items() if v is not None})
        where, args = filter_clause(p)
        return conn.execute(f"SELECT count(*) FROM reactions WHERE {where}", args).fetchone()[0]

    def group(key, column) -> dict:
        where, args = filter_clause({k: v for k, v in params.items() if k != key})
        return {r[0]: r[1] for r in conn.execute(
            f"SELECT {column}, count(*) FROM reactions WHERE {where} GROUP BY {column}", args)}

    def options(key) -> list:
        counts: dict = {}
        for value, n in group(key, key).items():
            value = NONE_VALUE if value in (None, "") else value
            counts[value] = counts.get(value, 0) + n
        return [{"value": v, "count": n, **({"label": NONE_LABEL} if v == NONE_VALUE else {})}
                for v, n in sorted(counts.items(), key=lambda kv: (kv[0] == NONE_VALUE, kv[0]))]

    papers = group("paper", "paper_id")
    paper_rows = sorted(conn.execute("SELECT paper_id, title FROM papers").fetchall(),
                        key=lambda r: _paper_key(r["paper_id"]))
    blocks = group("block", "block_pk")
    block_rows = conn.execute("SELECT block_pk, paper_id, doc, page, region_id, block_id, figure, layout, title"
                              " FROM blocks").fetchall()
    where, args = filter_clause({k: v for k, v in params.items() if k != "import"})
    imports = conn.execute(
        f"SELECT i.import_id, i.started_at, (SELECT count(*) FROM reactions WHERE ({where})"
        f" AND (first_import = i.import_id OR last_import = i.import_id)) FROM imports i ORDER BY i.import_id DESC",
        args).fetchall()
    current_flags = _values(params, "flag")
    statuses = group("status", "review_status")
    return {
        "total": count(),
        "paper": [{"value": r["paper_id"], "label": r["title"] or r["paper_id"], "count": papers.get(r["paper_id"], 0)}
                  for r in paper_rows],
        "figure": options("figure"),
        "block": [{"value": b["block_pk"], "label": f"{b['figure'] or b['region_id']} / {b['block_id']}"
                   + (f" {b['title']}" if b["title"] else ""), "paper_id": b["paper_id"], "figure": b["figure"],
                   "layout": b["layout"], "count": blocks.get(b["block_pk"], 0)}
                  for b in sorted(block_rows, key=_block_key)],
        "layout": options("layout"),
        "kind": options("kind"),
        "import": [{"value": r[0], "label": r[1], "count": r[2]} for r in imports],
        "status": [{"value": s, "count": statuses.get(s, 0)} for s in REVIEW_STATUSES],
        "flag": [{"value": f, "count": count(flag=",".join(dict.fromkeys(current_flags + [f])))}
                 for f in records.FLAGS],
        "edited": count(edited="1"),
        "pending": count(pending="1"),
        "not_latest": count(latest="0"),
        "deleted": count(deleted="1"),
    }


def _history(conn, entity: str, entity_id: str) -> list[dict]:
    rows = conn.execute("SELECT rev, action, author, comment, created_at, import_id, base_rev, target_rev, diff"
                        " FROM revisions WHERE entity = ? AND entity_id = ? ORDER BY rev DESC", (entity, entity_id))
    return [{**dict(r), "diff": db.loads(r["diff"])} for r in rows]


def history(conn, rid) -> list[dict]:
    """Every revision of a reaction, newest first, each with its diff against the one before."""
    rid = _reaction_id(rid)
    _row(conn, rid)
    return _history(conn, "reaction", str(rid))


def revision(conn, rid, rev) -> dict:
    rid = _reaction_id(rid)
    rev = _int(rev, "版本号")
    r = conn.execute("SELECT rev, action, author, comment, created_at, import_id, base_rev, target_rev, snapshot,"
                     " diff FROM revisions WHERE entity = 'reaction' AND entity_id = ? AND rev = ?",
                     (str(rid), rev)).fetchone()
    if r is None:
        raise NotFound(f"{display_id(rid)} 没有第 {rev} 版")
    return {**dict(r), "snapshot": db.loads(r["snapshot"]), "diff": db.loads(r["diff"])}


def _pipeline_data(conn, row):
    """The data of the pipeline version the reaction was last brought in line with (`pipeline_sha`): a
    snapshot's data, or the version a dismiss_import revision kept. NotFound rather than another version
    when it is not there (a version dismissed before the revisions kept it)."""
    if row["origin_id"] is None:
        raise NotFound(f"{display_id(row['id'])} 不是从流水线导入的，没有流水线版本")
    for r in conn.execute("SELECT snapshot FROM revisions WHERE entity = 'reaction' AND entity_id = ?"
                          " ORDER BY rev DESC", (str(row["id"]),)):
        snap = db.loads(r["snapshot"])
        dismissed = snap.get("dismissed")
        if isinstance(dismissed, dict) and dismissed.get("sha") == row["pipeline_sha"]:
            return dismissed.get("data")
        if row["pipeline_sha"] is not None and db.sha_json(snap.get("data")) == row["pipeline_sha"]:
            return snap.get("data")
    raise NotFound(f"{display_id(row['id'])} 的流水线版本没有保存")


def diff_between(conn, rid, frm, to) -> list:
    """Changes from `frm` to `to`, each a rev number or 'current', 'pipeline', 'pending'. Between two revisions
    (or 'current') the whole state is compared; with the pipeline or pending version, the data only (paths
    still start at 'data')."""
    rid = _reaction_id(rid)
    row = _row(conn, rid)

    def side(which):  # -> (value, is a full state)
        if which == "current":
            return state_of(row), True
        if which == "pending":
            if row["pending_sha"] is None:
                raise NotFound(f"{display_id(rid)} 没有待采用的流水线新版本")
            return db.loads(row["pending_data"]), False
        if which == "pipeline":
            return _pipeline_data(conn, row), False
        return snapshot_state(revision(conn, rid, which)["snapshot"]), True

    (old, old_state), (new, new_state) = side(frm), side(to)
    if old_state and new_state:
        return diff(old, new)
    return diff(old["data"] if old_state else old, new["data"] if new_state else new, ("data",))


def get_block(conn, block_pk) -> dict:
    """A block as the pipeline left it (region, view) and the reactions of the database that come from it."""
    block_pk = _int(block_pk, "block")
    b = conn.execute("SELECT * FROM blocks WHERE block_pk = ?", (block_pk,)).fetchone()
    if b is None:
        raise NotFound(f"没有 block {block_pk}")
    out = {k: b[k] for k in ("block_pk", "paper_id", "region_id", "block_id", "slug", "doc", "page", "figure",
                             "layout", "kind", "title", "import_id")}
    from .block_geometry import effective
    source_view = db.loads(b["view"])
    out.update(in_latest=bool(b["in_latest"]), region=db.loads(b["region"]),
               view=effective(conn, b, source_view), source_view=source_view)
    out["reactions"] = [{"id": r["id"], "rid": display_id(r["id"]), "label": r["label"], "entry_id": r["entry_id"],
                         "origin_id": r["origin_id"], "review_status": r["review_status"],
                         "deleted": bool(r["deleted"])}
                        for r in conn.execute("SELECT id, label, entry_id, origin_id, review_status, deleted"
                                              " FROM reactions WHERE block_pk = ? ORDER BY sort_key, id", (block_pk,))]
    return out


def list_imports(conn) -> list:
    """Import batches, newest first, with their report and what happened to each paper."""
    papers: dict = {}
    for r in conn.execute("SELECT import_id, paper_id, outcome, reason, counts FROM import_papers"):
        papers.setdefault(r["import_id"], []).append({"paper_id": r["paper_id"], "outcome": r["outcome"],
                                                      "reason": r["reason"], "counts": db.loads(r["counts"])})
    return [{**dict(r), "options": db.loads(r["options"]), "report": db.loads(r["report"]),
             "papers": sorted(papers.get(r["import_id"], []), key=lambda p: _paper_key(p["paper_id"]))}
            for r in conn.execute("SELECT * FROM imports ORDER BY import_id DESC")]


# ----------------------------------------------------------------------------- papers

def _paper_counts(conn, paper_id=None) -> dict:
    """{paper_id: counts}: current reactions not deleted, by review status, pending, edited; deleted ones; and
    `old`, the old versions re-imports replaced (counted nowhere else)."""
    where, args = ("WHERE paper_id = ?", [paper_id]) if paper_id is not None else ("", [])
    cur = "in_latest = 1 AND deleted = 0"
    statuses = ", ".join(f"sum({cur} AND review_status = '{s}') AS {s}" for s in REVIEW_STATUSES)
    return {r["paper_id"]: {k: r[k] or 0 for k in r.keys() if k != "paper_id"} for r in conn.execute(
        f"SELECT paper_id, sum({cur}) AS reactions, {statuses},"
        f" sum({cur} AND pending_sha IS NOT NULL) AS pending, sum({cur} AND {EDITED_SQL}) AS edited,"
        f" sum(in_latest = 1 AND deleted = 1) AS deleted, sum(in_latest = 0) AS old"
        f" FROM reactions {where} GROUP BY paper_id", args)}


def _empty_counts() -> dict:
    return dict.fromkeys(("reactions", *REVIEW_STATUSES, "pending", "edited", "deleted", "old"), 0)


def list_papers(conn) -> list:
    counts = _paper_counts(conn)
    docs: dict = {}
    for d in conn.execute("SELECT paper_id, doc, doc_id, filename, page_count FROM documents ORDER BY doc"):
        docs.setdefault(d["paper_id"], []).append({k: d[k] for k in ("doc", "doc_id", "filename", "page_count")})
    rows = sorted(conn.execute(f"SELECT {', '.join(PAPER_COLUMNS)} FROM papers").fetchall(),
                  key=lambda r: _paper_key(r["paper_id"]))
    return [{**dict(r), "documents": docs.get(r["paper_id"], []),
             "counts": counts.get(r["paper_id"], _empty_counts())} for r in rows]


def get_paper(conn, paper_id) -> dict:
    paper_id = str(paper_id)
    p = conn.execute("SELECT * FROM papers WHERE paper_id = ?", (paper_id,)).fetchone()
    if p is None:
        raise NotFound(f"没有文献 {paper_id}")
    documents = {d["doc"]: {"doc_id": d["doc_id"], "filename": d["filename"], "page_count": d["page_count"],
                            "sha256": d["sha256"], "pdf_meta": db.loads(d["pdf_meta"])}
                 for d in conn.execute("SELECT * FROM documents WHERE paper_id = ? ORDER BY doc", (paper_id,))}
    blocks = [{**{k: b[k] for k in ("block_pk", "region_id", "block_id", "slug", "figure", "layout", "kind", "title",
                                    "doc", "page")}, "in_latest": bool(b["in_latest"]), "reactions": b["n"]}
              for b in conn.execute("SELECT b.*, (SELECT count(*) FROM reactions r WHERE r.block_pk = b.block_pk"
                                    " AND r.deleted = 0 AND r.in_latest = 1) AS n FROM blocks b WHERE b.paper_id = ?"
                                    " ORDER BY b.doc, b.page, b.region_id, b.block_id", (paper_id,))]
    imports = [{**dict(r), "counts": db.loads(r["counts"])} for r in conn.execute(
        "SELECT ip.import_id, i.started_at, ip.outcome, ip.reason, ip.counts FROM import_papers ip"
        " JOIN imports i ON i.import_id = ip.import_id WHERE ip.paper_id = ? ORDER BY ip.import_id DESC",
        (paper_id,))]
    return {**{k: p[k] for k in PAPER_COLUMNS}, "context": db.loads(p["context"]), "documents": documents,
            "counts": _paper_counts(conn, paper_id).get(paper_id, _empty_counts()), "blocks": blocks,
            "imports": imports}


def paper_history(conn, paper_id) -> list:
    paper_id = str(paper_id)
    if conn.execute("SELECT 1 FROM papers WHERE paper_id = ?", (paper_id,)).fetchone() is None:
        raise NotFound(f"没有文献 {paper_id}")
    return _history(conn, "paper", paper_id)


def _paper_value(key, value):
    if value is None:
        return None
    if key == "year":
        return None if isinstance(value, str) and not value.strip() else _int(value, "年份")
    if not isinstance(value, str):
        raise BadRequest(f"{key} 应为字符串")
    return value.strip() or None


def update_paper(conn, paper_id, *, base_rev, fields: dict, author, comment=None) -> dict:
    """Edit a paper's bibliographic fields; from then on a re-import leaves them alone (meta_origin 'edited')."""
    author = _author(author)
    paper_id = str(paper_id)
    if not isinstance(fields, dict):
        raise BadRequest("fields 应为对象")
    unknown = sorted(set(fields) - set(PAPER_FIELDS))
    if unknown:
        raise BadRequest(f"不能修改的字段：{', '.join(unknown)}")
    with db.write(conn):
        p = conn.execute("SELECT * FROM papers WHERE paper_id = ?", (paper_id,)).fetchone()
        if p is None:
            raise NotFound(f"没有文献 {paper_id}")
        if _int(base_rev, "base_rev") != p["rev"]:
            raise Conflict(get_paper(conn, paper_id))
        old = {k: p[k] for k in PAPER_FIELDS}
        new = {**old, **{k: _paper_value(k, v) for k, v in fields.items()}}
        changes = diff(old, new)
        if not changes:
            return get_paper(conn, paper_id)
        rev, now = p["rev"] + 1, db.now_iso()
        db.insert_revision(conn, entity="paper", entity_id=paper_id, rev=rev, action="meta", author=author,
                           snapshot=new, diff=changes, comment=comment, base_rev=p["rev"], created_at=now)
        conn.execute(f"UPDATE papers SET {', '.join(f'{k} = ?' for k in PAPER_FIELDS)}, meta_origin = 'edited',"
                     " rev = ?, updated_at = ?, updated_by = ? WHERE paper_id = ?",
                     [*(new[k] for k in PAPER_FIELDS), rev, now, author, paper_id])
        return get_paper(conn, paper_id)


# ----------------------------------------------------------------------------- reactions: mutations

def _current(conn, rid, base_rev):
    """The row to change, provided it is no old version and the client saw its current rev."""
    row = _row(conn, rid)
    if row["superseded_by"] is not None:
        raise BadRequest(f"{display_id(rid)} 是旧版本：文献重新导入时已被导入批次 #{row['superseded_by']} 覆盖，只读"
                         "（可以复制成新的反应再改）")
    if _int(base_rev, "base_rev") != row["rev"]:
        raise Conflict(get_reaction(conn, rid))
    return row


def update(conn, rid, *, base_rev, data, author, comment=None) -> dict:
    """Save edited data. `reaction_id` stays the server's; errors the data had before the edit do not block."""
    author = _author(author)
    rid = _reaction_id(rid)
    with db.write(conn):
        row = _current(conn, rid, base_rev)
        state = state_of(row)
        if isinstance(data, dict):
            data = {**records.normalize(data),
                    "reaction_id": state["data"].get("reaction_id") if isinstance(state["data"], dict) else None}
        errors, warnings = records.validate(data, docs_for(conn, row["paper_id"]), base=state["data"])
        if errors:
            raise Invalid(errors, warnings)
        apply_state(conn, rid, {**state, "data": data}, action="edit", author=author, comment=comment,
                    base_rev=row["rev"])
        return {**get_reaction(conn, rid), "warnings": warnings}


def review(conn, rid, *, base_rev, status, note, author, comment=None) -> dict:
    author = _author(author)
    rid = _reaction_id(rid)
    if status not in REVIEW_STATUSES:
        raise BadRequest(f"未知的审核状态：{status}")
    if note is not None and not isinstance(note, str):
        raise BadRequest("审核备注应为字符串")
    with db.write(conn):
        row = _current(conn, rid, base_rev)
        apply_state(conn, rid, {**state_of(row), "review_status": status, "review_note": (note or "").strip() or None},
                    action="review", author=author, comment=comment, base_rev=row["rev"])
        return get_reaction(conn, rid)


def revert(conn, rid, *, base_rev, to_rev, author, comment=None) -> dict:
    """Bring back the data of an earlier revision, as a new revision; review state and deletion stay."""
    author = _author(author)
    rid = _reaction_id(rid)
    with db.write(conn):
        row = _current(conn, rid, base_rev)
        old = revision(conn, rid, to_rev)
        apply_state(conn, rid, {**state_of(row), "data": old["snapshot"]["data"]}, action="revert", author=author,
                    comment=comment, base_rev=row["rev"], target_rev=old["rev"])
        return get_reaction(conn, rid)


def _set_deleted(conn, rid, base_rev, author, comment, deleted: bool) -> dict:
    author = _author(author)
    rid = _reaction_id(rid)
    with db.write(conn):
        row = _current(conn, rid, base_rev)
        apply_state(conn, rid, {**state_of(row), "deleted": deleted}, action="delete" if deleted else "restore",
                    author=author, comment=comment, base_rev=row["rev"])
        return get_reaction(conn, rid)


def delete(conn, rid, *, base_rev, author, comment=None) -> dict:
    """Mark a reaction deleted (nothing is removed; the list hides it by default)."""
    return _set_deleted(conn, rid, base_rev, author, comment, True)


def restore(conn, rid, *, base_rev, author, comment=None) -> dict:
    return _set_deleted(conn, rid, base_rev, author, comment, False)


def copy(conn, rid, *, author, comment=None) -> dict:
    """A new reaction with the data of `rid` as it is now, not linked to the pipeline (no origin id)."""
    author = _author(author)
    rid = _reaction_id(rid)
    with db.write(conn):
        row = _row(conn, rid)
        data = db.loads(row["data"])
        if isinstance(data, dict):
            data["reaction_id"] = None
            if isinstance(data.get("source"), dict):
                data["source"]["reaction_id"] = None
        new = insert_reaction(conn, paper_id=row["paper_id"], block_pk=row["block_pk"], origin_id=None, data=data,
                              action="copy", author=author,
                              comment=comment or f"复制自 {display_id(rid)}（第 {row['rev']} 版）",
                              copied_from=rid, touched=True)
        return get_reaction(conn, new)


def create(conn, *, paper_id, block_pk=None, entry_id=None, author, comment=None) -> dict:
    """A reaction added by hand: an empty record whose source is the block (and entry) it was added to."""
    author = _author(author)
    paper_id = str(paper_id)
    block_pk = None if block_pk in (None, "") else _int(block_pk, "block_pk")
    entry_id = entry_id or None
    with db.write(conn):
        if conn.execute("SELECT 1 FROM papers WHERE paper_id = ?", (paper_id,)).fetchone() is None:
            raise NotFound(f"没有文献 {paper_id}")
        source, kind = None, None
        if block_pk is not None:
            b = conn.execute("SELECT * FROM blocks WHERE block_pk = ?", (block_pk,)).fetchone()
            if b is None:
                raise NotFound(f"没有 block {block_pk}")
            if b["paper_id"] != paper_id:
                raise BadRequest(f"block {block_pk} 不属于文献 {paper_id}")
            region = db.loads(b["region"]) or {}
            source = {"doc": b["doc"], "page": b["page"], "figure": b["figure"], "caption": region.get("caption"),
                      "region_id": b["region_id"], "block_id": b["block_id"]}
            kind = b["kind"]
            if entry_id is not None:
                entries = (db.loads(b["view"]) or {}).get("entries") or []
                e = next((e for e in entries if isinstance(e, dict) and e.get("eid") == entry_id), None)
                if e is None:
                    raise NotFound(f"block {block_pk} 里没有条目 {entry_id}")
                source.update(entry_id=entry_id, page=e.get("page") or b["page"], entry_bbox=e.get("bbox"))
        elif entry_id is not None:
            raise BadRequest("指定条目时也要指定 block")
        new = insert_reaction(conn, paper_id=paper_id, block_pk=block_pk, origin_id=None,
                              data=records.skeleton(source=source, kind=kind), action="create", author=author,
                              comment=comment, touched=True)
        return get_reaction(conn, new)


def _settle_pending(conn, rid, base_rev, author, comment, accept: bool) -> dict:
    author = _author(author)
    rid = _reaction_id(rid)
    with db.write(conn):
        row = _current(conn, rid, base_rev)
        if row["pending_sha"] is None:
            raise BadRequest(f"{display_id(rid)} 没有待采用的流水线新版本")
        state, pending = state_of(row), db.loads(row["pending_data"])
        if accept:
            state["data"] = pending
        # Logged even when the data does not change: the decision is what the revision records, and from
        # now on that pipeline version is the one the reaction is compared with (and not offered again).
        # A dismissed version is kept in the revision: `edited` and the diff against the pipeline need it.
        apply_state(conn, rid, state, action="accept_import" if accept else "dismiss_import", author=author,
                    comment=comment, import_id=row["pending_import"], base_rev=row["rev"], force=True,
                    extra={"pipeline_sha": row["pending_sha"], "pending_data": None, "pending_sha": None,
                           "pending_import": None},
                    kept=None if accept else {"dismissed": {"sha": row["pending_sha"], "data": pending}})
        return get_reaction(conn, rid)


def accept_pending(conn, rid, *, base_rev, author, comment=None) -> dict:
    """Take the newer pipeline version the import held back (the reaction had been touched)."""
    return _settle_pending(conn, rid, base_rev, author, comment, True)


def dismiss_pending(conn, rid, *, base_rev, author, comment=None) -> dict:
    """Keep the current data and stop offering that pipeline version."""
    return _settle_pending(conn, rid, base_rev, author, comment, False)
