"""Local API: flows, maps, runs, previews, activity and chat.

uv run uvicorn server.app:app --port 8000

Every flow-scoped endpoint takes `flow_id` (defaults to the live contact flow).
"""

from __future__ import annotations

import os
import secrets
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from server import agent, changes, checkup, connections, flows, harness, maps, mcp, nextstep, runs, runtime, testlab, whatif

app = FastAPI(title="Flowhaus")

# This API runs on your computer with your permissions (it can run code and switch your workflows).
# Only answer requests for localhost (blocks DNS rebinding) and refuse changes from other web pages.
LOCAL_HOSTS = ["127.0.0.1", "localhost", "[::1]", *filter(None, os.environ.get("FLOWHAUS_ALLOWED_HOSTS", "").split(","))]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)
# The pages allowed to make changes: this app's own UI (Vite dev server or the built UI served by this API).
PORTS = {os.environ.get("FLOWHAUS_API_PORT", "8000"), os.environ.get("FLOWHAUS_WEB_PORT", "5173")}
ALLOWED_ORIGINS = {f"http://{h}:{p}" for h in LOCAL_HOSTS for p in PORTS}


@app.middleware("http")
async def same_origin_only(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        site = request.headers.get("sec-fetch-site")
        if (origin and origin not in ALLOWED_ORIGINS) or site in ("cross-site", "same-site"):
            return JSONResponse({"detail": "Requests from other websites are not allowed."}, status_code=403)
    return await call_next(request)


@app.exception_handler(KeyError)
async def unknown_id(request: Request, exc: KeyError):
    return JSONResponse({"detail": f"Not found: {exc.args[0] if exc.args else ''}"}, status_code=404)


COUNT_FIELDS = ("status", "label", "group", "duration_ms", "rows_in", "rows_out", "rows_rejected",
                "rows_changed", "error", "calls_total", "credits")


def group_status(child_statuses: list[str], run_running: bool) -> str:
    if not child_statuses:
        return "not_run"
    if "failed" in child_statuses:
        return "failed"
    if "running" in child_statuses:
        return "running"
    if all(s == "success" for s in child_statuses):
        return "success"
    if run_running and "success" in child_statuses:
        return "running"
    return "not_run"


def _flow_map(flow_id: str) -> dict:
    try:
        return flows.get_map(flow_id)
    except KeyError:
        raise HTTPException(404, f"No flow '{flow_id}'")


def _run(flow_id: str, run_id: str) -> dict:
    run = flows.get_run(flow_id, run_id)
    if run is None:
        raise HTTPException(404, f"No run '{run_id}'")
    return run


def run_view(run: dict, fmap: dict, flow_id: str = flows.LIVE_ID) -> dict:
    """A run with per-step counts (no samples) plus computed group status."""
    groups, steps = fmap["groups"], fmap["steps"]
    nodes = {nid: {k: n.get(k) for k in COUNT_FIELDS} for nid, n in run["nodes"].items()}
    group_view = {}
    for g in groups:
        members = [s for s in maps.descendant_steps(g["id"], groups, steps) if s in nodes]
        statuses = [nodes[m]["status"] for m in members]
        counts = (run.get("groups") or {}).get(g["id"], {})
        failed_step = next((m for m in members if nodes[m]["status"] == "failed"), None)
        group_view[g["id"]] = {
            "status": group_status(statuses, run["status"] == "running"),
            "rows_in": counts.get("rows_in"),
            "rows_out": counts.get("rows_out"),
            "rows_rejected": counts.get("rows_rejected", 0),
            "rows_changed": counts.get("rows_changed", 0),
            "failed_step": failed_step,
            "calls_total": sum(nodes[m].get("calls_total") or 0 for m in members),
            "credits": sum(nodes[m].get("credits") or 0 for m in members),
        }
    view = {k: v for k, v in run.items() if k not in ("nodes", "groups", "contacts", "input_items", "output_items")}
    # how many came in: the items themselves if the run kept them, else the run's own count (many automations count
    # but don't keep items), else unknown (None): better no number than a wrong "0"
    items, read = run.get("input_items"), (run.get("summary") or {}).get("rows_read")
    view["input_count"] = len(items) if items else read
    view["output_count"] = None if run.get("output_items") is None else len(run["output_items"])
    previous = _previous_counts(flow_id, run) if run["status"] != "running" else None
    return {**view, "nodes": nodes, "groups": group_view, "previous": previous}


def _previous_counts(flow_id: str, run: dict) -> dict | None:
    """Counts from the last finished run on the same input, so the UI can show "+4" / "−4"."""
    for summary in flows.list_runs(flow_id):
        if (summary["started_at"] or "") >= (run["started_at"] or "") or summary["run_id"] == run["run_id"]:
            continue
        if summary["input_file"] != run.get("input_file") or summary["status"] == "running":
            continue
        prev = flows.get_run(flow_id, summary["run_id"])
        if prev is None:
            return None
        pick = lambda d: {"rows_rejected": d.get("rows_rejected"), "rows_out": d.get("rows_out")}  # noqa: E731
        return {
            "run_id": prev["run_id"],
            "nodes": {nid: pick(n) for nid, n in prev["nodes"].items() if n.get("status") == "success"},
            "groups": {gid: pick(g) for gid, g in (prev.get("groups") or {}).items()},
        }
    return None


# --------------------------------------------------------------------------- flows + activity


@app.get("/api/flows")
def get_flows():
    return {"flows": flows.overview()}


class FlowPatch(BaseModel):
    enabled: bool


@app.patch("/api/flows/{flow_id}")
def patch_flow(flow_id: str, body: FlowPatch):
    try:
        flows.set_enabled(flow_id, body.enabled)
    except KeyError:
        raise HTTPException(404, f"No flow '{flow_id}'")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"id": flow_id, "enabled": body.enabled}


