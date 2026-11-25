"""What leaves the curator: one reaction as JSON, a set as JSON Lines, or a ZIP with a file per reaction.

An exported reaction is the stored record (the pipeline's shape, without crop paths) wrapped with what
the database knows about it: its id, the paper, the review, and where it came from. Batch exports leave
out excluded and deleted reactions unless asked, and list reactions in printed order (sort_key). The ZIP
can carry pictures of the structures, rendered from the stored PDFs at the boxes the record holds now,
so nothing of work/ or Data/ is needed.
"""

from __future__ import annotations

import json
import re
import zipfile

from . import db, pdfdocs, records, store
from .config import display_id

IMAGE_DPI = 200
IMAGE_PAD = 0.0  # pt around a box; the pipeline's boxes are already trimmed to their ink


def _id(value) -> int | None:
    """A reaction id as given: 123, "123" or "R000123" (store._parse_id)."""
    return store._parse_id(value)


def _pipeline(ref: dict | None) -> dict | None:
    """An import as an exported record names it: when, at which commit, and per pipeline step its version,
    when it finished and the model it ran with (store._import_ref holds more)."""
    if ref is None:
        return None
    steps = ref.get("steps") if isinstance(ref.get("steps"), dict) else {}

    def step(s: dict) -> dict:
        params = s.get("params") if isinstance(s.get("params"), dict) else {}
        return {"version": s.get("version"), "finished_at": s.get("finished_at"), "codex": params.get("codex")}
    return {"import_id": ref["import_id"], "imported_at": ref["started_at"], "repo_commit": ref["repo_commit"],
            "repo_dirty": ref["repo_dirty"],
            "steps": {name: step(s) for name, s in steps.items() if isinstance(s, dict)}}


def export_record(conn, rid) -> dict:
    """{id, paper, review, provenance, record} of one reaction (store.NotFound if there is none). Besides
    the review, `review.deleted` (an export that includes deleted reactions keeps them apart); besides
    where it is printed, `provenance.data_import`: the import (pipeline versions and model) the data
    comes from, and `provenance.pending`: whether a newer pipeline version waits for a decision."""
    n = _id(rid)
    r = None if n is None else conn.execute(
        f"SELECT r.*, {store.EDITED_SQL} AS edited, p.title, p.authors, p.journal, p.year, p.doi,"
        " b.region_id AS b_region, b.block_id AS b_block, b.figure AS b_figure"
        " FROM reactions r JOIN papers p ON p.paper_id = r.paper_id"
        " LEFT JOIN blocks b ON b.block_pk = r.block_pk WHERE r.id = ?", (n,)).fetchone()
    if r is None:
        raise store.NotFound(f"没有反应 {rid}")
    data = db.loads(r["data"])
    source = data.get("source") if isinstance(data, dict) and isinstance(data.get("source"), dict) else {}
    # Where it came from: the block it was imported (or created) in; a reaction without a block keeps
    # what its record says.
    block = r["block_pk"] is not None
    return {
        "id": display_id(r["id"]),
        "paper": {k: r[k] for k in ("paper_id", "title", "authors", "journal", "year", "doi")},
        "review": {"status": r["review_status"], "note": r["review_note"], "deleted": bool(r["deleted"])},
        "provenance": {"origin_id": r["origin_id"],
                       "region_id": r["b_region"] if block else source.get("region_id"),
                       "block_id": r["b_block"] if block else source.get("block_id"),
                       "figure": (r["b_figure"] if block else None) or r["figure"],
                       "layout": r["layout"], "first_import": r["first_import"], "last_import": r["last_import"],
                       "rev": r["rev"], "edited": bool(r["edited"]), "updated_at": r["updated_at"],
                       "updated_by": r["updated_by"],
                       "copied_from": None if r["copied_from"] is None else display_id(r["copied_from"]),
                       "pending": r["pending_sha"] is not None,
                       # an old version: the import that replaced its paper's reactions
                       "superseded_by": r["superseded_by"],
                       "data_import": _pipeline(store._import_ref(conn, store.data_import(conn, r["id"]),
                                                                  r["paper_id"]))},
        "record": data,
    }


