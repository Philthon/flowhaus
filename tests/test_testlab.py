"""The test lab: generated items, test runs where the automation lives, checks, and no production side effects."""

import http.server
import json
import os
import sys
import threading

import pytest

from server import flows, runs, testlab

os.environ["STEP_DELAY_S"] = "0"


@pytest.fixture()
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(testlab, "TESTS_DIR", tmp_path / "tests")
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    (tmp_path / "runs").mkdir()
    # run in this process (the real one starts a subprocess), so the temporary folders above apply
    monkeypatch.setattr(runs, "run_blocking", lambda input_file, trigger, flow_id: runs.execute_run(
        runs.new_run_id(flow_id), input_file, trigger, step_delay_s=0, flow_id=flow_id))
    return tmp_path


def test_temperature_goes_from_typical_to_wild(lab):
    calm = testlab.generate("contact-cleaning", 30, 0.0, seed=1)
    wild = testlab.generate("contact-cleaning", 30, 1.0, seed=1)
    assert sum(c["note"] == "typical item" for c in calm) > 20
    assert sum(c["note"] != "typical item" for c in wild) > 20
    assert any(";" in c["note"] for c in wild)  # several problems at once
    assert testlab.generate("contact-cleaning", 5, 0.7, seed=9) == testlab.generate("contact-cleaning", 5, 0.7, seed=9)


def test_local_test_run_checks_every_item_and_leaves_production_alone(lab):
    real_output = runs.ROOT / runs.OUTPUT_PATH
    before = real_output.stat().st_mtime if real_output.exists() else None
    testlab.save_suite("contact-cleaning", {"cases": [
        {"item": {"name": "Ana Silva", "email": "ana@example.com", "company": "A"}, "note": "typical", "expect": "kept"},
        {"item": {"name": "Bo", "email": "bo at example.com", "company": "B"}, "note": "email without @", "expect": "skipped"},
        {"item": {"name": "Cy", "email": "cy@example.com", "company": "C"}, "note": "wrongly expected", "expect": "skipped"},
    ]})
    rec = testlab.start("contact-cleaning")
    checks = {c["name"]: c["ok"] for c in rec["checks"]}
    assert checks["The run finished"] and checks["No step failed"]
    assert checks["Every test item is accounted for (kept, or skipped with a reason)"]
    assert checks["Items end up where you expected"] is False  # the third case
    assert [r["got"] for r in rec["results"]] == ["kept", "skipped", "kept"]
    assert rec["results"][1]["reason"]
    assert (real_output.stat().st_mtime if real_output.exists() else None) == before
    assert rec["run_id"] in testlab.test_run_ids("contact-cleaning")
    assert all(r["run_id"] != rec["run_id"] for r in flows.production_runs("contact-cleaning", flows.list_runs("contact-cleaning")))


def connected(tmp_path, monkeypatch, test_block: dict, kind="folder_runs"):
    folder = tmp_path / "automations" / "auto"
    folder.mkdir(parents=True)
    (folder / "runs").mkdir()
    cfg = {"type": kind, "name": "Auto", "description": "d", "folder_runs": {"path": "runs"},
           "map": {"steps": [{"id": "a", "label": "A", "description": "d", "produces": "x.txt"}]},
           "test": {"fields": {"name": "text"}, "examples": [{"name": "Ana"}], **test_block}}
    import yaml

    (folder / "automation.yaml").write_text(yaml.safe_dump(cfg))
    monkeypatch.setenv("FLOWHAUS_AUTOMATIONS_DIR", str(tmp_path / "automations"))
    testlab.save_suite("auto", {"cases": testlab.generate("auto", 3, 0.5, seed=1)})


def test_remote_tests_need_a_non_production_promise_and_a_confirmation(lab, monkeypatch):
    connected(lab, monkeypatch, {"command": [sys.executable, "-c", "print('ok')"]})
    assert testlab.mode("auto")["ready"] is False
    with pytest.raises(ValueError, match="non_production"):
        testlab.start("auto", confirmed=True)


def test_command_mode_runs_your_command_with_the_items(lab, monkeypatch):
    script = lab / "check.py"
    script.write_text("import json, os, sys\nitems = json.load(open(sys.argv[1]))\n"
                      "print('test mode' if os.environ.get('FLOWHAUS_TEST') else 'PRODUCTION', len(items), 'items')\n")
    connected(lab, monkeypatch, {"command": [sys.executable, str(script), "{items_file}"],
                                 "non_production": "the script only prints"})
    with pytest.raises(ValueError, match="Confirm"):
        testlab.start("auto")
    rec = testlab.start("auto", confirmed=True)
    assert "test mode 3 items" in rec["output"]
    assert rec["checks"][0] == {"name": "The test command finished without an error", "ok": True, "detail": "exit code 0"}


def test_webhook_mode_posts_the_items(lab, monkeypatch):
    got = {}

    class Hook(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            got.update(json.loads(self.rfile.read(int(self.headers["content-length"]))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"received": true}')

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Hook)
    threading.Thread(target=server.handle_request, daemon=True).start()
    monkeypatch.setenv("TEST_HOOK", f"http://127.0.0.1:{server.server_port}/webhook-test/x")
    connected(lab, monkeypatch, {"webhook": "${TEST_HOOK}", "non_production": "n8n test webhook"})
    rec = testlab.start("auto", confirmed=True)
    assert got["test"] is True and len(got["items"]) == 3
    assert rec["checks"][0]["ok"] and '"received": true' in rec["output"]


def test_github_mode_dispatches_with_test_inputs(lab, monkeypatch):
    from server.automations import github_actions as ga

    calls = []
    monkeypatch.setattr(ga, "gh", lambda *a, **k: calls.append(a) or "[]")
    folder = lab / "automations" / "gha"
    folder.mkdir(parents=True)
    (folder / "automation.yaml").write_text(
        "type: github_actions\nname: G\ndescription: d\ngithub: {repo: someone/bot, workflow: run.yml}\n"
        "map: {steps: [{id: a, label: A, description: d, github_step: 'job/A'}]}\n"
        "test: {github: {inputs: {dry_run: 'true'}, items_input: test_items}, non_production: 'dry_run skips publishing',\n"
        "       examples: [{city: Berlin}]}\n")
    monkeypatch.setenv("FLOWHAUS_AUTOMATIONS_DIR", str(lab / "automations"))
    testlab.save_suite("gha", {"cases": [{"item": {"city": "Berlin"}, "note": "n", "expect": "any"}]})
    rec = testlab.start("gha", confirmed=True)
    dispatch = next(c for c in calls if c[:2] == ("workflow", "run"))
    assert "dry_run=true" in dispatch and any(str(x).startswith("test_items=[") for x in dispatch)
    assert rec["status"] == "running"  # picked up later, when GitHub has run it
