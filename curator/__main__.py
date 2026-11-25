"""python -m curator [--db PATH] {import,serve,export,check,backup}

  import   bring the pipeline's results (work/<id>/) into the database, which it creates if missing;
           exit status 1 if a paper was refused
  serve    the front end and its API (default http://127.0.0.1:8791/)
  export   reactions to JSON Lines or a ZIP (a JSON per reaction, optionally with structure pictures)
  check    the revision log against the rows: every reaction and paper is at its newest revision, whose
           snapshot is its current state, each revision's diff is the diff of its snapshots, what people
           changed is still marked as theirs (touched, meta_origin), foreign keys hold, and every PDF
           still hashes to its sha256; exit status 1 if not. One read transaction: safe beside a server
  backup   a consistent copy of the database to a new file (VACUUM INTO), also while a server runs
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from . import db, export, importer, server, store
from .config import DEFAULT_DB, DEFAULT_PORT, DEFAULT_WORK, default_author, display_id
from .diff import diff


def _missing(path: Path) -> bool:
    """serve, export and check need the database to exist: says so if it does not."""
    if Path(path).is_file():
        return False
    print(f"没有数据库 {path}：先运行 python -m curator import", file=sys.stderr)
    return True


def cmd_import(args) -> int:
    if not args.work.is_dir():
        print(f"错误：没有 work 目录：{args.work}", file=sys.stderr)
        return 1
    # A dry run against a database that does not exist yet needs no file: an empty one in memory says the same.
    try:
        conn = db.connect(":memory:" if args.dry_run and not args.db.exists() else args.db, create=True)
    except (sqlite3.DatabaseError, db.SchemaError) as e:
        print(f"无法打开数据库 {args.db}：{e}", file=sys.stderr)
        return 1
    try:
        report = importer.import_work(conn, args.work, papers=args.papers, dry_run=args.dry_run, author=args.author,
                                      force=args.force)
    except (FileNotFoundError, ValueError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 1 if any(p["outcome"] == "refused" for p in report["papers"].values()) else 0


def cmd_serve(args) -> int:
    if _missing(args.db):
        return 1
    try:
        server.serve(args.db, host=args.host, port=args.port)
    except (sqlite3.DatabaseError, db.SchemaError) as e:
        print(f"无法打开数据库 {args.db}：{e}", file=sys.stderr)
        return 1
    except OSError as e:  # the port is taken, the host does not resolve or is not this machine's
        hint = "：端口已被占用（另一个 serve 还在运行？）" if e.errno == errno.EADDRINUSE else ""
        print(f"无法在 {args.host}:{args.port} 上启动服务器{hint}（{e}）", file=sys.stderr)
        return 1
    return 0


def _split(values) -> list[str]:
    return [v.strip() for value in values or () for v in value.split(",") if v.strip()]


def cmd_export(args, conn) -> int:
    fmt = args.format or ("zip" if args.out.suffix.lower() == ".zip" else "jsonl")
    params = {k: ",".join(_split(v)) for k, v in (("paper", args.papers), ("status", args.status)) if v}
    if "excluded" in _split(args.status) and not args.include_excluded:
        print("注意：审核为排除（excluded）的反应只有加上 --include-excluded 才会导出", file=sys.stderr)
    if args.images and fmt != "zip":
        print("注意：--images 只对 zip 有效，已忽略", file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    part = args.out.with_name(args.out.name + ".part")  # a failed export leaves no half-written file
    try:
        with open(part, "wb") as fp, db.read(conn):  # the reactions as of one moment, whatever a server saves
            ids = export.select_ids(conn, params, _split(args.ids) if args.ids else None,
                                    include_excluded=args.include_excluded, include_deleted=args.include_deleted)
            if fmt == "zip":
                n = export.write_zip(conn, ids, fp, images=args.images, filter=params or None)
            else:
                n = export.write_jsonl(conn, ids, fp)
        part.replace(args.out)
    finally:
        part.unlink(missing_ok=True)
    print(f"已导出 {n} 条反应到 {args.out}（{fmt}）")
    return 0


def cmd_backup(args, conn) -> int:
    """A copy of the database as it is at one moment, safe while a server writes to it (a copy of the
    file is not: what is still in the -wal file would be missing)."""
    if args.out.exists():
        print(f"错误：{args.out} 已经存在", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    part = args.out.with_name(args.out.name + ".part")
    part.unlink(missing_ok=True)
    try:
        conn.execute("VACUUM INTO ?", (str(part),))
        part.replace(args.out)
    finally:
        part.unlink(missing_ok=True)
    print(f"已备份到 {args.out}")
    return 0


# ----------------------------------------------------------------------------- check

FIRST_ACTIONS = {"reaction": ("import", "create", "copy"), "paper": ("import",)}
BROKEN = object()  # a JSON column that does not parse


def _json(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError, RecursionError):
        return BROKEN


def _sha(value) -> str | None:
    try:
        return db.sha_json(value)
    except ValueError:  # NaN or Infinity: no hash matches it
        return None


def _same_changes(stored, expected) -> bool:
    """Whether a revision's stored diff is the diff of its snapshots. A change of number form only
    (126.0 → 126) that schema 1 logged is not counted against it."""
    if not isinstance(stored, list):
        return False
    stored = [op for op in stored if not (isinstance(op, dict) and op.get("op") == "change"
                                          and diff(op.get("old"), op.get("new")) == [])]
    try:
        return db.canonical_json(stored) == db.canonical_json(expected)
    except ValueError:
        return False


def check(conn) -> tuple[list[str], dict]:
    """(problems, counts): what `check` reports, as Chinese lines, and how much it looked at. One read
    transaction: a save the server makes meanwhile is either all seen or not at all."""
    with db.read(conn):
        return _check(conn)


def _check(conn) -> tuple[list[str], dict]:
    problems = [f"SQLite：{r[0]}" for r in conn.execute("PRAGMA quick_check") if r[0] != "ok"]
    problems += [f"外键：{r[0]} 的第 {r[1]} 行指向 {r[2]} 里没有的行"
                 for r in conn.execute("PRAGMA foreign_key_check")]
    log = {"reaction": {}, "paper": {}}  # entity -> {entity_id: [revision rows by rev]}
    for r in conn.execute("SELECT entity, entity_id, rev, action, snapshot, diff FROM revisions"
                          " ORDER BY entity, entity_id, rev"):
        log[r["entity"]].setdefault(r["entity_id"], []).append(r)

    def chain(entity, entity_id, name, rev, state) -> tuple[list, dict | None]:
        """The entity's revisions and its newest snapshot, after checking the chain: revs 1..rev without
        gaps, rev 1 a first action, and each stored diff the diff of the snapshots around it."""
        revs = log[entity].pop(entity_id, None)
        if not revs:
            problems.append(f"{name}：没有任何版本记录")
            return [], None
        numbers = [r["rev"] for r in revs]
        if numbers != list(range(1, len(numbers) + 1)):
            problems.append(f"{name}：版本号不连续（{len(numbers)} 个版本，第 {numbers[0]}–{numbers[-1]} 版）")
        if rev != numbers[-1]:
            problems.append(f"{name}：当前是第 {rev} 版，最新的版本记录却是第 {numbers[-1]} 版")
        if revs[0]["action"] not in FIRST_ACTIONS[entity]:
            problems.append(f"{name}：第 {numbers[0]} 版的操作是 {revs[0]['action']}，"
                            f"第一版只能是 {' / '.join(FIRST_ACTIONS[entity])}")
        before, snap = None, None
        for r in revs:
            snap, changes = _json(r["snapshot"]), _json(r["diff"])
            if not isinstance(snap, dict) or changes is BROKEN:
                problems.append(f"{name}：第 {r['rev']} 版的快照或改动不是有效的 JSON")
                before, snap = None, None
                continue
            now = state(snap)
            if before is not None or r is revs[0]:
                if not _same_changes(changes, [] if before is None else diff(before, now)):
                    problems.append(f"{name}：第 {r['rev']} 版记的改动和前后两版的快照对不上")
            before = now
        return revs, snap

    n_reactions = n_papers = n_blobs = 0
    for row in conn.execute("SELECT * FROM reactions ORDER BY id"):
        n_reactions += 1
        name = display_id(row["id"])
        revs, snap = chain("reaction", str(row["id"]), name, row["rev"], store.snapshot_state)
        people = sorted({r["action"] for r in revs} & set(store.PERSON_ACTIONS))
        if people and not row["touched"]:
            problems.append(f"{name}：有人改过（{'、'.join(people)}），touched 却是 0：重新导入会覆盖这些修改")
        data = _json(row["data"])
        if data is BROKEN:
            problems.append(f"{name}：data 不是有效的 JSON")
            continue
        if row["data_sha"] != _sha(data):
            problems.append(f"{name}：data_sha 和数据不符")
        if row["pending_data"] is not None:
            pending = _json(row["pending_data"])
            if pending is BROKEN:
                problems.append(f"{name}：待采用的数据不是有效的 JSON")
            elif row["pending_sha"] != _sha(pending):
                problems.append(f"{name}：pending_sha 和待采用的数据不符")
        if snap is None:
            continue
        if db.canonical_json(snap.get("data")) != db.canonical_json(data):
            problems.append(f"{name}：数据和最新版本的快照不一致")
        if (snap.get("review_status"), snap.get("review_note"), snap.get("deleted")) != \
                (row["review_status"], row["review_note"], bool(row["deleted"])):
            problems.append(f"{name}：审核状态、备注或删除标记和最新版本的快照不一致")
    for row in conn.execute("SELECT * FROM papers ORDER BY paper_id"):
        n_papers += 1
        name = f"文献 {row['paper_id']}"
        revs, snap = chain("paper", row["paper_id"], name, row["rev"], lambda s: s)
        if row["meta_origin"] != "edited" and any(r["action"] == "meta" for r in revs):
            problems.append(f"{name}：题录有人改过，meta_origin 却不是 edited：重新导入会覆盖这些修改")
        if snap is not None and db.canonical_json(snap) != db.canonical_json({k: row[k] for k in store.PAPER_FIELDS}):
            problems.append(f"{name}：题录和最新版本的快照不一致")
    for entity, left in log.items():
        for entity_id in left:
            what = display_id(int(entity_id)) if entity == "reaction" and entity_id.isdigit() else entity_id
            problems.append(f"版本记录指向不存在的{'反应' if entity == 'reaction' else '文献'} {what}")
    for b in conn.execute("SELECT rowid, sha256, size FROM blobs ORDER BY rowid").fetchall():
        n_blobs += 1
        with conn.blobopen("blobs", "data", b["rowid"], readonly=True) as blob:
            size, sha = len(blob), hashlib.sha256()
            while chunk := blob.read(1 << 20):
                sha.update(chunk)
        if (sha.hexdigest(), size) != (b["sha256"], b["size"]):
            problems.append(f"PDF {b['sha256'][:12]}…：内容和 sha256 或大小不符")
    return problems, {"reactions": n_reactions, "papers": n_papers, "pdfs": n_blobs}


def cmd_check(args, conn) -> int:
    problems, n = check(conn)
    for p in problems:
        print(p)
    old = conn.execute("SELECT count(*) FROM reactions WHERE in_latest = 0").fetchone()[0]
    what = (f"检查了 {n['reactions']} 条反应" + (f"（其中 {old} 条是重新导入替换掉的旧版本）" if old else "")
            + f"、{n['papers']} 篇文献、{n['pdfs']} 个 PDF")
    print(f"{what}：发现 {len(problems)} 个问题" if problems else f"{what}：没有发现问题")
    return 1 if problems else 0


# ----------------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m curator", description="反应数据集管理")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="the database file (default: %(default)s)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import", help="import the pipeline's results from a work dir; a paper imported again"
                                      " replaces its reactions (the old ones stay as read-only old versions)")
    p.add_argument("--work", type=Path, default=DEFAULT_WORK, help="the pipeline's work dir (default: %(default)s)")
    p.add_argument("--papers", nargs="+", help="paper ids (default: every paper in the work dir)")
    p.add_argument("--dry-run", action="store_true", help="do everything, then roll it back; print the report")
    p.add_argument("--author", default=default_author(), help="recorded as the importer (default: %(default)s)")
    p.add_argument("--force", action="store_true",
                   help="replace a paper's reactions even if nothing changed since its last import")

    p = sub.add_parser("serve", help="serve the web front end and its API")
    p.add_argument("--host", default="127.0.0.1", help="0.0.0.0 lets other machines in (there is no login)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)

    p = sub.add_parser("export", help="export reactions to JSON Lines or a ZIP")
    p.add_argument("--out", type=Path, required=True, help="the file to write")
    p.add_argument("--format", choices=["jsonl", "zip"], help="default: zip for a .zip file, else jsonl")
    p.add_argument("--images", action="store_true", help="zip: add structure pictures rendered from the PDFs")
    p.add_argument("--papers", nargs="+", help="only these papers")
    p.add_argument("--status", nargs="+", help="only these review statuses")
    p.add_argument("--ids", nargs="+", help="only these reactions (123 or R000123)")
    p.add_argument("--include-excluded", action="store_true", help="also reactions reviewed as excluded")
    p.add_argument("--include-deleted", action="store_true", help="also deleted reactions")

    sub.add_parser("check", help="check that the reactions and papers agree with their revision log")

    p = sub.add_parser("backup", help="copy the database, consistently, to a new file")
    p.add_argument("--out", type=Path, required=True, help="the file to write (must not exist)")

    args = ap.parse_args(argv)
    if args.cmd == "import":
        return cmd_import(args)
    if args.cmd == "serve":
        return cmd_serve(args)
    if _missing(args.db):
        return 1
    try:
        conn = db.connect(args.db)
    except (sqlite3.DatabaseError, db.SchemaError) as e:
        print(f"无法打开数据库 {args.db}：{e}", file=sys.stderr)
        return 1
    try:
        return {"export": cmd_export, "check": cmd_check, "backup": cmd_backup}[args.cmd](args, conn)
    except store.StoreError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
