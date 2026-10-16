"""The Review: drift, ideas and repeating failures are found, and everything comes with a next step."""

from fastapi.testclient import TestClient

from server import checkup, harness, insights, maps, sample_flows
from server.app import app

local = TestClient(app, base_url="http://127.0.0.1:8000")


def run(i, out=40, skip=10, n_in=100, status="success", secs=60, error=None):
    return {"run_id": f"r{i}", "status": status, "started_at": f"2026-10-{20 - i:02d}T07:00:00",
            "finished_at": f"2026-10-{20 - i:02d}T07:{secs // 60:02d}:{secs % 60:02d}", "error": error,
            "summary": {"rows_read": n_in, "rows_written": out},
            "nodes": {"keep": {"status": "success", "rows_in": n_in, "rows_out": n_in - skip, "rows_rejected": skip,
                               "reject_reasons": {"Too small": skip}}}}


def drift(runs, monkeypatch):
    monkeypatch.setattr(insights, "_full", lambda flow_id, r: r)
    return {i["kind"]: i for i in insights._drift("x", runs, {"keep": "Keep good ones"}, "leads")}


def test_a_slow_slide_in_output_is_drift_even_if_no_run_looks_broken(monkeypatch):
    runs = [run(i, out=o) for i, o in enumerate([26, 27, 28, 40, 41, 39, 42, 40])]
    found = drift(runs, monkeypatch)
    assert "output_drift" in found and "down from 40" in found["output_drift"]["title"]
    assert found["output_drift"]["evidence"]  # the numbers it's based on


def test_a_step_that_skips_more_and_more(monkeypatch):
    runs = [run(i, skip=s) for i, s in enumerate([40, 42, 45, 10, 12, 11, 10, 9])]
    assert "skip_drift" in drift(runs, monkeypatch)


def test_steady_runs_show_no_drift(monkeypatch):
    assert drift([run(i) for i in range(8)], monkeypatch) == {}


def test_the_same_kind_of_failure_again_and_again_is_an_actionable_idea(monkeypatch):
    err = {"node_id": "keep", "message": "429 rate limit"}
    runs = [run(0, status="failed", error=err), run(1), run(2, status="failed", error=err), run(3)]
    monkeypatch.setattr(insights, "_full", lambda flow_id, r: None)
    ideas = {i["kind"]: i for i in insights._ideas("x", runs, {"keep": "Keep good ones"}, "leads")}
    pattern = ideas["failure_pattern"]
    assert "2 of the last 4 runs failed on an app not answering or rate limits" in pattern["title"]
    assert "retries" in pattern["next_step"]


def test_every_insight_and_finding_says_what_to_do():
    for flow_id in sample_flows.SAMPLE_FLOWS:
        for i in insights.insights(flow_id):
            assert i.get("next_step") and i.get("prompt"), i
    missing = [k for k in ("no_test_mode", "rerun_unsafe", "no_numbers", "lost_between", "unmapped_code") if k not in harness.NEXT_STEP]
    assert not missing


def test_the_review_sorts_everything_into_sections():
    failed = next(r for r in sample_flows.history("salesforce-sheet-sync") if r["status"] == "failed")
    r = checkup.checkup("salesforce-sheet-sync", failed["run_id"])
    assert set(r) >= {"fix_now", "silent", "drift", "ideas", "setup", "questions", "errors", "improvements", "runs_checked"}
    assert r["fix_now"][0]["source"] == "run" and r["fix_now"][0]["next_step"]
    assert r["fix_now"][0]["priority"] == "P0"  # the Review button and Run turn red
    assert r["errors"] == len(r["fix_now"]) + len(r["silent"]) + len(r["drift"])


def test_setup_gaps_are_a_checklist_and_lost_items_are_a_silent_failure(monkeypatch):
    def finding(kind):
        return {"id": kind, "kind": kind, "level": "warn", "title": kind, "detail": "", "next_step": "x", "practice": "p"}

    monkeypatch.setattr(harness, "review", lambda flow_id: {"findings": [finding("no_test_mode"), finding("lost_between")],
                                                          "questions": [{"id": "q"}]})
    r = checkup.checkup("salesforce-sheet-sync")
    assert [i["id"] for i in r["setup"] if i["source"] == "finding"] == ["no_test_mode"]
    assert [i["id"] for i in r["silent"] if i["source"] == "finding"] == ["lost_between"]
    assert r["improvements"] == len(r["ideas"]) + len(r["setup"]) + 1


def test_conventions_are_warnings_with_a_fix():
    steps = [{"id": "a", "label": "Fetch", "description": "This turns the API's JSON into a DataFrame."},
             {"id": "b", "label": "Is it big", "kind": "decision", "branches": [], "description": "x"},
             {"id": "c", "label": "Send the weekly digest to every subscriber on the list now", "description": "Sends it."}]
    found = {c["id"].split(":")[0] for c in maps.conventions(steps, [], {})}
    assert found == {"description_verb", "code_word", "decision_rule", "label_long", "no_terms"}
    assert all(c["fix"] for c in maps.conventions(steps, [], {}))
    good = [{"id": "a", "label": "Fetch articles", "description": "Gives you every new article."}]
    assert maps.conventions(good, [], {"terms": {"item": "article", "items": "articles"}}) == []


def test_a_pull_request_needs_its_review_confirmed():
    r = local.post("/api/changes/nope/pull-request", json={"confirmed": []})
    assert r.status_code in (400, 404)  # unknown change: refused either way


def test_noise_is_not_drift_but_a_noisy_real_slide_is(monkeypatch):
    noisy = [run(i, out=o) for i, o in enumerate([38, 45, 33, 41, 36, 44, 39, 42])]
    assert "output_drift" not in drift(noisy, monkeypatch)
    sliding = [run(i, out=o) for i, o in enumerate([28, 30, 26, 41, 38, 44, 40, 37])]
    assert "output_drift" in drift(sliding, monkeypatch)


def test_skip_rates_on_a_handful_of_items_are_too_noisy_to_call(monkeypatch):
    few = [run(i, n_in=6, skip=s) for i, s in enumerate([4, 4, 5, 1, 1, 0, 1, 1])]
    assert "skip_drift" not in drift(few, monkeypatch)
