"""Chat agent: a Claude Agent SDK session that builds, explains and edits flows.

One long-lived worker task owns the SDK client (the client must stay inside a
single async context), and chat requests are handed to it through a queue.

The agent gets:
- `flow` tools (in-process MCP): list/create/update flows, groups, run, validate, inspect;
- `clay` and `firecrawl` tools (in-process MCP, DUMMY): to explore what the apps return while building;
- Claude Code's own tools (Read, Edit, Bash, ...), under the user's own Claude Code settings: their permission rules
  decide what runs without asking; anything else shows an Allow / Deny card in the chat (`ask_permission`).
Flowhaus's own tools keep Flowhaus's rules (`check_tool_use`): creating and running flows only for flows built in
Flowhaus, with the builder (demo mode) on; changes to connected automations go through a change copy and a pull
request the user opens.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import os
import re
import secrets
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    StreamEvent,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
    tool,
)

from server import automations, changes, connections, flows, harness, maps, mcp, review, runs, runtime

ROOT = runtime.ROOT
FLOWS_DIR = runs.FLOWS_DIR
MANAGED_GLOBS = ("pipeline/*.py", "flow_map.yaml", "flows/*/flow.yaml", "flows/*/steps/*.py",
                 "flows/*/data/*.csv", "flows/*/data/*.json")
def read_only_projects() -> list[Path]:
    """Code folders added to the chat's workspace: connected automations' code, and the private clones made for
    proposed changes (state/changes/<id>/repo)."""
    return [*changes.open_workspaces(), *automations.read_only_paths()]


FLOW_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,40}$")

SYSTEM_PROMPT = """\
You build and maintain automations ("flows") for a user who manages them from the top level and never reads code.
They see each flow as a map: boxes (groups) with a short label and one-line description, which open to show the
steps inside. Every step shows the items that went in and out, items it skipped (with a reason) and the calls it
made to outside apps. Your job is all the technical work: code, integrations, keeping the map accurate.

HOW YOU THINK ABOUT AUTOMATIONS (Flowhaus is a harness; full guide: docs/practices.md)
- An automation is a chain. Any change to one step reaches every step after it: more or fewer items, renamed or
  reformatted fields, different costs. Before changing anything, call downstream_of and say what happens to each
  step after it. A "small" change (a threshold, a field name, a date format, a log line) is often the big one.
- One source of truth: reuse or extend the existing function, list or setting instead of copying it. Don't create a
  variant of a step by copying it; give it a parameter.
- Items that leave the flow leave with a short, stable reason. Never drop silently; never swallow errors into an
  empty "success". Numbers must add up (in = out + skipped).
