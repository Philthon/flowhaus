"""Connected automations: config loading, log rules, folder runs, the on/off switch (gh is always faked)."""

import base64
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from server import automations, flows
from server.automations import github_actions as ga
from server.automations.github_actions import apply_rules, next_cron_run, render_summary

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "automations"
RUN = "9001"
LOG = [
    ("digest", "Run digest", "feed example.com/rss ok 25"),
    ("digest", "Run digest", "feed news.example.org/feed ok 15"),
    ("digest", "Run digest", "Fetched 40 articles"),
    ("digest", "Run digest", "skip https://a.example/1 old"),
    ("digest", "Run digest", "skip https://a.example/2 old"),
    ("digest", "Run digest", "skip https://a.example/3 dup"),
    ("digest", "Run digest", "pick How to stop worrying"),
    ("digest", "Run digest", "Picked 37"),
    ("digest", "Send digest", "Sent to 1200 subscribers"),
]


def log_text(lines):
    return "\n".join(f"{j}\t{s}\t2026-10-05T07:00:0{i % 10}.0000000Z {t}" for i, (j, s, t) in enumerate(lines))


class FakeGitHub:
    """Answers the few gh commands the adapter uses, and remembers enable/disable."""

    def __init__(self, log=LOG, conclusion="success"):
        self.state, self.calls, self.log, self.conclusion = "active", [], log, conclusion

    def __call__(self, *args, **_):
        self.calls.append(args)
        if args[:2] == ("workflow", "list"):
            return json.dumps([{"path": ".github/workflows/digest.yml", "state": self.state}])
        if args[:2] == ("workflow", "disable"):
            self.state = "disabled_manually"
            return ""
        if args[:2] == ("workflow", "enable"):
            self.state = "active"
            return ""
        if args[:2] == ("run", "list"):
            return json.dumps([{"databaseId": int(RUN), "status": "completed", "conclusion": self.conclusion,
                                "createdAt": "2026-10-05T07:00:00Z", "updatedAt": "2026-10-05T07:04:00Z",
                                "event": "schedule"}])
        if args[:2] == ("run", "view") and "--log" in args:
            return log_text(self.log)
        if args[:2] == ("run", "view"):
            step = {"name": "Send digest", "status": "completed", "conclusion": self.conclusion,
                    "startedAt": "2026-10-05T07:03:00Z", "completedAt": "2026-10-05T07:04:00Z"}
            return json.dumps({"jobs": [{"name": "digest", "status": "completed", "steps": [step]}]})
        if args[0] == "api":
            content = base64.b64encode(b"on:\n  schedule:\n    - cron: '0 7 * * 1'\n").decode()
            return json.dumps({"content": content})
        raise AssertionError(f"unexpected gh call {args}")


