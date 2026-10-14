"""Run store + runner: executes the pipeline and writes runs/<run_id>.json.

CLI:  uv run python -m server.runs [--input data/contacts_broken.csv]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

from server import maps, runtime

ROOT = runtime.ROOT
RUNS_DIR = ROOT / "runs"
DATA_DIR = ROOT / "data"
DEFAULT_INPUT = "data/contacts.csv"
OUTPUT_PATH = "output/contacts_clean.csv"
SAMPLE_ROWS = 10
MAX_REJECTED_SAMPLES = 200
STALE_AFTER_S = 300
RUN_TIMEOUT_S = 120

INTERNAL = ("_row_id", "_rejected_reason")
LIVE_FLOW = "contact-cleaning"
FLOWS_DIR = ROOT / "flows"
MAX_CALLS_PER_STEP = 25
MAX_IO_ITEMS = 500


def flow_paths(flow_id: str | None) -> dict:
    """Where a flow keeps its code, map, input data and output."""
    if not flow_id or flow_id == LIVE_FLOW:
        return {"code": runtime.PIPELINE_DIR, "map": maps.FLOW_MAP_PATH, "data": DATA_DIR,
                "output": ROOT / OUTPUT_PATH, "config": {}}
    base = FLOWS_DIR / flow_id
    if not (base / "flow.yaml").exists() or "/" in flow_id or flow_id.startswith("."):
        raise ValueError(f"Unknown flow: {flow_id}")
    return {"code": base / "steps", "map": base / "flow.yaml", "data": base / "data", "output": base / "output",
            "config": maps.read_yaml(base / "flow.yaml")}

_id_lock = threading.Lock()
_parse_cache: dict[Path, tuple[float, int, dict]] = {}


# --------------------------------------------------------------------------- store


def new_run_id(flow_id: str | None = None) -> str:
    """Reserve a unique run id by creating its file (safe across threads and processes)."""
    RUNS_DIR.mkdir(exist_ok=True)
    prefix = f"{flow_id}--" if flow_id and flow_id != LIVE_FLOW else ""
    base = prefix + datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    with _id_lock:
        run_id, n = base, 2
        while True:
            try:
                with open(RUNS_DIR / f"{run_id}.json", "x") as f:
                    f.write(json.dumps({"run_id": run_id, "flow_id": flow_id or LIVE_FLOW, "status": "running",
                                        "started_at": _now(), "nodes": {}}))
                return run_id
            except FileExistsError:
                run_id, n = f"{base}-{n}", n + 1


def _write(run: dict) -> None:
    RUNS_DIR.mkdir(exist_ok=True)
    path = RUNS_DIR / f"{run['run_id']}.json"
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(run, indent=2, default=str))
    os.replace(tmp, path)


def _load(path: Path) -> dict | None:
    """Parse a run file, cached by mtime/size. Corrupt files are skipped, never fatal."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    cached = _parse_cache.get(path)
    if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
        return cached[2]
    try:
        run = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    if not isinstance(run, dict) or "run_id" not in run:
        return None
    _parse_cache[path] = (stat.st_mtime, stat.st_size, run)
    return run


def get_run(run_id: str) -> dict | None:
    if "/" in run_id or "\\" in run_id or run_id.startswith("."):
        return None
    path = RUNS_DIR / f"{run_id}.json"
    run = _load(path)
    if run is None:
        return None
    if run.get("status") == "running" and time.time() - path.stat().st_mtime > STALE_AFTER_S:
        run = _mark_failed(dict(run), "The run stopped without finishing.")
    return run


def _mark_failed(run: dict, message: str) -> dict:
    run["status"] = "failed"
    run["error"] = run.get("error") or {"node_id": None, "message": message}
    run["nodes"] = {nid: ({**n, "status": "failed"} if n.get("status") == "running" else n)
                    for nid, n in (run.get("nodes") or {}).items()}
    run["finished_at"] = run.get("finished_at") or _now()
    return run


def list_runs(flow_id: str = LIVE_FLOW) -> list[dict]:
    runs = []
    for path in RUNS_DIR.glob("*.json"):
        run = get_run(path.stem)
        if run is None or (run.get("flow_id") or LIVE_FLOW) != flow_id:
            continue
        runs.append({k: run.get(k) for k in ("run_id", "flow_id", "status", "started_at", "finished_at", "input_file",
                                              "trigger", "summary", "error")})
    runs.sort(key=lambda r: (r.get("started_at") or "", r["run_id"]), reverse=True)
    return runs


