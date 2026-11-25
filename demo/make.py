"""Build the public demo: a synthetic one-page paper, its SI, and an importable work dir.

    python -m demo.make                # -> <repo>/demo-data/
    python -m demo.make /tmp/demo      # -> /tmp/demo/

Five entries are adapted from a published iron-catalysed C(sp3)-C(sp3) coupling study used during
development: their labels, isolated yields, conditions and product names. No page, text, spectrum
or image of that article is copied. The page and the SI are laid out here with PyMuPDF, and every
structure is redrawn from the recorded product name with RDKit. Nothing here calls a model.

What it writes:

    <root>/Data/1/<main>.pdf, SI-<main>.pdf
    <root>/work/1/paper.json, main/, si/, step1/, step2/
    <root>/build/img/                            the structures used on the main page

The whole tree is git-ignored: regenerate it at any time, then import it with
    python -m curator --db demo-data/db/curator.sqlite import --work demo-data/work
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops
from rdkit import Chem
from rdkit.Chem import Draw

DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "demo-data"
PAGE_W, PAGE_H = 595.0, 842.0

MAIN_NAME = "Demo et al. - J. Demo Chem. - 2026 - Iron-Catalysed Alkylation of N-Benzyl Amides.pdf"
SI_NAME = "SI-" + MAIN_NAME

# (label, product name, SMILES, isolated yield %, time)
ENTRIES = [
    ("3at", "N-benzylpivalamide", "CC(C)(C)C(=O)NCc1ccccc1", 80, "6 h"),
    ("3au", "N-benzyl-2,2-dimethylbutanamide", "CCC(C)(C)C(=O)NCc1ccccc1", 71, "6 h"),
    ("3aw", "N-benzyl-2,2-dimethyl-3-phenylpropanamide", "O=C(NCc1ccccc1)C(C)(C)Cc1ccccc1", 56, "6 h"),
    ("3az", "N-benzyl-2-methyl-2-phenylpropanamide", "CC(C)(c1ccccc1)C(=O)NCc1ccccc1", 66, "6 h"),
    ("3aag", "N-benzyl-2-cyclopentylacetamide", "O=C(NCc1ccccc1)CC1CCCC1", 69, "24 h"),
]
CONDITIONS = [
    ("cat", "catalyst", "Fe(BF-Phos)Cl2", "0.5 mol%"),
    ("additive1", "additive", "ZnCl2", "1.0 equiv"),
    ("additive2", "additive", "LiCl", "1.0 equiv"),
    ("solvent", "solvent", "THF", "2 mL"),
    ("temperature", "temperature", "22-25 °C", None),
    ("atmosphere", "atmosphere", "argon", None),
]

# ---------------------------------------------------------------- RDKit pictures

def _mol(smiles: str):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"bad SMILES: {smiles}")
    return mol


def _label_dummies(mol, labels=("R1", "R2", "R3")):
    i = 0
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() == 0:
            atom.SetProp("atomLabel", labels[min(i, len(labels) - 1)])
            i += 1
    return mol


def _trim(path: Path) -> tuple[int, int]:
    img = Image.open(path).convert("RGB")
    bg = Image.new("RGB", img.size, (255, 255, 255))
    box = ImageChops.difference(img, bg).getbbox()
    if box:
        pad = 8
        box = (max(0, box[0] - pad), max(0, box[1] - pad),
               min(img.width, box[2] + pad), min(img.height, box[3] + pad))
        img = img.crop(box)
        img.save(path)
    return img.size


def molecule(img: Path, name: str, smiles: str, labels=("R1", "R2", "R3")) -> tuple[Path, tuple[int, int]]:
    path = img / f"{name}.png"
    Draw.MolToImage(_label_dummies(_mol(smiles), labels), size=(900, 520)).save(path)
    return path, _trim(path)


# ---------------------------------------------------------------- PDF helpers

def _fit(box, size):
    x0, y0, x1, y1 = box
    iw, ih = size
    scale = min((x1 - x0) / iw, (y1 - y0) / ih)
    w, h = iw * scale, ih * scale
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]


def _picture(page, box, path, size):
    rect = pymupdf.Rect(_fit(box, size))
    page.insert_image(rect, filename=str(path), keep_proportion=True)
    return [round(v, 1) for v in rect]


def _text(page, x, y, text, size=8.0, font="helv", color=(0, 0, 0)):
    page.insert_text((x, y), text, fontname=font, fontsize=size, color=color)


def _wrap(text, size, width, font="helv"):
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if pymupdf.get_text_length(trial, fontname=font, fontsize=size) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _rule(page, y, x0=45, x1=550, color=(0.72, 0.72, 0.72), width=0.6):
    page.draw_line((x0, y), (x1, y), color=color, width=width)


def main_pdf(img: Path) -> tuple[pymupdf.Document, dict]:
    img.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    structs = {}
    boxes = {}

    # header
    _text(page, 45, 38, "DEMO PAGE  ·  assembled from five extracted records  ·  not a published article", 6.3, color=(0.45, 0.45, 0.45))
    _text(page, 45, 62, "Iron-Catalysed alpha-Alkylation of N-Benzyl Amides", 15.5, font="hebo")
    _text(page, 45, 80, "A small demo page for the layered extraction platform", 9.0, color=(0.25, 0.25, 0.25))
    _text(page, 45, 93, "Demo Authors  ·  Demo Institute of Chemistry  ·  demo@example.org", 7.4, color=(0.35, 0.35, 0.35))
    _rule(page, 103)

    # abstract
    _text(page, 45, 120, "Abstract", 8.6, font="hebo")
    abstract = ("Five entries of an iron-catalysed coupling of alpha-bromoamides with organozinc reagents are "
                "shown to exercise the extraction-and-review interface. Product structures are redrawn from the "
                "recorded product names; conditions and isolated yields are the recorded values.")
    y = 133
    for line in _wrap(abstract, 7.4, 505):
        _text(page, 45, y, line, 7.4)
        y += 9.6

    # scheme
    _text(page, 45, 190, "Scheme 1", 8.6, font="hebo")
    page.draw_rect(pymupdf.Rect(45, 198, 550, 340), color=(0.82, 0.82, 0.82), width=0.6)
    r1, r1_size = molecule(img, "reactant1", "O=C(NCc1ccccc1)C([*:1])([*:2])Br", ("R1", "R2"))
    p1, p1_size = molecule(img, "product_generic", "O=C(NCc1ccccc1)C([*:1])([*:2])[*:3]")
    boxes["reactant1"] = _picture(page, [60, 210, 185, 315], r1, r1_size)
    boxes["generic_product"] = _picture(page, [410, 210, 535, 315], p1, p1_size)
    _text(page, 110, 326, "1", 8.0)
    _text(page, 224, 268, "+", 12.0)
    _text(page, 240, 266, "R3-ZnBr", 9.0)
    _text(page, 248, 326, "2", 8.0)
    page.draw_line((295, 266), (395, 266), width=1.1)
    page.draw_polyline([(388, 261.5), (395, 266), (388, 270.5)], color=(0, 0, 0), width=1.1)
    _text(page, 296, 238, "Fe(BF-Phos)Cl2 (0.5 mol%)", 6.2)
    _text(page, 296, 248, "ZnCl2 (1.0 equiv), LiCl (1.0 equiv)", 6.2)
    _text(page, 296, 294, "THF, 22-25 °C, 6-24 h, Ar", 6.2)
    _text(page, 470, 326, "3", 8.0)
    _text(page, 45, 354, "Scheme 1. Iron-catalysed alpha-alkylation of N-benzyl amides; R1-R3 as defined in Table 1.", 7.2)

    # table
    _text(page, 45, 382, "Table 1", 8.6, font="hebo")
    _text(page, 95, 382, "Substrate scope. Conditions as in Scheme 1; isolated yields.", 7.2)
    cols = (45, 100, 255, 295, 550)
    top = 394
    page.draw_rect(pymupdf.Rect(45, top, 550, top + 18), color=(0.55, 0.55, 0.55), width=0.6, fill=(0.94, 0.95, 0.97))
    for x, label in ((52, "Entry"), (108, "Product"), (262, "Yield"), (303, "Conditions")):
        _text(page, x, top + 12, label, 7.0, font="hebo")

    row_h = 24 + 46  # placed below
    entries = []
    y0 = top + 18
    for i, (label, name, smiles, yield_pct, hours) in enumerate(ENTRIES):
        y0 = top + 18 + i * 66
        path, size = molecule(img, f"product_{label}", smiles, ())
        product_box = _picture(page, [105, y0 + 6, 245, y0 + 60], path, size)
        _text(page, 54, y0 + 31, str(i + 1), 8.2)
        _text(page, 54, y0 + 43, label, 6.6, color=(0.35, 0.35, 0.35))
        _text(page, 262, y0 + 37, f"{yield_pct}%", 9.0, font="hebo")
        cond = ("Fe(BF-Phos)Cl2 (0.5 mol%), ZnCl2 (1.0 equiv), "
                f"LiCl (1.0 equiv), THF, 22-25 °C, {hours}, Ar")
        lines = _wrap(cond, 6.3, 238)
        for j, line in enumerate(lines[:4]):
            _text(page, 303, y0 + 18 + j * 8.0, line, 6.3)
        _text(page, 303, y0 + 18 + len(lines[:4]) * 8.0 + 4, name, 6.0, color=(0.38, 0.38, 0.38))
        entries.append({"label": label, "name": name, "yield": yield_pct, "hours": hours,
                        "row": [45, y0, 550, y0 + 66], "product": product_box})
        _rule(page, y0 + 66, color=(0.82, 0.82, 0.82))

    for x in (100, 255, 295):
        page.draw_line((x, top), (x, top + 18 + 5 * 66), color=(0.78, 0.78, 0.78), width=0.5)

    _text(page, 45, 790, "Structures were redrawn from the recorded product names; conditions and yields are the recorded values.", 6.4, color=(0.4, 0.4, 0.4))
    _text(page, 45, 802, "Generated locally for the layered extraction platform demo.", 6.4, color=(0.4, 0.4, 0.4))
    page.insert_text((470, 820), "1", fontname="helv", fontsize=7.5, color=(0.4, 0.4, 0.4))

    doc.set_metadata({"title": "Iron-Catalysed alpha-Alkylation of N-Benzyl Amides: A Demo Page",
                      "author": "Demo Authors", "subject": "Demo page for the extraction platform",
                      "keywords": "demo, extraction, curation"})
    return doc, {"boxes": boxes, "entries": entries}


def si_pdf() -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    _text(page, 45, 55, "Supporting Information", 15.0, font="hebo")
    _text(page, 45, 78, "Iron-Catalysed alpha-Alkylation of N-Benzyl Amides: A Demo Page", 9.0)
    _text(page, 45, 92, "Demo Authors", 8.0, color=(0.35, 0.35, 0.35))
    _rule(page, 104)
    _text(page, 45, 124, "Contents", 8.6, font="hebo")
    _text(page, 45, 140, "1. General procedure", 7.6)
    _text(page, 45, 152, "2. Entries used in this demo", 7.6)
    _text(page, 45, 164, "3. Notes", 7.6)

    _text(page, 45, 194, "1. General procedure", 8.6, font="hebo")
    procedure = ("A representative procedure is shown for orientation only. An alpha-bromoamide "
                 "(0.2 mmol, 1.0 equiv), the organozinc reagent (0.4 mmol, 2.0 equiv), Fe(BF-Phos)Cl2 "
                 "(0.5 mol%), ZnCl2 (1.0 equiv) and LiCl (1.0 equiv) are combined in THF (2 mL) under argon "
                 "at 22-25 °C. The mixture is stirred for the time given in Table 1, then worked up and "
                 "purified. Isolated yields are reported.")
    y = 208
    for line in _wrap(procedure, 7.4, 505):
        _text(page, 45, y, line, 7.4)
        y += 9.6
    _text(page, 45, y + 10, "The analytical data of the original publication are not reproduced in this demo.", 7.2, color=(0.4, 0.4, 0.4))

    _text(page, 45, y + 40, "2. Entries used in this demo", 8.6, font="hebo")
    top = y + 52
    page.draw_rect(pymupdf.Rect(45, top, 550, top + 16), color=(0.55, 0.55, 0.55), width=0.6, fill=(0.94, 0.95, 0.97))
    for x, label in ((52, "Entry"), (110, "Product"), (390, "Yield"), (450, "Time")):
        _text(page, x, top + 11, label, 7.0, font="hebo")
    for i, (label, name, _smiles, yield_pct, hours) in enumerate(ENTRIES):
        ry = top + 16 + i * 20
        _text(page, 52, ry + 13, str(i + 1), 7.2)
        _text(page, 110, ry + 13, f"{label}  {name}", 7.2)
        _text(page, 390, ry + 13, f"{yield_pct}%", 7.2)
        _text(page, 450, ry + 13, hours, 7.2)
        _rule(page, ry + 20, color=(0.86, 0.86, 0.86), width=0.4)
    for x in (105, 385, 445):
        page.draw_line((x, top), (x, top + 16 + 5 * 20), color=(0.78, 0.78, 0.78), width=0.5)

    _text(page, 45, top + 150, "3. Notes", 8.6, font="hebo")
    notes = ("This file is synthetic. It contains no text, spectra or images from the published article; "
             "only the five recorded entries (labels, conditions, yields and product names) are used, and "
             "the structures on the main page are redrawn from those names.")
    yy = top + 164
    for line in _wrap(notes, 7.2, 505):
        _text(page, 45, yy, line, 7.2)
        yy += 9.2

    doc.set_metadata({"title": f"Supporting Information: {MAIN_NAME}", "author": "Demo Authors"})
    return doc


# ---------------------------------------------------------------- workspace

def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _condition(key, role, text, amount):
    return {"key": key, "role": role, "text": text, "amount": amount, "origin": "entry",
            "structure": None, "alternatives": [], "stated_at": None, "amount_stated_at": None,
            "inferred": None, "value_missing": False}


def _participant(key, role, label, text, amount, source, page, bbox, **extra):
    data = {"key": key, "role": role, "label": label, "text": text, "amount": amount,
            "amount_origin": "base" if amount else None, "amount_stated_at": None, "source": source,
            "unknown": False, "generic": False, "isolated": None, "page": page, "bbox": bbox,
            "crop": None, "variables": [], "basis": None, "alternatives": [], "stated_at": None,
            "choice": None, "inferred": None}
    data.update(extra)
    return data


def build(root: Path = DEFAULT_ROOT, quiet: bool = False) -> Path:
    root = Path(root).resolve()
    data = root / "Data" / "1"
    work_root = root / "work"
    work = work_root / "1"
    img = root / "build" / "img"
    data.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    main, layout = main_pdf(img)
    main_path = data / MAIN_NAME
    main.save(main_path)
    main.close()
    si = si_pdf()
    si_path = data / SI_NAME
    si.save(si_path)
    si.close()

    boxes = layout["boxes"]
    records = []
    entries = []
    for i, item in enumerate(layout["entries"], start=1):
        eid = f"e{i:03d}"
        rid = f"{eid}-1"
        label, name, y = item["label"], item["name"], item["yield"]
        conditions = [_condition(*c) for c in CONDITIONS]
        conditions.insert(5, _condition("time", "time", item["hours"], None))
        product = _participant("3", "product", label, name, None, "drawn", 1, item["product"],
                               outcomes=[{"yield": {"text": f"{y}%", "value": y, "qualifier": None,
                                                    "type": "isolated", "type_origin": "stated"},
                                          "selectivity": [], "footnote_markers": [], "notes": None,
                                          "stated_at": None}])
        reactants = [
            _participant("1", "reactant", "1", "alpha-bromoamide 1", "0.2 mmol, 1.0 equiv",
                         "drawn", 1, boxes["reactant1"], generic=True,
                         basis="R1 and R2 as printed in the general scheme"),
            _participant("2", "reactant", "2", "R3-ZnBr", "0.4 mmol, 2.0 equiv", "text", None, None,
                         generic=True, basis="the organozinc partner named for this entry"),
        ]
        record = {
            "reaction_id": f"main:scheme1/1/{rid}", "label": label, "kind": "substrate_scope",
            "variant": None, "conditions_given": True, "results": [f"{y}%"], "inferences": [],
            "source": {"doc": "main", "page": 1, "figure": "Scheme 1", "section": None,
                       "caption": "Scheme 1. Iron-catalysed alpha-alkylation of N-benzyl amides",
                       "region_id": "main:scheme1", "block_id": "1", "entry_id": eid, "reaction_id": rid,
                       "entry_bbox": item["row"], "crop": None},
            "steps": [{"step": 1, "description": "alpha-alkylation", "reactants": reactants,
                       "products": [product], "conditions": conditions}],
            "conditions": [], "removed_conditions": [], "unresolved": [], "other_outcomes": [],
            "footnotes": [], "related": [{"doc": "si", "page": 1,
                                          "text": "General procedure for the alpha-alkylation", "about": "procedure"}],
            "notes": "Preview record assembled from an extracted entry; structure redrawn from the product name.",
            "issues": [],
        }
        records.append(record)
        entries.append({
            "eid": eid, "status": "ok", "page": 1, "bbox": item["row"], "label": label,
            "errors": [], "warnings": [],
            "reactions": [{"rid": rid, "label": label, "results": [y], "results_text": [f"{y}%"],
                           "variant": None, "footnote_markers": [], "variables": [],
                           "drawn_structures": [], "overrides": [], "status": "ok", "errors": [],
                           "warnings": [], "record": record}],
        })

    docs = {"main": {"pdf": str(main_path), "sha256": _sha(main_path)},
            "si": {"pdf": str(si_path), "sha256": _sha(si_path)}}
    steps = {
        "preprocess": {"status": "done", "version": 1, "started_at": "2026-11-20T08:00:00+00:00",
                       "finished_at": "2026-11-20T08:01:00+00:00"},
        "locate": {"status": "done", "version": 1, "started_at": "2026-11-20T08:01:00+00:00",
                   "finished_at": "2026-11-20T08:05:00+00:00"},
        "extract": {"status": "done", "version": 1, "started_at": "2026-11-20T08:05:00+00:00",
                    "finished_at": "2026-11-20T08:20:00+00:00", "sources": docs,
                    "params": {"codex": {"model": "demo-model", "reasoning_effort": "medium"}},
                    "summary": {"blocks": 1, "records": len(records)}},
    }
    for step in steps.values():
        step["sources"] = docs
    _write(work / "paper.json", {"paper_id": "1", "source_dir": str(data), "documents": docs, "steps": steps})

    for name, path in (("main", main_path), ("si", si_path)):
        doc = pymupdf.open(path)
        pages = [{"page": p.number + 1, "size_pt": [p.rect.width, p.rect.height],
                  "render": f"pages/p{p.number + 1:03d}.png"} for p in doc]
        doc.close()
        _write(work / name / "manifest.json", {"pdf": str(path), "page_count": len(pages), "dpi": 200,
                                               "metadata": {}, "pages": pages})

    region = {"region_id": "main:scheme1", "doc": "main", "label": "Scheme 1",
              "caption": "Scheme 1. Iron-catalysed alpha-alkylation of N-benzyl amides",
              "kind": "substrate_scope", "presentation": "vector_graphic", "include": True,
              "first_page": 1, "last_page": 1, "footnotes": None, "notes": "",
              "related": [], "boxes": [{"page": 1, "bbox": [45, 190, 550, 760]}],
              "blocks": [{"block_id": "1", "title": "Scope of the alpha-alkylation", "kind": "substrate_scope",
                          "layout": "product_scope", "page": 1, "bbox": [45, 190, 550, 760],
                          "include": True, "scheme_id": None, "notes": ""}]}
    _write(work / "step1" / "regions.json", {
        "caption_check": [], "paper": {"reaction_class": "Iron-catalysed alpha-alkylation of N-benzyl amides",
                                       "numbering_convention": "", "notes": "Preview page."},
        "regions": [region], "schemes": [], "si_sections": [], "docs_in_scope": ["main", "si"]})

    view = {"slug": "main-scheme1__1", "ref": "main:scheme1/1", "status": "ok", "errors": [],
            "warnings": [], "seconds": 1.0, "region": region, "block": region["blocks"][0],
            "entries": entries}
    _write(work / "step2" / "blocks" / view["slug"] / "view.json", view)
    _write(work / "step2" / "reactions.json", {"paper_id": "1", "records": records})
    if not quiet:
        print(f"demo workspace: {work_root}")
        print(f"source PDFs:    {data}")
        print()
        print("Next:")
        print(f"  python -m curator --db {root / 'db' / 'curator.sqlite'} import --work {work_root}")
        print(f"  python -m curator --db {root / 'db' / 'curator.sqlite'} serve")
    return root


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ROOT)