def select_ids(conn, params=None, ids=None, include_excluded=False, include_deleted=False) -> list[int]:
    """The reactions a batch export takes, in printed order: those `params` (the list's filters; paging
    and sort are ignored) and `ids` (if given) both select. Excluded and deleted ones only when asked."""
    params = dict(params or {})
    if include_deleted and not str(params.get("deleted") or "").strip():
        params["deleted"] = "all"
    if ids is not None and not str(params.get("latest") or "").strip():
        params["latest"] = "all"  # reactions picked one by one may be old versions (chosen in the archive)
    where, args = store.filter_clause(params)
    clauses = [f"({where})"]
    if ids is not None:
        if isinstance(ids, (str, int)):
            ids = [ids]
        parsed = [_id(i) for i in ids]
        if None in parsed:
            raise store.BadRequest(f"ids 的取值不对：{[i for i, p in zip(ids, parsed) if p is None]!r}")
        if not parsed:
            return []
        clauses.append(f"id IN ({', '.join('?' * len(parsed))})")
        args = [*args, *parsed]
    if not include_excluded:
        clauses.append("review_status != 'excluded'")
    if not include_deleted:
        clauses.append("deleted = 0")
    # Auxiliary preparations remain individually exportable and explicitly selectable by their flag.
    if ids is None and "auxiliary" not in str(params.get("flag") or "").split(","):
        clauses.append("(' ' || flags || ' ') NOT LIKE '% auxiliary %'")
    return [r[0] for r in conn.execute(f"SELECT id FROM reactions WHERE {' AND '.join(clauses)}"
                                       " ORDER BY sort_key, id", args)]


def _json(obj, indent=None) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=indent).encode("utf-8")


def write_jsonl(conn, ids, fp) -> int:
    """One exported reaction per line, UTF-8, to the binary file `fp`; returns how many."""
    n = 0
    for rid in ids:
        fp.write(_json(export_record(conn, rid)) + b"\n")
        n += 1
    return n


# ----------------------------------------------------------------------------- ZIP

def _structures(owner: dict, *lists: str) -> list[dict]:
    """The drawn structures of the items in owner's lists (alternatives, a preparation's items), each
    named by its own key, else by the owner's."""
    out = []
    for name in lists:
        items = owner.get(name) if isinstance(owner.get(name), list) else []
        for s in [x.get("structure") for x in items if isinstance(x, dict)]:
            if isinstance(s, dict):
                out.append({**s, "key": s.get("key") or owner.get("key")})
    return out


def _boxed(data, with_doc=False) -> list[tuple]:
    """(key, page, bbox) of everything the record draws: participants and the structures of their
    alternatives, the compounds a preparation starts from and the structures of its items, and the
    structures of conditions (and of their alternatives)."""
    items = []
    for p in records.participants(data):
        items.append(p)
        items += _structures(p, "alternatives")
        prep = p.get("preparation")
        if isinstance(prep, dict):
            items += [f for f in prep["from"] if isinstance(f, dict)] if isinstance(prep.get("from"), list) else []
            items += _structures({**prep, "key": p.get("key")}, "items")
    steps = data.get("steps") if isinstance(data, dict) and isinstance(data.get("steps"), list) else []
    conditions = [c for st in steps if isinstance(st, dict) and isinstance(st.get("conditions"), list)
                  for c in st["conditions"]]
    conditions += data.get("conditions") if isinstance(data, dict) and isinstance(data.get("conditions"), list) else []
    for c in conditions:
        if not isinstance(c, dict):
            continue
        if isinstance(c.get("structure"), dict):
            items.append({**c["structure"], "key": c["structure"].get("key") or c.get("key")})
        items += _structures(c, "alternatives")
    out = []
    for x in items:
        bbox = x.get("bbox")
        if x.get("page") is not None and isinstance(bbox, list) and len(bbox) == 4:
            item = (str(x.get("key") or "item"), x["page"], bbox)
            out.append((x.get("doc", (data.get("source") or {}).get("doc")), *item) if with_doc else item)
    return out


