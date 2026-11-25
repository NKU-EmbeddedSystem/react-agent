"""Command-line entry point: python -m pipeline {list,run,publish,status,consolidate}."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import DEFAULT_DATA_DIR, DEFAULT_WORK_DIR, ExtractConfig, LocateConfig, PipelineConfig
from .papers import PaperWorkspace, discover_papers
from .runner import run
from .steps import STEPS


def _select(papers, ids):
    if not ids:
        return papers
    by_id = {p.paper_id: p for p in papers}
    missing = [i for i in ids if i not in by_id]
    if missing:
        sys.exit(f"unknown paper ids: {missing}; available: {list(by_id)}")
    return [by_id[i] for i in ids]


def cmd_list(args, cfg):
    for p in discover_papers(cfg.data_dir):
        si = p.si_pdf.name if p.si_pdf else "-"
        print(f"{p.paper_id:>4}  main: {p.main_pdf.name}\n      si:   {si}")


def cmd_run(args, cfg):
    papers = _select(discover_papers(cfg.data_dir), args.papers)
    steps = args.steps or list(STEPS)
    outcomes = run(papers, steps, cfg, jobs=args.jobs, force=args.force)
    failed = [o["paper_id"] for o in outcomes
              if any(r["status"] == "failed" for r in o["results"].values())]
    if failed:
        sys.exit(f"failed papers: {failed}")


def cmd_publish(args, cfg):
    import logging

    from .steps.s2_extract import republish

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for p in _select(discover_papers(cfg.data_dir), args.papers):
        summary = republish(PaperWorkspace(p, cfg.work_dir), cfg, logging.getLogger(f"pipeline.publish.{p.paper_id}"))
        print(f"[{p.paper_id}] {summary}")


def cmd_status(args, cfg):
    papers = _select(discover_papers(cfg.data_dir), args.papers)
    for p in papers:
        state = PaperWorkspace(p, cfg.work_dir).load_state()
        cells = []
        for name in STEPS:
            rec = state["steps"].get(name)
            cells.append(f"{name}={rec['status'] if rec else 'pending'}")
        print(f"{p.paper_id:>4}  " + "  ".join(cells))


def cmd_consolidate(args, cfg):
    import json
    from .consolidate import run, republish

    if args.republish:
        print(json.dumps(republish(args.output, args.paper), ensure_ascii=False, indent=2))
        return
    if not args.inputs:
        raise ValueError("--inputs is required for a model run")
    lanes = []
    for value in args.inputs:
        lane, separator, path = value.partition("=")
        if not separator or not path:
            raise ValueError("--inputs expects lane=/absolute/work/root")
        lanes.append((lane, Path(path)))
    report = run(lanes, args.paper, args.output, batch_size=args.batch_size, max_pages=args.max_pages,
                 max_calls=args.max_calls, limit=args.review_limit, timeout_s=args.timeout)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pipeline")
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA_DIR, help="dir with one sub-dir per paper")
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK_DIR, help="output workspace dir")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list discovered papers")

    p_run = sub.add_parser("run", help="run pipeline steps")
    p_run.add_argument("--papers", nargs="*", help="paper ids (default: all)")
    p_run.add_argument("--steps", nargs="*", choices=list(STEPS), help="steps (default: all)")
    p_run.add_argument("--jobs", type=int, default=1, help="papers processed in parallel")
    p_run.add_argument("--force", action="store_true", help="re-run even if up to date")
    g = p_run.add_argument_group("locate step")
    g.add_argument("--docs", nargs="+", choices=["main", "si"], default=list(LocateConfig.docs),
                   help="documents searched for reaction regions (default: %(default)s)")
    g = p_run.add_argument_group("extract step")
    g.add_argument("--blocks", nargs="*", help="only these blocks: region_id/block_id or region_id")
    g.add_argument("--kinds", nargs="*", help="only blocks of these kinds")
    g.add_argument("--limit", type=int, help="spell out at most this many entries per block")
    g.add_argument("--no-entries", action="store_true",
                   help="stop after the block reader has spelled out the entries into reactions")
    g.add_argument("-n", "--concurrency", type=int, default=ExtractConfig.concurrency,
                   help="Codex sessions at once within a paper (default: %(default)s)")
    g.add_argument("--retries", type=int, default=ExtractConfig.retries, metavar="N",
                   help="retry a block whose reader failed, up to N more attempts in fresh sessions "
                        "(default: %(default)s; 0 disables)")

    p_pub = sub.add_parser("publish", help="rebuild the extract step's outputs from disk (no Codex)")
    p_pub.add_argument("--papers", nargs="+", required=True, help="paper ids")

    p_st = sub.add_parser("status", help="show step status per paper")
    p_st.add_argument("--papers", nargs="*")

    p_co = sub.add_parser("consolidate", help="opt-in bounded review and summary of independent extraction lanes")
    p_co.add_argument("--inputs", nargs="+", help="lane=work-root (each contains paper ID directories)")
    p_co.add_argument("--republish", action="store_true", help="revalidate retained answers and rebuild views; no model calls")
    p_co.add_argument("--paper", required=True, help="exactly one paper ID; no default all-papers run")
    p_co.add_argument("--output", type=Path, required=True, help="new import workspace, separate from inputs")
    p_co.add_argument("--batch-size", type=int, default=8)
    p_co.add_argument("--max-pages", type=int, default=6, help="maximum supplied source pages per review batch")
    p_co.add_argument("--max-calls", type=int, default=10, help="maximum new model calls, including summary")
    p_co.add_argument("--timeout", type=int, default=1800, help="seconds one model call may take")
    p_co.add_argument("--review-limit", type=int, help="pilot only: review at most this many records (marked partial)")

    args = ap.parse_args(argv)
    extract, locate = ExtractConfig(), LocateConfig()
    if args.cmd == "run":
        locate = LocateConfig(docs=tuple(d for d in ("main", "si") if d in args.docs))
        extract = ExtractConfig(concurrency=args.concurrency, limit=args.limit, entries=not args.no_entries,
                                blocks=tuple(args.blocks) if args.blocks else None,
                                kinds=tuple(args.kinds) if args.kinds else None, retries=args.retries)
    cfg = PipelineConfig(data_dir=args.data.resolve(), work_dir=args.work.resolve(), locate=locate,
                         extract=extract)
    commands = {"list": cmd_list, "run": cmd_run, "publish": cmd_publish, "status": cmd_status,
                "consolidate": cmd_consolidate}
    commands[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
