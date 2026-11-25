"""Pipeline-wide settings."""

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "Data" / "papers"
DEFAULT_WORK_DIR = REPO_ROOT / "work"


def repo_rel(path: Path) -> str:
    """Path as Codex should see it: relative to the repo root when inside it."""
    path = Path(path)
    return os.path.relpath(path, REPO_ROOT) if path.is_relative_to(REPO_ROOT) else str(path)


@dataclass(frozen=True)
class PreprocessConfig:
    # Main-text schemes are dense, so they get a higher resolution than the SI.
    dpi_main: int = 200
    dpi_si: int = 150
    # Contact sheets: low-res page thumbnails tiled into a grid for a quick overview.
    thumb_width: int = 320
    sheet_cols: int = 5
    sheet_rows: int = 4

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CodexConfig:
    # None = inherit from the user's ~/.codex/config.toml
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_s: int = 3600
    # How many times a step may send validation errors back to the same Codex session.
    max_repair_rounds: int = 2

    def to_dict(self) -> dict:
        return asdict(self)

    def identity(self) -> dict:
        """What a result depends on: the model and its effort. The timeout and the repair rounds only
        decide how long a session may try, so they are kept out of step params and result hashes."""
        return {"model": self.model, "reasoning_effort": self.reasoning_effort}


@dataclass(frozen=True)
class LocateConfig:
    # Documents searched for reaction regions. The SI is left out for now.
    docs: tuple[str, ...] = ("main",)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ExtractConfig:
    # Codex sessions run at the same time inside one paper (one block reader per block, one
    # session per reaction).
    concurrency: int = 4
    # Optional filters: block refs "region_id/block_id" (or a bare region_id), and block kinds.
    blocks: tuple[str, ...] | None = None
    kinds: tuple[str, ...] | None = None
    # Spell out at most this many entries per block (for pilots).
    limit: int | None = None
    # False: stop after the block reader has spelled out the entries (no per-reaction sessions).
    entries: bool = True
    # Automatic retries of a block whose reader failed validation: a fresh session each time, the
    # failed attempt kept under step2/blocks/<slug>/attempts/. 0 disables the retry.
    retries: int = 2
    inventory_timeout_s: int = 1800
    expand_timeout_s: int = 900
    entry_timeout_s: int = 900

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PipelineConfig:
    data_dir: Path = DEFAULT_DATA_DIR
    work_dir: Path = DEFAULT_WORK_DIR
    preprocess: PreprocessConfig = field(default_factory=PreprocessConfig)
    codex: CodexConfig = field(default_factory=CodexConfig)
    locate: LocateConfig = field(default_factory=LocateConfig)
    extract: ExtractConfig = field(default_factory=ExtractConfig)
