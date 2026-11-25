"""The curator's SQLite file: schema, connections, the write transaction, the revision log.

One file holds everything: the PDFs (`blobs`), the papers and their documents, the import batches,
the blocks reactions come from, the reactions and every revision of them. `revisions` is append-only
(triggers refuse UPDATE, DELETE and REPLACE), and a reaction or paper cannot change state without a
revision row for its next `rev`: insert the revision first, then update the row. Reactions and papers
are never deleted, and the flags that keep a re-import off a person's work (`touched`, an edited
paper's `meta_origin`) are never cleared.

Connections: one per thread (sqlite3 objects must not cross threads), autocommit mode with explicit
transactions; every write goes through `write()`, which serialises writers of this process and takes
SQLite's write lock up front (BEGIN IMMEDIATE) so a concurrent `import` waits instead of failing.
`read()` gives a reader one consistent state of the database while others write (WAL).

Numbers are compared and hashed by value: a browser sends 126.0 back as 126 (JSON.parse, then
JSON.stringify), so `canonical_json` writes a whole-number float as an integer, and data_sha,
pipeline_sha and pending_sha do not change when a record only makes that round trip.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 3  # 2: canonical JSON; 3: a re-import replaces its paper's reactions
                    # (superseded_by, content_sha)
WRITE_LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE blobs (                 -- the PDFs, by content; a rowid table so blobopen can stream them
  sha256 TEXT NOT NULL UNIQUE,
  size INTEGER NOT NULL,
  data BLOB NOT NULL
);

CREATE TABLE papers (
  paper_id TEXT PRIMARY KEY,
  title TEXT, authors TEXT, journal TEXT, year INTEGER, doi TEXT, note TEXT,
  meta_origin TEXT NOT NULL DEFAULT 'auto' CHECK (meta_origin IN ('auto', 'edited')),
  context TEXT,                      -- JSON: regions.json paper{} (reaction_class, numbering_convention, notes)
  rev INTEGER NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT
);

CREATE TABLE documents (
  doc_id INTEGER PRIMARY KEY,
  paper_id TEXT NOT NULL REFERENCES papers(paper_id),
  doc TEXT NOT NULL CHECK (doc IN ('main', 'si')),
  filename TEXT NOT NULL,
  sha256 TEXT NOT NULL REFERENCES blobs(sha256),
  page_count INTEGER NOT NULL,
  pages TEXT NOT NULL,               -- JSON [[w, h, rotation, [a, b, c, d, e, f]], ...]: index = page - 1;
                                     -- the matrix maps page.rect coordinates to PDF user space
  pdf_meta TEXT,                     -- JSON: the PDF's metadata dict
  UNIQUE (paper_id, doc)
);

CREATE TABLE imports (
  import_id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL, finished_at TEXT,
  work_dir TEXT NOT NULL,
  repo_commit TEXT, repo_dirty INTEGER,
  author TEXT NOT NULL,
  options TEXT NOT NULL,             -- JSON: the command's options
  report TEXT                        -- JSON: what happened, per paper
);

CREATE TABLE import_papers (
  import_id INTEGER NOT NULL REFERENCES imports(import_id),
  paper_id TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('imported', 'skipped', 'refused')),
  reason TEXT,
  steps TEXT,                        -- JSON: paper.json steps (status, version, params, times, summary)
  reactions_sha TEXT,                -- sha256 of reactions.json as read
  counts TEXT,                       -- JSON
  content_sha TEXT,                  -- sha256 over everything read (reactions.json, regions.json, the views,
                                     -- the PDFs): the same again means nothing changed
  PRIMARY KEY (import_id, paper_id)
);

CREATE TABLE blocks (                -- where reactions come from; pipeline context, replaced on re-import
  block_pk INTEGER PRIMARY KEY,
  paper_id TEXT NOT NULL REFERENCES papers(paper_id),
  region_id TEXT NOT NULL, block_id TEXT NOT NULL,
  slug TEXT, doc TEXT NOT NULL, page INTEGER,
  figure TEXT, layout TEXT, kind TEXT, title TEXT,
  region TEXT NOT NULL,              -- JSON: view.json region{} plus regions.json boxes[]
  view TEXT NOT NULL,                -- JSON: view.json without the records and drafts of its reactions
  import_id INTEGER NOT NULL REFERENCES imports(import_id),
  in_latest INTEGER NOT NULL DEFAULT 1,
  UNIQUE (paper_id, region_id, block_id)
);

CREATE TABLE reactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,          -- shown as R000123; never reused
  paper_id TEXT NOT NULL REFERENCES papers(paper_id),
  block_pk INTEGER REFERENCES blocks(block_pk),
  origin_id TEXT,                                -- the pipeline's reaction_id; NULL for created or copied ones
  copied_from INTEGER REFERENCES reactions(id),
  data TEXT NOT NULL CHECK (json_valid(data)),   -- the record (pipeline shape, without crop paths)
  data_sha TEXT NOT NULL,
  rev INTEGER NOT NULL,
  review_status TEXT NOT NULL DEFAULT 'unreviewed'
    CHECK (review_status IN ('unreviewed', 'reviewed', 'problem', 'excluded')),
  review_note TEXT,
  deleted INTEGER NOT NULL DEFAULT 0,
  touched INTEGER NOT NULL DEFAULT 0,            -- a person has made a revision (re-import never overwrites)
  first_import INTEGER REFERENCES imports(import_id),
  last_import INTEGER REFERENCES imports(import_id),
  in_latest INTEGER NOT NULL DEFAULT 1,          -- 0: an old version (its paper was imported again)
  superseded_by INTEGER REFERENCES imports(import_id),  -- the import that replaced it: read-only from then on
  pipeline_sha TEXT,                             -- sha of the last pipeline version applied or dismissed
  pipeline_info TEXT,                            -- JSON {status, flags, errors, warnings, seconds} from view.json
  pending_data TEXT, pending_sha TEXT,           -- a newer pipeline version not applied (the reaction was touched)
  pending_import INTEGER REFERENCES imports(import_id),
  -- list columns, recomputed from data on every change (records.summarize)
  layout TEXT,
  label TEXT, kind TEXT, figure TEXT, doc TEXT, page INTEGER, entry_id TEXT,
  reactants TEXT, products TEXT, conditions TEXT, yields TEXT,
  flags TEXT,                                    -- space-delimited: inferred unresolved issues warned
  thumb TEXT,                                    -- JSON {doc, page, bbox} of a product drawing, or NULL
  search TEXT,                                   -- casefolded text for q=
  sort_key TEXT,                                 -- printed order: paper, doc, page, region, entry, rid
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT
);
-- A pipeline id names one current reaction of its paper; old versions keep theirs.
CREATE UNIQUE INDEX reactions_origin ON reactions(paper_id, origin_id) WHERE superseded_by IS NULL;
CREATE INDEX reactions_list ON reactions(deleted, sort_key);
CREATE INDEX reactions_paper ON reactions(paper_id);
CREATE INDEX reactions_block ON reactions(block_pk);
CREATE INDEX reactions_review ON reactions(review_status);

CREATE TABLE revisions (
  rev_id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity TEXT NOT NULL CHECK (entity IN ('reaction', 'paper')),
  entity_id TEXT NOT NULL,                       -- str(reactions.id) or papers.paper_id
  rev INTEGER NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('import', 'reimport', 'accept_import', 'dismiss_import', 'edit',
         'review', 'revert', 'copy', 'create', 'delete', 'restore', 'meta')),
  author TEXT NOT NULL,
  comment TEXT,
  created_at TEXT NOT NULL,
  import_id INTEGER REFERENCES imports(import_id),
  base_rev INTEGER,                              -- the rev the change was made on
  target_rev INTEGER,                            -- revert: the rev whose data was restored
  snapshot TEXT NOT NULL,                        -- JSON: the full state after this revision
  diff TEXT NOT NULL,                            -- JSON: changes against the previous snapshot
  UNIQUE (entity, entity_id, rev)
);

"""

