"""What if: a step tried on edited items runs in test mode, and says plainly what happened to each item."""

from fastapi.testclient import TestClient

from server import flows, runs, whatif
from server.app import app

local = TestClient(app, base_url="http://127.0.0.1:8000")


def _by_step(result):
    return {s["id"]: s for s in result["steps"]}


def test_a_built_step_runs_on_edited_items_and_everything_after_it(tmp_path):
    before = runs.list_runs(flows.LIVE_ID)
    r = whatif.try_step(flows.LIVE_ID, "normalize_strings", [
        {"name": "  ana SILVA ", "email": " ANA@Example.com ", "company": "A"},
        {"name": "Bo", "email": "no-at-sign", "company": "B"},
    ])
    assert r["mode"] == "run"
    steps = _by_step(r)
    assert steps["normalize_strings"]["items"][0]["changes"]["name"] == ["  ana SILVA ", "Ana Silva"]
    assert steps["verify_email_format"]["items"][1] == {"n": 2, "outcome": "skipped", "reason": "Email has no @ sign"}
    assert r["out"] == [{"name": "Ana Silva", "email": "ana@example.com", "company": "A"}]
    # test mode: the flow's own output and run history are untouched
    assert not (tmp_path / "contacts_clean.csv").exists()
    assert runs.list_runs(flows.LIVE_ID) == before


def test_only_the_step_itself_when_asked():
    r = whatif.try_step(flows.LIVE_ID, "normalize_strings", [{"name": "x", "email": "a@b.c", "company": "C"}], downstream=False)
    assert [s["id"] for s in r["steps"]] == ["normalize_strings"]


def test_a_missing_field_is_explained_in_plain_words():
    r = whatif.try_step("lead-enrichment", "score_lead", [{"company": "Acme", "email": "jo@acme.com"}])
    step = r["steps"][0]
    assert step["status"] == "failed"
    assert "needs a field called" in step["error"] and "KeyError" not in step["error"]


def test_connected_automations_are_predicted_not_run(tmp_path, monkeypatch):
    folder = tmp_path / "automations" / "alpha"
    folder.mkdir(parents=True)
    (folder / "automation.yaml").write_text(
        "type: python\nname: A\ndescription: d\ntrigger: {label: Daily}\noutput: {label: Done}\n"
        "map: {steps: [{id: x, label: X, description: d}]}\n")
    (folder / "adapter.py").write_text("from server.automations.base import Automation\n"
                                       "class A(Automation):\n    def list_runs(self): return []\n"
                                       "    def get_run(self, r): return None\n"
                                       "def create(c, f): return A(c, f)\n")
    monkeypatch.setenv("FLOWHAUS_AUTOMATIONS_DIR", str(tmp_path / "automations"))
    r = whatif.try_step("alpha", "x", [{"a": 1}])
    assert r["mode"] == "predict" and "steps" not in r


def test_the_endpoint_checks_its_input():
    assert local.post("/api/whatif", json={"flow_id": flows.LIVE_ID, "step_id": "nope", "items": [{"a": 1}]}).status_code == 404
    assert local.post("/api/whatif", json={"flow_id": flows.LIVE_ID, "step_id": "normalize_strings", "items": []}).status_code == 400
    assert local.post("/api/whatif", headers={"origin": "https://evil.example"},
                      json={"flow_id": flows.LIVE_ID, "step_id": "normalize_strings", "items": [{"a": 1}]}).status_code == 403


def _latest_success(flow_id):
    return next(r["run_id"] for r in flows.list_runs(flow_id) if r["status"] == "success")


def test_replaying_an_unchanged_flow_gives_the_same_result():
    r = whatif.replay("lead-enrichment", _latest_success("lead-enrichment"))
    c = r["compare"]
    assert r["mode"] == "run" and c["before"] == c["after"]
    assert c["changed"] == c["now_skipped"] == c["now_kept"] == 0


def test_a_replay_shows_what_a_change_would_do(monkeypatch):
    from server import sample_flows

    step = next(s for s in sample_flows.SAMPLE_FLOWS["lead-enrichment"].steps if s.id == "check_fit")
    stricter = lambda item, rng: {**item, "_rejected_reason": "Fit score is below the new cut-off of 99"}  # noqa: E731
    monkeypatch.setattr(step, "fn", stricter)
    c = whatif.replay("lead-enrichment", _latest_success("lead-enrichment"))["compare"]
    assert c["after"] == 0 and c["now_skipped"] == c["before"] > 0
    assert "new cut-off of 99" in c["examples"][0]["now"]


