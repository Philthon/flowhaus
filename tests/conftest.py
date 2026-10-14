"""Every test runs against empty, temporary state: never your real automations, settings, runs or GitHub."""

import pytest

from connectors import _base
from server import flows, mcp, runs
from server.automations import github_actions


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWHAUS_AUTOMATIONS_DIR", str(tmp_path / "no-automations"))
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # never your real ~/.claude.json, ~/.cursor, ...
    monkeypatch.setattr(mcp, "STATE_PATH", tmp_path / "mcp-state.json")
    monkeypatch.setattr(flows, "STATE_PATH", tmp_path / "flows.json")
    monkeypatch.setattr(github_actions, "STATE_DIR", tmp_path / "gh-cache")
    monkeypatch.setattr(_base, "CALLS_PATH", tmp_path / "calls.jsonl")
    monkeypatch.setattr(runs, "OUTPUT_PATH", str(tmp_path / "contacts_clean.csv"))

    def no_network_gh(*args, **_):
        raise github_actions.GhError("gh is disabled in tests (fake it with monkeypatch)")

    monkeypatch.setattr(github_actions, "gh", no_network_gh)
