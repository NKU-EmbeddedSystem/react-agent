"""The Step 2 results as a viewer reads them.

  step2/index.json                one line per block: what it is, how far it got, a revision stamp
  step2/blocks/<slug>/view.json   the block in full: template, entries, their reactions and records

Built from the views `publish()` gathers from disk. Everything a page needs is spelled out
(states, counts, crop paths relative to step2/), so a viewer never has to know how the pipeline
names its files. Nothing here renders anything.
"""

from __future__ import annotations

import hashlib
import json

REGION_KEYS = ("region_id", "doc", "label", "caption", "kind", "presentation", "footnotes",
               "first_page", "last_page", "notes")
BLOCK_KEYS = ("block_id", "title", "kind", "layout", "page", "bbox", "scheme_id", "general_reaction",
              "conditions_text", "n_entries_est", "labels_seen", "entries_first_page",
              "entries_last_page", "notes")


def _draft(template: dict, reaction: dict, protocol: dict, crops: dict, structures: dict) -> dict:
    """A reaction whose own session has not finished, laid out like a record: the template as
    merged for it (variant, footnotes, the row's changes), with the generic drawings. The row's
    variables are listed for the reaction as a whole: which compound carries one is not known here
    (a leaving group "X = Cl" is on a reactant only, not on the product)."""
    steps = protocol["steps"] or [{"n": 1, "description": "", "reactants": [], "products": []}]
    multi = len(steps) > 1

    def part(x, product=False):
        # The product is reported under the reaction's own number in the figure, not the scheme's "3–40".
        return {"key": x["key"], "role": x["role"], "text": x["text"], "generic": x["generic"],
                "label": (reaction["label"] or x["label"]) if product else x["label"],
                "amount": x["amount"], "amount_origin": x.get("amount_origin", x["origin"]) if x["amount"] else None,
                "crop": crops.get(x["key"]), "variables": []}

    def cond(c):
        return {**{k: c.get(k) for k in ("key", "role", "text", "amount", "origin", "stated_at", "inferred")},
                "structure": structures.get(c["structure_key"]),
                "alternatives": [{"text": a["text"], "structure": structures.get(a["structure_key"])}
                                 for a in c["alternatives"]]}

    out = []
    for i, st in enumerate(steps):
        last = i == len(steps) - 1
        mine = [c for c in protocol["conditions"]
                if c["step"] == st["n"] or (c["step"] is None and (not multi or last))]
        out.append({"step": i + 1, "description": st["description"],
                    "reactants": [part(x) for x in st["reactants"]],
                    "products": [part(x, product=last) for x in st["products"]],
                    "conditions": [cond(c) for c in mine]})
    v = next((v for v in template["variants"] if v["key"] == reaction["variant"]), None)
    return {"variant": {"key": v["key"], "title": v["title"], "notes": v["notes"]} if v else None,
            "conditions_given": v.get("conditions_given", True) if v else True,
            "variables": [{"name": x["name"], "value": x["value"]} for x in reaction["variables"]],
            "steps": out}


def _flags(rv: dict) -> list[str]:
    """What makes a reaction worth a second look: `inferred` (something in it is a conclusion),
    `unresolved` (the source leaves a choice open), `issues` (errors, warnings, doubts)."""
    rec = rv["record"]
    flags = []
    if rec:
        parts = [p for st in rec["steps"] for p in st["reactants"] + st["products"]]
        if rec["inferences"] or any(p.get("inferred") for p in parts):
            flags.append("inferred")
        if rec["unresolved"] or any(p.get("undecided_with") for p in parts):
            flags.append("unresolved")
    if rv["errors"] or rv["warnings"] or (rec and rec["issues"]):
        flags.append("issues")
    return flags