def test_replay_endpoint():
    run_id = _latest_success("lead-enrichment")
    assert local.post("/api/whatif/replay", json={"flow_id": "lead-enrichment", "run_id": run_id}).json()["compare"]["changed"] == 0
    assert local.post("/api/whatif/replay", json={"flow_id": "lead-enrichment", "run_id": "nope"}).status_code == 404


def test_items_never_share_a_number():
    rows = whatif._numbered([{"_row_id": 0, "a": 1}, {"_row_id": 7, "a": 2}])
    assert [r["_row_id"] for r in rows] == [0, 7]  # from a run: kept, including 0
    mixed = whatif._numbered([{"_row_id": 2, "a": 1}, {"a": 2}, {"_row_id": 2, "a": 3}])
    assert [r["_row_id"] for r in mixed] == [1, 2, 3]  # some missing or repeated: numbered by position


def test_a_try_runs_isolated_and_cleans_up(tmp_path, monkeypatch):
    from server import runtime

    if runtime.sandbox_tool() is None:
        import pytest
        pytest.skip("no sandbox on this computer")
    monkeypatch.setattr(runs, "test_dir", lambda flow_id: tmp_path / flow_id)
    whatif.try_step(flows.LIVE_ID, "normalize_strings", [{"name": "a", "email": "a@b.c", "company": "C"}])
    assert list((tmp_path / flows.LIVE_ID).iterdir()) == []  # the scratch folder of the try is gone again


def test_the_sandbox_blocks_writes_outside_and_the_network(tmp_path):
    import subprocess
    import sys

    from server import runtime

    if runtime.sandbox_tool() is None:
        import pytest
        pytest.skip("no sandbox on this computer")
    inside, outside = tmp_path / "scratch", tmp_path / "elsewhere"
    outside.mkdir()
    code = ("import pathlib, urllib.request, sys\n"
            f"pathlib.Path({str(inside / 'ok.txt')!r}).write_text('ok')\n"
            "try:\n"
            f"    pathlib.Path({str(outside / 'no.txt')!r}).write_text('no'); print('wrote outside')\n"
            "except OSError: print('blocked write')\n"
            "try:\n"
            "    urllib.request.urlopen('http://example.com', timeout=5); print('reached network')\n"
            "except OSError: print('blocked network')\n")
    cmd, isolated = runtime.sandboxed([sys.executable, "-c", code], [inside])
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=runtime.test_env(inside)).stdout
    assert isolated and (inside / "ok.txt").exists()
    assert "blocked write" in out and "blocked network" in out and not (outside / "no.txt").exists()


# --------------------------------------------------------------------------- the Salesforce demo (n8n template 1792)


def test_the_salesforce_demo_branches_and_joins_again():
    from server import sample_flows

    m = sample_flows.build_map(sample_flows.SAMPLE_FLOWS["salesforce-sheet-sync"])
    assert m["problems"] == []
    out = {(e["source"], e["target"], e.get("label")) for e in m["edges"]}
    assert {("account_found", "use_account", "Yes"), ("account_found", "create_account", "No"),
            ("use_account", "upsert_contact", None), ("create_account", "upsert_contact", None)} <= out
    for run in sample_flows.history("salesforce-sheet-sync"):
        n = run["nodes"]
        if run["status"] == "success":  # every row takes exactly one path, and all of them reach the contact step
            assert (n["use_account"]["rows_in"] or 0) + (n["create_account"]["rows_in"] or 0) == n["account_found"]["rows_in"]
            assert n["upsert_contact"]["rows_in"] == n["read_sheet"]["rows_out"]


def test_a_near_miss_name_creates_a_second_account_and_an_empty_email_stops_the_run():
    r = whatif.try_step("salesforce-sheet-sync", "search_account", [
        {"first_name": "Ana", "last_name": "Silva", "email": "ana@kite.com", "company_name": "Kite Analytics Inc."},
        {"first_name": "Bo", "last_name": "Lee", "email": "bo@kite.com", "company_name": "Kite Analytics"},
        {"first_name": "Cy", "last_name": "Ng", "email": "", "company_name": "Orbit Robotics"}])
    steps = _by_step(r)
    assert [f["path"] for f in steps["account_found"]["items"]] == ["No", "Yes", "No"]
    assert [f["n"] for f in steps["create_account"]["items"]] == [1, 3]  # numbered as entered, not per path
    assert steps["upsert_contact"]["status"] == "failed" and "Email is empty for Cy Ng" in steps["upsert_contact"]["error"]
