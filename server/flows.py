"""Flow registry: the live code-backed flow plus sample flows, behind one interface.

The live flow ("contact-cleaning") runs the real Hamilton pipeline in pipeline/.
Sample flows (server/sample_flows.py) have generated history, for validating the
concept with integration-style automations (Clay, HubSpot, Slack, ...).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta

from server import automations, maps, runs, runtime, sample_flows
from server.automations.base import render_summary


def connected() -> dict:
    """The user's own automations, configured in automations/<id>/automation.yaml (read-only)."""
    return automations.all_automations()


_read_errors: dict[str, str] = {}  # flow id -> why reading it failed last time (adapter code is the user's)


def _adapter(flow_id: str, call, default):
    """Call an adapter; a crash becomes a message on the flow instead of breaking every page."""
    try:
        result = call()
    except Exception as exc:  # errors are data
        _read_errors[flow_id] = f"{type(exc).__name__}: {exc}"
        return default
    _read_errors.pop(flow_id, None)
    return result


def _with_summary_text(adapter, run: dict | None) -> dict | None:
    """`summary:` in automation.yaml works for every type: fill it in from the run's step counts."""
    template = adapter.config.get("summary")
    if run and template and run.get("nodes") and not (run.get("summary") or {}).get("text"):
        if text := render_summary(template, run["nodes"]):
            run = {**run, "summary": {**(run.get("summary") or {}), "text": text}}
    return run

FLOWS_DIR = runs.FLOWS_DIR

LIVE_ID = "contact-cleaning"
STATE_PATH = runtime.ROOT / "state" / "flows.json"
_state_lock = threading.Lock()

LIVE_META = {
    "id": LIVE_ID,
    "name": "Contact list cleaning",
    "description": "Cleans a contact list: tidies names and emails, sets invalid and duplicate contacts aside, saves a clean list.",
    "trigger": {"type": "manual", "label": "Run by hand on a CSV file", "app": "CSV file"},
    "terms": {"item": "contact", "items": "contacts"},
    "next_run": "When you press Run",
    "output": {"label": "Saved as a clean contact list"},
    "kind": "live",
}


# --------------------------------------------------------------------------- state (enabled, events, requests)


def _read_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"enabled": {}, "events": []}


def _write_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def log_event(flow_id: str | None, level: str, text: str) -> None:
    with _state_lock:
        state = _read_state()
        state.setdefault("events", []).append(
            {"t": datetime.now().isoformat(timespec="seconds"), "flow_id": flow_id, "level": level, "text": text})
        state["events"] = state["events"][-500:]
        _write_state(state)


def is_enabled(flow_id: str) -> bool:
    if flow_id in connected():
        return connected()[flow_id].meta()["enabled"]
    default = sample_flows.ENABLED_BY_DEFAULT.get(flow_id, True)
    return _read_state().get("enabled", {}).get(flow_id, default)


def set_enabled(flow_id: str, enabled: bool) -> None:
    get_meta(flow_id)  # raises KeyError for unknown flows
    if flow_id in connected():
        adapter = connected()[flow_id]
        if not adapter.meta().get("can_toggle"):
            raise ValueError("This automation can't be switched on or off from here.")
        where = adapter.source_label()
        try:
            adapter.set_enabled(enabled)
        except Exception as exc:
            raise ValueError(f"Couldn't change it on {where}: {exc}") from exc
        log_event(flow_id, "change", f"{'Turned on' if enabled else 'Turned off'} on {where} by you")
        return
    with _state_lock:
        state = _read_state()
        state.setdefault("enabled", {})[flow_id] = enabled
        _write_state(state)
    log_event(flow_id, "change", f"Flow {'turned on' if enabled else 'paused'} by you")


# --------------------------------------------------------------------------- registry


def built_flow_ids() -> list[str]:
    """Flows Claude built: one folder per flow under flows/, with a flow.yaml."""
    if not FLOWS_DIR.exists():
        return []
    found = [p.parent for p in FLOWS_DIR.glob("*/flow.yaml")]
    found.sort(key=lambda d: (d / "flow.yaml").stat().st_ctime)
    return [d.name for d in found]


def show_demo() -> bool:
    """Demo and builder flows are hidden until asked for: a new user starts with an empty, honest app."""
    return bool(_read_state().get("show_demo", False))


ENGINES = ("claude", "codex")


def chat_engine() -> str:
    """Which agent runs the in-app chat: Claude (Agent SDK) or Codex (the Codex CLI). Same tools, same rules."""
    value = _read_state().get("chat_engine", "claude")
    return value if value in ENGINES else "claude"


def set_chat_engine(value: str) -> None:
    if value not in ENGINES:
        raise ValueError(f"The chat runs on {' or '.join(ENGINES)}")
    with _state_lock:
        state = _read_state()
        state["chat_engine"] = value
        _write_state(state)


