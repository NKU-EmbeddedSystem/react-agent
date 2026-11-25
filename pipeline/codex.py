"""Thin wrapper around `codex exec` for schema-constrained, non-interactive runs.

Every call runs from the repo root so Codex picks up the repo-local skills in
.agents/skills; the first message of a session names `.agents/worker-guide.md`, which carries the
workspace rules and the page-tool reference. The JSONL event stream is appended to a log file; the
final (schema-conforming) message is read back from the -o file.

The commands of a session run in a permission profile (`_sandbox`): the whole disk is readable and
only the directories the caller names (the paper's scratch directories) and the temp dir are
writable. The workspace-write mode would let a session write anywhere in the repo, work/ included:
its task file, other blocks' results.

Sessions get no collaboration tools (`_no_agents`): no sub-agents, no messages to other agents.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import REPO_ROOT, CodexConfig


class CodexError(RuntimeError):
    pass


@dataclass
class CodexResult:
    data: dict
    thread_id: str | None
    usage: dict | None
    # The final message was not one JSON object (prose around it, the object repeated or streamed in
    # pieces) and `data` is the object taken from it (`final_object`).
    salvaged: bool = False


def _overrides(cfg: CodexConfig) -> list[str]:
    args = []
    if cfg.model:
        args += ["-m", cfg.model]
    if cfg.reasoning_effort:
        args += ["-c", f'model_reasoning_effort="{cfg.reasoning_effort}"']
    return args


PROFILE = "pipeline"
WORKER_GUIDE = ".agents/worker-guide.md"


def with_worker_guide(prompt: str) -> str:
    """The workspace rules and the page-tool reference are a file, not the root AGENTS.md: a
    session is told to read it before it starts."""
    if WORKER_GUIDE in prompt:
        return prompt
    return f"Read {WORKER_GUIDE} first; it holds the rules of the workspace and the page tools.\n\n{prompt}"


def _sandbox(writable) -> list[str]:
    roots = {"/": "read", ":tmpdir": "write", "/tmp": "write"}
    for path in writable:
        path = Path(path).resolve()
        path.mkdir(parents=True, exist_ok=True)
        roots[str(path)] = "write"
    table = ", ".join(f"{json.dumps(k)} = {json.dumps(v)}" for k, v in roots.items())
    return ["-c", f'default_permissions="{PROFILE}"', "-c", f"permissions.{PROFILE}.filesystem={{{table}}}"]


@functools.cache
def _no_agents() -> list[str]:
    """Codex offers the model collaboration tools (spawn_agent, send_message, wait_agent...) when the
    `multi_agent` feature is on (v1) or the model's entry in Codex's model catalog has a
    `multi_agent_version` (v2, which no feature flag removes). The pipeline already runs its sessions
    side by side, and the tools only lead a session astray: sub-agents that write answer drafts where
    they do not belong, a session that messages agents that do not exist until it times out. So the
    feature is switched off, and the catalog is a copy of Codex's model cache ($CODEX_HOME/
    models_cache.json) whose models have no multi_agent_version. Without a cache only the feature is
    switched off."""
    args = ["-c", "features.multi_agent=false"]
    cache = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "models_cache.json"
    try:
        catalog = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return args
    for model in catalog.get("models", []):
        model["multi_agent_version"] = None
    text = json.dumps(catalog, ensure_ascii=False, sort_keys=True)
    name = f"model_catalog_{hashlib.sha256(text.encode()).hexdigest()[:16]}.json"
    path = Path(tempfile.gettempdir()) / "react-agent" / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    return args + ["-c", f"model_catalog_json={json.dumps(str(path))}"]


def _images(images) -> list[str]:
    args = []
    for image in images or []:
        path = Path(image).resolve()
        if not path.is_file() or path.stat().st_size == 0:
            raise CodexError(f"image attachment is missing or empty: {path}")
        args += ["-i", str(path)]
    return args


@functools.cache
def page_environment(root: Path = REPO_ROOT):
    """Fail before a paid call if the exact interpreter named by worker skills cannot run tools."""
    python = root / ".venv/bin/python"
    if not python.is_file():
        raise CodexError(f"worker page-tool interpreter is missing: {python}; do not fall back to system Python")
    result = subprocess.run([str(python), "-c", "import pymupdf, PIL, numpy; import pipeline.pagetools.layout"],
                            cwd=root, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise CodexError("worker page-tool preflight failed: " + result.stderr[-2000:])


def _record_attachments(out_json, images, cfg):
    """Local attachment evidence, explicitly not an upstream receipt confirmation."""
    from .papers import write_json
    attachments = []
    for image in images or []:
        path = Path(image).resolve()
        data = path.read_bytes()
        attachments.append({"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    path = Path(out_json).with_suffix(".attachments.json")
    call = {"model": cfg.identity(), "attachments": attachments, "upstream_receipt_verified": False}
    previous = json.loads(path.read_text()) if path.exists() else {}
    calls = previous.get("calls", [previous] if previous else [])
    write_json(path, {**call, "calls": [*calls, call]})


def run_codex(prompt: str, *, schema: Path, out_json: Path, events_log: Path,
              cfg: CodexConfig, images=None, timeout: int | None = None,
              writable=(), cwd: Path = REPO_ROOT) -> CodexResult:
    page_environment()
    # "--" keeps the prompt from being read as one more value of the variadic -i option.
    cmd = ["codex", "exec", "-C", str(cwd), *_sandbox(writable), *_no_agents(),
           "--output-schema", str(schema), "-o", str(out_json), "--json",
           *_overrides(cfg), *_images(images), "--", with_worker_guide(prompt)]
    _record_attachments(out_json, images, cfg)
    return _invoke(cmd, out_json, events_log, timeout or cfg.timeout_s, cwd, schema)


def resume_codex(thread_id: str, prompt: str, *, schema: Path, out_json: Path,
                 events_log: Path, cfg: CodexConfig, images=None, timeout: int | None = None,
                 writable=(), cwd: Path = REPO_ROOT) -> CodexResult:
    page_environment()
    cmd = ["codex", "exec", "resume",
           "--output-schema", str(schema), "-o", str(out_json), "--json",
           *_sandbox(writable), *_no_agents(), *_overrides(cfg), *_images(images),
           "--", thread_id, prompt]
    _record_attachments(out_json, images, cfg)
    return _invoke(cmd, out_json, events_log, timeout or cfg.timeout_s, cwd, schema)


def final_object(text: str, required=()) -> dict | None:
    """The answer in a final message that is not one JSON object. A provider that does not enforce
    the output schema lets the model put prose before the object, repeat it, or stream it in pieces
    with the complete one last. Takes the last top-level object that has every `required` key, else
    the largest one; None when there is no object at all."""
    decoder, objects, i = json.JSONDecoder(), [], text.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict):
            objects.append((obj, end - i))
        i = text.find("{", end)
    complete = [obj for obj, _ in objects if all(k in obj for k in required)]
    if complete:
        return complete[-1]
    return max(objects, key=lambda x: x[1])[0] if objects else None


def _invoke(cmd: list[str], out_json: Path, events_log: Path, timeout: int,
            cwd: Path, schema: Path | None = None) -> CodexResult:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    events_log.parent.mkdir(parents=True, exist_ok=True)
    if out_json.exists():
        out_json.unlink()
    start = events_log.stat().st_size if events_log.exists() else 0

    with open(events_log, "a", encoding="utf-8") as events:
        try:
            # stdin must be closed: with an open pipe `codex exec` waits for extra input forever.
            proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=events,
                                  stderr=subprocess.PIPE, text=True, cwd=cwd, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise CodexError(f"codex timed out after {timeout}s") from exc

    thread_id, usage, failures = _scan_events(events_log, start)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise CodexError(f"codex exited {proc.returncode}; {failures}\n{tail}")
    if not out_json.exists():
        raise CodexError(f"codex produced no final message; {failures}")
    text = out_json.read_text(encoding="utf-8")
    try:
        return CodexResult(data=json.loads(text), thread_id=thread_id, usage=usage)
    except json.JSONDecodeError as exc:
        required = json.loads(schema.read_text(encoding="utf-8")).get("required", []) if schema else []
        data = final_object(text, required)
        if data is None:
            raise CodexError(f"final message is not valid JSON: {exc}") from exc
        return CodexResult(data=data, thread_id=thread_id, usage=usage, salvaged=True)


def _scan_events(events_log: Path, start: int):
    thread_id, usage, failures = None, None, []
    with open(events_log, encoding="utf-8") as f:
        f.seek(start)
        for line in f:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = ev.get("type")
            if kind == "thread.started":
                thread_id = ev.get("thread_id")
            elif kind == "turn.completed":
                usage = ev.get("usage")
            elif kind in ("turn.failed", "error"):
                failures.append(ev.get("error") or ev.get("message") or ev)
    return thread_id, usage, failures
