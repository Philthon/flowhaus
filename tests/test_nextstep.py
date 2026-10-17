"""The chat's first message when something is wrong: each problem with a short, specific next step."""

import pytest
from fastapi.testclient import TestClient

from server import nextstep, sample_flows
from server.app import app

local = TestClient(app, base_url="http://127.0.0.1:8000")


@pytest.mark.parametrize("message, expected", [
    ("HTTP 401: invalid API key", "Renew Slack's key"),
    ("Clay returned 429: rate limit reached", "too many requests"),
    ("Your credit balance is too low", "out of credits"),
    ("Read timed out after 30s", "didn't answer"),
    ("Backup drive not mounted", "Connect the backup drive, then run it again"),
    ("Slack said channel_not_found: #cs-alerts no longer exists", "points at something that no longer exists in Slack"),
    ("FileNotFoundError: data/contacts.csv", "isn't there"),
    ("Salesforce: REQUIRED_FIELD_MISSING: Email is empty for Cy Ng", "without a field it needs"),
    ("TypeError: unsupported operand type(s)", "The code behind “Post it” broke (TypeError)"),
    ("Something odd happened", "Read the log of “Post it”"),
])
def test_each_kind_of_error_gets_its_own_next_step(message, expected):
    step = {"id": "post", "label": "Post it", "app": "Slack", "file": "bot/post.py"}
    assert expected in nextstep.next_step(message, step)


def test_a_failed_run_becomes_one_problem_with_a_next_step_and_a_prompt():
    failed = next(r for r in sample_flows.history("salesforce-sheet-sync") if r["status"] == "failed")
    problems = nextstep.problems("salesforce-sheet-sync", failed["run_id"])
    first = problems[0]
    assert first["title"] == "Failed in “Create or update the contact”" and first["node_id"] == "upsert_contact"
    assert "without a field it needs" in first["next_step"]
    assert "Don't change anything yet" in first["prompt"]


def test_no_problems_for_a_good_run():
    ok = next(r for r in sample_flows.history("salesforce-sheet-sync") if r["status"] == "success")
    assert nextstep.problems("salesforce-sheet-sync", ok["run_id"]) == []


def test_the_review_carries_the_problem_to_solve_first():
    r = local.get("/api/checkup", params={"flow_id": "salesforce-sheet-sync"})
    assert r.status_code == 200 and set(r.json()["plan"]) == {"first", "others"}
    assert local.get("/api/checkup", params={"flow_id": "nope"}).status_code == 404


def test_with_several_problems_it_picks_one_to_solve_first(monkeypatch):
    run = {"status": "failed", "error": {"node_id": "b", "message": "x"}, "nodes": {
        "a": {"status": "failed", "error": {"message": "Read timed out"}},
        "b": {"status": "failed", "error": {"message": "HTTP 401: invalid API key"}}}}
    fmap = {"steps": [{"id": "a", "label": "Fetch"}, {"id": "b", "label": "Post"}], "problems": ["Step 'c' has no label"]}
    monkeypatch.setattr(nextstep.flows, "get_map", lambda f: fmap)
    monkeypatch.setattr(nextstep.flows, "get_run", lambda f, r: run)
    monkeypatch.setattr(nextstep.flows, "kind", lambda f: "sample")
    monkeypatch.setattr("server.insights.insights", lambda f: [])
    p = nextstep.plan("x", "r1")
    # the earliest failure comes first, even though the later one is a blocker: it may only be a consequence
    assert p["first"]["node_id"] == "a" and "earliest failure" in p["first"]["why"]
    assert [o["id"] for o in p["others"]] == ["run:b", "map"]
    assert "didn't answer" in p["first"]["next_step"]


def test_one_problem_needs_no_why():
    failed = next(r for r in sample_flows.history("salesforce-sheet-sync") if r["status"] == "failed")
    p = nextstep.plan("salesforce-sheet-sync", failed["run_id"])
    assert p["first"]["why"] is None and p["others"] == []


def test_a_failed_step_and_its_overview_card_say_what_to_do():
    failed = next(r for r in sample_flows.history("salesforce-sheet-sync") if r["status"] == "failed")
    p = local.get("/api/nodes/upsert_contact/preview",
                  params={"flow_id": "salesforce-sheet-sync", "run_id": failed["run_id"]}).json()
    assert p["status"] == "failed" and "without a field it needs" in p["next_step"]
    ok = next(r for r in sample_flows.history("salesforce-sheet-sync") if r["status"] == "success")
    p = local.get("/api/nodes/upsert_contact/preview", params={"flow_id": "salesforce-sheet-sync", "run_id": ok["run_id"]}).json()
    assert "next_step" not in p  # nothing to do for a step that went fine


def test_next_steps_read_cleanly():
    assert nextstep.next_step("The connection to the reporting Postgres database is offline", None) == \
        "Connect the reporting Postgres database, then run it again."
    assert nextstep.next_step("VPN is not connected", None).startswith("Connect the VPN")
    # a declared kind picks its rule that fits the message: a timeout isn't a rate limit
    assert "didn't answer" in nextstep.next_step("Read timed out after 30s", None, "transient")
    assert nextstep.next_step_for({"message": "channel_not_found", "kind": "auth"}, None) == \
        nextstep.next_step("channel_not_found", None, "auth")


def test_evidence_without_an_error_message_keeps_the_log_lines():
    assert nextstep.evidence({}, {"log": [{"level": "error", "text": "HTTP 401"}]}) == (["HTTP 401"], None)


def test_the_latest_run_means_the_latest_real_run(monkeypatch):
    real = {"run_id": "real", "status": "success"}
    monkeypatch.setattr(nextstep.flows, "list_runs", lambda flow_id: [{"run_id": "test", "status": "failed"}, real])
    monkeypatch.setattr(nextstep.flows, "production_runs", lambda flow_id, rs: [r for r in rs if r["run_id"] != "test"])
    seen = []
    monkeypatch.setattr(nextstep.flows, "get_run", lambda flow_id, run_id: seen.append(run_id) or None)
    nextstep.problems("salesforce-sheet-sync", None, found_insights=[], review={})
    assert seen == ["real"]
