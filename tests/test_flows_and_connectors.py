import json

import pandas as pd
import pytest

from connectors import _base, clay, firecrawl
from flowkit import Skip, skip_where, update_items
from server.agent import check_tool_use


@pytest.fixture()
def connected(tmp_path, monkeypatch):
    monkeypatch.setattr(_base, "CALLS_PATH", tmp_path / "calls.jsonl")
    return tmp_path


def test_dummy_clay_is_deterministic(connected):
    a = clay.enrich_company("someone@northwind.io")
    assert a == clay.enrich_company("northwind.io")
    assert a["name"] == "Northwind Logistics" and a["employees"] == 420


def test_personal_email_is_an_item_error(connected):
    with pytest.raises(_base.ItemError):
        clay.enrich_company("joe@gmail.com")


def test_demo_connectors_need_no_setup_and_store_nothing(connected):
    """Flowhaus never stores keys: the demo connectors work without any connection state."""
    assert firecrawl.scrape("https://kiteanalytics.com")["url"]
    assert not hasattr(_base, "CONNECTIONS_PATH")


def test_calls_are_recorded(connected):
    before = len(_base.CALLS)
    firecrawl.search("pricing pages", limit=2)
    assert len(_base.CALLS) == before + 1 and _base.CALLS[-1]["app"] == "firecrawl"


def test_update_items_skips_on_skip_and_item_error(connected):
    df = pd.DataFrame({"_row_id": [1, 2, 3], "_rejected_reason": [None, None, "already out"],
                       "email": ["a@northwind.io", "b@gmail.com", "c@northwind.io"]})

    def fn(item):
        if item["email"].startswith("a"):
            raise Skip("custom reason")
        return {"company": clay.enrich_company(item["email"])["name"]}

    out = update_items(df, fn)
    assert list(out["_rejected_reason"]) == ["custom reason", "gmail.com is a personal email provider, so there is no company to look up", "already out"]
    assert df["_rejected_reason"].isna().tolist() == [True, True, False]  # input untouched


def test_skip_where_keeps_existing_reasons():
    df = pd.DataFrame({"_row_id": [1, 2], "_rejected_reason": ["first", None], "n": [1, 1]})
    out = skip_where(df, df["n"] < 5, "too small")
    assert out["_rejected_reason"].tolist() == ["first", "too small"]


@pytest.mark.parametrize("tool,inp,allowed", [
    ("Write", {"file_path": "flows/demo/steps/a.py"}, True),
    ("Write", {"file_path": "flows/demo/data/sample.csv"}, True),
    ("Write", {"file_path": "Data/contacts.csv"}, False),
    ("Write", {"file_path": "flows/demo/flow.yaml"}, False),
    ("Write", {"file_path": "server/app.py"}, False),
    ("Write", {"file_path": "/etc/hosts"}, False),
    ("Read", {"file_path": "STATE/connections.json"}, False),
    ("Glob", {"pattern": "/Users/**/.env"}, False),
    ("Read", {"file_path": "~/.ssh/id_rsa"}, False),
    ("Read", {"file_path": "~/.zshrc"}, False),
    ("Read", {"file_path": "../../.ssh/id_rsa"}, False),
    ("Read", {"file_path": ".env"}, False),
    ("Read", {"file_path": "flows/demo/steps/a.py"}, True),
    ("Glob", {"pattern": "docs/*/state/*"}, False),
    ("Glob", {"pattern": "**/*.py"}, False),  # replaced by the guarded find_files / search_files tools
    ("Grep", {"pattern": "x", "path": "/etc"}, False),
    ("Bash", {"command": "python -V"}, False),
    ("mcp__clay__enrich_company", {"domain_or_email": "x.io"}, True),
])
def test_agent_guardrails(tool, inp, allowed):
    assert (check_tool_use(tool, inp, builder=True) is None) is allowed


@pytest.mark.parametrize("tool,inp", [
    ("Write", {"file_path": "pipeline/clean.py"}),
    ("Edit", {"file_path": "flows/demo/steps/a.py"}),
    ("mcp__flow__run_flow", {"flow_id": "contact-cleaning"}),
    ("mcp__flow__create_flow", {"flow_id": "x"}),
])
def test_no_writing_or_running_without_the_builder(tool, inp):
    """With the builder off (or on a connected automation), text in logs or code can't get code written or run."""
    assert check_tool_use(tool, inp, builder=False) is not None
    assert check_tool_use(tool, inp) is not None  # default state in tests: demo off


def test_file_search_checks_every_file(tmp_path):
    from server import agent

    (agent.ROOT / "state").exists() or pytest.skip("needs the project folder")
    files = {str(p.relative_to(agent.ROOT)) for p in agent._readable_files(None, None, 100_000)}
    assert "server/agent.py" in files
    assert not any(f.startswith(("state/", ".git/", ".venv/")) or "/.env" in f or f.startswith(".env") for f in files)
    assert not list(agent._readable_files(None, ".e[n]v*", 100))


def test_step_code_gets_no_secrets(monkeypatch):
    from server import runtime

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("GH_TOKEN", "ghp_test")
    env = runtime.step_env()
    assert "ANTHROPIC_API_KEY" not in env and "GH_TOKEN" not in env and "PATH" in env
