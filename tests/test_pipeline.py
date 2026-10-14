import os

import pytest
from fastapi.testclient import TestClient

os.environ["STEP_DELAY_S"] = "0"

from server import maps, runs  # noqa: E402
from server.app import app  # noqa: E402

client = TestClient(app, base_url="http://127.0.0.1:8000")


@pytest.fixture(scope="module", autouse=True)
def isolated_runs_dir(tmp_path_factory):
    original = runs.RUNS_DIR
    runs.RUNS_DIR = tmp_path_factory.mktemp("runs")
    yield
    runs.RUNS_DIR = original


@pytest.fixture(scope="module")
def good_run():
    return runs.execute_run(runs.new_run_id(), "data/contacts.csv", trigger="test")


@pytest.fixture(scope="module")
def broken_run():
    return runs.execute_run(runs.new_run_id(), "data/contacts_broken.csv", trigger="test")


def test_good_run_has_all_six_steps(good_run):
    assert good_run["status"] == "success"
    assert len(good_run["nodes"]) == 6
    for node in good_run["nodes"].values():
        assert node["status"] == "success"
        assert node["rows_in"] is not None and node["rows_out"] is not None


def test_counts_chain_together(good_run):
    n = good_run["nodes"]
    assert n["load_contacts"]["rows_out"] == 50
    assert n["verify_email_format"]["rows_rejected"] > 0
    assert n["remove_duplicates"]["rows_in"] == n["verify_email_format"]["rows_out"]
    assert good_run["summary"]["rows_written"] == n["export_clean_list"]["rows_out"]


def test_plus_signs_rejected_by_default(good_run):
    reasons = good_run["nodes"]["verify_email_format"]["reject_reasons"]
    assert any("'+'" in r for r in reasons)


def test_samples_are_paired_by_row_id(good_run):
    node = good_run["nodes"]["strip_unwanted_characters"]
    assert [r["_row_id"] for r in node["sample_in"]] == [r["_row_id"] for r in node["sample_out"]]
    assert 0 < len(node["sample_in"]) <= 10


def test_broken_csv_fails_in_clean(broken_run):
    assert broken_run["status"] == "failed"
    assert broken_run["error"]["node_id"] == "normalize_strings"
    assert "email" in broken_run["error"]["message"]
    assert broken_run["nodes"]["load_contacts"]["status"] == "success"
    assert broken_run["nodes"]["export_clean_list"]["status"] == "not_run"


def test_failure_bubbles_to_group(broken_run):
    view = client.get(f"/api/runs/{broken_run['run_id']}").json()
    assert view["groups"]["clean"]["status"] == "failed"
    assert view["groups"]["clean"]["failed_step"] == "normalize_strings"
    assert view["groups"]["load"]["status"] == "success"
    assert view["groups"]["export"]["status"] == "not_run"


def test_map_is_valid():
    data = client.get("/api/map").json()
    assert data["problems"] == []
    assert data["levels"]["root"]["children"] == ["load", "clean", "dedupe", "export"]
    assert len(data["levels"]["clean"]["children"]) == 3


def test_preview_for_step_and_group(good_run):
    step = client.get(f"/api/nodes/verify_email_format/preview?run_id={good_run['run_id']}").json()
    assert step["rejected_samples"] and all(r["reason"] for r in step["rejected_samples"])
    group = client.get(f"/api/nodes/clean/preview?run_id={good_run['run_id']}").json()
    assert group["kind"] == "group" and group["rows_in"] == 50


def test_validate_catches_bad_tags():
    groups = [{"id": "a", "label": "A", "description": "", "parent": None},
              {"id": "empty", "label": "E", "description": "", "parent": None}]
    steps = [{"id": "s", "label": "S", "description": None, "group": "nope"}]
    problems = maps.validate(groups, steps)
    assert any("description" in p for p in problems)
    assert any("'nope'" in p for p in problems)
    assert any("'empty'" in p for p in problems)
