"""Runs pipeline steps over papers, one worker process per paper."""

from __future__ import annotations

import logging
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

from .config import PipelineConfig
from .papers import Paper, PaperWorkspace, now_iso, sha256_file
from .steps import STEPS


def _paper_logger(ws: PaperWorkspace) -> logging.Logger:
    ws.log_dir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(f"pipeline.paper.{ws.paper.paper_id}")
    log.setLevel(logging.INFO)
    log.propagate = False
    for h in list(log.handlers):
        log.removeHandler(h)
        h.close()
    handler = logging.FileHandler(ws.log_dir / "pipeline.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    return log


def _earlier(name: str) -> list[str]:
    order = list(STEPS)
    return order[:order.index(name)]


def has_failures(summary: dict | None) -> bool:
    """A step that finished with failed sessions (its summary counts them as `<what>_failed`): running it
    again redoes those and takes everything else from its cache. Sessions a filter left out (`--blocks`,
    `--limit`) are not failures."""
    return any(isinstance(v, int) and v > 0 for k, v in (summary or {}).items() if k.endswith("_failed"))


def run_paper(paper: Paper, step_names: list[str], cfg: PipelineConfig, force: bool) -> dict:
    ws = PaperWorkspace(paper, cfg.work_dir)
    log = _paper_logger(ws)
    state = ws.load_state()
    sources = {
        doc: {"pdf": str(path), "sha256": sha256_file(path)}
        for doc, path in paper.documents().items()
    }
    state["documents"] = sources
    results = {}
    upstream_ran = False  # once a step re-runs, everything after it must re-run too

    for name in step_names:
        step = STEPS[name]
        params = step.params(cfg)
        prev = state["steps"].get(name, {})
        # A step is stale if any earlier step finished after it started (e.g. preprocess re-run alone).
        upstream_done = [state["steps"].get(s, {}).get("finished_at", "") for s in _earlier(name)]
        up_to_date = (
            prev.get("status") == "done"
            and prev.get("version") == step.VERSION
            and prev.get("params") == params
            and prev.get("sources") == sources
            and all(t <= prev.get("started_at", "") for t in upstream_done)
            and not has_failures(prev.get("summary"))
        )
        if up_to_date and not force and not upstream_ran:
            log.info("step %s: up to date, skipped", name)
            results[name] = {"status": "skipped"}
            continue

        record = {"status": "running", "version": step.VERSION, "params": params,
                  "sources": sources, "started_at": now_iso()}
        state["steps"][name] = record
        ws.save_state(state)
        log.info("step %s: start", name)
        t0 = time.time()
        try:
            summary = step.run(ws, cfg, log, force=force)
        except Exception as exc:
            log.error("step %s failed:\n%s", name, traceback.format_exc())
            record.update(status="failed", error=f"{type(exc).__name__}: {exc}",
                          finished_at=now_iso(), seconds=round(time.time() - t0, 1))
            ws.save_state(state)
            results[name] = {"status": "failed", "error": record["error"]}
            break  # later steps depend on this one
        record.update(status="done", finished_at=now_iso(),
                      seconds=round(time.time() - t0, 1), summary=summary)
        ws.save_state(state)
        log.info("step %s: done in %.1fs", name, record["seconds"])
        results[name] = {"status": "done", "seconds": record["seconds"], "summary": summary}
        upstream_ran = True

    return {"paper_id": paper.paper_id, "results": results}


def run(papers: list[Paper], step_names: list[str], cfg: PipelineConfig,
        jobs: int = 1, force: bool = False, echo=print) -> list[dict]:
    unknown = [s for s in step_names if s not in STEPS]
    if unknown:
        raise ValueError(f"unknown steps {unknown}; available: {list(STEPS)}")
    ordered = [s for s in STEPS if s in step_names]

    outcomes = []
    if jobs <= 1 or len(papers) <= 1:
        for paper in papers:
            echo(f"[{paper.paper_id}] running {ordered}")
            outcomes.append(run_paper(paper, ordered, cfg, force))
            echo(_format(outcomes[-1]))
        return outcomes

    with ProcessPoolExecutor(max_workers=min(jobs, len(papers))) as pool:
        futures = {pool.submit(run_paper, p, ordered, cfg, force): p for p in papers}
        echo(f"submitted {len(futures)} papers, steps={ordered}, jobs={min(jobs, len(papers))}")
        for fut in as_completed(futures):
            paper = futures[fut]
            try:
                outcome = fut.result()
            except Exception as exc:  # worker crashed before it could record state
                outcome = {"paper_id": paper.paper_id,
                           "results": {"_worker": {"status": "failed", "error": repr(exc)}}}
            outcomes.append(outcome)
            echo(_format(outcome))
    return outcomes


def _format(outcome: dict) -> str:
    parts = []
    for name, r in outcome["results"].items():
        if r["status"] == "done":
            parts.append(f"{name}=done({r['seconds']}s) {r.get('summary')}")
        elif r["status"] == "failed":
            parts.append(f"{name}=FAILED {r['error']}")
        else:
            parts.append(f"{name}={r['status']}")
    return f"[{outcome['paper_id']}] " + "; ".join(parts)