class Settings(BaseModel):
    show_demo: bool | None = None
    chat_engine: str | None = None


def _settings() -> dict:
    """App state the UI needs, including what onboarding shows to a new user."""
    from server import automations, codex_engine

    found, errors = automations.load_all()
    return {"show_demo": flows.show_demo(), "automations": len(found), "automation_errors": errors,
            "chat_engine": flows.chat_engine(), "codex": codex_engine.status(),
            "project_dir": str(runtime.ROOT), "automations_dir": str(automations.automations_dir())}


@app.get("/api/settings")
def get_settings():
    return _settings()


@app.put("/api/settings")
def put_settings(body: Settings):
    if body.show_demo is not None:
        flows.set_show_demo(body.show_demo)
    if body.chat_engine is not None:
        try:
            flows.set_chat_engine(body.chat_engine)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    return _settings()


@app.get("/api/activity")
def get_activity(flow_id: str | None = None, limit: int = 300, refresh: bool = False):
    return {"events": flows.activity(flow_id, limit, refresh)}


# --------------------------------------------------------------------------- connections


@app.get("/api/connections")
def get_connections():
    return {"connections": connections.list_connections()}


class ConnectBody(BaseModel):
    api_key: str


# --------------------------------------------------------------------------- one flow


@app.get("/api/map")
def get_map(flow_id: str = flows.LIVE_ID):
    return _flow_map(flow_id)


@app.get("/api/inputs")
def get_inputs(flow_id: str = flows.LIVE_ID):
    try:
        if flows.kind(flow_id) in ("sample", "connected"):
            return {"inputs": [], "default": None}
    except KeyError:
        raise HTTPException(404, f"No flow '{flow_id}'")
    return {"inputs": runs.list_inputs(flow_id), "default": runs.default_input(flow_id)}


@app.get("/api/runs")
def get_runs(flow_id: str = flows.LIVE_ID):
    return {"runs": flows.list_runs(flow_id)}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, flow_id: str = flows.LIVE_ID):
    return run_view(_run(flow_id, run_id), _flow_map(flow_id), flow_id)


class StartRun(BaseModel):
    input_file: str | None = None


@app.post("/api/runs")
def start_run(body: StartRun | None = None, flow_id: str = flows.LIVE_ID):
    try:
        run_id = flows.start_run(flow_id, body.input_file if body else None)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except KeyError:
        raise HTTPException(404, f"No flow '{flow_id}'")
    return {"run_id": run_id}


@app.get("/api/runs/{run_id}/contacts")
def find_contacts(run_id: str, q: str = "", flow_id: str = flows.LIVE_ID):
    return {"matches": runs.find_contacts(_run(flow_id, run_id), q)}