def set_show_demo(value: bool) -> None:
    with _state_lock:
        state = _read_state()
        state["show_demo"] = value
        _write_state(state)


def is_demo(flow_id: str | None) -> bool:
    """Everything except the user's connected automations: the demo flows and flows built in the app."""
    return flow_id is not None and flow_id not in connected()


def all_flow_ids() -> list[str]:
    return [*connected(), LIVE_ID, *built_flow_ids(), *sample_flows.SAMPLE_FLOWS]


def flow_ids() -> list[str]:
    """Flows shown in the app: the real ones, plus demo/test flows only when asked for."""
    ids = all_flow_ids()
    return ids if show_demo() else [f for f in ids if not is_demo(f)]


def kind(flow_id: str) -> str:
    if flow_id == LIVE_ID:
        return "live"
    if flow_id in connected():
        return "connected"
    if flow_id in sample_flows.SAMPLE_FLOWS:
        return "sample"
    if (FLOWS_DIR / flow_id / "flow.yaml").exists():
        return "built"
    raise KeyError(flow_id)


def _built_meta(flow_id: str) -> dict:
    cfg = maps.read_yaml(FLOWS_DIR / flow_id / "flow.yaml")
    trigger = cfg.get("trigger") or {}
    return {"id": flow_id, "name": cfg.get("title") or cfg.get("name") or flow_id,
            "description": cfg.get("description") or "",
            "trigger": {"type": trigger.get("type") or "manual", "label": trigger.get("label") or "Run by hand on sample data",
                        "app": trigger.get("app")},
            "terms": {"item": (cfg.get("terms") or {}).get("item") or "item",
                      "items": (cfg.get("terms") or {}).get("items") or "items"},
            "next_run": cfg.get("next_run") or "When you press Run", "kind": "built",
            "output": {"label": (cfg.get("output") or {}).get("label") or f"The {((cfg.get('terms') or {}).get('items') or 'items')} that made it through"},
            "created_by": cfg.get("created_by") or "Claude"}


def get_meta(flow_id: str) -> dict:
    if flow_id in connected():
        return connected()[flow_id].meta()
    if flow_id == LIVE_ID:
        return dict(LIVE_META)
    if kind(flow_id) == "built":
        return _built_meta(flow_id)
    f = sample_flows.SAMPLE_FLOWS[flow_id]
    return {"id": f.id, "name": f.name, "description": f.description, "trigger": f.trigger, "terms": f.terms,
            "next_run": f.next_run, "output": {"label": f.output}, "kind": "sample"}


def get_map(flow_id: str) -> dict:
    k = kind(flow_id)
    if k == "connected":
        m = connected()[flow_id].get_map()
    elif flow_id == LIVE_ID:
        m = maps.build_map()
        m["title"] = LIVE_META["name"]
    elif k == "built":
        paths = runs.flow_paths(flow_id)
        m = maps.build_map(paths["map"], paths["code"])
        m["title"] = _built_meta(flow_id)["name"]
        if not m["steps"] and not m["problems"]:
            m["problems"] = []
    else:
        m = sample_flows.build_map(sample_flows.SAMPLE_FLOWS[flow_id])
    m = maps.without_single_child_groups(m)  # nothing to open in a box with one step: show the step
    return {**m, "flow": {**get_meta(flow_id), "enabled": is_enabled(flow_id)}}


def list_runs(flow_id: str) -> list[dict]:
    if flow_id in connected():
        return _adapter(flow_id, connected()[flow_id].list_runs, [])
    if kind(flow_id) in ("live", "built"):
        return runs.list_runs(flow_id)
    keys = ("run_id", "status", "started_at", "finished_at", "input_file", "trigger", "summary", "error")
    return [{k: r.get(k) for k in keys} for r in sample_flows.history(flow_id)]


def get_run(flow_id: str, run_id: str) -> dict | None:
    if flow_id in connected():
        a = connected()[flow_id]
        return _with_summary_text(a, _adapter(flow_id, lambda: a.get_run(run_id), None))
    if kind(flow_id) in ("live", "built"):
        run = runs.get_run(run_id)
        return run if run and (run.get("flow_id") or LIVE_ID) == flow_id else None
    return next((r for r in sample_flows.history(flow_id) if r["run_id"] == run_id), None)


def start_run(flow_id: str, input_file: str | None) -> str:
    if flow_id in connected():
        where = connected()[flow_id].source_label()
        raise ValueError(f"This automation runs on {where} on its own; this view is read-only.")
    if kind(flow_id) in ("live", "built"):
        return runs.start_run_background(input_file, trigger="ui", flow_id=flow_id)
    return sample_flows.trigger_now(flow_id)["run_id"]


