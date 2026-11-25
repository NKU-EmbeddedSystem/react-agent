"""Paper discovery and per-paper workspace/state management.

Input layout: one sub-directory per paper under the data dir, holding the main-text
PDF and (optionally) one SI PDF whose file name starts with "SI-".

Output layout: work/<paper_id>/ with one sub-directory per document ("main", "si"),
plus paper.json recording sources and the status of every pipeline step.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SI_NAME_RE = re.compile(r"^(SI|ESI|supp(orting)?)[\s_-]", re.IGNORECASE)


@dataclass(frozen=True)
class Paper:
    paper_id: str
    source_dir: Path
    main_pdf: Path
    si_pdf: Path | None

    def documents(self) -> dict[str, Path]:
        docs = {"main": self.main_pdf}
        if self.si_pdf is not None:
            docs["si"] = self.si_pdf
        return docs


def _sort_key(paper_id: str):
    return (0, int(paper_id), "") if paper_id.isdigit() else (1, 0, paper_id)


def discover_papers(data_dir: Path) -> list[Paper]:
    papers = []
    for sub in sorted(p for p in Path(data_dir).iterdir() if p.is_dir()):
        pdfs = sorted(sub.glob("*.pdf"))
        if not pdfs:
            continue
        si = [p for p in pdfs if SI_NAME_RE.match(p.name)]
        main = [p for p in pdfs if p not in si]
        if len(main) != 1 or len(si) > 1:
            raise ValueError(
                f"{sub}: expected exactly 1 main PDF and at most 1 SI PDF, "
                f"found main={[p.name for p in main]} si={[p.name for p in si]}"
            )
        papers.append(Paper(sub.name, sub, main[0], si[0] if si else None))
    return sorted(papers, key=lambda p: _sort_key(p.paper_id))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, data) -> None:
    """Write JSON atomically so a crashed run never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class PaperWorkspace:
    def __init__(self, paper: Paper, work_dir: Path):
        self.paper = paper
        self.root = Path(work_dir) / paper.paper_id
        self.state_path = self.root / "paper.json"
        self.log_dir = self.root / "logs"

    def doc_dir(self, doc: str) -> Path:
        return self.root / doc

    def load_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {
            "paper_id": self.paper.paper_id,
            "source_dir": str(self.paper.source_dir),
            "documents": {},
            "steps": {},
        }

    def save_state(self, state: dict) -> None:
        write_json(self.state_path, state)
