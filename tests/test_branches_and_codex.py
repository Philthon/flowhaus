"""Flowchart maps (start, decisions with labelled branches, waits, ends) and the Codex chat engine."""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import agent, automations, codex_engine, flows, maps, mcp

STEPS = [{"id": "get"},
         {"id": "coach", "kind": "decision", "branches": [{"label": "Yes", "to": "book", "when": "date set"},
                                                           {"label": "No", "to": "skipped"}]},
         {"id": "book"}, {"id": "notify"},
         {"id": "skipped", "kind": "end"}]


def test_branches_become_labelled_paths_and_ends_are_reached_on_purpose():
    edges = maps.chain_edges(STEPS)
    assert {(e["source"], e["target"], e.get("label")) for e in edges} == {
        ("get", "coach", None), ("coach", "book", "Yes"), ("coach", "skipped", "No"), ("book", "notify", None)}
    assert maps.path_problems(STEPS, edges, True, True) == []  # notify ends at the flow's result


def test_every_map_needs_a_start_an_end_and_complete_decisions():
    bad = [{"id": "a"}, {"id": "d", "kind": "decision", "branches": [{"to": "a"}]}, {"id": "lost", "kind": "end"}]
    problems = " | ".join(maps.path_problems(bad, maps.chain_edges(bad), has_start=False, has_end=False))
    assert "no start" in problems and "at least two" in problems and "needs a `label`" in problems
    assert "Nothing leads to 'lost'" in problems


def test_branch_labels_survive_grouping():
    groups = [{"id": "g", "parent": None, "label": "G", "description": ""}]
    steps = [{**s, "group": "g" if s["id"] in ("book", "notify") else None} for s in STEPS]
    root = maps.build_levels(groups, steps, maps.chain_edges(steps))["root"]
    assert {"source": "coach", "target": "g", "label": "Yes", "when": "date set"} in root["edges"]


def test_connected_automation_checks_start_and_end(tmp_path, monkeypatch):
    folder = tmp_path / "automations" / "alpha"
    folder.mkdir(parents=True)
    (folder / "automation.yaml").write_text(
        "type: python\nname: A\ndescription: d\nmap: {steps: [{id: x, label: X, description: d}]}\n")
    (folder / "adapter.py").write_text("from server.automations.base import Automation\n"
                                       "class A(Automation):\n    def list_runs(self): return []\n"
                                       "    def get_run(self, r): return None\n"
                                       "def create(c, f): return A(c, f)\n")
    monkeypatch.setenv("FLOWHAUS_AUTOMATIONS_DIR", str(tmp_path / "automations"))
    problems = " | ".join(automations.all_automations()["alpha"].check())
    assert "no start" in problems and "no end" in problems


def test_a_choice_numbers_its_answers_and_ends_with_otherwise():
    steps = [{"id": "size", "kind": "decision", "label": "How big?", "branches": [
        {"label": "Enterprise", "to": "a", "when": "500+ people"}, {"label": "Mid-market", "to": "b"},
        {"label": "Otherwise", "to": "c"}]}, {"id": "a"}, {"id": "b"}, {"id": "c"}]
    edges = [e for e in maps.chain_edges(steps) if e["source"] == "size"]
    assert [(e["order"], e["otherwise"]) for e in edges] == [(1, False), (2, False), (3, True)]
    assert maps.path_problems(steps, maps.chain_edges(steps), True, True) == []
    steps[0]["branches"].append(steps[0]["branches"].pop(0))  # "Otherwise" no longer last
    assert any("must be the last answer" in p for p in maps.path_problems(steps, maps.chain_edges(steps), True, True))
    # a yes/no decision stays a plain diamond: no numbering
    yes_no = [{"id": "q", "kind": "decision", "label": "Q?", "branches": [{"label": "Yes", "to": "a"}, {"label": "No", "to": "b"}]},
              {"id": "a"}, {"id": "b"}]
    assert all("order" not in e for e in maps.chain_edges(yes_no))