def apps(flow_id: str, m: dict | None = None) -> list[str]:
    m = m or get_map(flow_id)
    seen = [m["flow"]["trigger"].get("app")] + [s.get("app") for s in m["steps"]]
    return [a for a in dict.fromkeys(seen) if a]


def production_runs(flow_id: str, run_list: list[dict]) -> list[dict]:
    """Runs without test runs: test runs never count toward KPIs, success rates or insights."""
    from server import testlab

    tests = testlab.test_run_ids(flow_id)
    return [r for r in run_list if not r.get("test_mode") and r.get("trigger") != "test" and r["run_id"] not in tests]


def overview() -> list[dict]:
    """One card per flow for the Flows page."""
    week_ago = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
    cards = []
    for fid in flow_ids():
        try:
            m = get_map(fid)
        except Exception:
            continue
        all_runs = production_runs(fid, list_runs(fid))
        recent = [r for r in all_runs if (r.get("started_at") or "") >= week_ago and r["status"] != "running"]
        ok = sum(r["status"] == "success" for r in recent)
        cards.append({
            **m["flow"],
            "apps": apps(fid, m),
            "step_count": len(m["steps"]),
            "problems": m["problems"],
            "last_run": all_runs[0] if all_runs else None,
            "recent": [{"run_id": r["run_id"], "status": r["status"], "started_at": r["started_at"]} for r in all_runs[:14]],
            "stats_7d": {
                "runs": len(recent),
                "success_rate": round(100 * ok / len(recent)) if recent else None,
                "items_in": sum((r.get("summary") or {}).get("rows_read") or 0 for r in recent),
                "items_out": sum((r.get("summary") or {}).get("rows_written") or 0 for r in recent),
            },
            "kpis": _adapter(fid, lambda: kpis(fid, m["flow"], all_runs, recent), []),
            "freshness": freshness(fid),
            "next_step": _attention_next_step(m, all_runs[0] if all_runs else None),
        })
    return cards


def _attention_next_step(m: dict, last: dict | None) -> str | None:
    """What to do about a flow that needs attention (the card says why; this says what to do)."""
    from server import nextstep

    if last and last.get("status") == "failed":
        error = last.get("error") or {}
        step = next((s for s in m["steps"] if s["id"] == error.get("node_id")), None)
        return nextstep.next_step(error.get("message") or "", step)
    if m["flow"].get("overdue"):
        return "Check the schedule where it runs (cron, GitHub Actions, launchd) and whether it's switched on."
    if m["problems"]:
        return "Fix the map's config; `uv run flowhaus check` lists what's wrong."
    return None


def freshness(flow_id: str) -> dict:
    """Where the data on screen came from and when it was read. Shown instead of pretending to be live."""
    now = datetime.now().isoformat(timespec="seconds")
    if flow_id in connected():
        f = _adapter(flow_id, connected()[flow_id].freshness, {"source": "", "checked_at": None, "error": None})
        return {**f, "error": _read_errors.get(flow_id) or f.get("error")}
    return {"source": "this computer" if kind(flow_id) in ("live", "built") else "made-up demo data",
            "checked_at": now, "error": None}


def _full_run(flow_id: str, summary: dict) -> dict | None:
    if flow_id in connected():  # cheap: cached details only, never a slow fetch for a card
        a = connected()[flow_id]
        return _with_summary_text(a, a.cached_run(summary["run_id"]))
    return get_run(flow_id, summary["run_id"])


def _number(text: str | None) -> float | None:
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


def kpis(flow_id: str, meta: dict, all_runs: list[dict], recent: list[dict]) -> list[dict]:
    """Two numbers that say how an automation is doing. From `kpis:` in automation.yaml, else sensible defaults:
    what came out of the last finished run (vs. the one before) and how many runs went fine this week."""
    finished = [r for r in all_runs if r["status"] in ("success", "failed")][:2]
    items = meta["terms"]["items"]
    out: list[dict] = []
    configured = (connected()[flow_id].config.get("kpis") or [])[:2] if flow_id in connected() else []
    if configured and finished:
        runs_full = [_full_run(flow_id, r) for r in finished]
        for k in configured:
            now_text = render_summary(str(k.get("value", "")), (runs_full[0] or {}).get("nodes") or {}) if runs_full[0] else None
            before = runs_full[1] if len(runs_full) > 1 else None
            prev_text = render_summary(str(k.get("value", "")), before.get("nodes") or {}) if before else None
            a, b = _number(now_text), _number(prev_text)
            out.append({"value": now_text or "—", "label": k.get("label") or "", "hint": "last finished run",
                        "delta": (a - b) if a is not None and b is not None else None,
                        "good": k.get("good", "up")})
    if not configured and finished:
        last = finished[0].get("summary") or {}
        if last.get("rows_written") is not None:
            prev = (finished[1].get("summary") or {}).get("rows_written") if len(finished) > 1 else None
            one = meta["terms"]["item"]
            out.append({"value": f"{last['rows_written']:,}", "label": f"{one if last['rows_written'] == 1 else items} out",
                        "hint": "last finished run",
                        "delta": last["rows_written"] - prev if prev is not None else None, "good": "up"})
    if len(out) < 2:
        ok = sum(r["status"] == "success" for r in recent)
        out.append({"value": f"{ok} of {len(recent)}" if recent else "0",
                    "label": ("run went fine" if len(recent) == 1 else "runs went fine") if recent else "runs",
                    "hint": "last 7 days", "delta": None, "good": "up",
                    "tone": "bad" if ok < len(recent) else "good" if recent else None})
    return out[:2]


