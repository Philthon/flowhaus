"""Proposed changes become pull requests only on approval; MCP tools ask before each call."""

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from server import agent, automations, changes, mcp


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """A 'GitHub' repo (bare, at .../someone/bot.git), the user's clone of it, and an automation pointing at it."""
    remote = tmp_path / "github" / "someone" / "bot.git"
    remote.parent.mkdir(parents=True)
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    local = tmp_path / "code" / "bot"
    git(tmp_path, "clone", "-q", str(remote), str(local))
    (local / "bot.py").write_text("LIMIT = 10\n")
    git(local, "add", "-A")
    git(local, "commit", "-q", "-m", "first")
    git(local, "push", "-q", "origin", "HEAD:main")
    autos = tmp_path / "automations" / "bot"
    autos.mkdir(parents=True)
    (autos / "automation.yaml").write_text(
        f"type: folder_runs\nname: Bot\ndescription: d\nlocal_path: '{local}'\n"
        "pull_requests: {enabled: true, base: main, repo: someone/bot}\n"
        "folder_runs: {path: runs}\nmap: {steps: [{id: a, label: A, description: d, produces: x.txt}]}\n")
    monkeypatch.setenv("FLOWHAUS_AUTOMATIONS_DIR", str(tmp_path / "automations"))
    monkeypatch.setattr(changes, "CHANGES_DIR", tmp_path / "changes")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "gh").write_text("#!/bin/sh\necho \"$@\" > \"$(dirname \"$0\")/gh-args\"\necho https://github.com/someone/bot/pull/7\n")
    (fake_bin / "gh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    return {"remote": remote, "local": local, "bin": fake_bin, "adapter": automations.all_automations()["bot"]}


def test_change_becomes_a_pull_request_only_when_opened(project):
    meta = changes.start(project["adapter"], "Raise the limit")
    ws = changes.workspace(meta["id"])
    assert (ws / "bot.py").read_text() == "LIMIT = 10\n" and meta["base"] == "main"
    (ws / "bot.py").write_text("LIMIT = 20\n")
    (ws / ".github" / "workflows").mkdir(parents=True)
    (ws / ".github" / "workflows" / "ci.yml").write_text("on: push\n")
    meta = changes.propose(meta["id"], "Lets 20 items through instead of 10.")
    assert meta["status"] == "proposed" and "+LIMIT = 20" in meta["diff"]
    assert any(".github/workflows/ci.yml" in w for w in meta["warnings"])
    branches = subprocess.run(["git", "branch", "--list"], cwd=project["remote"], capture_output=True, text=True).stdout
    assert "flowhaus/" not in branches  # proposing sent nothing anywhere
    assert (project["local"] / "bot.py").read_text() == "LIMIT = 10\n"  # the user's folder is untouched

    # it edits a CI file (P0): it can't open until that's confirmed; the rest are suggestions
    with pytest.raises(changes.GateError):
        changes.open_pull_request(meta["id"])
    critical = [g["id"] for g in meta["gate"] if g["priority"] == "P0"]
    assert critical and all(c.startswith("sensitive:") for c in critical)
    assert {g["id"] for g in meta["gate"] if g["priority"] != "P0"} >= {"untested"}
    meta = changes.open_pull_request(meta["id"], critical)  # suggestions left unticked: fine
    assert meta["status"] == "opened" and meta["pr_url"].endswith("/pull/7")
    branches = subprocess.run(["git", "branch", "--list"], cwd=project["remote"], capture_output=True, text=True).stdout
    assert meta["branch"] in branches
    assert "--base main" in (project["bin"] / "gh-args").read_text()


def test_hooks_never_run(project, tmp_path):
    meta = changes.start(project["adapter"], "Hook test")
    ws = changes.workspace(meta["id"])
    marker = tmp_path / "hook-ran"
    hooks = ws / "hooks"
    hooks.mkdir()
    for name in ("pre-commit", "pre-push", "commit-msg"):
        (hooks / name).write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        (hooks / name).chmod(0o755)
    git(ws, "config", "core.hooksPath", "hooks")  # as if a file the chat wrote tried to install hooks
    (ws / "bot.py").write_text("LIMIT = 30\n")
    proposed = changes.propose(meta["id"], "s")
    assert changes.required(proposed) == []  # nothing critical: it opens without ticking anything
    changes.open_pull_request(proposed["id"])
    assert not marker.exists()


def test_changes_need_opt_in(project, tmp_path):
    cfg = Path(project["adapter"].folder) / "automation.yaml"
    cfg.write_text(cfg.read_text().replace("enabled: true", "enabled: false"))
    with pytest.raises(changes.ChangeError, match="pull_requests"):
        changes.start(automations.all_automations()["bot"], "x")


def claude_setup(home: Path, servers: dict, allow: list[str] | None = None, project: Path | None = None):
    """A fake Claude Code setup in a temporary home folder."""
    data = {"projects": {str(project): {"mcpServers": servers}}} if project else {"mcpServers": servers}
    (home / ".claude.json").write_text(json.dumps(data))
    if allow is not None:
        (home / ".claude").mkdir(exist_ok=True)
        (home / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"allow": allow}}))