def test_a_box_with_one_thing_inside_is_shown_as_that_thing():
    fmap = {"groups": [{"id": "outer", "label": "O", "description": "", "parent": None},
                       {"id": "inner", "label": "I", "description": "", "parent": "outer"},
                       {"id": "two", "label": "T", "description": "", "parent": None}],
            "steps": [{"id": "a", "group": "inner"}, {"id": "b", "group": "two"}, {"id": "c", "group": "two"}],
            "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]}
    out = maps.without_single_child_groups(fmap)
    # "inner" held one step, then "outer" held only that: both go, and the step sits at the top
    assert [g["id"] for g in out["groups"]] == ["two"]
    assert set(out["levels"]["root"]["children"]) == {"two", "a"}
    assert out["levels"]["two"]["children"] == ["b", "c"]
    assert maps.without_single_child_groups(out) is out  # nothing left to remove


def test_codex_mcp_servers_are_found(monkeypatch):
    home = Path(os.environ["HOME"])
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text(
        '[mcp_servers.n8n]\ncommand = "npx"\nargs = ["-y", "n8n-mcp"]\nenv_vars = ["N8N_API_KEY"]\n\n'
        '[mcp_servers.linear]\nurl = "https://mcp.example.com/mcp"\nbearer_token_env_var = "LINEAR_TOKEN"\n\n'
        '[mcp_servers.figma]\nurl = "https://mcp.example.com/figma"\n\n'
        '[mcp_servers.off]\ncommand = "x"\nenabled = false\n')
    monkeypatch.setenv("N8N_API_KEY", "k1")
    monkeypatch.setenv("LINEAR_TOKEN", "t1")
    found = mcp.discover()
    assert found["n8n"]["source"] == "Codex" and found["n8n"]["sdk"]["env"] == {"N8N_API_KEY": "k1"}
    assert found["linear"]["sdk"]["headers"] == {"Authorization": "Bearer t1"}
    assert "OAuth" in found["figma"]["problem"] and "off" not in found


def test_tools_of_a_connected_server_can_be_listed_and_called(tmp_path):
    from server import mcp_client

    script = tmp_path / "fake_n8n.py"
    script.write_text("from mcp.server.mcpserver import MCPServer\napp = MCPServer('n8n')\n\n"
                      "@app.tool()\ndef list_workflows() -> str:\n    '''List workflows.'''\n    return 'Monday report'\n\n"
                      "app.run()\n")
    sdk = {"type": "stdio", "command": sys.executable, "args": [str(script)]}
    tools = asyncio.run(mcp_client.list_tools(sdk))
    assert [t["name"] for t in tools] == ["list_workflows"] and tools[0]["description"] == "List workflows."
    assert asyncio.run(mcp_client.call_tool(sdk, "list_workflows", {})) == "Monday report"


# --------------------------------------------------------------------------- Codex: your Codex setup, plus Flowhaus's tools


def test_codex_runs_with_your_own_codex_setup_plus_flowhaus_tools():
    cmd = codex_engine.command("hello", None)
    joined = " ".join(cmd)
    # your Codex config, sandbox and approvals decide what Codex may do: Flowhaus doesn't override them
    assert not any(flag in cmd for flag in ("--ignore-user-config", "--ignore-rules", "--sandbox"))
    assert "features.shell_tool" not in joined
    # Flowhaus only adds its own tools, with the token passed through the environment, never on the command line
    assert "server.codex_bridge" in joined and "FLOWHAUS_TOKEN" in joined and agent.CODEX_TOKEN not in joined
    again = codex_engine.command("again", "thread-1")
    assert again[2:4] == ["resume", "thread-1"] and "-C" not in again  # `codex exec resume` has no -C


def test_codex_errors_read_as_plain_words():
    raw = ('{"type":"error","status":400,"error":{"type":"invalid_request_error",'
           '"message":"The \'gpt-5.5\' model is not supported when using Codex with a ChatGPT account."}}')
    assert codex_engine.plain_error(raw) == "The 'gpt-5.5' model is not supported when using Codex with a ChatGPT account."
    assert codex_engine.plain_error("Codex stopped.") == "Codex stopped."


def test_codex_tools_go_through_the_same_guard():
    def call(name, args):
        return asyncio.run(agent.call_codex_tool(name, args))

    assert call("read_file", {"path": "server/maps.py"})[1]  # gone: Codex reads with its own tools, under its setup
    assert call("run_flow", {"flow_id": "contact-cleaning"})[1]  # builder off: no running
    assert call("use_connected_tool", {"server": "nope", "tool": "x"})[1]  # only servers you switched on
    assert "list_flows" in {t["name"] for t in agent.codex_tools()}


def test_only_the_codex_flowhaus_started_may_call_tools():
    from server.app import app

    c = TestClient(app, base_url="http://127.0.0.1:8000")
    assert c.get("/api/agent/tools").status_code == 403
    assert c.post("/api/agent/call", json={"name": "list_flows"}, headers={"X-Flowhaus-Token": "wrong"}).status_code == 403
    ok = c.get("/api/agent/tools", headers={"X-Flowhaus-Token": agent.CODEX_TOKEN})
    assert ok.status_code == 200 and any(t["name"] == "list_flows" for t in ok.json()["tools"])


def test_other_web_pages_cant_start_an_mcp_server():
    from server.app import app

    c = TestClient(app, base_url="http://127.0.0.1:8000")
    # it starts a program from your setup: a plain link or <img> from another page (a GET) must not reach it
    assert c.get("/api/mcp/anything/tools").status_code == 405
    assert c.post("/api/mcp/anything/tools", headers={"sec-fetch-site": "cross-site"}).status_code == 403


def test_a_codex_turn_streams_the_answer_and_keeps_the_thread(tmp_path, monkeypatch):
    fake = tmp_path / "codex"
    fake.write_text("#!/usr/bin/env python3\nimport json, sys\n"
                    "args = sys.argv[1:]\n"
                    "tid = args[args.index('resume') + 1] if 'resume' in args else 'thread-42'\n"
                    "print(json.dumps({'type': 'thread.started', 'thread_id': tid}))\n"
                    "print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Hi from ' + tid}}))\n"
                    "print(json.dumps({'type': 'turn.completed', 'usage': {}}))\n")
    fake.chmod(0o755)
    (tmp_path / "codex-home").mkdir()
    (tmp_path / "codex-home" / "auth.json").write_text("{}")
    monkeypatch.setenv("FLOWHAUS_CODEX", str(fake))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.setattr(codex_engine, "WORKDIR", tmp_path)
    assert codex_engine.status()["available"] and codex_engine.status()["signed_in"]
    worker = agent.AgentWorker()

    async def turn(text):
        job = agent.Job(kind="chat", message=text, flow_id=None)
        worker.sink = job.sink
        await worker._codex_chat(job)
        events = []
        while not job.sink.queue.empty():
            events.append(job.sink.queue.get_nowait())
        return events

    first = asyncio.run(turn("hello"))
    assert {"type": "text", "text": "Hi from thread-42"} in first and worker.codex_thread == "thread-42"
    second = asyncio.run(turn("again"))
    assert {"type": "text", "text": "Hi from thread-42"} in second  # resumed the same conversation
    assert first[-1]["type"] == "done"


def test_codex_not_set_up_says_what_to_do(monkeypatch, tmp_path):
    monkeypatch.setenv("FLOWHAUS_CODEX", "")
    monkeypatch.setattr(codex_engine.shutil, "which", lambda _: None)
    st = codex_engine.status()
    assert not st["available"] and "npm install -g @openai/codex" in st["why"]


def test_chat_engine_setting(tmp_path):
    assert flows.chat_engine() == "claude"
    flows.set_chat_engine("codex")
    assert flows.chat_engine() == "codex"
    with pytest.raises(ValueError):
        flows.set_chat_engine("gpt")