# The triggers that keep the log honest; replaced as a whole when the schema moves on (migrate).
GUARDS_V2 = """
CREATE TRIGGER revisions_no_update BEFORE UPDATE ON revisions
BEGIN SELECT RAISE(ABORT, 'revisions are append-only'); END;
CREATE TRIGGER revisions_no_delete BEFORE DELETE ON revisions
BEGIN SELECT RAISE(ABORT, 'revisions are append-only'); END;
-- INSERT OR REPLACE removes the row it replaces without firing the delete trigger: refuse it first.
CREATE TRIGGER revisions_no_replace BEFORE INSERT ON revisions
WHEN EXISTS (SELECT 1 FROM revisions WHERE entity = NEW.entity AND entity_id = NEW.entity_id AND rev = NEW.rev)
BEGIN SELECT RAISE(ABORT, 'revisions are append-only'); END;

-- No change of state without the revision that records it (insert the revision first): a changed
-- state needs the next rev, and that rev needs its revision row.
CREATE TRIGGER reactions_need_revision
BEFORE UPDATE OF data, review_status, review_note, deleted, rev ON reactions
WHEN (NEW.rev IS OLD.rev AND (NEW.data IS NOT OLD.data OR NEW.review_status IS NOT OLD.review_status
                              OR NEW.review_note IS NOT OLD.review_note OR NEW.deleted IS NOT OLD.deleted))
  OR (NEW.rev IS NOT OLD.rev AND NEW.rev IS NOT OLD.rev + 1)
  OR (SELECT count(*) FROM revisions
      WHERE entity = 'reaction' AND entity_id = CAST(NEW.id AS TEXT) AND rev = NEW.rev) = 0
BEGIN SELECT RAISE(ABORT, 'reaction changed without a revision'); END;

-- What keeps a re-import off people's work: once set, `touched` and an edited paper's meta_origin stay.
CREATE TRIGGER reactions_stay_touched BEFORE UPDATE OF touched ON reactions
WHEN OLD.touched = 1 AND NEW.touched IS NOT 1
BEGIN SELECT RAISE(ABORT, 'a reaction a person changed stays touched'); END;
CREATE TRIGGER reactions_no_delete BEFORE DELETE ON reactions
BEGIN SELECT RAISE(ABORT, 'reactions are never deleted (they are marked deleted)'); END;

CREATE TRIGGER papers_need_revision
BEFORE UPDATE OF title, authors, journal, year, doi, note, rev ON papers
WHEN (NEW.rev IS OLD.rev AND (NEW.title IS NOT OLD.title OR NEW.authors IS NOT OLD.authors
                              OR NEW.journal IS NOT OLD.journal OR NEW.year IS NOT OLD.year
                              OR NEW.doi IS NOT OLD.doi OR NEW.note IS NOT OLD.note))
  OR (NEW.rev IS NOT OLD.rev AND NEW.rev IS NOT OLD.rev + 1)
  OR (SELECT count(*) FROM revisions
      WHERE entity = 'paper' AND entity_id = NEW.paper_id AND rev = NEW.rev) = 0
BEGIN SELECT RAISE(ABORT, 'paper changed without a revision'); END;
CREATE TRIGGER papers_stay_edited BEFORE UPDATE OF meta_origin ON papers
WHEN OLD.meta_origin = 'edited' AND NEW.meta_origin IS NOT 'edited'
BEGIN SELECT RAISE(ABORT, 'bibliographic data a person edited stays edited'); END;
CREATE TRIGGER papers_no_delete BEFORE DELETE ON papers
BEGIN SELECT RAISE(ABORT, 'papers are never deleted'); END;
"""
GUARDS_V3 = """
-- An old version (its paper was imported again) is read-only, and stays an old version.
CREATE TRIGGER reactions_superseded_read_only
BEFORE UPDATE OF data, review_status, review_note, deleted, rev ON reactions
WHEN OLD.superseded_by IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'a superseded reaction is read-only'); END;
CREATE TRIGGER reactions_stay_superseded BEFORE UPDATE OF superseded_by, in_latest ON reactions
WHEN OLD.superseded_by IS NOT NULL AND (NEW.superseded_by IS NOT OLD.superseded_by OR NEW.in_latest IS NOT 0)
BEGIN SELECT RAISE(ABORT, 'a superseded reaction stays superseded'); END;
"""
GUARDS = GUARDS_V2 + GUARDS_V3