- Keep it safe to run twice (no double publishing, emailing or charging).
- Log lines are part of the contract: the map counts them. If you reword one, say so and update the counting rule.
- One change at a time. Say beforehand which number on the map should move and by roughly how much.
- Pressure-test: the user has a test lab (Test button; docs/testing.md) that runs the flow on tricky items in test
  mode. You can't start test runs, but suggest which edge cases to try. If an automation has no safe test mode (no
  dry_run input, no test webhook), offer to prepare one as a pull request: an input that skips publishing and paid
  calls, plus the `test:` block for its automation.yaml (as text for the user; you can't edit automation.yaml).

BE OPINIONATED, NOT STUBBORN (the user's own automations, connected or built here, come with a "harness" context)
- Look past the question. After answering, if one of the open findings (gaps, blind spots) matters for what the user
  is doing, name the single most important one in one sentence, with why it matters for them. Not a list, not every time.
- When you notice a big-picture gap or blind spot yourself (a step nobody counts, a filter with no skip reason, a
  re-run that would publish twice, a cost nobody sees), say so plainly even if they didn't ask.
- When the right answer depends on something only the user knows (what a normal run looks like, whether a high skip
  rate is intended, who relies on the output), ask ONE short question instead of assuming. Say why you ask.
- When the user tells you such context, save it with remember_context (short topic, one-sentence note) so it isn't
  asked again. Respect what they dismissed and why ("dismissed_by_user"): don't raise it again unless something
  changed, and then say what changed.
- State your view and the reason once; if the user disagrees, go with their call.

FILES
- You have your usual tools. The user's own Claude Code permissions decide what you may do without asking; anything
  else asks them first (an Allow / Deny card). If they deny something, don't retry it; ask what they'd like instead.
- Never run, deploy or push the user's connected automations, and don't edit their code directly.
- Creating and running flows (the flow tools) only works for flows built in Flowhaus, while the user has demo flows
  turned on.
- For connected automations with pull requests enabled: start_change, edit the private copy, propose_change. The user
  reviews the diff and opens the pull request. Otherwise explain and propose changes in words.
- Tools from the user's own MCP servers (mcp__<name>__...) ask the user before each call unless they allowed the tool.
  If a call is denied, don't retry it.

HOW FLOWS ARE STORED
- New flows live in flows/<flow_id>/:
  - flow.yaml: name, description, trigger, output (where results go, e.g. "Handed to sales"), terms (what one item
    is called), groups. Create and change it ONLY with
    the create_flow / update_flow / update_group tools.
  - steps/*.py: one Hamilton function per step (you write these with Write/Edit).
  - data/*.csv or *.json: sample input items (you write these). A run feeds the file to the first step as `input_path`.
- The older "contact-cleaning" flow lives in pipeline/*.py with groups in flow_map.yaml (flow_id "contact-cleaning").
- Sample flows (lead-enrichment, churn-digest, invoice-booking, salesforce-sheet-sync) are read-only demos with made-up
  history and no code.

HOW A STEP LOOKS (flows/<id>/steps/<name>.py)
    import pandas as pd
    from hamilton.function_modifiers import tag

    from connectors import clay, firecrawl
    from flowkit import Skip, load_items, skip_where, update_items


    @tag(label="Receive leads", description="Gives you each new lead with name and email.", group="receive", app="Sample file")
    def receive_leads(input_path: str) -> pd.DataFrame:
        return load_items(input_path)


    @tag(label="Add company details", description="Adds company name, size and industry from Clay.", group="enrich", app="Clay")
    def add_company_details(receive_leads: pd.DataFrame) -> pd.DataFrame:
        def enrich(lead: dict) -> dict:
            info = clay.enrich_company(lead["email"])
            return {"company": info["name"], "employees": info["employees"], "industry": info["industry"]}
        return update_items(receive_leads, enrich)

- Steps are wired by parameter name: a parameter named like another step receives that step's output.
- Every step has tags label, description, group (a group id from flow.yaml) and app (the app it talks to:
  "Clay", "Firecrawl", "Code", "Claude", "Sample file", ...).
- Items travel as a DataFrame with `_row_id` and `_rejected_reason`. Never drop items: skip them with a short
  plain-English reason (raise Skip("...") inside update_items, or use skip_where). Never overwrite an existing reason.
- flowkit.update_items(df, fn): fn(item_dict) returns a dict of fields to add/change. A connector ItemError (e.g. page
  not found) skips just that item; a ConnectorError (not connected, rate limit) fails the step, which is correct.
- Keep one step = one function. Keep steps small and named the way the user would describe them.

CONNECTED APPS (DUMMIES in this prototype: no real network calls, realistic made-up answers)
- Clay (connectors.clay): enrich_company(domain_or_email) -> {domain, name, employees, industry, location,
  linkedin_url, founded}; enrich_person(email) -> {email, full_name, job_title, seniority, linkedin_url}.
- Firecrawl (connectors.firecrawl): scrape(url) -> {url, title, description, word_count, has_pricing_page,
  has_careers_page, tech_stack (list), summary}; search(query, limit=3) -> [{url, title, snippet}].
- Before writing a step that uses an app, try it once with the mcp__clay__* / mcp__firecrawl__* tools on a sample
  value so you know the exact fields. Clay and Firecrawl here are demo connectors (no keys, no network). Flowhaus never stores
  keys: for real apps, tell the user how to set them up in their own tools (CLI, .env, CI secrets). Apps without a connector (HubSpot, Slack, Gmail, ...) can't be called yet: represent them
  as a clearly labelled placeholder step (label ends with "(not connected yet)", app set to that app) that passes
  items through and adds a note field describing what would happen.

NAMING (titles and descriptions of steps AND groups)
- Describe what the box PRODUCES, not the mechanics. The user reads the map to know what comes out of each box.
- Title: 2-5 words, starting with the outcome verb: "Add company details", "Skip small companies",
  "Keep managers and above", "Tidy names and emails", "Post to #sales". Not "Read website", "Call Clay", "Process leads".
- Description: one sentence naming the concrete output, then the source app:
  "Adds what the company does, tech stack, pricing page and careers page from Firecrawl."
  "Skips companies with fewer than 50 employees."  "Posts each lead to #sales-leads in Slack."
  Name the actual fields added (use the field names a person would say, e.g. "company size", not "employees_count");
  if there are more than four, name the three most useful "and more".
- Group descriptions summarise the outputs of the steps inside ("Adds company size, industry and job title; skips poor fits").
- After a run, validate_map shows what each step actually added, changed and skipped: make the words match that.

RULES
1. The map is yours to keep accurate. When a step's behaviour changes, update its label/description tags in the same
   edit; when steps are added, removed or moved, update the groups (update_group) so every group still describes
   everything inside it. Groups are the top-level story: 3-6 groups, each a plain-English phase.
2. If the user has a box selected, the request is about it: call get_node_context first.
3. Talk in plain English about the process, in short sentences. No code unless asked. Refer to steps by label.
4. After any change: validate_map, then run_flow, then summarise the effect in counts and calls
   (e.g. "12 leads in, 3 skipped because Clay found no company, 9 passed on; 21 Clay calls").
5. When building a new flow: pick a short kebab-case flow_id, call create_flow with the groups and an output_label, write sample data
   (6-12 realistic items that exercise the skip rules), write the steps, validate, run, and report. Ask at most one
   clarifying question, and only if the request is genuinely ambiguous; otherwise make sensible choices and say so.
6. Never touch anything outside the project folder. You cannot read state/ (it holds connection keys).
Do not narrate your plan between tool calls. Write your answer once, after your last tool call. Keep it brief.
"""


# --------------------------------------------------------------------------- helpers


def _text(data: Any) -> dict:
    body = data if isinstance(data, str) else json.dumps(data, indent=1, default=str)
    return {"content": [{"type": "text", "text": body}]}


def _schema(props: dict[str, str], required: list[str]) -> dict:
    return {"type": "object", "properties": {k: {"type": t} for k, t in props.items()}, "required": required}


def _flow_or_error(flow_id: str | None) -> tuple[str | None, dict | None]:
    flow_id = flow_id or WORKER.current_flow
    if not flow_id:
        return None, _text("Say which flow: pass flow_id (see list_flows).")
    try:
        flows.kind(flow_id)
    except KeyError:
        return None, _text(f"No flow '{flow_id}'. Call list_flows to see the ids.")
    return flow_id, None


def _map_path(flow_id: str) -> Path:
    return runs.flow_paths(flow_id)["map"]


# --------------------------------------------------------------------------- flow tools


@tool("list_flows", "All flows with id, name, kind (live/built/sample), trigger and last run.", {})
async def list_flows_tool(args: dict) -> dict:
    out = []
    for f in await asyncio.to_thread(flows.overview):
        out.append({k: f.get(k) for k in ("id", "name", "kind", "enabled", "description", "trigger", "apps")}
                   | {"last_run": (f.get("last_run") or {}).get("status")})
    return _text(out)


@tool("get_map", "Groups, steps (with tags), edges and map problems of one flow.", _schema({"flow_id": "string"}, []))
async def get_map_tool(args: dict) -> dict:
    flow_id, err = _flow_or_error(args.get("flow_id"))
    if err:
        return err
    m = await asyncio.to_thread(flows.get_map, flow_id)
    return _text({k: m[k] for k in ("flow", "groups", "steps", "edges", "problems")})


@tool("get_node_context", "Code, tags and latest run data (items in/out, skips, app calls) for one step or group.",
      _schema({"node_id": "string", "flow_id": "string", "run_id": "string"}, ["node_id"]))
async def get_node_context_tool(args: dict) -> dict:
    flow_id, err = _flow_or_error(args.get("flow_id"))
    if err:
        return err
    node_id = args["node_id"]
    m = await asyncio.to_thread(flows.get_map, flow_id)
    group = next((g for g in m["groups"] if g["id"] == node_id), None)
    step = next((s for s in m["steps"] if s["id"] == node_id), None)
    if not group and not step:
        return _text(f"No step or group '{node_id}' in {flow_id}. Call get_map to see the ids.")
    listed = flows.list_runs(flow_id)
    run_id = args.get("run_id") or (listed[0]["run_id"] if listed else None)
    run = flows.get_run(flow_id, run_id) if run_id else None
    ctx: dict[str, Any] = {"flow_id": flow_id, "run_id": run_id}
    if flows.kind(flow_id) == "connected":
        # only what the adapter chooses to share: counts, reasons, errors; never item tables or file previews
        shared = flows.connected()[flow_id].agent_context(run)
        viewed = (shared.get("run_being_viewed") or {}).get("steps") or {}
        inside = [node_id] if step else maps.descendant_steps(node_id, m["groups"], m["steps"])
        ctx.update({"step": step, "group": group, "latest_run": {s: viewed.get(s) for s in inside}})
        return _text(ctx)
    if step:
        ctx["step"] = step
        if flows.kind(flow_id) != "sample":
            ctx["code"] = runtime.step_source(node_id, runs.flow_paths(flow_id)["code"])
        if run and node_id in run["nodes"]:
            n = run["nodes"][node_id]
            ctx["latest_run"] = {k: n.get(k) for k in ("status", "rows_in", "rows_out", "rows_rejected", "reject_reasons",
                                                       "sample_in", "sample_out", "error", "calls_total", "credits")}
            ctx["latest_run"]["skipped"] = [{"row": r["_row_id"], "reason": r["reason"], "item": r["before"]}
                                            for r in n.get("rejected_samples", [])[:30]]
            ctx["latest_run"]["calls"] = (n.get("calls") or [])[:8]
    else:
        ctx["group"] = group
        inside = maps.descendant_steps(node_id, m["groups"], m["steps"])
        ctx["steps_inside"] = [s for s in m["steps"] if s["id"] in inside]
        if run:
            ctx["latest_run"] = {s: {k: run["nodes"].get(s, {}).get(k) for k in
                                     ("status", "rows_in", "rows_out", "rows_rejected", "reject_reasons")} for s in inside}
    return _text(ctx)


@tool("create_flow",
      "Create a new flow folder with flow.yaml. groups_json is a JSON list of {id, label, description}. "
      "trigger_type is one of manual, webhook, schedule, event.",
      _schema({"flow_id": "string", "name": "string", "description": "string", "trigger_type": "string",
               "trigger_label": "string", "item": "string", "items": "string", "title_field": "string",
               "subtitle_field": "string", "groups_json": "string", "output_label": "string"},
              ["flow_id", "name", "description", "item", "items", "groups_json"]))
async def create_flow_tool(args: dict) -> dict:
    flow_id = args["flow_id"].strip().lower()
    if not FLOW_ID_RE.match(flow_id) or flow_id in flows.flow_ids():
        return _text(f"Pick another flow_id: '{flow_id}' is taken or not kebab-case (a-z, 0-9, dashes, 3-40 chars).")
    try:
        groups = json.loads(args["groups_json"])
        groups = [{"id": str(g["id"]), "label": g["label"], "description": g.get("description", ""), "parent": g.get("parent")}
                  for g in groups]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return _text(f"groups_json must be a JSON list of {{id, label, description}}: {exc}")
    base = FLOWS_DIR / flow_id
    (base / "steps").mkdir(parents=True, exist_ok=True)
    (base / "data").mkdir(exist_ok=True)
    config = {
        "title": args["name"], "description": args["description"],
        "trigger": {"type": args.get("trigger_type") or "manual",
                    "label": args.get("trigger_label") or "Run by hand on sample data"},
        "terms": {"item": args["item"], "items": args["items"]},
        "title_field": args.get("title_field") or "name", "subtitle_field": args.get("subtitle_field") or "email",
        "sample_input": "data/sample.csv", "created_by": "Claude",
        "output": {"label": args.get("output_label") or f"The {args['items']} that made it through"}, "groups": groups,
    }
    maps.write_yaml(config, base / "flow.yaml")
    WORKER.current_flow = flow_id
    WORKER.created_flows.append(flow_id)
    _current_events().emit({"type": "flow_created", "flow_id": flow_id, "name": args["name"]})
    flows.log_event(flow_id, "change", f"Claude created the flow “{args['name']}”")
    return _text({"created": f"flows/{flow_id}", "next": "Write data/sample.csv (or .json; then update_flow sample_input) "
                  "and steps/*.py, then validate_map and run_flow."})


@tool("update_flow", "Change a built flow's name, description, trigger, item words, title/subtitle fields or sample_input.",
      _schema({"flow_id": "string", "name": "string", "description": "string", "trigger_type": "string",
               "trigger_label": "string", "item": "string", "items": "string", "title_field": "string",
               "subtitle_field": "string", "sample_input": "string", "output_label": "string"}, ["flow_id"]))
async def update_flow_tool(args: dict) -> dict:
    flow_id, err = _flow_or_error(args.get("flow_id"))
    if err:
        return err
    if flows.kind(flow_id) != "built":
        return _text("Only flows in flows/ can be changed with update_flow.")
    path = _map_path(flow_id)
    cfg = maps.read_yaml(path)
    if args.get("name"):
        cfg["title"] = args["name"]
    for key in ("description", "title_field", "subtitle_field", "sample_input"):
        if args.get(key):
            cfg[key] = args[key]
    if args.get("trigger_type") or args.get("trigger_label"):
        cfg["trigger"] = {**(cfg.get("trigger") or {}), **({"type": args["trigger_type"]} if args.get("trigger_type") else {}),
                          **({"label": args["trigger_label"]} if args.get("trigger_label") else {})}
    if args.get("output_label"):
        cfg["output"] = {"label": args["output_label"]}
    if args.get("item") or args.get("items"):
        cfg["terms"] = {**(cfg.get("terms") or {}), **({"item": args["item"]} if args.get("item") else {}),
                        **({"items": args["items"]} if args.get("items") else {})}
    maps.write_yaml(cfg, path)
    return _text({"updated": {k: v for k, v in cfg.items() if k != "groups"}})


@tool("update_group", "Create or edit a group (a box on the top level) of a flow. parent='' means top level.",
      _schema({"flow_id": "string", "id": "string", "label": "string", "description": "string", "parent": "string"}, ["id"]))
async def update_group_tool(args: dict) -> dict:
    flow_id, err = _flow_or_error(args.get("flow_id"))
    if err:
        return err
    if flows.kind(flow_id) == "sample":
        return _text("Sample flows are read-only. Offer to build it as a new flow instead.")
    path = _map_path(flow_id)
    try:
        exists = any(g["id"] == args["id"] for g in maps.read_groups(path))
        group = maps.update_group(args["id"], args.get("label"), args.get("description"), args.get("parent"),
                                     create=not exists, path=path)
    except Exception as exc:
        return _text(f"Could not update group: {exc}")
    return _text({"updated": group, "problems": flows.get_map(flow_id)["problems"]})


@tool("validate_map", "Check every step has label/description/group/app and every group has something inside.",
      _schema({"flow_id": "string"}, []))
async def validate_map_tool(args: dict) -> dict:
    flow_id, err = _flow_or_error(args.get("flow_id"))
    if err:
        return err
    m = await asyncio.to_thread(flows.get_map, flow_id)
    problems = list(m["problems"])
    if flows.kind(flow_id) == "built":
        problems += [f"Step '{s['id']}' has no 'app' tag" for s in m["steps"] if not s.get("app")]
        if not m["steps"]:
            problems.append("The flow has no steps yet")
    return _text({"valid": not problems, "problems": problems,
                  "what_each_step_outputs": step_outputs(flow_id, m),
                  "check": "Make every title and description describe this output (see NAMING)."})


def step_outputs(flow_id: str, m: dict) -> dict:
    """From the latest run: the fields each step added or changed and why it skipped items."""
    listed = flows.list_runs(flow_id)
    run = flows.get_run(flow_id, listed[0]["run_id"]) if listed else None
    if not run:
        return {"note": "No run yet: run_flow first, then compare the labels with what each step outputs."}
    out = {}
    for s in m["steps"]:
        n = run["nodes"].get(s["id"])
        if not n:
            continue
        before = {r["_row_id"]: r for r in n.get("sample_in") or []}
        added, changed = [], []
        for row in n.get("sample_out") or []:
            prev = before.get(row["_row_id"], {})
            for k, v in row.items():
                if k.startswith("_"):
                    continue
                if k not in prev and k not in added:
                    added.append(k)
                elif k in prev and prev[k] != v and k not in changed:
                    changed.append(k)
        out[s["id"]] = {"title": s.get("label"), "description": s.get("description"), "fields_added": added,
                        "fields_changed": changed, "skip_reasons": list((n.get("reject_reasons") or {}).keys())}
    return out


@tool("run_flow", "Run a flow on its sample input (or input_file). Returns per-step counts, skip reasons and app calls.",
      _schema({"flow_id": "string", "input_file": "string"}, []))
async def run_flow_tool(args: dict) -> dict:
    flow_id, err = _flow_or_error(args.get("flow_id"))
    if err:
        return err
    if flows.kind(flow_id) == "sample":
        return _text("Sample flows can't be run for real; they have no code.")
    try:
        run = await asyncio.to_thread(runs.run_blocking, args.get("input_file") or None, "chat", flow_id=flow_id)
    except ValueError as exc:
        return _text(str(exc))
    _current_events().emit({"type": "run", "run_id": run["run_id"], "flow_id": flow_id, "status": run["status"]})
    WORKER.ran_at[flow_id] = flow_fingerprint(flow_id)
    return _text({
        "run_id": run["run_id"], "status": run["status"], "error": run.get("error"), "summary": run.get("summary"),
        "steps": {nid: {k: n.get(k) for k in ("label", "status", "rows_in", "rows_rejected", "rows_out", "reject_reasons",
                                               "calls_total", "error")}
                  for nid, n in run.get("nodes", {}).items()},
    })


@tool("list_connections", "The apps your flows and automations use, and how each is set up (Clay and Firecrawl demo "
      "connectors need no setup).", {})
async def list_connections_tool(args: dict) -> dict:
    return _text([{k: c.get(k) for k in ("id", "name", "available", "connected", "description", "actions")}
                  for c in connections.list_connections()])


FLOW_TOOLS = [list_flows_tool, get_map_tool, get_node_context_tool, create_flow_tool, update_flow_tool, update_group_tool,
              validate_map_tool, run_flow_tool, list_connections_tool]
FLOW_SERVER = create_sdk_mcp_server(name="flow", version="1.0.0", tools=FLOW_TOOLS)


# --------------------------------------------------------------------------- dummy app MCP servers


async def _connector(module_name: str, action: str, **kwargs) -> dict:
    import importlib

    from connectors import ConnectorError, ItemError

    module = importlib.import_module(f"connectors.{module_name}")
    try:
        result = await asyncio.to_thread(getattr(module, action), **kwargs)
        return _text({"dummy": True, "result": result})
    except (ConnectorError, ItemError) as exc:
        return _text({"dummy": True, "error": str(exc), "kind": type(exc).__name__})


@tool("enrich_company", "DUMMY Clay: company facts for a domain or work email.", {"domain_or_email": str})
async def clay_company(args: dict) -> dict:
    return await _connector("clay", "enrich_company", domain_or_email=args["domain_or_email"])


@tool("enrich_person", "DUMMY Clay: person facts (job title, seniority, LinkedIn) for an email.", {"email": str})
async def clay_person(args: dict) -> dict:
    return await _connector("clay", "enrich_person", email=args["email"])


@tool("scrape", "DUMMY Firecrawl: read one web page (title, summary, pricing/careers page, tech stack).", {"url": str})
async def fc_scrape(args: dict) -> dict:
    return await _connector("firecrawl", "scrape", url=args["url"])


@tool("search", "DUMMY Firecrawl: web search, returns url/title/snippet.", _schema({"query": "string", "limit": "integer"}, ["query"]))
async def fc_search(args: dict) -> dict:
    return await _connector("firecrawl", "search", query=args["query"], limit=int(args.get("limit") or 3))


CLAY_SERVER = create_sdk_mcp_server(name="clay", version="0.1.0-dummy", tools=[clay_company, clay_person])
FIRECRAWL_SERVER = create_sdk_mcp_server(name="firecrawl", version="0.1.0-dummy", tools=[fc_scrape, fc_search])

ALL_TOOL_NAMES = ([f"mcp__flow__{t.name}" for t in FLOW_TOOLS]
                  + ["mcp__clay__enrich_company", "mcp__clay__enrich_person", "mcp__firecrawl__scrape", "mcp__firecrawl__search"])


# --------------------------------------------------------------------------- guardrails

def _connected_adapter():
    flow_id = WORKER.current_flow
    if not flow_id or flow_id not in flows.connected():
        return None
    return flows.connected()[flow_id]


@tool("start_change", "Start a proposed code change to the connected automation the user is looking at. Makes a private "
      "copy of its repository; edit files there with Edit/Write (paths inside the returned folder). Nothing reaches "
      "GitHub until the user approves the pull request.", _schema({"title": "string"}, ["title"]))
async def start_change_tool(args: dict) -> dict:
    adapter = _connected_adapter()
    if adapter is None:
        return _text("Open a connected automation first: changes are for the user's own automations.")
    if (ws := active_workspace()) is not None:
        return _text(f"A change is already in progress in {ws}. Finish it with propose_change or discard_change.")
    try:
        meta = await asyncio.to_thread(changes.start, adapter, args["title"])
    except changes.ChangeError as exc:
        return _text(str(exc))
    WORKER.active_change = meta["id"]
    return _text({"folder": str(changes.workspace(meta["id"])), "branch": meta["branch"], "base": meta["base"],
                  "note": "Edit files under `folder` with your file tools. Don't run anything. When done, call "
                          "propose_change with a plain-English summary."})


def _latest_finished_run(flow_id: str) -> dict | None:
    summary = next((r for r in flows.list_runs(flow_id) if r["status"] in ("success", "failed")), None)
    return flows.get_run(flow_id, summary["run_id"]) if summary else None


def _review(change_id: str, adapter) -> dict:
    diff, files = changes.current_diff(change_id)
    fmap = flows.get_map(adapter.id)
    return review.review(fmap, adapter.config, changes.workspace(change_id), diff, files, _latest_finished_run(adapter.id))


@tool("downstream_of", "Everything that comes after a step (or group) in the flow you're looking at, with its latest "
      "numbers. Use it before changing a step: those are the steps your change can affect.",
      _schema({"node_id": "string"}, ["node_id"]))
async def downstream_of_tool(args: dict) -> dict:
    flow_id = WORKER.current_flow
    if not flow_id:
        return _text("Open a flow first.")
    fmap = await asyncio.to_thread(flows.get_map, flow_id)
    ids = maps.descendant_steps(args["node_id"], fmap["groups"], fmap["steps"]) or [args["node_id"]]
    after = review.downstream(fmap, ids)
    run = await asyncio.to_thread(_latest_finished_run, flow_id)
    nodes = (run or {}).get("nodes") or {}
    steps = {s["id"]: s for s in fmap["steps"]}
    return _text({"changed": ids, "downstream": [
        {"id": s, "label": steps[s].get("label"), "description": steps[s].get("description"), "file": steps[s].get("file"),
         "last_run": {k: nodes.get(s, {}).get(k) for k in ("rows_in", "rows_out", "rows_rejected", "reject_reasons")}}
        for s in after]})


@tool("review_change", "Check the change in progress the way the user's review will: which steps it touches, what comes "
      "after them, repeated code (reuse instead), log lines the map counts on. Fix what it finds before proposing.",
      _schema({}, []))
async def review_change_tool(args: dict) -> dict:
    adapter, change_id = _connected_adapter(), WORKER.active_change
    if adapter is None or not change_id or active_workspace() is None:
        return _text("No change in progress. Call start_change first.")
    result = await asyncio.to_thread(_review, change_id, adapter)
    result.pop("baseline", None)
    return _text(result)


@tool("propose_change", "Finish the change and show it to the user as a diff with an 'Open pull request' button. "
      "summary: what changes for the user and why, in plain English (it becomes the PR description). "
      "impact: the effect on every step after the changed ones (items, fields, counts, cost), and which number "
      "on the map should move and roughly how much.",
      _schema({"summary": "string", "impact": "string"}, ["summary", "impact"]))
async def propose_change_tool(args: dict) -> dict:
    adapter, change_id = _connected_adapter(), WORKER.active_change
    if adapter is None or not change_id or active_workspace() is None:
        return _text("No change in progress. Call start_change first.")
    try:
        findings = await asyncio.to_thread(_review, change_id, adapter)
        meta = await asyncio.to_thread(changes.propose, change_id, args["summary"], args.get("impact", ""), findings)
    except changes.ChangeError as exc:
        return _text(str(exc))
    WORKER.active_change = None
    _current_events().emit({"type": "proposal", "change": meta})
    return _text(f"Shown to the user for review ({len(meta['files'])} files). They decide whether to open the pull "
                 "request; don't say it's opened or merged. After it's merged, Flowhaus compares the next run with "
                 "today's numbers.")


@tool("discard_change", "Throw away the change in progress.", _schema({}, []))
async def discard_change_tool(args: dict) -> dict:
    change_id = WORKER.active_change
    if not change_id:
        return _text("No change in progress.")
    await asyncio.to_thread(changes.discard, change_id)
    WORKER.active_change = None
    return _text("Discarded.")


@tool("remember_context", "Keep something the user told you about the automation they're looking at (what a normal run "
      "looks like, why a step skips a lot, who relies on the output), so it isn't asked again. topic: a few words; "
      "note: one plain sentence in the user's terms.", _schema({"topic": "string", "note": "string"}, ["topic", "note"]))
async def remember_context_tool(args: dict) -> dict:
    flow_id = WORKER.current_flow
    if not flow_id or not harness.reviewed(flow_id):
        return _text("Context is kept for the user's own automations only (connected or built in Flowhaus).")
    try:
        await asyncio.to_thread(harness.note, flow_id, args.get("topic", ""), args.get("note", ""))
    except ValueError as exc:
        return _text(str(exc))
    return _text("Kept. It's in the flow's context.yaml, which the user can read and edit.")


CHANGES_SERVER = create_sdk_mcp_server(name="changes", version="1.0.0",
                                       tools=[start_change_tool, review_change_tool, propose_change_tool,
                                              discard_change_tool, downstream_of_tool, remember_context_tool])


BUILDER_TOOLS = {"mcp__flow__create_flow", "mcp__flow__update_flow", "mcp__flow__update_group", "mcp__flow__run_flow"}


def active_workspace() -> Path | None:
    """The clone the chat is editing for a proposed change, if any (only while on that automation)."""
    change_id = WORKER.active_change
    if not change_id:
        return None
    try:
        meta = changes.get(change_id)
    except KeyError:
        return None
    if meta["status"] != "editing" or meta["flow_id"] != WORKER.current_flow:
        return None
    return changes.workspace(change_id).resolve()


def builder_allowed() -> bool:
    """Writing and running code: only for flows built in Flowhaus, and only while the builder (demo mode) is on.

    Never while the user looks at a connected automation, so text from its logs or code can't get code run.
    """
    if not flows.show_demo():
        return False
    flow_id = WORKER.current_flow
    if flow_id is None:
        return True  # the "new flow" page
    try:
        return flows.kind(flow_id) != "connected"
    except KeyError:
        return False


# Claude Code's file tools and the input that names the file or folder they touch
FILE_TOOLS = {"Read": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "Write": "file_path",
              "NotebookEdit": "notebook_path", "Grep": "path", "Glob": "path"}
EDIT_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}


def _resolve(raw: str | None) -> Path:
    p = Path(raw).expanduser() if raw else ROOT
    return (p if p.is_absolute() else ROOT / p).resolve()


def _within(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def check_tool_use(tool_name: str, tool_input: dict, builder: bool | None = None) -> str | None:
    """Flowhaus's rules: a reason to deny the call, or None. Everything else follows the user's own Claude Code
    permission rules (`ask_permission`). Flowhaus adds only what its docs promise:

      - its flow tools work only in the builder
      - `private_paths`, and a folder-runs automation's run outputs, are never read (personal data)
      - a connected automation's real code is never edited: changes go to the private copy (`start_change`)
    """
    if tool_name in BUILDER_TOOLS and not (builder_allowed() if builder is None else builder):
        return ("Creating, changing or running flows is off here. Connected automations are read-only, and the builder "
                "only works on flows built in Flowhaus with demo flows turned on.")
    key = FILE_TOOLS.get(tool_name)
    if key is None:
        return None
    target = _resolve(tool_input.get(key))
    private = [p.resolve() for p in automations.private_paths()]
    if any(_within(target, p) for p in private):
        return ("That folder is private (personal data: an automation's run outputs or its `private_paths`). Work from "
                "the counts, skip reasons and log lines Flowhaus's own tools give you.")
    if tool_name in ("Grep", "Glob") and any(_within(p, target) for p in private):
        return "That search would include a private folder (run outputs or `private_paths`). Search a narrower folder."
    if tool_name in EDIT_TOOLS:
        workspace = active_workspace()
        if workspace and _within(target, workspace):
            return None
        if any(_within(target, p.resolve()) for p in automations.read_only_paths()):
            return ("A connected automation's code is read-only here. To change it, start a change (start_change) and "
                    "edit the private copy; the user opens the pull request.")
    return None


APPROVAL_TIMEOUT_S = 600
_approvals: dict[str, asyncio.Future] = {}


def answer_approval(approval_id: str, allow: bool) -> bool:
    """Called by the API when the user clicks Allow or Deny in the chat."""
    fut = _approvals.get(approval_id)
    if fut is None or fut.done():
        return False
    fut.set_result(allow)
    return True


async def ask_user(tool_name: str, tool_input: dict) -> bool:
    """Show an Allow / Deny card in the chat and wait for the click."""
    approval_id = uuid.uuid4().hex[:12]
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    _approvals[approval_id] = fut
    server, tool = mcp.server_of(tool_name) or ("", tool_name)
    _current_events().emit({"type": "approval", "id": approval_id, "server": server, "tool": tool,
                            "input": json.dumps(tool_input, indent=2, default=str)[:4000]})
    try:
        return await asyncio.wait_for(fut, APPROVAL_TIMEOUT_S)
    except asyncio.TimeoutError:
        return False
    finally:
        _approvals.pop(approval_id, None)
        _current_events().emit({"type": "approval_done", "id": approval_id})


def friendly_error(text: str) -> str:
    """Turn the errors people actually hit into what to do about them."""
    t = text.lower()
    if any(k in t for k in ("authenticat", "oauth", "invalid api key", "401", "/login", "not logged in")):
        return ("The chat isn't signed in to Claude. In a terminal, run `claude` and then `/login` (or start Flowhaus "
                "with ANTHROPIC_API_KEY set), then send your message again.")
    if "credit balance" in t or "billing" in t:
        return "Your Claude account is out of credits, so the chat can't answer right now."
    if "rate limit" in t or "429" in t or "overloaded" in t:
        return "Claude is busy right now (rate limited). Wait a minute and send your message again."
    if "claude code not found" in t or "cli not found" in t:
        return "The chat couldn't start Claude. Run `uv sync` in the Flowhaus folder, then try again."
    return text


def _deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


async def pre_tool_hook(input_data: dict, tool_use_id: str | None, context: Any) -> dict:
    name, tool_input = input_data.get("tool_name", ""), input_data.get("tool_input", {}) or {}
    if reason := check_tool_use(name, tool_input):
        return _deny(reason)
    return {}


async def ask_permission(tool_name: str, tool_input: dict, context: Any):
    """Claude Code asks this when the user's own permission rules don't already allow a tool: Allow / Deny card."""
    if await ask_user(tool_name, tool_input):
        return PermissionResultAllow()
    return PermissionResultDeny(message="The user didn't allow this. Don't retry it; ask what they'd like instead.")


# --------------------------------------------------------------------------- snapshots (undo)


def snapshot() -> dict[str, str]:
    files: dict[str, str] = {}
    for pattern in MANAGED_GLOBS:
        for p in ROOT.glob(pattern):
            files[str(p.relative_to(ROOT))] = p.read_text()
    return files


def restore(snap: dict[str, str]) -> list[str]:
    changed = []
    current = snapshot()
    for rel, text in snap.items():
        if current.get(rel) != text:
            (ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
            (ROOT / rel).write_text(text)
            changed.append(rel)
    for rel in current:
        if rel not in snap and rel.startswith(("pipeline/", "flows/")):
            (ROOT / rel).unlink()  # a file the agent created in that turn
            changed.append(rel)
    return changed


def unified_diff(before: dict[str, str], after: dict[str, str]) -> str:
    chunks = []
    for rel in sorted(set(before) | set(after)):
        if before.get(rel) == after.get(rel):
            continue
        chunks.extend(difflib.unified_diff(
            (before.get(rel) or "").splitlines(keepends=True), (after.get(rel) or "").splitlines(keepends=True),
            fromfile=f"a/{rel}", tofile=f"b/{rel}", n=2,
        ))
    return "".join(chunks)


def fingerprint(snap: dict[str, str]) -> str:
    return hashlib.sha1(json.dumps(snap, sort_keys=True).encode()).hexdigest()


def flow_of(rel: str) -> str | None:
    if rel.startswith("pipeline/") or rel == "flow_map.yaml":
        return flows.LIVE_ID
    if rel.startswith("flows/"):
        return rel.split("/")[1]
    return None


def flow_fingerprint(flow_id: str) -> str:
    return fingerprint({k: v for k, v in snapshot().items() if flow_of(k) == flow_id})


# --------------------------------------------------------------------------- worker


class EventSink:
    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()

    def emit(self, event: dict) -> None:
        self.queue.put_nowait(event)


_NULL_SINK = EventSink()


def _current_events() -> EventSink:
    return WORKER.sink or _NULL_SINK


TOOL_LABELS = {
    "Read": "Reading {file_path}",
    "Edit": "Editing {file_path}",
    "Write": "Writing {file_path}",
    "mcp__changes__start_change": "Making a private copy to work on “{title}”",
    "mcp__changes__propose_change": "Preparing the change for your review",
    "mcp__changes__discard_change": "Throwing the change away",
    "mcp__changes__review_change": "Reviewing the change against the map",
    "mcp__changes__downstream_of": "Checking what comes after {node_id}",
    "mcp__changes__remember_context": "Noting: {topic}",
    "mcp__flow__list_flows": "Looking at your flows",
    "mcp__flow__get_map": "Reading the map",
    "mcp__flow__get_node_context": "Looking at {node_id}",
    "mcp__flow__create_flow": "Creating the flow “{name}”",
    "mcp__flow__update_flow": "Updating the flow details",
    "mcp__flow__run_flow": "Running the flow",
    "mcp__flow__update_group": "Updating the box {id}",
    "mcp__flow__validate_map": "Checking the map",
    "mcp__flow__list_connections": "Checking connected apps",
    "mcp__clay__enrich_company": "Trying Clay: company lookup for {domain_or_email}",
    "mcp__clay__enrich_person": "Trying Clay: person lookup for {email}",
    "mcp__firecrawl__scrape": "Trying Firecrawl: reading {url}",
    "mcp__firecrawl__search": "Trying Firecrawl: searching “{query}”",
}


def _node_label(node_id: str) -> str:
    try:
        m = flows.get_map(WORKER.current_flow or flows.LIVE_ID)
    except Exception:
        return node_id
    found = next((x["label"] for x in m["groups"] + m["steps"] if x["id"] == node_id), None)
    return f"“{found}”" if found else node_id


def tool_label(name: str, args: dict) -> str:
    template = TOOL_LABELS.get(name, name)
    values = {k: (str(v).replace(str(ROOT) + "/", "")[:60]) for k, v in (args or {}).items()}
    if "node_id" in values:
        values["node_id"] = _node_label(values["node_id"])
    if "id" in values and name.endswith("update_group"):
        values["id"] = _node_label(values["id"])
    try:
        return template.format(**values)
    except (KeyError, IndexError):
        return template.split(" {")[0].split(":")[0]


@dataclass
class Job:
    kind: str  # chat | undo | reset
    message: str = ""
    selected_node_id: str | None = None
    run_id: str | None = None
    sink: EventSink = field(default_factory=EventSink)
    flow_id: str | None = flows.LIVE_ID  # None = the "new flow" page


def _mcp_fingerprint() -> tuple:
    """Changes when you switch an MCP server on/off or edit the files they come from: the chat reconnects."""
    files = [mcp.STATE_PATH, *(path for _, path, _ in mcp.sources())]
    return tuple(sorted((str(f), f.stat().st_mtime_ns) for f in set(files) if f.exists()))



def replay_check(flow_id: str) -> dict | None:
    """Flowhaus's own check of a change the chat made, not the chat's: replay the last real run's items through the
    flow as it is now (test mode, sandboxed) and compare with what that run gave. {same, summary, examples} or None."""
    from server import whatif

    real = next((r for r in flows.list_runs(flow_id) if r["status"] == "success" and not r.get("test_mode")
                 and r.get("trigger") != "test"), None)
    if real is None:
        return None
    try:
        result = whatif.replay(flow_id, real["run_id"])
    except (KeyError, ValueError):
        return None
    c = result.get("compare")
    failed = next((s for s in result.get("steps") or [] if s["status"] == "failed"), None)
    if failed:
        return {"same": False, "summary": f"Replaying the last real run now fails at “{failed['label']}”: {failed['error']}",
                "examples": []}
    if not c:
        return None
    same = not (c["changed"] or c["now_skipped"] or c["now_kept"])
    parts = [p for p in (c["changed"] and f"{c['changed']} come out different", c["now_skipped"] and
                         f"{c['now_skipped']} now skipped", c["now_kept"] and f"{c['now_kept']} now kept") if p]
    examples = []
    for x in c.get("examples") or []:
        if x.get("now"):
            examples.append(f"{x['item']}: {x['now']}")
        else:
            changed = ", ".join(f"{k} {v[0]} → {v[1]}" for k, v in list((x.get("changes") or {}).items())[:2])
            examples.append(f"{x['item']}: {changed}")
    return {"same": same,
            "summary": (f"Replayed the last real run ({c['before']} out then): same result with this change." if same
                        else f"Replayed the last real run with this change: {c['before']} out then, {c['after']} now; "
                             + ", ".join(parts) + "."),
            "examples": examples[:3]}


class AgentWorker:
    def __init__(self) -> None:
        self.jobs: asyncio.Queue[Job] | None = None
        self.task: asyncio.Task | None = None
        self.sink: EventSink | None = None
        self.current_flow: str | None = None
        self.created_flows: list[str] = []
        self.ran_at: dict[str, str] = {}  # flow id -> fingerprint of its files when last run
        self.undo_stack: list[tuple[str | None, dict[str, str], dict[str, str]]] = []  # (uuid, before, after)
        self.notes: list[str] = []  # things to tell the agent with the next message
        self.busy = False
        self.client: ClaudeSDKClient | None = None
        self.active_change: str | None = None  # change id being edited (see server/changes.py)
        self.mcp_fingerprint: tuple = ()
        self.pending: Job | None = None  # a job held over while the client reconnects
        self.engine: str = "claude"  # which agent this session runs on (flows.chat_engine)
        self.codex_thread: str | None = None  # the Codex conversation to resume
        self.codex_proc: asyncio.subprocess.Process | None = None

    def options(self) -> ClaudeAgentOptions:
        external, _ = mcp.load()
        self.mcp_fingerprint = _mcp_fingerprint()
        return ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            cwd=str(ROOT),
            add_dirs=[str(d) for d in read_only_projects() if d.exists()],
            # the user's own Claude Code setup: its tools, and its permission rules decide what runs without asking
            setting_sources=["user"],
            # Flowhaus's own tools never ask (its rules apply in pre_tool_hook); anything else follows the user's rules
            allowed_tools=["mcp__changes__start_change", "mcp__changes__propose_change", "mcp__changes__discard_change",
                           "mcp__changes__review_change", "mcp__changes__downstream_of", "mcp__changes__remember_context",
                           *ALL_TOOL_NAMES],
            can_use_tool=ask_permission,  # what the user's rules don't allow: an Allow / Deny card in the chat
            mcp_servers={"flow": FLOW_SERVER, "clay": CLAY_SERVER, "firecrawl": FIRECRAWL_SERVER,
                         "changes": CHANGES_SERVER, **{name: srv["sdk"] for name, srv in external.items()}},
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_hook], timeout=APPROVAL_TIMEOUT_S + 30)]},
            include_partial_messages=True,
            enable_file_checkpointing=True,
            # MCP servers: only the ones switched on in Flowhaus, not every server in the user's Claude Code setup
            extra_args={"replay-user-messages": None, "strict-mcp-config": None},
            model=os.environ.get("CHAT_MODEL") or None,
            max_turns=60,
        )

    def ensure_started(self) -> None:
        if self.task is None or self.task.done():
            self.jobs = asyncio.Queue()
            self.task = asyncio.create_task(self._loop())

    async def submit(self, job: Job) -> None:
        self.ensure_started()
        assert self.jobs is not None
        await self.jobs.put(job)

    async def interrupt(self) -> bool:
        if self.codex_proc and self.codex_proc.returncode is None and self.busy:
            self.codex_proc.kill()
            return True
        if self.client and self.busy:
            await self.client.interrupt()
            return True
        return False

    async def _loop(self) -> None:
        assert self.jobs is not None
        while True:
            job: Job | None = None
            try:
                self.engine = flows.chat_engine()
                if self.engine == "codex":
                    self.client = None
                    job = await self._serve(None)
                else:
                    async with ClaudeSDKClient(self.options()) as client:
                        self.client = client
                        job = await self._serve(client)
            except Exception as exc:  # keep the worker alive; report to whoever is waiting
                stuck, self.pending = job or self.pending, None  # e.g. the agent couldn't start: don't leave it hanging
                if stuck is not None:
                    stuck.sink.emit({"type": "error", "message": friendly_error(f"The chat agent stopped: {exc}")})
                    stuck.sink.emit({"type": "done"})
                    stuck.sink.emit({"type": "end"})
                self.sink = None
                self.client = None
                self.busy = False
                await asyncio.sleep(1)

    async def _serve(self, client: ClaudeSDKClient | None) -> None:
        """Handle jobs until the session must restart (reset, engine switch, MCP change). Raises on failure."""
        assert self.jobs is not None
        while True:
            job = self.pending or await self.jobs.get()
            self.pending = None
            if flows.chat_engine() != self.engine or (client is not None and _mcp_fingerprint() != self.mcp_fingerprint):
                self.pending = job  # start a fresh session with the new settings, then handle it
                return None
            if job.kind == "reset":
                self.active_change = None
                self.codex_thread = None
                self.undo_stack.clear()
                self.notes.clear()
                job.sink.emit({"type": "done", "reset": True})
                job.sink.emit({"type": "end"})
                self.busy = False
                return None  # reconnect with a fresh session
            await self._handle(client, job)

    async def _handle(self, client: ClaudeSDKClient | None, job: Job) -> None:
        self.sink = job.sink
        self.current_flow = job.flow_id
        try:
            if job.kind == "undo":
                await self._undo(client, job)
            elif client is None:
                await self._codex_chat(job)
            else:
                await self._chat(client, job)
        except Exception as exc:
            job.sink.emit({"type": "error", "message": friendly_error(f"Something went wrong: {exc}")})
            job.sink.emit({"type": "done", "changed": False, "can_undo": bool(self.undo_stack)})
        finally:
            self.busy = False
            self.sink = None
            job.sink.emit({"type": "end"})

    async def _chat(self, client: ClaudeSDKClient, job: Job) -> None:
        sink = job.sink
        before = snapshot()
        await client.query(self._prompt(job))
        user_uuid = None
        streamed_text = False
        async for msg in client.receive_response():
            if isinstance(msg, UserMessage) and msg.uuid and user_uuid is None and not msg.parent_tool_use_id:
                user_uuid = msg.uuid
            elif isinstance(msg, StreamEvent):
                ev = msg.event
                if ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                    streamed_text = True
                    sink.emit({"type": "text", "text": ev["delta"]["text"]})
                elif ev.get("type") == "message_start" and streamed_text:
                    sink.emit({"type": "text", "text": "\n\n"})
            elif isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        sink.emit({"type": "tool", "name": block.name, "label": tool_label(block.name, block.input)})
            elif isinstance(msg, ResultMessage):
                if msg.is_error and msg.subtype != "error_during_execution":
                    sink.emit({"type": "error", "message": friendly_error(str(msg.result or "The agent hit an error."))})

        await self._after_turn(sink, before, user_uuid)

    async def _after_turn(self, sink: EventSink, before: dict[str, str], user_uuid: str | None) -> None:
        """What every turn ends with, whichever agent ran it: undo point, map refresh, re-run of changed flows."""
        after = snapshot()
        changed = fingerprint(before) != fingerprint(after)
        if changed:
            self.undo_stack.append((user_uuid, before, after))
            files = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
            sink.emit({"type": "map_changed", "files": files, "diff": unified_diff(before, after)})
            await self._rerun_changed(sink, files, trigger="chat")
        sink.emit({"type": "done", "changed": changed, "can_undo": bool(self.undo_stack)})

    async def _codex_chat(self, job: Job) -> None:
        """One message on Codex, under the user's own Codex setup: its sandbox and approval policy decide what its
        shell and file edits may do. Flowhaus's own tools reach it through the bridge, with Flowhaus's rules."""
        from server import codex_engine

        sink = job.sink
        st = codex_engine.status()
        if not st["available"] or not st["signed_in"]:
            sink.emit({"type": "error", "message": f"The chat is set to Codex, but it can't run here. {st['why']} "
                                                   "Or switch the chat back to Claude."})
            sink.emit({"type": "done", "changed": False, "can_undo": bool(self.undo_stack)})
            return
        before = snapshot()
        prompt = self._prompt(job)
        if not self.codex_thread:  # Codex has no separate system prompt: the instructions open the conversation
            prompt = f"{SYSTEM_PROMPT}\n\n{CODEX_NOTE}\n\n---\n\n{prompt}"
        port = os.environ.get("FLOWHAUS_API_PORT", "8000")

        def proc_started(proc: asyncio.subprocess.Process) -> None:
            self.codex_proc = proc

        thread, error = await codex_engine.run(
            prompt, self.codex_thread, f"http://127.0.0.1:{port}", CODEX_TOKEN,
            on_text=lambda t: sink.emit({"type": "text", "text": t}),
            model=os.environ.get("CODEX_MODEL") or None, on_start=proc_started)
        self.codex_proc = None
        self.codex_thread = thread or self.codex_thread
        if error:
            sink.emit({"type": "error", "message": friendly_error(error)})
        await self._after_turn(sink, before, None)

    async def _rerun_changed(self, sink: EventSink, files: list[str], trigger: str) -> None:
        """Run every flow whose files changed and that the agent didn't run since, so previews are never stale."""
        if not flows.show_demo():
            return  # the builder is off: never run code
        for flow_id in dict.fromkeys(f for f in (flow_of(p) for p in files) if f):
            try:
                flows.kind(flow_id)
            except KeyError:
                continue  # flow was removed (e.g. by undo)
            problems = (await asyncio.to_thread(flows.get_map, flow_id))["problems"]
            if problems:
                sink.emit({"type": "problems", "flow_id": flow_id, "problems": problems})
            if trigger == "chat" and self.ran_at.get(flow_id) == flow_fingerprint(flow_id):
                continue
            sink.emit({"type": "tool", "name": "auto_run", "label": "Running the flow again"})
            try:
                run = await asyncio.to_thread(runs.run_blocking, None, trigger, flow_id=flow_id)
            except ValueError:
                continue  # no input yet
            self.ran_at[flow_id] = flow_fingerprint(flow_id)
            sink.emit({"type": "run", "run_id": run["run_id"], "flow_id": flow_id, "status": run["status"]})
            if check := await asyncio.to_thread(replay_check, flow_id):
                sink.emit({"type": "check", "flow_id": flow_id, **check})

    async def _undo(self, client: ClaudeSDKClient | None, job: Job) -> None:
        sink = job.sink
        if not self.undo_stack:
            sink.emit({"type": "text", "text": "There is nothing to undo."})
            sink.emit({"type": "done", "changed": False, "can_undo": False})
            return
        user_uuid, files_before, files_after = self.undo_stack[-1]
        current = snapshot()
        if fingerprint(current) != fingerprint(files_after):
            sink.emit({"type": "text", "text": "The files changed after that edit, so undoing it could throw away newer "
                                               "work. Nothing was changed. Ask me to revert it instead."})
            sink.emit({"type": "done", "changed": False, "can_undo": bool(self.undo_stack)})
            return
        self.undo_stack.pop()
        if user_uuid and client is not None:
            try:
                await client.rewind_files(user_uuid)
            except Exception:
                pass  # the snapshot below is authoritative either way
        reverted = restore(files_before)
        for flow_id in list(self.created_flows):
            folder = FLOWS_DIR / flow_id
            if folder.exists() and not (folder / "flow.yaml").exists():
                _remove_empty_tree(folder)
                self.created_flows.remove(flow_id)
        self.notes.append("The user pressed Undo: your previous change was reverted, and the files are back to how they "
                          "were before it. Re-read files before editing them.")
        sink.emit({"type": "text", "text": "Undid the last change and ran the flow again."})
        sink.emit({"type": "map_changed", "files": reverted, "diff": unified_diff(current, snapshot())})
        await self._rerun_changed(sink, reverted, trigger="undo")
        sink.emit({"type": "done", "changed": True, "can_undo": bool(self.undo_stack)})

    def _prompt(self, job: Job) -> str:
        context = list(self.notes)
        self.notes.clear()
        if job.flow_id is None:
            context.append("The user is on the NEW FLOW page: they want you to build a new flow (create_flow).")
        else:
            try:
                meta = flows.get_meta(job.flow_id)
                kind = flows.kind(job.flow_id)
            except KeyError:
                meta, kind = {"name": job.flow_id}, "unknown"
            context.append(f"The user is looking at the flow \"{meta['name']}\" (flow_id: {job.flow_id}, kind: {kind}).")
            if kind == "sample":
                return self._sample_prompt(job, context)
            if kind == "connected":
                return self._connected_prompt(job, context)
            if job.selected_node_id in ("__input__", "__output__"):
                which = "everything that came INTO the flow" if job.selected_node_id == "__input__" else \
                    "the flow's final OUTPUT (the items that made it through)"
                context.append(f"They selected the box showing {which}.")
            elif job.selected_node_id:
                label = _node_label(job.selected_node_id)
                context.append(f"They selected the box {label} (id: {job.selected_node_id}); the request is about it.")
            if job.run_id:
                context.append(f"They are looking at run {job.run_id}.")
            if kind == "built":
                try:  # gaps, blind spots, open questions, what the user said: see BE OPINIONATED, NOT STUBBORN
                    context.append("Harness JSON: " + json.dumps(harness.for_chat(job.flow_id), default=str))
                except Exception:
                    pass
        prefix = "".join(f"[{c}]\n" for c in context)
        return f"{prefix}{job.message}"

    def _connected_prompt(self, job: Job, context: list[str]) -> str:
        """A real automation the user already runs elsewhere: explain and propose, never change it."""
        adapter = flows.connected()[job.flow_id]
        runs_ = adapter.list_runs()
        run = adapter.get_run(job.run_id or (runs_[0]["run_id"] if runs_ else "")) if runs_ else None
        if job.selected_node_id:
            label = next((x.get("label") for x in [*adapter.groups, *adapter.steps] if x["id"] == job.selected_node_id),
                         job.selected_node_id)
            context.append(f"They selected the box \"{label}\" (id: {job.selected_node_id}); the request is about it.")
        context.append(
            "This is the user's REAL, existing automation. It runs on "
            f"{adapter.source_label()} from the code in {adapter.meta()['source']['path'] or '(no local copy configured)'}. "
            "Each step's 'file' says which code implements it; read it there. Never run it. Answer in plain English from "
            "the run data below and the code.")
        if changes.settings(adapter) is not None:
            context.append(
                "CHANGES ARE ENABLED for this automation, through pull requests the user approves. When they ask for a "
                "change: call downstream_of for the step, explain what you'd change and the effect on it and every step "
                "after it, then call start_change, edit the files in the folder it returns (only there), call "
                "review_change and fix what it finds (reuse existing code instead of repeating it), then call "
                "propose_change with a plain-English summary and the downstream impact. "
                "The user sees the diff and decides whether to open the pull request; you can't open it yourself and "
                "must never say it's opened or merged. Keep changes small and focused; don't touch CI/workflow files "
                "unless that's the point of the change.")
        else:
            context.append(
                "Changes are off for this automation: for change requests, propose the exact change in words (file, "
                "what to change, expected effect on the counts). Mention that the user can let you prepare pull "
                "requests by adding `pull_requests: {enabled: true}` to its automation.yaml.")
        from server import insights as _insights

        shared = adapter.agent_context(run)
        try:
            shared["insights"] = _insights.insights(job.flow_id)  # what a reviewer would notice; mention if relevant
        except Exception:
            shared["insights"] = []
        try:
            shared["harness"] = harness.for_chat(job.flow_id)  # gaps, blind spots, open questions, what the user said
        except Exception:
            shared["harness"] = {}
        data = json.dumps(shared, default=str)
        prefix = "".join(f"[{c}]\n" for c in context)
        return f"{prefix}[Automation context JSON]\n{data}\n\n{job.message}"

    def _sample_prompt(self, job: Job, context: list[str]) -> str:
        """Sample flows have no code: give the agent the flow as context and ask it to act as the operator."""
        m = flows.get_map(job.flow_id)
        run_list = flows.list_runs(job.flow_id)
        run = flows.get_run(job.flow_id, job.run_id or (run_list[0]["run_id"] if run_list else "")) or {}
        steps = [{k: s[k] for k in ("id", "label", "description", "group", "app")} for s in m["steps"]]
        nodes = {nid: {k: n.get(k) for k in ("label", "status", "rows_in", "rows_out", "rows_rejected",
                                                "reject_reasons", "error", "sample_in", "sample_out")}
                 for nid, n in (run.get("nodes") or {}).items()}
        recent = [{k: r.get(k) for k in ("run_id", "status", "started_at", "summary", "error")} for r in run_list[:10]]
        if job.selected_node_id:
            label = next((x["label"] for x in m["groups"] + m["steps"] if x["id"] == job.selected_node_id), job.selected_node_id)
            context.append(f"They selected \"{label}\"; treat the request as being about it.")
        data = json.dumps({"flow": m["flow"], "groups": m["groups"], "steps": steps, "recent_runs": recent,
                           "run_being_viewed": {"run_id": run.get("run_id"), "status": run.get("status"),
                                                "error": run.get("error"), "steps": nodes}}, default=str)
        context.append(
            "This is a read-only SAMPLE flow with made-up history and no code. Answer from the context below without "
            "editing anything. For change requests, say exactly what you would change and the expected effect on the "
            "counts. If the user wants it for real, offer to build it as a new flow with create_flow, using the Clay "
            "and Firecrawl connectors and placeholder steps for apps that have no connector yet.")
        prefix = "".join(f"[{c}]\n" for c in context)
        return f"{prefix}[Sample flow context JSON]\n{data}\n\n{job.message}"


def _remove_empty_tree(folder: Path) -> None:
    for p in sorted(folder.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        if p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    if folder.exists() and not any(folder.iterdir()):
        folder.rmdir()


WORKER = AgentWorker()


async def stream_job(job: Job):
    """Async generator of NDJSON lines for one chat/undo request."""
    if WORKER.busy:
        yield json.dumps({"type": "error", "message": "The agent is still working on the previous message."}) + "\n"
        yield json.dumps({"type": "end"}) + "\n"
        return
    WORKER.busy = True
    await WORKER.submit(job)
    while True:
        event = await job.sink.queue.get()
        yield json.dumps(event, default=str) + "\n"
        if event["type"] == "end":
            return


# --------------------------------------------------------------------------- the same tools, for the Codex engine
#
# When the chat runs on Codex (server/codex_engine.py), Codex works under the user's own Codex setup and reaches
# Flowhaus's tools through server/codex_bridge.py. Every call lands here and gets the same rules as in the Claude
# chat: check_tool_use for Flowhaus's own tools, and the Allow / Deny question for the MCP servers switched on here.

CODEX_TOKEN = secrets.token_urlsafe(24)  # given only to the Codex process Flowhaus starts
CODEX_NOTE = """\
RUNNING ON CODEX
- Read and edit files with your own tools; the user's Codex settings decide what you may do. Use the flowhaus tools
  for flows, runs and changes, and list_connected_tools / use_connected_tool for the MCP servers switched on in
  Flowhaus.
- The tool names in these instructions match the flowhaus tools (create_flow, run_flow, start_change, ...); the
  demo connectors are demo_clay_* and demo_firecrawl_*."""
_PY_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", dict: "object", list: "array"}


def _json_schema(schema: dict) -> dict:
    if schema.get("type") == "object":
        return schema
    return {"type": "object", "properties": {k: {"type": _PY_TYPES.get(v, "string") if not isinstance(v, str) else v}
                                             for k, v in schema.items()}, "required": list(schema)}


def _sdk_tools() -> dict[str, tuple[str, Any]]:
    """{name Codex sees: (name the guard knows, tool)}. Demo connectors are prefixed so their names say what they are."""
    out: dict[str, tuple[str, Any]] = {}
    for server, tools in (("flow", FLOW_TOOLS),
                          ("changes", [start_change_tool, review_change_tool, propose_change_tool, discard_change_tool,
                                       downstream_of_tool, remember_context_tool]),
                          ("clay", [clay_company, clay_person]), ("firecrawl", [fc_scrape, fc_search])):
        for t in tools:
            name = f"demo_{server}_{t.name}" if server in ("clay", "firecrawl") else t.name
            out[name] = (f"mcp__{server}__{t.name}", t)
    return out


CONNECTED_TOOLS = {
    "list_connected_tools": ("mcp__connected__list", "The tools one of the user's MCP servers offers (servers they "
                                                     "switched on for the chat).", {"server": "string"}, ["server"]),
    "use_connected_tool": ("mcp__connected__use", "Call a tool on one of the user's MCP servers. The user is asked "
                                                  "first unless their own rules allow it.",
                           {"server": "string", "tool": "string", "arguments": "object"}, ["server", "tool"]),
}


def codex_tools() -> list[dict]:
    tools = [{"name": n, "description": t.description, "input_schema": _json_schema(t.input_schema or {})}
             for n, (_, t) in _sdk_tools().items()]
    tools += [{"name": n, "description": d, "input_schema": _schema(p, req)} for n, (_, d, p, req) in CONNECTED_TOOLS.items()]
    return tools


async def call_codex_tool(name: str, args: dict) -> tuple[str, bool]:
    """Run one tool for Codex. Returns (text, is_error)."""
    args = args or {}
    sdk = _sdk_tools().get(name)
    if sdk:
        guard_name, tool_obj = sdk
        _current_events().emit({"type": "tool", "name": guard_name, "label": tool_label(guard_name, args)})
        if reason := check_tool_use(guard_name, args):
            return reason, True
        try:
            result = await tool_obj.handler(args)
        except Exception as exc:  # errors are data: Codex gets the error, not "Flowhaus didn't answer"
            return f"{name} failed: {type(exc).__name__}: {exc}", True
        text = "\n".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
        return text, bool(result.get("is_error"))
    if name not in CONNECTED_TOOLS:
        return f"No tool called {name}.", True
    guard_name = CONNECTED_TOOLS[name][0]
    # the user's own MCP servers: only those switched on, and calls ask first unless their rules allow them
    from server import mcp_client

    servers, _ = mcp.load()
    server = servers.get(str(args.get("server") or ""))
    if server is None:
        return f"No MCP server '{args.get('server')}' is switched on for the chat. Switched on: {', '.join(servers) or 'none'}.", True
    if name == "list_connected_tools":
        _current_events().emit({"type": "tool", "name": guard_name, "label": f"Looking at {args['server']}'s tools"})
        try:
            tools = await mcp_client.list_tools(server["sdk"])
        except RuntimeError as exc:
            return str(exc), True
        return json.dumps([{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
                           for t in tools], indent=1)[:60_000], False
    tool = str(args.get("tool") or "")
    full = f"mcp__{args['server']}__{tool}"
    _current_events().emit({"type": "tool", "name": full, "label": f"Using {tool} on {args['server']}"})
    if mcp.needs_approval(full) and not await ask_user(full, args.get("arguments") or {}):
        return "The user didn't allow this call. Don't retry it; ask what they'd like instead.", True
    try:
        return await mcp_client.call_tool(server["sdk"], tool, args.get("arguments") or {}), False
    except RuntimeError as exc:
        return str(exc), True
