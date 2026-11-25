"""Lines of a table from the Step 0 text layer (work/<id>/<doc>/words/pNNN.jsonl).

For a table whose cells are real text, the words of its area grouped into lines give a draft of
its rows, with the x position of every word, which the condition-table reader gets as a
transcription aid. Only a draft: the text layer can misspell ("Li" for "L1"), it glues footnote
markers to the word before them ("2b" is entry 2 with marker b), and a raised marker sits a little
higher than the rest of its line, so lines are grouped by the centres of the words, not by their tops.

Pure functions apart from `load_words`; no PyMuPDF.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median


def load_words(doc_dir: Path, tag: str) -> list[dict]:
    path = Path(doc_dir) / "words" / f"{tag}.jsonl"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def words_in(words: list[dict], area) -> list[dict]:
    """The words whose centre lies inside `area` ([x0, y0, x1, y1])."""
    x0, y0, x1, y1 = area
    out = []
    for w in words:
        b = w["bbox"]
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            out.append(w)
    return out


def group_lines(words: list[dict], tolerance: float | None = None) -> list[dict]:
    """Words grouped into lines, top to bottom; each line {"y": centre, "words": [...] left to right}.

    A word joins the line above when its centre is within `tolerance` of that line's centre
    (default: 0.45 x the median word height, which keeps a raised footnote marker on its line
    and the next row of a table apart)."""
    if not words:
        return []
    heights = [w["bbox"][3] - w["bbox"][1] for w in words]
    tol = tolerance if tolerance is not None else 0.45 * median(heights)
    centre = lambda w: (w["bbox"][1] + w["bbox"][3]) / 2
    lines: list[dict] = []
    for w in sorted(words, key=centre):
        c = centre(w)
        if lines and c - lines[-1]["y"] <= tol:
            line = lines[-1]
            line["words"].append(w)
            line["y"] = sum(centre(x) for x in line["words"]) / len(line["words"])
        else:
            lines.append({"y": c, "words": [w]})
    for line in lines:
        line["words"].sort(key=lambda w: w["bbox"][0])
        line["y"] = round(line["y"], 1)
    return lines


def format_lines(lines: list[dict]) -> list[str]:
    """One string per line: 'y=140.8 | 2b@325  FeCl2@359  >98@446  49/44/0@505' (word@x0)."""
    return [f"y={line['y']:.1f} | " + "  ".join(f"{w['text']}@{w['bbox'][0]:.0f}" for w in line["words"])
            for line in lines]


def passage_text(words: list[dict], area) -> str:
    """The words of `area` as running text, for a passage: in the order of the text layer (which
    follows the columns), one line of output per line of the layer."""
    lines: list[list[str]] = []
    key = None
    for w in words_in(words, area):
        k = (w.get("block"), w.get("line"))
        if k != key or not lines:
            lines.append([])
            key = k
        lines[-1].append(w["text"])
    return "\n".join(" ".join(line) for line in lines)


def table_lines(words: list[dict], area, min_words: int = 8) -> list[str] | None:
    """The text layer of `area` as lines, or None when it holds too few words to be a text table
    (a drawn or scanned table: its text is not in the text layer)."""
    inside = words_in(words, area)
    if len(inside) < min_words:
        return None
    return format_lines(group_lines(inside))