def latest_run_id(flow_id: str = LIVE_FLOW) -> str | None:
    runs = list_runs(flow_id)
    return runs[0]["run_id"] if runs else None


def list_inputs(flow_id: str = LIVE_FLOW) -> list[str]:
    data = flow_paths(flow_id)["data"]
    return sorted(str(p.relative_to(ROOT)) for p in data.glob("*") if p.suffix in (".csv", ".json"))


def default_input(flow_id: str = LIVE_FLOW) -> str | None:
    if flow_id == LIVE_FLOW:
        return DEFAULT_INPUT
    paths = flow_paths(flow_id)
    configured = paths["config"].get("sample_input")
    if configured and (paths["map"].parent / configured).exists():
        return str((paths["map"].parent / configured).relative_to(ROOT))
    inputs = list_inputs(flow_id)
    return inputs[0] if inputs else None


def resolve_input(input_file: str | None, flow_id: str = LIVE_FLOW) -> str:
    rel = input_file or default_input(flow_id)
    if not rel:
        raise ValueError("This flow has no input file yet. Add sample data to its data/ folder.")
    path = (ROOT / rel).resolve()
    data = flow_paths(flow_id)["data"].resolve()
    if data not in path.parents or path.suffix not in (".csv", ".json") or not path.exists():
        raise ValueError(f"Unknown input file: {rel}")
    return str(path.relative_to(ROOT))


# --------------------------------------------------------------------------- samples


