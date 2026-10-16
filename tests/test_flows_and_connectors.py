
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


@pytest.mark.parametrize("tool,inp", [
    ("Read", {"file_path": "server/app.py"}),
    ("Write", {"file_path": "flows/demo/steps/a.py"}),
    ("Bash", {"command": "python -V"}),
    ("mcp__clay__enrich_company", {"domain_or_email": "x.io"}),
])
def test_claude_codes_own_tools_follow_the_users_setup(tool, inp):
    """Flowhaus doesn't police Claude Code's own tools: the user's Claude Code permissions do (see ask_permission)."""
    assert check_tool_use(tool, inp, builder=False) is None


@pytest.mark.parametrize("tool,inp", [
    ("mcp__flow__run_flow", {"flow_id": "contact-cleaning"}),
    ("mcp__flow__create_flow", {"flow_id": "x"}),
])
def test_no_creating_or_running_flows_without_the_builder(tool, inp):
    """With the builder off (or on a connected automation), text in logs or code can't get a flow created or run."""
    assert check_tool_use(tool, inp, builder=False) is not None
    assert check_tool_use(tool, inp) is not None  # default state in tests: demo off
    assert check_tool_use(tool, inp, builder=True) is None


def test_the_chat_runs_under_the_users_claude_code_setup():
    from server import agent

    opts = agent.WORKER.options()
    assert opts.setting_sources == ["user"] and opts.can_use_tool is agent.ask_permission
    assert "strict-mcp-config" in opts.extra_args  # MCP servers: only the ones switched on in Flowhaus
    assert not opts.tools and "Read" not in opts.allowed_tools  # its own tools, under its own permission rules


def test_step_code_gets_no_secrets(monkeypatch):
    from server import runtime

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("GH_TOKEN", "ghp_test")
    env = runtime.step_env()
    assert "ANTHROPIC_API_KEY" not in env and "GH_TOKEN" not in env and "PATH" in env