class SchemaError(RuntimeError):
    pass


def connect(path, create: bool = False, *, threads: bool = False) -> sqlite3.Connection:
    """A connection to the curator database. `create`: make the file (and its directory) if missing.
    ':memory:' gives a fresh in-memory database (tests). `threads`: the connection may be handed from one
    thread to the next (the server's pool; never used by two threads at once)."""
    memory = str(path) == ":memory:"
    if not memory:
        path = Path(path)
        if not path.exists():
            if not create:
                raise FileNotFoundError(f"no curator database at {path} (python -m curator import creates it)")
            path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=10, check_same_thread=not threads)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        if not memory:
            conn.execute("PRAGMA journal_mode = WAL")
            # FULL: a save the server has answered survives a power cut (NORMAL in WAL mode may roll the
            # newest commits back); one person's clicks cost nothing in fsyncs.
            conn.execute("PRAGMA synchronous = FULL")
        migrate(conn)
    except BaseException:
        conn.close()  # e.g. SchemaError, or a file that is no database: do not leave it open
        raise
    return conn


def _statements(script: str):
    """The statements of a script one by one (a trigger's body has semicolons of its own)."""
    buf = ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            yield buf.strip()
            buf = ""


def migrate(conn: sqlite3.Connection) -> None:
    def version() -> int:
        return conn.execute("PRAGMA user_version").fetchone()[0]

    if version() == SCHEMA_VERSION:
        return
    with write(conn):
        v = version()  # again, under the write lock: another process may have just created it
        if v > SCHEMA_VERSION:
            raise SchemaError(f"database schema {v} is newer than this curator ({SCHEMA_VERSION})")
        if v == 0:
            for stmt in _statements(SCHEMA + GUARDS):
                conn.execute(stmt)
        if v == 1:
            _upgrade_to_2(conn)
        if v in (1, 2):
            _upgrade_to_3(conn)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


