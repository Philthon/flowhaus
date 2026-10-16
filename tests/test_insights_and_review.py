"""The harness: insights from run history, and the review of a proposed change (downstream, DRY, log lines)."""

import json
import subprocess

import pytest

from server import insights, review

ADAPTER = '''
import json
from pathlib import Path
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

STEPS = "map: {steps: [{id: fetch, label: Fetch, description: d}, {id: keep, label: Keep good ones, description: d}]}\n"


def run(i, status="success", out=100, keep=None, error_node=None):
    keep = keep or {"status": "success", "rows_in": out, "rows_out": out, "rows_rejected": 0, "reject_reasons": {}}
    return {"run_id": f"r{i}", "status": status, "started_at": f"2026-10-{10 - i:02d}T07:00:00", "finished_at": None,
            "trigger": "schedule", "error": {"node_id": error_node, "message": "x"} if error_node else None,
            "summary": {"rows_read": out, "rows_written": out, "rows_rejected": 0}, "nodes": {"keep": keep}}


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    folder = tmp_path / "automations" / "fake"
    folder.mkdir(parents=True)
    (folder / "automation.yaml").write_text("type: python\nname: Fake\ndescription: d\nterms: {item: lead, items: leads}\n" + STEPS)
    (folder / "adapter.py").write_text(ADAPTER)
    monkeypatch.setenv("FLOWHAUS_AUTOMATIONS_DIR", str(tmp_path / "automations"))

    def set_runs(runs):
        (folder / "runs.json").write_text(json.dumps(runs))
        return [(i["kind"], i["title"]) for i in insights.insights("fake")]
    return set_runs


def test_healthy_automation_has_no_insights(fake):
    assert fake([run(i) for i in range(6)]) == []


def test_fewer_than_usual_and_nothing_out(fake):
    assert fake([run(0, out=30)] + [run(i) for i in range(1, 6)])[0][0] == "fewer_than_usual"
    assert fake([run(0, out=0)] + [run(i) for i in range(1, 6)])[0] == ("nothing_out", "Ran fine but produced no leads")


def test_repeated_failures_at_one_step(fake):
    found = fake([run(i, status="failed", error_node="keep") for i in range(3)] + [run(3)])
    assert found[0] == ("repeated_failure", "Failed 3 runs in a row at “Keep good ones”")


def test_items_that_vanish_without_a_reason(fake):
    lossy = {"status": "success", "rows_in": 100, "rows_out": 60, "rows_rejected": 10, "reject_reasons": {"Spam": 10}}
    found = fake([run(0, keep=lossy)] + [run(i) for i in range(1, 4)])
    assert ("unexplained_loss", "30 leads left “Keep good ones” without a reason") in found


def test_step_that_suddenly_skips_everything(fake):
    broken = {"status": "success", "rows_in": 100, "rows_out": 2, "rows_rejected": 98, "reject_reasons": {"Missing date": 98}}
    found = fake([run(0, keep=broken), run(1)])
    assert ("skips_everything", "“Keep good ones” now skips almost everything") in found


# --------------------------------------------------------------------------- review of a change

FMAP = {"steps": [{"id": s, "label": s.title(), "file": f} for s, f in
                  [("fetch", "src/fetch.py"), ("extract", "src/extract.py"), ("dedupe", None), ("publish", "src/publish.py")]],
        "edges": [{"source": "fetch", "target": "extract"}, {"source": "extract", "target": "dedupe"},
                  {"source": "dedupe", "target": "publish"}]}


def test_a_change_reaches_everything_downstream():
    touched, unmapped = review.touched_steps(FMAP, ["src/extract.py", "src/util.py", "README.md"])
    assert touched == ["extract"] and unmapped == ["src/util.py"]
    assert review.downstream(FMAP, touched) == ["dedupe", "publish"]


def test_repeated_code_is_flagged(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    helper = "def clean(name):\n    name = name.strip()\n    name = name.replace('  ', ' ')\n    name = name.title()\n    return name\n"
    (repo / "src" / "util.py").write_text(helper)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e.st", "commit", "-qm", "x"], cwd=repo, check=True)
    diff = ("+++ b/src/extract.py\n@@\n+def tidy(name):\n+    name = name.strip()\n+    name = name.replace('  ', ' ')\n"
            "+    name = name.title()\n+    return name\n")
    found = review.repeats(repo, diff)
    assert found and found[0]["same_as"].startswith("src/util.py:")


def test_rewording_a_counted_log_line_is_flagged():
    config = {"map": {"steps": [{"id": "fetch", "out": {"sum": r"^Fetched (\d+) pages"}}]}}
    diff = "--- a/src/fetch.py\n+++ b/src/fetch.py\n-    print(f\"Fetched {len(pages)} pages\")\n+    print(f\"Got {len(pages)} pages\")\n"
    assert review.log_line_changes(config, diff) == [{"step": "fetch", "line": 'print(f"Fetched {len(pages)} pages")'}]