def _clean(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if hasattr(v, "item"):  # numpy scalar -> python
        v = v.item()
    if isinstance(v, float) and v.is_integer():  # ints turned into floats by missing values
        return int(v)
    return v


def _records(df: pd.DataFrame, ids: list) -> list[dict]:
    if df is None or "_row_id" not in df.columns:
        return []
    rows = df[df["_row_id"].isin(ids)].copy()
    rows["_order"] = rows["_row_id"].map({v: i for i, v in enumerate(ids)})
    rows = rows.sort_values("_order").drop(columns="_order")
    return [{k: _clean(v) for k, v in rec.items()} for rec in rows.to_dict(orient="records")]


def _active_ids(df: pd.DataFrame | None) -> set:
    if df is None or "_row_id" not in df.columns:
        return set()
    if "_rejected_reason" not in df.columns:
        return set(df["_row_id"])
    return set(df.loc[df["_rejected_reason"].isna(), "_row_id"])


def _same(a, b) -> bool:
    a, b = _clean(a), _clean(b)
    return a == b or (a is not None and b is not None and str(a) == str(b))


def newly_rejected(before: pd.DataFrame, after: pd.DataFrame | None) -> list[tuple]:
    """(row_id, reason) for rows active before the step and flagged (or dropped) after it."""
    before_active = _active_ids(before)
    after_active = _active_ids(after)
    reasons = {}
    if after is not None and "_row_id" in after.columns and "_rejected_reason" in after.columns:
        reasons = dict(zip(after["_row_id"], after["_rejected_reason"]))
    after_ids = set(after["_row_id"]) if after is not None and "_row_id" in after.columns else set()
    out = []
    for rid in before["_row_id"]:
        if rid in before_active and rid not in after_active:
            reason = reasons.get(rid) if rid in after_ids else "Left out by this step without a reason"
            out.append((rid, _clean(reason) or "Flagged without a reason"))
    return out


def compare(before: pd.DataFrame | None, after: pd.DataFrame | None) -> dict:
    """Counts + paired samples between the frame entering and leaving a step (or group)."""
    result = {"rows_in": None, "rows_out": None, "rows_rejected": 0, "rows_changed": 0,
              "sample_in": [], "sample_out": [], "rejected_samples": [], "reject_reasons": {}}
    if after is None:
        if before is not None:
            result["rows_in"] = len(_active_ids(before)) if "_row_id" in before.columns else len(before)
            if "_row_id" in before.columns:  # failed step: show what it received
                result["sample_in"] = _records(before, list(before["_row_id"])[:SAMPLE_ROWS])
        return result
    result["rows_out"] = len(_active_ids(after)) if "_row_id" in after.columns else len(after)
    if before is None or "_row_id" not in before.columns:
        # First step: nothing to compare against, just show what came out.
        result["rows_in"] = result["rows_out"]
        ids = list(after["_row_id"])[:SAMPLE_ROWS] if "_row_id" in after.columns else []
        result["sample_out"] = _records(after, ids)
        return result

    before_active = _active_ids(before)
    result["rows_in"] = len(before_active)
    after_ids = set(after["_row_id"]) if "_row_id" in after.columns else set()
    rejected = newly_rejected(before, after)
    rejected_ids = [rid for rid, _ in rejected]

    # Union of columns: a step may add fields (e.g. enrichment), which counts as a change.
    visible = [c for c in dict.fromkeys([*before.columns, *after.columns]) if c not in INTERNAL]
    b = before.drop_duplicates("_row_id").set_index("_row_id")
    a = after.drop_duplicates("_row_id").set_index("_row_id") if "_row_id" in after.columns else None

    def cell(frame, rid, c):
        return frame.at[rid, c] if c in frame.columns else None

    changed = []
    if a is not None:
        for rid in before["_row_id"]:
            if rid in a.index and rid in before_active and any(not _same(cell(b, rid, c), cell(a, rid, c)) for c in visible):
                changed.append(rid)
    result["rows_changed"] = len(changed)

    rejected_records = []
    for rid, reason in rejected[:MAX_REJECTED_SAMPLES]:
        rec = _records(before, [rid])[0]
        after_rec = _records(after, [rid])[0] if rid in after_ids else None
        rejected_records.append({"_row_id": rid, "reason": reason, "before": rec, "after": after_rec})
    result["rows_rejected"] = len(rejected)
    result["rejected_samples"] = rejected_records
    result["reject_reasons"] = dict(Counter(reason for _, reason in rejected).most_common())

    # Prefer rows that were rejected or changed, then fill with unchanged ones.
    picked: list = []
    for rid in rejected_ids[:4] + changed + list(before["_row_id"]):
        if rid not in picked and (rid in before_active or rid in rejected_ids):
            picked.append(rid)
        if len(picked) >= SAMPLE_ROWS:
            break
    result["sample_in"] = _records(before, picked)
    result["sample_out"] = _records(after, [i for i in picked if i in after_ids])
    return result


def explain_error(exc: BaseException, frame: pd.DataFrame | None) -> str:
    if isinstance(exc, runtime.RowContractError):
        return str(exc)
    if isinstance(exc, KeyError):
        missing = exc.args[0] if exc.args else "?"
        cols = ", ".join(c for c in (frame.columns if frame is not None else []) if c not in INTERNAL)
        msg = f"The data has no column called '{missing}'."
        return msg + (f" Columns that do exist: {cols}." if cols else "")
    if isinstance(exc, FileNotFoundError):
        return f"A file could not be found: {exc.filename or exc}"
    return f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------- runner


def add_step_log(node: dict, t: str, stdout: str = "", error: str | None = None, items: str = "items") -> None:
    """Plain-English log lines for a finished step (shared by the real runner and sample flows)."""
    log = node["log"]
    for line in stdout.splitlines():
        log.append({"t": t, "level": "print", "text": line})
    if error:
        log.append({"t": t, "level": "error", "text": f"Step failed: {error}"})
        return
    if node["rows_in"] is not None:
        log.append({"t": t, "level": "info", "text": f"Received {node['rows_in']} {items}"})
    if node["rows_changed"]:
        log.append({"t": t, "level": "info", "text": f"Changed {node['rows_changed']} {items}"})
    for reason, n in node["reject_reasons"].items():
        log.append({"t": t, "level": "warn", "text": f"Skipped {n}: {reason}"})
    log.append({"t": t, "level": "info", "text": f"Passed on {node['rows_out']} {items} in {node['duration_ms']} ms"})


def _empty_node(step: dict) -> dict:
    return {"status": "not_run", "label": step.get("label") or step["id"], "group": step.get("group"),
            "duration_ms": None, "rows_in": None, "rows_out": None, "rows_rejected": 0, "rows_changed": 0,
            "sample_in": [], "sample_out": [], "rejected_samples": [], "reject_reasons": {},
            "log": [], "error": None}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_run_stub(run_id: str, input_file: str, trigger: str, flow_id: str = LIVE_FLOW) -> dict:
    try:
        steps, _, _ = runtime.describe_steps(flow_paths(flow_id)["code"])
    except Exception:
        steps = []
    run = {"run_id": run_id, "flow_id": flow_id, "status": "running", "started_at": _now(), "finished_at": None,
           "input_file": input_file, "trigger": trigger, "error": None, "summary": None,
           "nodes": {s["id"]: _empty_node(s) for s in steps}, "groups": {}, "contacts": []}
    _write(run)
    return run


def execute_run(run_id: str, input_file: str | None = None, trigger: str = "cli",
                step_delay_s: float | None = None, flow_id: str = LIVE_FLOW) -> dict:
    """Run a flow in this process and keep runs/<run_id>.json up to date."""
    paths = flow_paths(flow_id)
    config = paths["config"]
    items = (config.get("terms") or {}).get("items") or ("contacts" if flow_id == LIVE_FLOW else "items")
    runtime.PIPELINE_DIR = paths["code"]  # this process runs exactly one flow
    input_file = resolve_input(input_file, flow_id)
    if step_delay_s is None:
        step_delay_s = float(os.environ.get("STEP_DELAY_S", "0.35"))
    existing = get_run(run_id)
    if existing and existing.get("input_file") == input_file and existing.get("nodes"):
        run = existing  # stub written by the API: keep its start time and trigger
    else:
        run = create_run_stub(run_id, input_file, trigger, flow_id)
    frames: dict[str, tuple] = {}
    graph: list[dict] = []

    def on_event(ev: runtime.NodeEvent) -> None:
        node = run["nodes"].setdefault(ev.node_id, _empty_node({"id": ev.node_id}))
        node["status"] = ev.status
        if ev.status == "running":
            node["log"] = [{"t": _now(), "level": "info", "text": "Step started"}]
        else:
            frames[ev.node_id] = (ev.input_frame, ev.output_frame)
            node.update(compare(ev.input_frame, ev.output_frame))
            node["duration_ms"] = ev.duration_ms
            message = None if ev.status == "success" else explain_error(ev.error, ev.input_frame)
            if message:
                node["error"] = {"message": message, "type": type(ev.error).__name__,
                                 "traceback": ev.error_traceback}
                run["error"] = {"node_id": ev.node_id, "message": message}
            node["calls"] = [_trim_call(c) for c in ev.calls[:MAX_CALLS_PER_STEP]]
            node["calls_total"] = len(ev.calls)
            node["credits"] = sum(c.get("credits") or 0 for c in ev.calls)
            for c in ev.calls:
                if c.get("error"):
                    node.setdefault("log", []).append(
                        {"t": _now(), "level": "warn" if c.get("error_kind") == "item" else "error",
                         "text": f"{c['label']} {c['action']}: {c['error']}"})
            add_step_log(node, _now(), ev.stdout, message, items=items)
        _write(run)

    try:
        output = paths["output"]
        if trigger == "test":  # test runs never touch the real output: they write to a scratch folder
            output = ROOT / "state" / "tests" / (flow_id or LIVE_FLOW) / "output" / (output.name if output.suffix else "")
            (output.parent if output.suffix else output).mkdir(parents=True, exist_ok=True)
        inputs = {"input_path": str(ROOT / input_file), "csv_path": str(ROOT / input_file),
                  "output_dir": str(output if output.suffix == "" else output.parent),
                  "output_path": str(output if output.suffix else output / "result.csv")}
        graph = runtime.execute(inputs, on_event, step_delay_s=step_delay_s)
        run["status"] = "success"
    except BaseException as exc:  # noqa: BLE001 - user code may raise SystemExit etc.; always record it
        run["status"] = "failed"
        if not run["error"]:  # failed before any step ran, e.g. a syntax error in the pipeline
            run["error"] = {"node_id": None, "message": f"The pipeline code could not run: {type(exc).__name__}: {exc}"}
        if isinstance(exc, KeyboardInterrupt):
            raise
    for node in run["nodes"].values():
        if node["status"] == "running":
            node["status"] = "failed"
    steps = graph or [{"id": nid, "group": n.get("group")} for nid, n in run["nodes"].items()]
    run["groups"] = _group_results(frames, steps, maps.read_groups(paths["map"]))
    run["input_items"], run["output_items"] = io_items(frames, [s["id"] for s in steps])
    if run["status"] != "success":
        run["output_items"] = None
    run["contacts"] = _contact_trace(run, frames, [s["id"] for s in steps],
                                     config.get("title_field") or "name", config.get("subtitle_field") or "email")
    run["summary"] = _summary(run)
    run["finished_at"] = _now()
    _write(run)
    return run


def _trim_call(c: dict) -> dict:
    """Keep call records small enough for the run file."""
    out = dict(c)
    text = json.dumps(out.get("output"), default=str)
    if len(text) > 1500:
        out["output"] = text[:1500] + "…"
    return out


def _group_results(frames: dict[str, tuple], steps: list[dict], groups: list[dict] | None = None) -> dict:
    groups = maps.read_groups() if groups is None else groups
    order = [s["id"] for s in steps]
    results = {}
    for g in groups:
        members = maps.descendant_steps(g["id"], groups, steps)
        ran = [sid for sid in order if sid in members and sid in frames]
        if not ran:
            continue
        before = frames[ran[0]][0]
        if before is None or "_row_id" not in before.columns:
            before = frames[ran[0]][1]  # the group starts with the loading step: count what it loaded
        after = next((frames[sid][1] for sid in reversed(ran) if frames[sid][1] is not None), None)
        results[g["id"]] = compare(before, after)
    return results


def io_items(frames: dict[str, tuple], order: list[str]) -> tuple[list[dict], list[dict] | None]:
    """(everything that came in, everything that came out) for a run, without the internal columns.

    Output is None when the run didn't finish, so there is no output yet.
    """
    ordered = [nid for nid in order if nid in frames]
    first = next((frames[n][1] for n in ordered if frames[n][1] is not None), None)
    last = frames[ordered[-1]][1] if ordered and len(ordered) == len(order) else None

    def rows(df: pd.DataFrame | None, only_active: bool) -> list[dict]:
        if df is None or "_row_id" not in df.columns:
            return []
        if only_active:
            df = df[df["_rejected_reason"].isna()] if "_rejected_reason" in df.columns else df
        recs = _records(df, list(df["_row_id"])[:MAX_IO_ITEMS])
        return [{k: v for k, v in r.items() if k != "_rejected_reason"} for r in recs]

    return rows(first, only_active=False), (rows(last, only_active=True) if last is not None else None)


def _contact_trace(run: dict, frames: dict[str, tuple], order: list[str],
                   title_field: str = "name", subtitle_field: str = "email") -> list[dict]:
    """One line per input row: what it looked like, and where (if anywhere) it was flagged.

    Built from the full frames, not the capped samples, so large runs stay correct.
    """
    ordered = [nid for nid in order if nid in frames]
    first = next((frames[n][1] for n in ordered if frames[n][1] is not None), None)
    if first is None or "_row_id" not in first.columns:
        return []
    fate: dict = {}
    for nid in ordered:
        before, after = frames[nid]
        if before is None or "_row_id" not in before.columns:
            continue
        for rid, reason in newly_rejected(before, after):
            fate.setdefault(rid, (nid, reason))
    finished = run["status"] == "success"
    trace = []
    for rec in _records(first, list(first["_row_id"])):
        step_id, reason = fate.get(rec["_row_id"], (None, None))
        outcome = "rejected" if step_id else ("kept" if finished else "unknown")
        trace.append({"row_id": rec["_row_id"], "name": rec.get(title_field), "email": rec.get(subtitle_field),
                      "outcome": outcome, "step_id": step_id, "reason": reason})
    return trace


def find_contacts(run: dict, query: str, limit: int = 20) -> list[dict]:
    q = " ".join(query.lower().split())
    if not q:
        return []

    def text(v) -> str:
        return " ".join(str(v or "").lower().replace("​", "").split())

    matches = [c for c in run.get("contacts", [])
               if q in text(c["name"]) or q in text(c["email"]) or q == str(c["row_id"])]
    return matches[:limit]


def compare_outcomes(old: dict, new: dict) -> dict:
    """Which contacts changed outcome between two runs (by row id)."""
    before = {c["row_id"]: c for c in old.get("contacts", [])}
    changes = []
    for c in new.get("contacts", []):
        prev = before.get(c["row_id"])
        if prev is None or (prev["outcome"], prev["reason"]) == (c["outcome"], c["reason"]):
            continue
        changes.append({"row_id": c["row_id"], "name": c["name"], "email": c["email"],
                        "was": prev["reason"] or prev["outcome"], "now": c["reason"] or c["outcome"]})
    return {"old_run": old["run_id"], "new_run": new["run_id"],
            "old_summary": old.get("summary"), "new_summary": new.get("summary"), "changed_contacts": changes}


def _summary(run: dict) -> dict:
    nodes = list(run["nodes"].values())
    first = next((n for n in nodes if n["rows_in"] is not None), None)
    last = nodes[-1] if nodes else None
    return {
        "rows_read": first["rows_in"] if first else None,
        "rows_written": last["rows_out"] if last and last["status"] == "success" else None,
        "rows_rejected": sum(n["rows_rejected"] or 0 for n in nodes),
        "calls": sum(n.get("calls_total") or 0 for n in nodes),
        "credits": sum(n.get("credits") or 0 for n in nodes),
    }


# --------------------------------------------------------------------------- subprocess control


def _spawn(run_id: str, input_file: str, trigger: str, flow_id: str = LIVE_FLOW) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "server.runs", "--run-id", run_id, "--input", input_file, "--trigger", trigger,
         "--flow", flow_id],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, env=runtime.step_env(),
    )


