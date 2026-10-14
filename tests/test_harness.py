"""The harness's big picture: gaps, blind spots, questions, and the user's answers and dismissals (server/harness.py)."""

import json

import pytest
import yaml
from fastapi.testclient import TestClient

from server import harness
from server.app import app

ADAPTER = '''
import json
from server.automations.base import Automation, empty_node

class Fake(Automation):
    def _runs(self):
        return json.loads((self.folder / "runs.json").read_text())
    def list_runs(self):
        return [{k: v for k, v in r.items() if k != "nodes"} for r in self._runs()]
    def get_run(self, run_id):
        r = next((r for r in self._runs() if r["run_id"] == run_id), None)
        if r is None:
            return None
        nodes = {s["id"]: {**empty_node(s), **r.get("nodes", {}).get(s["id"], {})} for s in self.steps}
        return {**r, "nodes": nodes, "groups": {}}

def create(config, folder):
    return Fake(config, folder)
'''

CONFIG = {
    "type": "python", "name": "Fake", "description": "d", "terms": {"item": "lead", "items": "leads"},
    "trigger": {"type": "schedule", "label": "Daily"},
    "map": {"steps": [
        {"id": "fetch", "label": "Fetch leads", "description": "Gives you leads.", "app": "Firecrawl"},
        {"id": "keep", "label": "Keep good ones", "description": "Keeps good leads.", "app": "Code"},
        {"id": "post", "label": "Post to Slack", "description": "Posts each lead.", "app": "Slack"},
    ]},
}


def node(n_in, n_out, skipped=0):
    return {"status": "success", "rows_in": n_in, "rows_out": n_out, "rows_rejected": skipped,
            "reject_reasons": {"Too small": skipped} if skipped else {}}


def run(i, nodes=None, out=40):
    nodes = nodes or {"fetch": node(100, 100), "keep": node(100, 40, 60), "post": node(40, 40)}
    return {"run_id": f"r{i}", "status": "success", "started_at": f"2026-10-{10 - i:02d}T07:00:00", "finished_at": None,
            "trigger": "schedule", "error": None, "summary": {"rows_read": 100, "rows_written": out, "rows_rejected": 60},
            "nodes": nodes}


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    folder = tmp_path / "automations" / "fake"
    folder.mkdir(parents=True)
    (folder / "adapter.py").write_text(ADAPTER)
    monkeypatch.setenv("FLOWHAUS_AUTOMATIONS_DIR", str(tmp_path / "automations"))

    def setup(runs, **config):
        (folder / "automation.yaml").write_text(yaml.safe_dump({**CONFIG, **config}))
        (folder / "runs.json").write_text(json.dumps(runs))
        return harness.review("fake")
    setup.folder = folder
    return setup


def ids(items):
    return {i["id"] for i in items}


def test_big_picture_gaps_and_questions(fake):
    r = fake([run(i) for i in range(4)])
    found = ids(r["findings"])
    assert {"no_test_mode", "no_kpis", "cost_invisible"} <= found
    assert next(f for f in r["findings"] if f["id"] == "no_test_mode")["level"] == "warn"  # it posts to Slack
    asked = ids(r["questions"])
    assert {"rerun_safe:post", "expected_output", "skips_expected:keep", "who_notices"} == asked
    assert r["coverage"] == {"steps": 3, "with_numbers": 3, "linked_to_code": 0, "questions_answered": 0, "questions": 4}


def test_a_test_mode_and_kpis_quiet_those_gaps(fake):
    r = fake([run(i) for i in range(4)], test={"github": {"inputs": {"dry_run": True}}, "non_production": "dry run"},
             kpis=[{"label": "posted", "value": "{post.out}"}])
    assert not {"no_test_mode", "no_kpis"} & ids(r["findings"])


def test_answers_become_checks(fake):
    fake([run(i) for i in range(4)])
    harness.answer("fake", "rerun_safe:post", "duplicates")
    harness.answer("fake", "skips_expected:keep", "expected")
    r = harness.answer("fake", "expected_output", "50-80")
    found = {f["id"]: f for f in r["findings"]}
    assert found["rerun_unsafe:post"]["level"] == "warn"
    assert found["outside_expected"]["title"] == "40 leads came out; you said normal is 50-80"
    assert "skips_expected:keep" not in ids(r["questions"]) and "skips_too_many:keep" not in found
    assert {a["title"]: a["answer"] for a in r["answered"]}["If “Post to Slack” runs twice, does it publish twice?"] \
        == "Yes, it would duplicate"