def test_mcp_servers_come_from_your_existing_setup(monkeypatch):
    home = Path(os.environ["HOME"])
    monkeypatch.setenv("N8N_KEY", "abc")
    claude_setup(home, {
        "n8n": {"command": "npx", "args": ["-y", "n8n-mcp"], "env": {"N8N_API_KEY": "${N8N_KEY}"}},
        "remote": {"type": "http", "url": "https://example.com/mcp?token=x", "headers": {"Authorization": "Bearer ${NOPE}"}},
        "firecrawl": {"type": "http", "url": "https://mcp.example.com"},
    }, allow=["mcp__n8n__list_*", "Bash(ls)"])
    found = mcp.discover()
    assert set(found) == {"n8n", "remote", "firecrawl_local"}  # never shadows Flowhaus's own demo tools
    assert found["n8n"]["sdk"]["env"] == {"N8N_API_KEY": "abc"} and "NOPE" in found["remote"]["problem"]
    assert mcp.load() == ({}, {})  # nothing is used until you switch it on
    mcp.set_enabled("n8n", True)
    servers, _ = mcp.load()
    assert list(servers) == ["n8n"]
    summary = json.dumps(mcp.summary())
    assert "abc" not in summary and "token=x" not in summary  # keys never leave their files
    assert mcp.needs_approval("mcp__n8n__activate_workflow")
    assert not mcp.needs_approval("mcp__n8n__list_workflows")  # your Claude Code rule already allows it
    assert not mcp.needs_approval("mcp__flow__get_map") and not mcp.needs_approval("Read")


def test_desktop_and_project_files_are_found(tmp_path):
    home = Path(os.environ["HOME"])
    desktop = mcp._desktop_config()
    desktop.parent.mkdir(parents=True)
    desktop.write_text(json.dumps({"mcpServers": {"db": {"command": "uvx", "args": ["db-mcp"]}}}))
    claude_setup(home, {"notes": {"command": "notes-mcp"}}, project=tmp_path / "some-project")
    found = mcp.discover()
    assert found["db"]["source"] == "Claude Desktop" and found["notes"]["source"].startswith("Claude Code (project")


def test_mcp_call_waits_for_the_user():
    claude_setup(Path(os.environ["HOME"]), {"n8n": {"command": "npx"}})

    async def scenario(allow: bool):
        sink = agent.EventSink()
        agent.WORKER.sink = sink
        # Claude Code asks this when the user's own rules don't allow the tool
        task = asyncio.create_task(agent.ask_permission("mcp__n8n__activate_workflow", {"id": 3}, None))
        event = await asyncio.wait_for(sink.queue.get(), 2)
        assert event["type"] == "approval" and event["tool"] == "activate_workflow"
        assert not task.done()  # nothing happens until the user answers
        agent.answer_approval(event["id"], allow)
        return await asyncio.wait_for(task, 2)

    try:
        assert isinstance(asyncio.run(scenario(True)), agent.PermissionResultAllow)
        assert isinstance(asyncio.run(scenario(False)), agent.PermissionResultDeny)
    finally:
        agent.WORKER.sink = None


def test_mcp_approvals_follow_only_your_own_settings(tmp_path, monkeypatch):
    """A connected repo's (or this project's) .claude/settings.json can't pre-approve MCP calls: someone else could
    have written it. Only ~/.claude/settings.json counts, as in the Claude chat."""
    home = Path(os.environ["HOME"])
    claude_setup(home, {"n8n": {"command": "npx"}}, allow=[])
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"allow": ["mcp__*"]}}))
    monkeypatch.setattr(mcp.runtime, "ROOT", repo)
    assert mcp.needs_approval("mcp__n8n__activate_workflow")