@app.get("/api/nodes/{node_id}/preview")
def get_preview(node_id: str, run_id: str | None = None, flow_id: str = flows.LIVE_ID):
    if not run_id:
        listed = flows.list_runs(flow_id)
        run_id = listed[0]["run_id"] if listed else None
    run = flows.get_run(flow_id, run_id) if run_id else None
    if run is None:
        raise HTTPException(404, "No run yet. Start a run first.")
    if node_id in run["nodes"]:
        node = run["nodes"][node_id]
        return {"kind": "step", "node_id": node_id, "run_id": run_id, **node, **_next_step(flow_id, node_id, node)}
    if node_id in ("__input__", "__output__"):
        return _io_preview(run, node_id == "__output__", flow_id)
    fmap = _flow_map(flow_id)
    view = run_view(run, fmap, flow_id)
    if node_id not in view["groups"]:
        raise HTTPException(404, f"No node '{node_id}' in run {run_id}")
    data = (run.get("groups") or {}).get(node_id, {})
    g = view["groups"][node_id]
    log = [
        {"level": "error" if run["nodes"][s]["status"] == "failed" else "info",
         "text": f"{run['nodes'][s]['label']}: {run['nodes'][s]['status'].replace('_', ' ')}"
         + (f" ({run['nodes'][s]['rows_rejected']} skipped)" if run["nodes"][s]["rows_rejected"] else "")}
        for s in maps.descendant_steps(node_id, fmap["groups"], fmap["steps"])
        if s in run["nodes"]
    ]
    error = run["nodes"][g["failed_step"]]["error"] if g["failed_step"] else None
    hint = _next_step(flow_id, g["failed_step"], run["nodes"][g["failed_step"]]) if g["failed_step"] else {}
    return {"kind": "group", "node_id": node_id, "run_id": run_id, "status": g["status"], **hint,
            "failed_step": g["failed_step"], "error": error, "log": log,
            "rows_in": data.get("rows_in"), "rows_out": data.get("rows_out"),
            "rows_rejected": data.get("rows_rejected", 0), "rows_changed": data.get("rows_changed", 0),
            "sample_in": data.get("sample_in") or [], "sample_out": data.get("sample_out") or [],
            "rejected_samples": data.get("rejected_samples") or [],
            "reject_reasons": data.get("reject_reasons") or {}, "paired": data.get("paired", True)}


def _next_step(flow_id: str, step_id: str, node: dict) -> dict:
    """For a failed step: what to do first, and what that's based on (actionable, not only "it failed")."""
    message = (node.get("error") or {}).get("message")
    if node.get("status") != "failed" or not message:
        return {}
    step = next((s for s in _flow_map(flow_id)["steps"] if s["id"] == step_id), None)
    seen, unseen = nextstep.evidence(node, None)
    return {"next_step": nextstep.next_step(message, step), "evidence": seen, "unseen": unseen}


def _io_preview(run: dict, output: bool, flow_id: str) -> dict:
    """What came into the flow, or what came out of it, for the start/end boxes."""
    key = "output_items" if output else "input_items"
    items = run.get(key)
    summary = run.get("summary") or {}
    if items is None and not output:  # runs from before this was stored: fall back to the contact trace
        items = [{"_row_id": c["row_id"], "name": c["name"], "email": c["email"]} for c in run.get("contacts", [])]
    meta = flows.get_meta(flow_id)
    return {"kind": "output" if output else "input", "node_id": "__output__" if output else "__input__",
            "run_id": run["run_id"], "status": run["status"], "items": items,
            "destination": (meta.get("output") or {}).get("label") if output else meta["trigger"]["label"],
            "rows_in": summary.get("rows_read"), "rows_out": summary.get("rows_written"),
            "rows_rejected": summary.get("rows_rejected") or 0, "rows_changed": 0, "error": run.get("error")}


@app.get("/api/runs/{run_id}/items.csv", response_class=PlainTextResponse)
def items_csv(run_id: str, which: Literal["input", "output"] = "output", flow_id: str = flows.LIVE_ID):
    import csv
    import io

    items = _run(flow_id, run_id).get("output_items" if which == "output" else "input_items") or []
    buf = io.StringIO()
    cols = [c for c in dict.fromkeys(k for it in items for k in it) if not c.startswith("_")]
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    # cells starting with = + - @ would run as formulas in a spreadsheet: prefix them with '
    writer.writerows({k: f"'{v}" if isinstance(v, str) and v[:1] in "=+-@\t\r" else v for k, v in it.items()}
                     for it in items)
    name = f"{flow_id}-{which}-{run_id.split('--')[-1]}.csv"
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/nodes/{node_id}/code")
def get_code(node_id: str, flow_id: str = flows.LIVE_ID):
    if flows.kind(flow_id) in ("sample", "connected"):
        raise HTTPException(404, "Code isn't shown for this flow.")
    source = runtime.step_source(node_id, runs.flow_paths(flow_id)["code"])
    if source is None:
        raise HTTPException(404, f"No step '{node_id}'")
    return {"node_id": node_id, "code": source}


# --------------------------------------------------------------------------- chat


class ChatRequest(BaseModel):
    message: str
    selected_node_id: str | None = None
    run_id: str | None = None
    flow_id: str | None = flows.LIVE_ID  # None = the "new flow" page


