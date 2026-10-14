"""Runtime adapter: the only module that knows the pipeline is built with Hamilton.

Everything else in `server/` talks to this module in terms of plain dicts
(steps, edges, node results), so the runtime can later be swapped for
Windmill/Prefect without touching the API or the UI.

Pipeline code is written by the chat agent, so the API process never imports
it: the graph is described in a subprocess (cached per code version) and runs
happen in a subprocess too (see server/runs.py). Only those subprocesses call
`load_pipeline_modules`.

CLI (used by the API):  python -m server.runtime describe
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import inspect
import io
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import pandas as pd
from hamilton import driver
from hamilton.lifecycle import NodeExecutionHook

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT / "pipeline"
DESCRIBE_TIMEOUT_S = 60

_cache_lock = threading.Lock()
_describe_cache: dict[str, tuple] = {}


class PipelineLoadError(RuntimeError):
    """The pipeline code could not be imported or its graph could not be built."""


class RowContractError(RuntimeError):
    """A step broke the row convention (must hand on the full table with `_row_id`)."""


def pipeline_files(pipeline_dir: Path | None = None) -> list[Path]:
    return sorted(p for p in (pipeline_dir or PIPELINE_DIR).glob("*.py") if not p.stem.startswith("_"))


def pipeline_fingerprint(pipeline_dir: Path | None = None) -> str:
    h = hashlib.sha1(str(pipeline_dir or PIPELINE_DIR).encode())
    for path in sorted((pipeline_dir or PIPELINE_DIR).glob("*.py")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def load_pipeline_modules() -> list[ModuleType]:
    """Import every module in PIPELINE_DIR fresh. Only call this in a subprocess."""
    for name in [m for m in sys.modules if m == "pipeline" or m.startswith("pipeline.")]:
        del sys.modules[name]
    package = ModuleType("pipeline")
    package.__path__ = [str(PIPELINE_DIR)]  # lets steps do `from pipeline.clean import ...`
    sys.modules["pipeline"] = package
    modules = []
    for path in pipeline_files():
        name = f"pipeline.{path.stem}"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def build_driver(modules: list[ModuleType] | None = None, hooks: list[Any] = ()) -> driver.Driver:
    builder = driver.Builder().with_modules(*(modules or load_pipeline_modules()))
    if hooks:
        builder = builder.with_adapters(*hooks)
    return builder.build()


def describe_steps(pipeline_dir: Path | None = None) -> tuple[list[dict], list[dict], list[str]]:
    """(steps, edges, external_inputs), computed in a subprocess and cached per code version.

    Raises PipelineLoadError if the code cannot be loaded.
    """
    pipeline_dir = pipeline_dir or PIPELINE_DIR
    key = pipeline_fingerprint(pipeline_dir)
    with _cache_lock:
        cached = _describe_cache.get(key)
    if cached is None:
        if not pipeline_files(pipeline_dir):
            cached = ([], [], [])
        else:
            cached = _describe_in_subprocess(pipeline_dir)
        with _cache_lock:
            if len(_describe_cache) > 50:
                _describe_cache.clear()
            _describe_cache[key] = cached
    if isinstance(cached, PipelineLoadError):
        raise cached
    steps, edges, inputs = cached
    return [dict(s) for s in steps], [dict(e) for e in edges], list(inputs)


# Step code is written by the chat agent and runs as you. It gets a minimal environment, so API keys and
# tokens in your shell (ANTHROPIC_API_KEY, GH_TOKEN, ...) are not visible to it. See SECURITY.md.
SAFE_ENV_KEYS = {"PATH", "HOME", "USER", "LOGNAME", "LANG", "TMPDIR", "TEMP", "TMP", "TZ", "VIRTUAL_ENV",
                 "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "STEP_DELAY_S"}


def step_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in SAFE_ENV_KEYS or k.startswith(("LC_", "FLOWHAUS_"))}


def _describe_in_subprocess(pipeline_dir: Path):
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "server.runtime", "describe", str(pipeline_dir)],
            cwd=ROOT, capture_output=True, text=True, timeout=DESCRIBE_TIMEOUT_S, env=step_env(),
        )
    except subprocess.TimeoutExpired:
        return PipelineLoadError(f"Loading the pipeline code took longer than {DESCRIBE_TIMEOUT_S} seconds")
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return PipelineLoadError((proc.stderr or "unknown error").strip().splitlines()[-1][:500])
    if "error" in out:
        return PipelineLoadError(out["error"])
    return out["steps"], out["edges"], out["inputs"]


def describe_driver(dr: driver.Driver) -> tuple[list[dict], list[dict], list[str]]:
    """Describe an already-built driver (in the current process)."""
    variables = [v for v in dr.list_available_variables() if not v.is_external_input]
    step_ids = {v.name for v in variables}
    steps, edges, inputs = [], [], set()
    for v in variables:
        fn = v.originating_functions[0] if v.originating_functions else None
        source_file, line = None, None
        if fn is not None:
            with contextlib.suppress(TypeError, OSError, ValueError):
                source_file = str(Path(inspect.getsourcefile(fn)).resolve().relative_to(ROOT))
                line = inspect.getsourcelines(fn)[1]
        deps = list(v.required_dependencies) + list(v.optional_dependencies)
        steps.append(
            {
                "id": v.name,
                "label": v.tags.get("label"),
                "description": v.tags.get("description"),
                "group": v.tags.get("group"),
                "app": v.tags.get("app"),
                "file": source_file,
                "line": line,
                "inputs": [d for d in deps if d not in step_ids],
            }
        )
        for dep in deps:
            if dep in step_ids:
                edges.append({"source": dep, "target": v.name})
            else:
                inputs.add(dep)
    order = _topological_order([s["id"] for s in steps], edges)
    steps.sort(key=lambda s: order[s["id"]])
    return steps, edges, sorted(inputs)


def _topological_order(ids: list[str], edges: list[dict]) -> dict[str, int]:
    incoming = {i: 0 for i in ids}
    for e in edges:
        incoming[e["target"]] += 1
    ready = sorted(i for i, n in incoming.items() if n == 0)
    order: dict[str, int] = {}
    while ready:
        node = ready.pop(0)
        order[node] = len(order)
        for e in edges:
            if e["source"] == node:
                incoming[e["target"]] -= 1
                if incoming[e["target"]] == 0:
                    ready.append(e["target"])
    for i in ids:  # cycles should not happen in Hamilton, but never crash on them
        order.setdefault(i, len(order))
    return order


def step_source(step_id: str, pipeline_dir: Path | None = None) -> str | None:
    """Source of one step function (with decorators), read with `ast` so nothing is executed."""
    for path in pipeline_files(pipeline_dir):
        text = path.read_text()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == step_id:
                lines = text.splitlines()
                start = min([d.lineno for d in node.decorator_list] + [node.lineno]) - 1
                return "\n".join(lines[start:node.end_lineno])
    return None


# --------------------------------------------------------------------------- execution


@dataclass
class NodeEvent:
    """What the runtime reports about one step, independent of Hamilton."""

    node_id: str
    status: str  # running | success | failed
    input_frame: pd.DataFrame | None = None
    output_frame: pd.DataFrame | None = None
    started_at: float = 0.0
    duration_ms: int | None = None
    error: BaseException | None = None
    error_traceback: str | None = None
    stdout: str = ""
    calls: list = field(default_factory=list)


def _contract_problem(input_frame: pd.DataFrame | None, result: Any) -> str | None:
    if input_frame is None or "_row_id" not in input_frame.columns:
        return None
    if not isinstance(result, pd.DataFrame):
        return f"This step must hand on the contact table, but it returned {type(result).__name__}."
    if "_row_id" not in result.columns:
        return "This step removed the _row_id column, so rows can no longer be followed through the flow."
    if result["_row_id"].duplicated().any():
        return "This step produced duplicate _row_id values, so rows can no longer be told apart."
    return None


@dataclass
class _Capture(NodeExecutionHook):
    on_event: Callable[[NodeEvent], None]
    step_delay_s: float = 0.0
    _events: dict[str, NodeEvent] = field(default_factory=dict)
    _stdout: dict[str, tuple[contextlib.redirect_stdout, io.StringIO]] = field(default_factory=dict)
    _call_start: dict[str, int] = field(default_factory=dict)

    def run_before_node_execution(self, *, node_name, node_kwargs, **_):
        frame = next((v for v in node_kwargs.values() if isinstance(v, pd.DataFrame)), None)
        # Deep copy: a step that edits its input in place must not rewrite our "before" picture.
        frame = frame.copy(deep=True) if frame is not None else None
        event = NodeEvent(node_name, "running", input_frame=frame, started_at=time.time())
        self._events[node_name] = event
        self._call_start[node_name] = len(_connector_calls())
        self.on_event(event)
        if self.step_delay_s:
            time.sleep(self.step_delay_s)
        buffer = io.StringIO()
        redirect = contextlib.redirect_stdout(buffer)
        redirect.__enter__()
        self._stdout[node_name] = (redirect, buffer)

    def run_after_node_execution(self, *, node_name, result, error, success, **_):
        redirect, buffer = self._stdout.pop(node_name, (None, None))
        if redirect is not None:
            redirect.__exit__(None, None, None)
        event = self._events.get(node_name) or NodeEvent(node_name, "running", started_at=time.time())
        event.duration_ms = int((time.time() - event.started_at) * 1000)
        event.stdout = buffer.getvalue() if buffer else ""
        event.calls = _connector_calls()[self._call_start.pop(node_name, 0):]
        problem = _contract_problem(event.input_frame, result) if success else None
        if success and not problem:
            event.status = "success"
            event.output_frame = result if isinstance(result, pd.DataFrame) else None
            self.on_event(event)
            return
        if problem:
            error = RowContractError(problem)
            event.error_traceback = problem
        else:
            event.error_traceback = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        event.status = "failed"
        event.error = error
        self.on_event(event)
        if problem:
            raise error  # stop the run here instead of feeding broken data to later steps


def _connector_calls() -> list:
    try:
        from connectors import CALLS
    except ImportError:
        return []
    return CALLS


def execute(
    inputs: dict[str, Any],
    on_event: Callable[[NodeEvent], None],
    step_delay_s: float = 0.0,
) -> list[dict]:
    """Run every step. Raises if a step fails (after reporting it through on_event)."""
    try:
        modules = load_pipeline_modules()
        capture = _Capture(on_event=on_event, step_delay_s=step_delay_s)
        dr = build_driver(modules, hooks=[capture])
    except Exception as exc:
        raise PipelineLoadError(f"{type(exc).__name__}: {exc}") from exc
    steps, _, needed = describe_driver(dr)
    missing = [n for n in needed if n not in inputs]
    if missing:
        raise PipelineLoadError(f"The first step expects an input called {', '.join(missing)}, which the runner doesn't provide. "
                                f"Available inputs: {', '.join(inputs)}.")
    dr.execute([s["id"] for s in steps], inputs={k: v for k, v in inputs.items() if k in needed})
    return steps


def _cli_describe(pipeline_dir: str | None) -> None:
    global PIPELINE_DIR
    if pipeline_dir:
        PIPELINE_DIR = Path(pipeline_dir)
    try:
        with contextlib.redirect_stdout(io.StringIO()):  # module-level prints must not break the JSON line
            steps, edges, inputs = describe_driver(build_driver())
        print(json.dumps({"steps": steps, "edges": edges, "inputs": inputs}))
    except BaseException as exc:  # noqa: BLE001 - report anything, including SystemExit from user code
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "describe":
        _cli_describe(sys.argv[2] if len(sys.argv) > 2 else None)