V1_TRIGGERS = ("revisions_no_update", "revisions_no_delete", "reactions_need_revision", "papers_need_revision")


def _sha_v1(obj) -> str:
    """How schema 1 hashed JSON: numbers as Python wrote them, 126.0 apart from 126."""
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def _upgrade_to_2(conn: sqlite3.Connection) -> None:
    """Schema 1 → 2: the guards of GUARDS, and the sha columns recomputed with numbers hashed by value.
    No data and no revision changes. pipeline_sha moves along when its version can be found (the data
    itself, or a revision's snapshot); a hash that did not match its data before still does not."""
    for name in V1_TRIGGERS:
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
    for stmt in _statements(GUARDS_V2):
        conn.execute(stmt)

    def parsed(text, key=None):
        try:
            value = json.loads(text)
            return value if key is None else value[key]
        except (TypeError, KeyError, IndexError, ValueError):
            return None

    def new_sha(value, old_sha):
        """value's hash now if old_sha was its hash before, else None."""
        try:
            return sha_json(value) if value is not None and _sha_v1(value) == old_sha else None
        except ValueError:  # NaN or Infinity: schema 1 did not keep them out of every column
            return None

    rows = conn.execute("SELECT id, data, data_sha, pipeline_sha, pending_data, pending_sha FROM reactions").fetchall()
    for r in rows:
        data = parsed(r["data"])
        pipeline_sha = r["pipeline_sha"]
        if pipeline_sha is not None:  # the version it names: the data itself, else a revision's (newest first)
            snapshots = conn.execute("SELECT snapshot FROM revisions WHERE entity = 'reaction' AND entity_id = ?"
                                     " ORDER BY rev DESC", (str(r["id"]),)).fetchall()
            versions = itertools.chain([data], (parsed(s, "data") for (s,) in snapshots))
            pipeline_sha = next(filter(None, (new_sha(v, pipeline_sha) for v in versions)), pipeline_sha)
        conn.execute("UPDATE reactions SET data_sha = ?, pipeline_sha = ?, pending_sha = ? WHERE id = ?",
                     (new_sha(data, r["data_sha"]) or r["data_sha"], pipeline_sha,
                      new_sha(parsed(r["pending_data"]), r["pending_sha"]) or r["pending_sha"], r["id"]))


