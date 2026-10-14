"""The onboarding CLI an agent drives: scan -> add -> check."""

import json
import subprocess

from server import cli


def make_runs(base, names=("2026-10-01_09-00-00", "2026-10-02_09-00-00", "2026-10-03_09-00-00")):
    for n in names:
        (base / n).mkdir(parents=True)
        (base / n / "orders.csv").write_text("a\n1\n")
        (base / n / "summary.md").write_text("done\n")


def test_scan_finds_workflows_and_run_folders(tmp_path, capsys):
    wf = tmp_path / "code" / "bot" / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "digest.yml").write_text("name: Digest\non:\n  schedule:\n    - cron: '0 7 * * 1'\n")
    subprocess.run(["git", "init", "-q", str(tmp_path / "code" / "bot")], check=True)
    subprocess.run(["git", "-C", str(tmp_path / "code" / "bot"), "remote", "add", "origin",
                    "https://github.com/someone/bot.git"], check=True)
    make_runs(tmp_path / "code" / "exporter" / "out")
    assert cli.main(["scan", str(tmp_path / "code"), "--no-system", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)["candidates"]
    gha = next(c for c in found if c["type"] == "github_actions")
    assert (gha["repo"], gha["workflow"], gha["schedule"]) == ("someone/bot", "digest.yml", ["0 7 * * 1"])
    runs = next(c for c in found if c["type"] == "folder_runs")
    assert runs["runs"] == 3 and "add folder-runs exporter-out" in runs["add"]


def test_add_folder_runs_then_check(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FLOWHAUS_AUTOMATIONS_DIR", str(tmp_path / "automations"))
    make_runs(tmp_path / "out")
    assert cli.main(["add", "folder-runs", "exporter", "--path", str(tmp_path / "out")]) == 0
    capsys.readouterr()
    assert cli.main(["--json", "check", "exporter"]) == 1  # TODOs left for the agent to fill in
    report = json.loads(capsys.readouterr().out)["automations"][0]
    assert any("TODO" in p for p in report["problems"]) and report["runs"] == 3
    cfg = tmp_path / "automations" / "exporter" / "automation.yaml"
    cfg.write_text(cfg.read_text().replace("TODO: ", ""))
    assert cli.main(["check", "exporter"]) == 0


def test_doctor_reports_json(capsys):
    cli.main(["doctor", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert {c["check"] for c in data["checks"]} >= {"python", "node", "GitHub CLI"}


def test_add_github_refuses_an_unreadable_repo(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setenv("FLOWHAUS_AUTOMATIONS_DIR", str(tmp_path / "automations"))
    with pytest.raises(SystemExit, match="Couldn't read"):
        cli.main(["add", "github-actions", "my-bot", "--repo", "someone/nothing", "--workflow", "a.yml"])
    assert not (tmp_path / "automations" / "my-bot").exists()


def test_scan_never_prints_tokens_from_crontab(tmp_path, monkeypatch, capsys):
    lines = ("SLACK_WEBHOOK=https://hooks.slack.com/services/T0/B0/SECRET\n"
             "0 7 * * * curl https://hooks.example.com/run?token=tok_SECRET\n"
             "@daily /usr/bin/python3 /home/me/jobs/export.py --api-key=SECRET\n")
    monkeypatch.setattr(cli, "run_cmd", lambda *a, **k: (0, lines) if a[0] == "crontab" else (1, ""))
    monkeypatch.setattr(cli.Path, "home", lambda: tmp_path)
    cli.main(["scan", str(tmp_path), "--json"])
    printed = capsys.readouterr().out
    assert "SECRET" not in printed and "/home/me/jobs/export.py" in printed and "@daily" in printed