def _ndjson(job: agent.Job) -> StreamingResponse:
    return StreamingResponse(agent.stream_job(job), media_type="application/x-ndjson")


@app.post("/api/chat")
async def chat(body: ChatRequest):
    return _ndjson(agent.Job("chat", body.message, body.selected_node_id, body.run_id, flow_id=body.flow_id))


class UndoRequest(BaseModel):
    run_id: str | None = None


@app.post("/api/chat/undo")
async def chat_undo(body: UndoRequest | None = None):
    return _ndjson(agent.Job("undo", run_id=body.run_id if body else None))


@app.post("/api/chat/reset")
async def chat_reset():
    return _ndjson(agent.Job("reset"))


@app.post("/api/chat/stop")
async def chat_stop():
    return {"stopped": await agent.WORKER.interrupt()}


@app.get("/api/chat/status")
def chat_status():
    return {"busy": agent.WORKER.busy, "can_undo": bool(agent.WORKER.undo_stack)}


# --------------------------------------------------------------------------- proposed changes, approvals, MCP


@app.get("/api/changes")
def list_changes(flow_id: str | None = None):
    return {"changes": [{k: v for k, v in c.items() if k != "diff"} for c in changes.list_changes(flow_id)]}


@app.get("/api/changes/{change_id}")
def get_change(change_id: str):
    meta = changes.get(change_id)
    return {**meta, "gate": changes.gate(meta)} if meta["status"] == "proposed" else meta


class OpenPullRequest(BaseModel):
    confirmed: list[str] = []  # the ids of the change's `gate` the user ticked


@app.post("/api/changes/{change_id}/pull-request")
def open_pull_request(change_id: str, body: OpenPullRequest | None = None):
    """The user's approval: only this endpoint (called by the "Open pull request" button) opens a pull request, and
    only once everything the review found is confirmed."""
    try:
        meta = changes.open_pull_request(change_id, (body.confirmed if body else []))
    except changes.ChangeError as exc:
        raise HTTPException(400, str(exc))
    flows.log_event(meta["flow_id"], "change", f"Pull request opened by you: “{meta['title']}” {meta['pr_url']}")
    return meta


@app.post("/api/changes/{change_id}/discard")
def discard_change(change_id: str):
    try:
        return changes.discard(change_id)
    except changes.ChangeError as exc:
        raise HTTPException(400, str(exc))


class Approval(BaseModel):
    allow: bool


@app.post("/api/chat/approvals/{approval_id}")
async def answer_approval(approval_id: str, body: Approval):
    if not agent.answer_approval(approval_id, body.allow):
        raise HTTPException(404, "That request is no longer waiting (it was answered or timed out).")
    return {"ok": True}


# --------------------------------------------------------------------------- tools for the Codex chat engine


def _codex_only(request: Request) -> None:
    """Only the Codex process Flowhaus started has this token (see server/codex_engine.py)."""
    if not secrets.compare_digest(request.headers.get("x-flowhaus-token", ""), agent.CODEX_TOKEN):
        raise HTTPException(403, "Not allowed")


@app.get("/api/agent/tools")
def agent_tools(request: Request):
    _codex_only(request)
    return {"tools": agent.codex_tools()}


class ToolCall(BaseModel):
    name: str
    arguments: dict = {}


@app.post("/api/agent/call")
async def agent_call(request: Request, body: ToolCall):
    _codex_only(request)
    text, is_error = await agent.call_codex_tool(body.name, body.arguments)
    return {"text": text, "is_error": is_error}


class WhatIf(BaseModel):
    flow_id: str
    step_id: str
    items: list[dict]
    downstream: bool = True


@app.post("/api/whatif")
def what_if(body: WhatIf):
    """Run one step (and what comes after it) on edited items, in test mode: nothing published or saved."""
    try:
        return whatif.try_step(body.flow_id, body.step_id, body.items, body.downstream)
    except KeyError:
        raise HTTPException(404, "No such flow or step")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class Replay(BaseModel):
    flow_id: str
    run_id: str


@app.post("/api/whatif/replay")
def replay_run(body: Replay):
    """Send a past run's items through the flow as it is now, in test mode, and compare with what that run gave."""
    try:
        return whatif.replay(body.flow_id, body.run_id)
    except KeyError:
        raise HTTPException(404, "No such flow or run")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/checkup")
def get_checkup(flow_id: str, run_id: str | None = None):
    """The Review button: everything that's broken, silently failing, drifting or could be better, each with its
    next step, and the problem to solve first (the chat's first message when there are errors)."""
    flows.get_meta(flow_id)
    return checkup.checkup(flow_id, run_id)