def _finish(proc: subprocess.Popen, run_id: str, timeout_s: float) -> None:
    """Wait for a runner process; if it hangs or dies, make sure the run is marked failed."""
    try:
        _, stderr = proc.communicate(timeout=timeout_s)
        message = None
        if proc.returncode != 0:
            last = (stderr or "").strip().splitlines()[-1:] or ["no details"]
            message = f"The runner stopped unexpectedly (exit code {proc.returncode}): {last[0][:300]}"
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        message = f"The run took longer than {timeout_s:.0f} seconds and was stopped. A step may be stuck in a loop."
    run = get_run(run_id)
    if run and run.get("status") == "running":
        _write(_mark_failed(dict(run), message or "The run stopped without finishing."))


def start_run_background(input_file: str | None, trigger: str = "ui", flow_id: str = LIVE_FLOW) -> str:
    """Start a run in a separate process (so broken code can't crash the server)."""
    input_file = resolve_input(input_file, flow_id)
    run_id = new_run_id(flow_id)
    create_run_stub(run_id, input_file, trigger, flow_id)
    proc = _spawn(run_id, input_file, trigger, flow_id)
    threading.Thread(target=_finish, args=(proc, run_id, RUN_TIMEOUT_S), daemon=True).start()
    return run_id


def run_blocking(input_file: str | None = None, trigger: str = "chat", timeout_s: float = RUN_TIMEOUT_S,
                 flow_id: str = LIVE_FLOW) -> dict:
    """Run in a subprocess and wait for it; used by the chat agent."""
    input_file = resolve_input(input_file, flow_id)
    run_id = new_run_id(flow_id)
    create_run_stub(run_id, input_file, trigger, flow_id)
    _finish(_spawn(run_id, input_file, trigger, flow_id), run_id, timeout_s)
    return get_run(run_id) or {"run_id": run_id, "status": "failed", "nodes": {}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the contact pipeline once.")
    parser.add_argument("--input", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--trigger", default="cli")
    parser.add_argument("--flow", default=LIVE_FLOW)
    args = parser.parse_args()
    run = execute_run(args.run_id or new_run_id(args.flow), args.input, args.trigger, flow_id=args.flow)
    print(f"{run['run_id']}: {run['status']}")
    for node_id, node in run["nodes"].items():
        print(f"  {node['status']:8} {node_id:28} in={node['rows_in']} rejected={node['rows_rejected']} out={node['rows_out']}")
    if run["error"]:
        print(f"  error in {run['error']['node_id']}: {run['error']['message']}")


if __name__ == "__main__":
    main()