def _trigger_names(script: str) -> list[str]:
    return re.findall(r"CREATE TRIGGER (\w+)", script)


def _upgrade_to_3(conn: sqlite3.Connection) -> None:
    """Schema 2 → 3: importing a paper again replaces its reactions. `reactions` gets superseded_by, and a
    pipeline id has to be unique only among the current reactions of a paper: SQLite drops a table's
    UNIQUE only by rebuilding the table, so the table is built again from SCHEMA and its rows copied over
    unchanged. import_papers gets content_sha. The guards are installed again (they went with the table)."""
    def columns(table):
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]

    for name in _trigger_names(GUARDS):
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
    if "superseded_by" not in columns("reactions"):
        conn.execute("PRAGMA defer_foreign_keys = ON")  # copied_from points into the table being rebuilt
        names = ", ".join(columns("reactions"))
        schema = list(_statements(SCHEMA))
        conn.execute("ALTER TABLE reactions RENAME TO reactions_v2")
        conn.execute(next(s for s in schema if s.startswith("CREATE TABLE reactions (")))
        conn.execute(f"INSERT INTO reactions ({names}) SELECT {names} FROM reactions_v2")
        conn.execute("DROP TABLE reactions_v2")  # its indexes go with it; the new table gets SCHEMA's
        for stmt in schema:
            if re.match(r"(?:--[^\n]*\n)*CREATE (?:UNIQUE )?INDEX reactions_\w+ ON reactions\b", stmt):
                conn.execute(stmt)
    if "content_sha" not in columns("import_papers"):
        conn.execute("ALTER TABLE import_papers ADD COLUMN content_sha TEXT")
    for stmt in _statements(GUARDS):
        conn.execute(stmt)


@contextmanager
def read(conn: sqlite3.Connection):
    """One read transaction: every query inside sees the same state of the database, while others go on
    writing (WAL). Only for reading: a write() inside joins it and is rolled back at the end."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN")
    try:
        yield conn
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")


@contextmanager
def write(conn: sqlite3.Connection, rollback: bool = False):
    """One write transaction. Nested use joins the outer transaction. `rollback`: undo everything at
    the end (a dry run)."""
    with WRITE_LOCK:
        if conn.in_transaction:
            yield conn
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        if rollback:
            conn.execute("ROLLBACK")
        else:
            conn.execute("COMMIT")


# ----------------------------------------------------------------------------- JSON and hashes

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dumps(obj) -> str:
    """How JSON is stored: compact, not ASCII-escaped, key order kept. NaN and Infinity are no JSON
    (SQLite's json_valid and browsers refuse them): ValueError."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def loads(text):
    return None if text is None else json.loads(text)


def plain_numbers(obj):
    """obj with every whole-number float below 1e21 as an int: the form a browser sends a value back in
    (JavaScript writes 126.0 as 126, and 1e21 and up with an exponent)."""
    if isinstance(obj, float):
        return int(obj) if obj.is_integer() and abs(obj) < 1e21 else obj
    if isinstance(obj, dict):
        return {k: plain_numbers(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [plain_numbers(v) for v in obj]
    return obj


def canonical_json(obj) -> str:
    """The form hashes are taken of: sorted keys, compact, numbers by value (plain_numbers)."""
    return json.dumps(plain_numbers(obj), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha_json(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ----------------------------------------------------------------------------- revisions

def insert_revision(conn: sqlite3.Connection, *, entity: str, entity_id, rev: int, action: str, author: str,
                    snapshot: dict, diff: list, comment: str | None = None, import_id: int | None = None,
                    base_rev: int | None = None, target_rev: int | None = None, created_at: str | None = None) -> int:
    """Append one revision; returns its rev_id. Must run inside write()."""
    cur = conn.execute(
        "INSERT INTO revisions (entity, entity_id, rev, action, author, comment, created_at, import_id,"
        " base_rev, target_rev, snapshot, diff) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (entity, str(entity_id), rev, action, author, comment, created_at or now_iso(), import_id,
         base_rev, target_rev, dumps(snapshot), dumps(diff)))
    return cur.lastrowid