# --------------------------------------------------------------------------- activity log

TRIGGER_TEXT = {"ui": "started by you", "manual": "started by you", "cli": "started from the command line",
                "chat": "test run by the chat", "undo": "test run after undoing a change",
                "webhook": "triggered by a new submission", "schedule": "started on schedule",
                "event": "triggered by a new email", "test": "test run"}


def _run_events(flow_id: str, meta: dict, run: dict, full: dict | None) -> list[dict]:
    items = meta["terms"]["items"]
    base = {"flow_id": flow_id, "run_id": run["run_id"]}
    events = [{**base, "t": run["started_at"], "level": "info",
               "text": f"Run {TRIGGER_TEXT.get(run.get('trigger'), 'started')}"}]
    if full:
        for node_id, node in full.get("nodes", {}).items():
            if node.get("rejected_samples") or node.get("reject_reasons"):
                reasons = "; ".join(f"{r} ({n})" for r, n in node["reject_reasons"].items())
                # routine skips are information, not warnings: they happen on every healthy run
                events.append({**base, "t": run["finished_at"] or run["started_at"], "level": "info", "node_id": node_id,
                               "text": f"{node['label']}: skipped {node['rows_rejected']} "
                                       f"{_unit(node, meta, node['rows_rejected'])}: {reasons}"})
    s = run.get("summary") or {}
    if run["status"] == "failed":
        err = run.get("error") or {}
        where = (full or {}).get("nodes", {}).get(err.get("node_id") or "", {}).get("label")
        events.append({**base, "t": run["finished_at"] or run["started_at"], "level": "error", "node_id": err.get("node_id"),
                       "text": f"Failed{f' in {where}' if where else ''}: {err.get('message', 'unknown error')}"})
    elif run["status"] == "success":
        events.append({**base, "t": run["finished_at"], "level": "success",
                       "text": f"Finished: {s['text']}" if s.get("text") else
                               "Finished" if s.get("rows_read") is None else
                               f"Finished: {s.get('rows_read')} {meta['terms']['item'] if s.get('rows_read') == 1 else items} in → "
                               f"{s.get('rows_written')} out"
                               + (f", {s.get('rows_rejected')} skipped" if s.get("rows_rejected") else "")})
    elif run["status"] == "running":
        events.append({**base, "t": run["started_at"], "level": "running", "text": "Running…"})
    return events


def _unit(node: dict, meta: dict, n: int) -> str:
    unit = node.get("unit") or meta["terms"]["items"]
    return unit[:-1] if n == 1 and unit.endswith("s") else unit


def activity(flow_id: str | None = None, limit: int = 300, refresh: bool = False) -> list[dict]:
    """Every run and change, newest first. `refresh` reads connected automations' newest runs now (the Refresh
    button) instead of a list read in the last minute."""
    events = []
    ids = [flow_id] if flow_id else flow_ids()
    for fid in ids:
        if refresh and fid in connected():
            _adapter(fid, connected()[fid].refresh, None)
        meta = get_meta(fid)
        for summary in list_runs(fid)[:40]:
            full = _adapter(fid, lambda: connected()[fid].cached_run(summary["run_id"]), None) if fid in connected() else get_run(fid, summary["run_id"])
            events.extend(_run_events(fid, meta, summary, full))
        if fid in sample_flows.SAMPLE_FLOWS:
            now = datetime.now()
            for hours, level, text in sample_flows.SAMPLE_FLOWS[fid].events:
                events.append({"flow_id": fid, "t": (now - timedelta(hours=hours)).isoformat(timespec="seconds"),
                               "level": level, "text": text})
    visible = set(flow_ids())
    for e in _read_state().get("events", []):
        if flow_id and e.get("flow_id") != flow_id:
            continue
        if e.get("flow_id") and e["flow_id"] not in visible:
            continue
        if not e.get("flow_id") and not show_demo():
            continue  # global test events (dummy apps connected, ...)
        events.append(e)
    names = {fid: get_meta(fid)["name"] for fid in all_flow_ids()}
    for e in events:
        e["flow_name"] = names.get(e.get("flow_id"), "All flows")
    events.sort(key=lambda e: e.get("t") or "", reverse=True)
    return events[:limit]