def test_dismissed_findings_stay_quiet_with_their_reason(fake):
    fake([run(i) for i in range(4)])
    r = harness.dismiss("fake", "no_kpis", "The default numbers are what I check")
    assert "no_kpis" not in ids(r["findings"])
    assert r["dismissed"][0]["reason"] == "The default numbers are what I check"
    assert harness.for_chat("fake")["dismissed_by_user"] == {"The overview doesn't show what matters most":
                                                            "The default numbers are what I check"}
    assert "no_kpis" in ids(harness.restore("fake", "no_kpis")["findings"])
    saved = yaml.safe_load((fake.folder / "context.yaml").read_text())
    assert "no_kpis" not in (saved.get("dismissed") or {})


def test_only_open_items_can_be_answered_or_dismissed(fake):
    fake([run(i) for i in range(4)])
    with pytest.raises(ValueError):
        harness.dismiss("fake", "no_kpis", "  ")
    with pytest.raises(ValueError):
        harness.dismiss("fake", "made_up", "because")
    with pytest.raises(ValueError):
        harness.answer("fake", "made_up", "yes")


def test_items_lost_between_steps_are_a_blind_spot(fake):
    nodes = {"fetch": node(100, 100), "keep": node(70, 40, 30), "post": node(40, 40)}
    r = fake([run(i, nodes) for i in range(4)])
    lost = next(f for f in r["findings"] if f["id"] == "lost_between:fetch:keep")
    assert lost["title"] == "30 leads vanish between “Fetch leads” and “Keep good ones”"


def test_steps_without_numbers_are_a_blind_spot(fake):
    nodes = {"fetch": node(100, 100), "keep": {"status": "success"}, "post": node(40, 40)}
    r = fake([run(i, nodes) for i in range(4)])
    assert any(f["id"].startswith("no_numbers:") and f["node_id"] == "keep" for f in r["findings"])
    assert r["coverage"]["with_numbers"] == 2


def test_code_next_to_the_steps_but_off_the_map(fake, tmp_path):
    code = tmp_path / "project"
    (code / "src").mkdir(parents=True)
    for name in ("fetch.py", "post.py", "notify.py", "utils.py", "__init__.py"):
        (code / "src" / name).write_text("")
    steps = [dict(s, file=f"src/{s['id']}.py") for s in CONFIG["map"]["steps"]]
    r = fake([run(i) for i in range(4)], local_path=str(code), map={"steps": steps})
    unmapped = next(f for f in r["findings"] if f["id"].startswith("unmapped_code:"))
    assert unmapped["title"] == "1 code file next to the steps isn't on the map"
    assert unmapped["detail"].startswith("src/notify.py.")


def test_demo_flows_have_no_harness_review():
    assert harness.review("lead-enrichment")["findings"] == []


local = TestClient(app, base_url="http://127.0.0.1:8000")


def test_api_answer_dismiss_restore(fake):
    fake([run(i) for i in range(4)])
    assert local.get("/api/harness", params={"flow_id": "fake"}).json()["questions"]
    r = local.post("/api/harness/fake/answer", json={"question_id": "who_notices", "answer": "others"})
    assert r.status_code == 200 and "failure_unannounced" in ids(r.json()["findings"])
    assert local.post("/api/harness/fake/dismiss", json={"finding_id": "nope", "reason": "x"}).status_code == 400
    assert local.post("/api/harness/lead-enrichment/dismiss", json={"finding_id": "x", "reason": "x"}).status_code == 404
    blocked = local.post("/api/harness/fake/answer", json={"question_id": "who_notices", "answer": "me"},
                         headers={"origin": "https://evil.example"})
    assert blocked.status_code == 403


def test_flows_built_in_flowhaus_are_reviewed_too(tmp_path, monkeypatch):
    import shutil

    from server import flows, runs

    shutil.copytree(runs.FLOWS_DIR / "lead-qualification", tmp_path / "flows" / "lq")
    monkeypatch.setattr(flows, "FLOWS_DIR", tmp_path / "flows")
    monkeypatch.setattr(runs, "FLOWS_DIR", tmp_path / "flows")
    steps = [s["id"] for s in flows.get_map("lq")["steps"]]
    history = [{"run_id": f"r{i}", "status": "success", "trigger": "ui", "started_at": f"2026-10-0{i + 1}",
                "summary": {"rows_written": 3}, "nodes": {s: node(10, 3, 7) for s in steps}} for i in range(3)]
    monkeypatch.setattr(flows, "list_runs", lambda fid: history)
    monkeypatch.setattr(flows, "get_run", lambda fid, rid: next(r for r in history if r["run_id"] == rid))

    r = harness.review("lq")
    assert harness.reviewed("lq") and r["context_file"].endswith("flows/lq/context.yaml")
    assert not {"no_test_mode", "no_kpis", "cost_invisible"} & ids(r["findings"])  # tested and counted here
    assert "expected_output" in ids(r["questions"])
    harness.answer("lq", "expected_output", "any")
    assert (tmp_path / "flows" / "lq" / "context.yaml").exists()
