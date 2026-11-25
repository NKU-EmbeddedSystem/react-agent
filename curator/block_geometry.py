"""Audited source-block geometry overlays, leaving imported source views immutable."""
import copy
import math


def apply(view, correction, docs, doc):
    if set(correction) - {"reason", "entries", "participants", "scheme", "notes", "shared_regions"}:
        raise ValueError("unsupported block correction fields")
    result = copy.deepcopy(view)
    entries = {e["eid"]: e for e in result.get("entries", [])}
    rows = correction.get("entries", [])
    if not correction.get("reason") or not rows:
        raise ValueError("block geometry correction requires reason and entries")
    if len(rows) != len(entries) or {e["eid"] for e in rows} != set(entries):
        raise ValueError("block geometry correction must cover every entry exactly once")

    def box(page, bbox):
        pages = docs[doc]["pages"]
        if not isinstance(page, int) or not 1 <= page <= len(pages):
            raise ValueError("invalid block geometry page")
        w, h = pages[page - 1][:2]
        if (len(bbox) != 4 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in bbox)
                or not (0 <= bbox[0] < bbox[2] <= w and 0 <= bbox[1] < bbox[3] <= h)):
            raise ValueError("invalid block geometry bbox")

    for row in rows:
        if set(row) - {"eid", "page", "bbox", "note"}:
            raise ValueError("only geometry and source-reading notes may change")
        box(row["page"], row["bbox"])
        entry = entries[row["eid"]]
        entry.update(page=row["page"], bbox=row["bbox"], geometry_note=row.get("note", ""))
    # Distinct table rows may not share vertical space. Shared definitions belong to a separate layer.
    if result.get("block", {}).get("layout") == "condition_table":
        ordered = sorted(entries.values(), key=lambda e: (e["page"], e["bbox"][1]))
        for a, b in zip(ordered, ordered[1:]):
            if a["page"] == b["page"] and a["bbox"][3] > b["bbox"][1]:
                raise ValueError("corrected table row boxes overlap")
    participants = {p["key"]: p for p in result.get("template", {}).get("participants", [])}
    for part in correction.get("participants", []):
        if set(part) != {"key", "page", "bbox"} or part["key"] not in participants:
            raise ValueError("invalid participant geometry target")
        box(part["page"], part["bbox"])
        participants[part["key"]].update(page=part["page"], bbox=part["bbox"])
    if correction.get("scheme"):
        s = correction["scheme"]
        if set(s) != {"page", "bbox"}:
            raise ValueError("invalid scheme geometry")
        box(s["page"], s["bbox"])
        result["template"]["scheme"] = copy.deepcopy(s)
    shared = correction.get("shared_regions", [])
    for region in shared:
        if set(region) != {"page", "bbox", "label"}:
            raise ValueError("invalid shared definition region")
        box(region["page"], region["bbox"])
    result["shared_geometry_regions"] = copy.deepcopy(shared)
    result["geometry_correction"] = {"reason": correction["reason"], "method": "visual-review",
                                       "notes": correction.get("notes", "")}
    return result


def save(conn, block_pk, correction, *, author, base_sha):
    from . import db, store
    with db.write(conn):
        block = conn.execute("SELECT * FROM blocks WHERE block_pk = ?", (block_pk,)).fetchone()
        if block is None or not block["in_latest"]:
            raise ValueError("source block is not current")
        if db.sha_json(db.loads(block["view"])) != base_sha:
            raise ValueError("source block changed; re-read before correcting")
        apply(db.loads(block["view"]), correction, store.docs_for(conn, block["paper_id"]), block["doc"])
        row = conn.execute("SELECT * FROM reactions WHERE block_pk=? AND in_latest=1 AND deleted=0 ORDER BY id LIMIT 1",
                           (block_pk,)).fetchone()
        if row is None:
            raise ValueError("block has no current reaction for an audit revision")
        return store.apply_state(conn, row["id"], store.state_of(row), action="edit", author=author,
                                 comment="来源块几何校正：" + correction["reason"], force=True,
                                 kept={"block_geometry": {"block_pk": block_pk, "base_sha": base_sha,
                                                          "correction": correction}})


def effective(conn, block, view):
    from . import db, store
    row = conn.execute("SELECT snapshot, rev_id, author, created_at FROM revisions WHERE entity='reaction' "
                       "AND json_extract(snapshot, '$.block_geometry.block_pk')=? ORDER BY rev_id DESC LIMIT 1",
                       (block["block_pk"],)).fetchone()
    if row is None:
        return view
    saved = db.loads(row["snapshot"])["block_geometry"]
    if saved["base_sha"] != db.sha_json(view):
        return view  # a re-import is a different source; do not silently apply an old overlay
    result = apply(view, saved["correction"], store.docs_for(conn, block["paper_id"]), block["doc"])
    result["geometry_correction"].update(revision_id=row["rev_id"], author=row["author"], created_at=row["created_at"])
    return result