def _file_name(key: str) -> str:
    """A key as a file name: no path separators, control or reserved characters, no leading dot."""
    return re.sub(r'[\x00-\x1f\\/:*?"<>|\s]+', "_", key).strip("._") or "item"


def _images(conn, z: zipfile.ZipFile, rec: dict, doc_ids: dict, errors: list) -> list[dict]:
    """Render and add images/<id>/<key>.png for every boxed item of one exported reaction."""
    source = rec["record"].get("source") if isinstance(rec["record"], dict) else None
    doc = source.get("doc") if isinstance(source, dict) else None
    seen, out = set(), []
    boxes = _boxed(rec["record"], with_doc=True)
    review = rec["record"].get("review") or {}
    boxes += [(e.get("doc"), e.get("id", "evidence"), e.get("page"), e["bbox"])
              for e in review.get("evidence", []) if isinstance(e, dict) and isinstance(e.get("bbox"), list)]
    for doc, key, page, bbox in boxes:
        if (doc, key, repr(page), repr(bbox)) in seen:
            continue
        seen.add((doc, key, repr(page), repr(bbox)))
        taken = {x["file"] for x in out}
        path, n = f"images/{rec['id']}/{_file_name(key)}.png", 1
        while path in taken:  # two boxes under one key, or keys that differ only in removed characters
            n += 1
            path = f"images/{rec['id']}/{_file_name(key)}-{n}.png"
        try:
            if doc not in doc_ids:
                raise LookupError(f"文档 {doc!r} 不在库里")
            png, _ = pdfdocs.render_png(conn, doc_ids[doc], page, bbox, dpi=IMAGE_DPI, pad=IMAGE_PAD)
        except (LookupError, ValueError) as e:
            errors.append({"id": rec["id"], "key": key, "page": page, "bbox": bbox, "error": str(e)})
            continue
        z.writestr(path, png, compress_type=zipfile.ZIP_STORED)  # PNG is compressed already
        item = {"key": key, "page": page, "bbox": bbox, "file": path}
        item["doc"] = doc
        out.append(item)
    return out


def write_zip(conn, ids, fp, images=False, *, filter=None) -> int:
    """A ZIP to `fp`: manifest.json and reactions/<id>.json per reaction; with `images`, the structures
    as images/<id>/<key>.png at IMAGE_DPI (the manifest lists them, and the boxes that could not be
    rendered). `filter`: the filters the set was chosen by, kept in the manifest. Returns how many."""
    manifest = {"created_at": db.now_iso(), "count": 0, "ids": []}
    if filter is not None:
        manifest["filter"] = filter
    pictures, errors = {}, []
    doc_ids: dict[str, dict] = {}
    with zipfile.ZipFile(fp, "w", zipfile.ZIP_DEFLATED) as z:
        for rid in ids:
            rec = export_record(conn, rid)
            z.writestr(f"reactions/{rec['id']}.json", _json(rec, indent=2))
            manifest["ids"].append(rec["id"])
            if images:
                pid = rec["paper"]["paper_id"]
                if pid not in doc_ids:
                    doc_ids[pid] = {r["doc"]: r["doc_id"] for r in conn.execute(
                        "SELECT doc, doc_id FROM documents WHERE paper_id = ?", (pid,))}
                pictures[rec["id"]] = _images(conn, z, rec, doc_ids[pid], errors)
        manifest["count"] = len(manifest["ids"])
        if images:
            manifest.update(images=pictures, image_errors=errors)
        z.writestr("manifest.json", _json(manifest, indent=2))
    return manifest["count"]
