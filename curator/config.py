"""Paths, defaults and the fixed vocabularies of the curator."""

from __future__ import annotations

import getpass
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "curator.sqlite"
DEFAULT_WORK = ROOT / "work"
WEB_DIR = Path(__file__).resolve().parent / "web"
DEFAULT_PORT = 8791

REVIEW_STATUSES = ("unreviewed", "reviewed", "problem", "excluded")
# What a revision records. import/reimport/accept_import/dismiss_import come from the pipeline side;
# the others are a person's changes.
ACTIONS = ("import", "reimport", "accept_import", "dismiss_import", "edit", "review", "revert",
           "copy", "create", "delete", "restore", "meta")
PIPELINE_ACTIONS = ("import", "reimport")
# Items a person adds in the editor carry this origin (shown as 人工).
CURATOR_ORIGIN = "curator"


def default_author() -> str:
    return os.environ.get("CURATOR_AUTHOR") or getpass.getuser()


def display_id(reaction_id: int) -> str:
    """How a reaction is named in the UI and in exports: R000123."""
    return f"R{reaction_id:06d}"