@app.get("/api/harness")
def get_harness(flow_id: str):
    """The big picture: gaps, blind spots and questions for the user, plus what they already answered or dismissed."""
    flows.get_meta(flow_id)
    return harness.review(flow_id)


class HarnessAnswer(BaseModel):
    question_id: str
    answer: str
    note: str = ""


class HarnessDismiss(BaseModel):
    finding_id: str
    reason: str


class HarnessRestore(BaseModel):
    id: str


def _harness_call(flow_id: str, call):
    if not harness.reviewed(flow_id):
        raise HTTPException(404, f"No automation of yours called '{flow_id}'")
    try:
        return call()
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/harness/{flow_id}/answer")
def answer_question(flow_id: str, body: HarnessAnswer):
    return _harness_call(flow_id, lambda: harness.answer(flow_id, body.question_id, body.answer, body.note))


@app.post("/api/harness/{flow_id}/dismiss")
def dismiss_finding(flow_id: str, body: HarnessDismiss):
    return _harness_call(flow_id, lambda: harness.dismiss(flow_id, body.finding_id, body.reason))


@app.post("/api/harness/{flow_id}/restore")
def restore_finding(flow_id: str, body: HarnessRestore):
    return _harness_call(flow_id, lambda: harness.restore(flow_id, body.id))


# --------------------------------------------------------------------------- test lab


@app.get("/api/tests/{flow_id}")
def get_tests(flow_id: str):
    """Everything the test lab shows: how tests run here, the item fields, the suite, recent test runs."""
    return {"mode": testlab.mode(flow_id), "fields": testlab.shape(flow_id), "suite": testlab.get_suite(flow_id),
            "runs": [{k: v for k, v in r.items() if k not in ("cases", "run")} for r in testlab.list_test_runs(flow_id)]}


class Suite(BaseModel):
    cases: list[dict]
    checks: list[dict] = []


@app.put("/api/tests/{flow_id}/suite")
def put_suite(flow_id: str, body: Suite):
    return testlab.save_suite(flow_id, body.model_dump())


class Generate(BaseModel):
    count: int = 10
    temperature: float = 0.5


@app.post("/api/tests/{flow_id}/generate")
def generate_tests(flow_id: str, body: Generate):
    flows.get_meta(flow_id)
    return {"cases": testlab.generate(flow_id, body.count, body.temperature)}


class StartTest(BaseModel):
    confirmed: bool = False


@app.post("/api/tests/{flow_id}/run")
def run_tests(flow_id: str, body: StartTest):
    """Only the UI's "Run test" button (or `flowhaus test`) starts a test run; remote ones need confirmation."""
    try:
        return testlab.start(flow_id, body.confirmed)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/tests/{flow_id}/runs/{test_id}")
def get_test_run(flow_id: str, test_id: str):
    return testlab.refresh(flow_id, test_id)


@app.get("/api/mcp")
def get_mcp():
    """MCP servers found in your Claude Code / Claude Desktop / Cursor / project settings, and which the chat may use."""
    return mcp.summary()


@app.post("/api/mcp/{name}/tools")
async def mcp_tools(name: str):
    """Start the server briefly and ask which tools it offers (only when you click "Show tools").

    A POST, not a GET: it starts a program from your setup, so other web pages must not be able to trigger it.
    """
    from server import mcp_client

    server = mcp.discover().get(name)
    if server is None:
        raise HTTPException(404, f"No MCP server '{name}' in your setup")
    if server["problem"]:
        raise HTTPException(400, f"Can't start it: {server['problem']}")
    try:
        tools = await mcp_client.list_tools(server["sdk"])
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))
    allowed = {t["name"]: not mcp.needs_approval(f"mcp__{name}__{t['name']}") for t in tools}
    return {"tools": [{"name": t["name"], "description": t["description"], "asks_first": not allowed[t["name"]]} for t in tools]}


class McpToggle(BaseModel):
    enabled: bool


@app.put("/api/mcp/{name}")
def toggle_mcp(name: str, body: McpToggle):
    mcp.set_enabled(name, body.enabled)
    return mcp.summary()


# --------------------------------------------------------------------------- the built UI (flowhaus start)

if os.environ.get("FLOWHAUS_SERVE_UI") == "1":
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    class _UI(StaticFiles):
        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            if path in ("", ".", "index.html"):
                response.headers["Cache-Control"] = "no-cache"  # always pick up a rebuilt UI
            return response

    _dist = Path(__file__).resolve().parent.parent / "web" / "dist"
    if _dist.is_dir():
        app.mount("/", _UI(directory=_dist, html=True), name="ui")