@pytest.fixture()
def autodir(tmp_path, monkeypatch):
    """An automations folder with copies of the examples, the app pointed at it, and no real gh or state."""
    base = tmp_path / "automations"
    for name in ("newsletter-digest", "invoice-export", "backup-log"):
        shutil.copytree(EXAMPLES / name, base / name)
    cfg = base / "newsletter-digest" / "automation.yaml"
    cfg.write_text(cfg.read_text().replace("allow_toggle: false", "allow_toggle: true")
                   .replace("local_path: ~/code/newsletter-bot", "local_path: " + str(tmp_path / "bot")))
    monkeypatch.setenv("FLOWHAUS_AUTOMATIONS_DIR", str(base))
    monkeypatch.setattr(ga, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(flows, "STATE_PATH", tmp_path / "flows.json")
    fake = FakeGitHub()
    monkeypatch.setattr(ga, "gh", fake)
    return base, fake


def test_examples_load_without_problems(autodir):
    found, errors = automations.load_all()
    assert errors == {}
    assert set(found) == {"newsletter-digest", "invoice-export", "backup-log"}
    for a in found.values():
        problems = [p for p in a.check() if "local_path" not in p]
        assert problems == [], (a.id, problems)


def test_bad_config_is_reported_not_raised(autodir):
    base, _ = autodir
    (base / "broken").mkdir()
    (base / "broken" / "automation.yaml").write_text("type: nope\n")
    found, errors = automations.load_all()
    assert "broken" in errors and "type must be one of" in errors["broken"]
    assert "invoice-export" in found


def test_log_rules_fill_counts_reasons_and_tables(autodir):
    a = automations.all_automations()["newsletter-digest"]
    run = a.get_run(RUN)
    fetch, pick, send = (run["nodes"][k] for k in ("fetch_feeds", "pick_articles", "send_email"))
    assert (fetch["rows_out"], [r["feed"] for r in fetch["sample_out"]]) == (40, ["example.com/rss", "news.example.org/feed"])
    assert (pick["rows_in"], pick["rows_out"], pick["rows_rejected"]) == (40, 37, 3)
    assert pick["reject_reasons"] == {"Older than a week": 2, "Already sent": 1}
    assert send["status"] == "success" and send["rows_out"] == 1200 and send["duration_ms"] == 60_000
    assert run["summary"]["text"] == "40 articles read → 37 picked → sent to 1200 subscribers"
    assert run["input_items"] == fetch["sample_out"]


def test_fail_rule_explains_the_failure(autodir, monkeypatch):
    fake = FakeGitHub(log=[*LOG[:-1], ("digest", "Send digest", "Mailgun error 401 Unauthorized")], conclusion="failure")
    monkeypatch.setattr(ga, "gh", fake)
    a = automations.all_automations()["newsletter-digest"]
    a._list = (0.0, [])
    run = a.get_run(RUN)
    assert run["status"] == "failed"
    assert run["error"] == {"node_id": "send_email", "message": "The email could not be sent: Mailgun error 401 Unauthorized"}


def test_rule_that_never_matches_counts_zero():
    steps = [{"id": "a", "out": {"count": "^ok"}, "skip": [{"count": "^bad", "reason": "Bad"}]}]
    tally = apply_rules(["bad", "bad"], steps, None, None)
    assert tally["a"]["out"] is None and sum(tally["a"]["skip"].values()) == 2


def test_sections_name_the_failing_block():
    steps = [{"id": "fetch", "fail": {"pattern": "all failed", "message": "Nothing fetched for {sections}"}}]
    lines = ["##[group]Berlin", "all failed", "##[endgroup]", "##[group]Paris", "fine", "##[endgroup]"]
    tally = apply_rules(lines, steps, re.compile(r"^##\[group\](?P<section>\w+)$"), re.compile(r"^##\[endgroup\]"))
    assert tally["fetch"]["fail_sections"] == ["Berlin"]


def test_render_summary_needs_every_value():
    nodes = {"a": {"rows_in": 3, "rows_out": 2, "rows_rejected": 1}}
    assert render_summary("{a.in} in, {a.out} out, {a.skipped} skipped", nodes) == "3 in, 2 out, 1 skipped"
    assert render_summary("{a.out} then {b.out}", nodes) is None


def test_next_cron_run():
    monday_6am = datetime(2026, 10, 5, 6, 0, tzinfo=timezone.utc)
    expected = datetime(2026, 10, 5, 7, 30, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    assert next_cron_run("30 7 * * 1,3", monday_6am) == expected
    wednesday = datetime(2026, 10, 7, 7, 30, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    assert next_cron_run("30 7 * * 1,3", datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)) == wednesday
    assert next_cron_run("*/5 * * * *") is None  # unsupported forms give "unknown", never a wrong time


def test_toggle_runs_gh_and_logs(autodir):
    _, fake = autodir
    flows.set_enabled("newsletter-digest", False)
    assert ("workflow", "disable", "digest.yml", "-R", "your-name/newsletter-bot") in fake.calls
    assert flows.is_enabled("newsletter-digest") is False
    flows.set_enabled("newsletter-digest", True)
    texts = [e["text"] for e in flows._read_state()["events"]]
    assert texts == ["Turned off on GitHub Actions by you", "Turned on on GitHub Actions by you"]


def test_toggle_is_refused_unless_allowed(autodir):
    with pytest.raises(ValueError):
        flows.set_enabled("invoice-export", False)
    a = automations.all_automations()["newsletter-digest"]
    a.allow_toggle = False
    with pytest.raises(ValueError):
        flows.set_enabled("newsletter-digest", False)


def test_folder_runs(autodir):
    a = automations.all_automations()["invoice-export"]
    runs = a.list_runs()
    assert [r["status"] for r in runs] == ["success", "failed", "success"]
    failed = a.get_run(runs[1]["run_id"])
    assert failed["error"]["node_id"] == "make_invoices"
    assert failed["nodes"]["pull_orders"]["status"] == "success"
    assert a.get_run("../../etc") is None and a.get_run("..") is None


def test_folder_runs_are_private_to_the_agent(autodir):
    from server.agent import check_tool_use

    base, _ = autodir
    target = base / "invoice-export" / "runs" / "2026-10-01_09-00-00" / "orders.csv"
    assert check_tool_use("Read", {"file_path": str(target)}) is not None
    shouted = base / "invoice-export" / "RUNS" / "2026-10-01_09-00-00" / "orders.csv"  # macOS ignores case
    assert check_tool_use("Read", {"file_path": str(shouted)}) is not None
    ctx = automations.all_automations()["invoice-export"].agent_context(None)
    assert ctx["run_being_viewed"] is None and len(ctx["recent_runs"]) == 3


def test_agent_reads_only_source_in_connected_code(autodir, tmp_path):
    from server.agent import check_tool_use

    bot = tmp_path / "bot"
    (bot / ".git").mkdir(parents=True)
    for name in ("send.py", ".env", "credentials.json", "events.sqlite", "notes.bin", "gcp-key.json"):
        (bot / name).write_text("x")
    allowed = {name: check_tool_use("Read", {"file_path": str(bot / name)}) is None
               for name in ("send.py", ".env", "credentials.json", "events.sqlite", "notes.bin", ".git/config", "gcp-key.json")}
    assert allowed == {"send.py": True, ".env": False, "credentials.json": False, "events.sqlite": False,
                       "notes.bin": False, ".git/config": False, "gcp-key.json": False}
    from server.agent import _readable_files

    assert {p.name for p in _readable_files(str(bot), None, 100)} == {"send.py"}
    assert {p.name for p in _readable_files(str(bot), "?env", 100)} == set()


def test_python_adapter(autodir):
    a = automations.all_automations()["backup-log"]
    runs = a.list_runs()
    assert runs[0]["error"]["message"] == "Backup drive not mounted"
    assert a.get_run(runs[1]["run_id"])["nodes"]["verify"]["reject_reasons"] == {"Checksum differs": 1}


def test_new_user_starts_empty(tmp_path, monkeypatch):
    """No automations and demo off: no flows and no apps, so the UI shows onboarding instead."""
    from server import connections

    monkeypatch.setenv("FLOWHAUS_AUTOMATIONS_DIR", str(tmp_path / "none"))
    monkeypatch.setattr(flows, "STATE_PATH", tmp_path / "flows.json")
    assert flows.show_demo() is False
    assert flows.flow_ids() == [] and connections.list_connections() == []
    flows.set_show_demo(True)
    assert flows.LIVE_ID in flows.flow_ids()


def test_home_folder_is_never_readable_code(autodir):
    from pathlib import Path

    base, _ = autodir
    cfg = base / "invoice-export" / "automation.yaml"
    cfg.write_text(cfg.read_text() + "\nlocal_path: '~/'\n")
    a = automations.all_automations()["invoice-export"]
    assert a.readable_code_path() is None and Path.home().resolve() not in automations.read_only_paths()
    assert any("too broad" in p for p in a.check())


def test_colour_codes_are_removed_before_rules_match():
    from server.automations.github_actions import log_lines

    text = "job\tstep\t2026-10-05T07:00:00.0000000Z Processed items: ^[[97m1303^[[39m and \x1b[36m7\x1b[0m"
    assert log_lines(text)[0]["text"] == "Processed items: 1303 and 7"


def test_schedules_in_words():
    from server.automations.github_actions import describe_cron

    assert describe_cron("0 13 * * 1,3,5") == "Mondays, Wednesdays and Fridays at 13:00 UTC"
    assert describe_cron("0 * * * *") == "Every hour at :00"
    assert describe_cron("30 7 * * 1-5") == "Weekdays at 07:30 UTC"
    assert describe_cron("5 4 1 * *") == "On schedule (5 4 1 * * UTC)"  # unusual: say it as it is


def test_run_that_never_started_is_explained(autodir, monkeypatch):
    fake = FakeGitHub(conclusion="failure")

    def no_log(*args, **kw):
        if "--log" in args:
            raise ga.GhError("log not found: 111960151153")
        if args[:2] == ("run", "view"):
            return json.dumps({"jobs": [{"name": "digest", "status": "completed", "conclusion": "cancelled", "steps": []}]})
        return fake(*args, **kw)

    monkeypatch.setattr(ga, "gh", no_log)
    run = automations.all_automations()["newsletter-digest"].get_run(RUN)
    assert run["status"] == "failed" and "didn't start this run" in run["error"]["message"]


def test_totals_dont_double_count_chained_skips():
    from server.automations.base import run_totals

    nodes = {"a": {"rows_in": 100, "rows_out": 60, "rows_rejected": 40},
             "b": {"rows_in": 60, "rows_out": 10, "rows_rejected": 50}}
    assert run_totals([{"id": "a"}, {"id": "b"}], nodes) == {"rows_read": 100, "rows_written": 10, "rows_rejected": 90}


def test_folder_runs_count_items_and_quote_the_log(autodir):
    a = automations.all_automations()["invoice-export"]
    ok, failed = a.get_run("2026-10-03_09-00-00"), a.get_run("2026-10-02_09-00-00")
    assert ok["nodes"]["make_invoices"]["rows_out"] == 3 and ok["summary"]["rows_written"] == 3
    assert "tax service timed out" in failed["error"]["message"]


def test_typos_in_config_are_reported(autodir):
    base, _ = autodir
    cfg = base / "invoice-export" / "automation.yaml"
    cfg.write_text(cfg.read_text().replace("produces: invoices.csv", "produce: invoices.csv").replace("output: invoices.csv", "outptu: invoices.csv"))
    problems = automations.all_automations()["invoice-export"].check()
    assert any("`produce`" in p for p in problems) and any("`outptu`" in p for p in problems)


def test_bad_rule_names_the_step(autodir):
    base, _ = autodir
    cfg = base / "newsletter-digest" / "automation.yaml"
    cfg.write_text(cfg.read_text().replace("out: {sum: '^Picked (\\d+)'}", "out: {sum: '^Picked (\\d+'}"))
    _, errors = automations.load_all()
    assert "step 'pick_articles' has an invalid rule" in errors["newsletter-digest"]


def test_missed_schedule_is_flagged():
    from datetime import datetime, timezone

    from server.automations.github_actions import overdue_message

    now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)  # Wednesday noon
    ran_monday = datetime(2026, 10, 5, 7, 1, tzinfo=timezone.utc).astimezone().replace(tzinfo=None).isoformat()
    ran_today = datetime(2026, 10, 7, 7, 2, tzinfo=timezone.utc).astimezone().replace(tzinfo=None).isoformat()
    assert overdue_message("0 7 * * 1,3", ran_monday, now).startswith("Didn't run when expected")
    assert overdue_message("0 7 * * 1,3", ran_today, now) is None
    assert overdue_message("0 7 * * 1,3", ran_monday, datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)) is None  # grace


def test_pages_never_wait_for_github_once_runs_are_known(autodir, monkeypatch):
    import time as _time

    a = automations.all_automations()["newsletter-digest"]
    a.list_runs()  # first read: waits for GitHub
    slow = FakeGitHub()

    def slow_gh(*args, **kw):
        _time.sleep(1)
        return slow(*args, **kw)

    monkeypatch.setattr(ga, "gh", slow_gh)
    a._list = (_time.time() - 120, a._list[1])  # stale
    started = _time.time()
    assert a.list_runs() == a._list[1]
    assert _time.time() - started < 0.3  # answered from what it had; refreshing in the background