def block_view(view: dict) -> dict:
    """view.json of one block. `view` is what publish() gathered: region, block, slug, status, meta,
    template, template_crops, structure_crops, ignored, notes and the entries with their reactions."""
    region, block, meta = view["region"], view["block"], view["meta"]
    template, structures = None, {}

    def with_crops(t: dict) -> dict:
        return {**t,
                "participants": [{**p, "crop": view["template_crops"].get(p["key"])} for p in t["participants"]],
                "structures": [{**x, "crop": view["structure_crops"].get(x["key"])} for x in t["structures"]]}

    if view["template"]:
        template = with_crops(view["template"])
        structures = {x["key"]: x for x in template["structures"]}
    # Equation blocks and prose passages: every equation or experiment has a template of its own (the
    # block's lists the compounds).
    own = {key: [{**eq, "template": with_crops(eq["template"])} for eq in view[key]]
           for key in ("equations", "experiments") if key in view}

    entries = []
    for ev in view["entries"]:
        exp = ev["expansion"]
        reactions = []
        for rv in ev["reactions"]:
            r = rv["reaction"]
            reactions.append({
                "rid": r["rid"], "label": r["label"], "status": rv["status"],
                "errors": rv["errors"], "warnings": rv["warnings"], "seconds": rv["seconds"],
                "variant": r["variant"], "footnote_markers": r["footnote_markers"],
                # As printed; the reaction's own session splits them into values and types.
                "results_text": r["results_text"],
                "flags": _flags(rv),
                "record": rv["record"],
                "draft": None if rv["record"] else _draft(rv.get("template") or view["template"], r, rv["protocol"],
                                                         view["template_crops"], structures),
            })
        entries.append({
            **{k: ev["entry"][k] for k in ("eid", "label", "page", "bbox", "descriptor")},
            "crop": ev["crop"], "status": ev["status"], "errors": ev["errors"], "warnings": ev["warnings"],
            "expansion": {k: exp[k] for k in ("printed", "results", "reasoning", "issues")} if exp else None,
            "reactions": reactions,
        })
    return {
        "slug": view["slug"], "ref": f"{region['region_id']}/{block['block_id']}", "status": view["status"],
        "errors": meta.get("errors", []),
        # A value measured on a starting material is now recorded as `recovered_starting_material`;
        # the old column-level note is not repeated as a block warning.
        "warnings": [w for w in meta.get("warnings", []) if "is not a product or byproduct" not in w],
        "seconds": meta.get("seconds"),
        "region": {k: region.get(k) for k in REGION_KEYS},
        "block": {k: block.get(k) for k in BLOCK_KEYS},
        "template": template,
        **own,
        # What a passage says that is no experiment of its own.
        **({"set_aside": view["set_aside"]} if view.get("set_aside") else {}),
        "ignored": view["ignored"], "notes": view["notes"],
        "entries": entries,
    }


def block_head(data: dict) -> dict:
    """The block's line in index.json, from its view.json."""
    entries = data["entries"]
    reactions = [r for e in entries for r in e["reactions"]]
    count = lambda items, status: sum(x["status"] == status for x in items)
    flagged = lambda flag: sum(flag in r["flags"] for r in reactions)
    return {
        "slug": data["slug"], "ref": data["ref"],
        "region_id": data["region"]["region_id"], "block_id": data["block"]["block_id"],
        "figure": data["region"]["label"], "title": data["block"]["title"], "kind": data["block"]["kind"],
        "doc": data["region"]["doc"], "page": data["block"]["page"],
        "status": data["status"],
        "entries": {"listed": len(entries), "ok": count(entries, "ok"), "failed": count(entries, "failed"),
                    "skipped": count(entries, "skipped")},
        "reactions": {"listed": len(reactions), "ok": count(reactions, "ok"), "failed": count(reactions, "failed"),
                      "inferred": flagged("inferred"), "unresolved": flagged("unresolved"),
                      "issues": flagged("issues")},
        # Changes whenever view.json does: a viewer reloads the block only then.
        "rev": hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12],
    }


def index(paper_id: str, paper: dict, summary: dict, heads: list[dict]) -> dict:
    return {"paper_id": paper_id, "paper": paper, "summary": summary, "blocks": heads}
