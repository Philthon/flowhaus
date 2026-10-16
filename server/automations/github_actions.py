"""Generic adapter for a GitHub Actions workflow (read through the `gh` CLI).

Without any map in automation.yaml it shows the workflow's own jobs and steps with their real
status per run. With a plain-English map, each step can take its status from a workflow step
(`github_step`) and/or derive counts from the run log with small regex rules:

    in:   {sum: '^Sources: (\\d+)'}            # sum of capture group 1 over all matching lines
    out:  {count: '✓ fetched'}                 # number of matching lines
    skip: [{count: '✗ \\S+ (?P<reason>\\w+)', reason_map: {PaymentRequiredError: 'Out of credits'}},
           {sum: 'folded (\\d+)', reason: 'Duplicate'},
           {json_counts: 'dropped: (\\{.*\\})'}]  # a {reason: n} dict printed in the log
    rows: '✓ fetched (?P<page>\\S+)'           # named groups become a table of what the step did
    fail: {pattern: '✗ all .* failed', message: 'Nothing could be fetched for {sections}'}

`log.section` (a regex with a named group `section`) marks log blocks, e.g. one per city;
rows get a `section` column and fail messages can name the sections.

Only `gh run list`, `gh run view`, `gh workflow list` and `gh api` (GET) are used to read.
The single write is `gh workflow enable/disable`, and only if `github.allow_toggle: true`.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from server.automations.base import (Automation, as_int, empty_node, group_results, render_summary,  # noqa: F401
                                     run_totals, slugify)

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state" / "automations"
LINE = re.compile(r"^(?P<job>[^\t]*)\t(?P<step>[^\t]*)\t(?:﻿)?\d{4}-\d\d-\d\dT[\d:.]+Z ?(?P<text>.*)$")
BOILERPLATE = re.compile(r"^(Set up job|Complete job|Post .*|Run actions/(checkout|setup-\w+|cache)@.*|Checkout.*)$", re.I)
RUN_ID = re.compile(r"^\d{1,20}$")
# colour codes some actions print, as real escapes or as the literal text "^[[36m"
ANSI = re.compile(r"(?:\x1b|\^\[)\[[0-9;]*[A-Za-z]")


def _job_failure(jobs: list[dict]) -> str:
    """A plain reason for a failed run that no step explains."""
    conclusions = {j.get("conclusion") for j in jobs}
    if jobs and not any(j.get("steps") for j in jobs):
        return "GitHub didn't start this run: no machine picked it up, so nothing ran. It usually works on the next run."
    if "timed_out" in conclusions:
        return "The run took too long and GitHub stopped it."
    if "cancelled" in conclusions:
        return "The run was cancelled on GitHub before it finished."
    return "The run failed. Open it on GitHub for details."


def log_lines(text: str) -> list[dict]:
    """A `gh run view --log` dump as [{job, step, text}], colour codes removed (rules match the clean text)."""
    rows = []
    for line in text.splitlines():
        if m := LINE.match(line):
            rows.append({"job": m.group("job"), "step": m.group("step"), "text": ANSI.sub("", m.group("text"))})
    return rows


class GhError(RuntimeError):
    pass


def gh(*args: str, timeout: int = 60) -> str:
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise GhError("The GitHub CLI (gh) is not installed. Install it and run `gh auth login`.") from exc
    except subprocess.TimeoutExpired as exc:
        raise GhError("GitHub didn't answer in time.") from exc
    if proc.returncode != 0:
        msg = (proc.stderr or "gh failed").strip().splitlines()
        raise GhError(msg[-1][:300] if msg else "gh failed")
    return proc.stdout


def local_time(iso: str | None) -> str | None:
    if not iso:
        return None
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().replace(tzinfo=None).isoformat(timespec="seconds")


DAYS = ["Sundays", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays"]


def _cron_days(field: str) -> set[int]:
    days: set[int] = set()
    for chunk in field.split(","):
        if chunk == "*":
            days |= set(range(7))
        elif "-" in chunk and all(x.isdigit() for x in chunk.split("-")):
            a, b = (int(x) for x in chunk.split("-"))
            days |= {d % 7 for d in range(a, b + 1)}
        elif chunk.isdigit():
            days.add(int(chunk) % 7)
    return days


def describe_cron(cron: str) -> str:
    """'0 13 * * 1,3,5' -> 'Mondays, Wednesdays and Fridays at 13:00 UTC'. Falls back to the raw cron."""
    parts = cron.split()
    if len(parts) != 5 or parts[2] != "*" or parts[3] != "*":
        return f"On schedule ({cron} UTC)"
    minute, hour, dow = parts[0], parts[1], parts[4]
    days = _cron_days(dow)
    names = [DAYS[d] for d in sorted(days)]
    when = ("Every day" if days == set(range(7)) else "Weekdays" if days == {1, 2, 3, 4, 5}
            else ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0] if names else None)
    if when is None:
        return f"On schedule ({cron} UTC)"
    if minute.isdigit() and hour == "*":
        return f"Every hour at :{int(minute):02d}" + ("" if when == "Every day" else f", {when.lower()}")
    if minute.startswith("*/") and hour == "*":
        return f"Every {minute[2:]} minutes" + ("" if when == "Every day" else f", {when.lower()}")
    if minute.isdigit() and hour.isdigit():
        return f"{when} at {int(hour):02d}:{int(minute):02d} UTC"
    return f"On schedule ({cron} UTC)"


def next_cron_run(cron: str, now: datetime | None = None) -> datetime | None:
    """Next start for a 'minute hour * * days' cron (UTC), in local time. Hourly ('M * * * *') works too."""
    parts = cron.split()
    if len(parts) == 5 and parts[0].isdigit() and parts[1] == "*" and parts[2] == parts[3] == "*":
        now = now or datetime.now(timezone.utc)
        days = _cron_days(parts[4])
        t = now.replace(minute=int(parts[0]), second=0, microsecond=0)
        for i in range(24 * 8):
            cand = t + timedelta(hours=i)
            if cand > now and (cand.isoweekday() % 7) in days:
                return cand.astimezone().replace(tzinfo=None)
        return None
    if len(parts) != 5 or not parts[0].isdigit() or not parts[1].isdigit() or parts[2] != "*" or parts[3] != "*":
        return None
    minute, hour, dows = int(parts[0]), int(parts[1]), parts[4]
    days: set[int] = set()
    for chunk in dows.split(","):
        if chunk == "*":
            days |= set(range(7))
        elif "-" in chunk and all(x.isdigit() for x in chunk.split("-")):
            a, b = (int(x) for x in chunk.split("-"))
            days |= {d % 7 for d in range(a, b + 1)}
        elif chunk.isdigit():
            days.add(int(chunk) % 7)
    now = now or datetime.now(timezone.utc)
    for i in range(8):
        day = (now + timedelta(days=i)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if (day.isoweekday() % 7) in days and day > now:
            return day.astimezone().replace(tzinfo=None)
    return None


def last_cron_run(cron: str, now: datetime | None = None) -> datetime | None:
    """The most recent time (UTC) a 'minute hour|* * * days' cron should have started, or None if unsupported."""
    parts = cron.split()
    if len(parts) != 5 or not parts[0].isdigit() or parts[2] != "*" or parts[3] != "*" or not (parts[1].isdigit() or parts[1] == "*"):
        return None
    now = now or datetime.now(timezone.utc)
    days = _cron_days(parts[4])
    for i in range(24 * 8):
        cand = (now - timedelta(hours=i)).replace(minute=int(parts[0]), second=0, microsecond=0)
        if cand <= now and (parts[1] == "*" or cand.hour == int(parts[1])) and (cand.isoweekday() % 7) in days:
            return cand
    return None


def overdue_message(cron: str, last_started_local: str | None, now: datetime | None = None,
                    grace: timedelta = timedelta(hours=2)) -> str | None:
    """'Didn't run when expected' — the failure you'd otherwise never see. GitHub can start scheduled runs late,
    and turns schedules off in repos without activity for 60 days."""
    now = now or datetime.now(timezone.utc)
    expected = last_cron_run(cron, now - grace)
    if expected is None:
        return None
    expected_local = expected.astimezone().replace(tzinfo=None)
    if last_started_local and datetime.fromisoformat(last_started_local) >= expected_local - timedelta(minutes=10):
        return None
    return (f"Didn't run when expected ({expected_local:%a} {expected_local.day} {expected_local:%b, %H:%M}). "
            "GitHub may have skipped or delayed it; it also turns schedules off in repos with no activity for 60 days.")


# --------------------------------------------------------------------------- log rules


class Rule:
    """One `in`/`out`/`skip` rule: count or sum over matching log lines."""

    def __init__(self, spec: Any):
        if isinstance(spec, str):
            spec = {"count": spec}
        self.mode = next((m for m in ("count", "sum", "json_counts") if m in spec), None)
        if not self.mode:
            raise ValueError(f"A rule needs one of count/sum/json_counts: {spec}")
        self.pattern = re.compile(spec[self.mode])
        self.group = spec.get("group", 1)
        self.reason = spec.get("reason")
        self.reason_map = spec.get("reason_map") or {}

    def apply(self, text: str) -> tuple[int, Counter] | None:
        m = self.pattern.search(text)
        if not m:
            return None
        reasons: Counter = Counter()
        if self.mode == "json_counts":
            raw = m.group(self.group)
            try:
                data = json.loads(raw.replace("'", '"'))
            except json.JSONDecodeError:
                data = {}
            for k, v in data.items():
                n = as_int(v) or 0
                reasons[self._reason(str(k))] += n
            return sum(reasons.values()), reasons
        n = 1 if self.mode == "count" else (as_int(m.group(self.group)) or 0)
        if "reason" in m.groupdict() and m.group("reason"):
            reasons[self._reason(m.group("reason"))] += n
        elif self.reason:
            reasons[self.reason.format(**m.groupdict())] += n
        return n, reasons

    def _reason(self, raw: str) -> str:
        text = self.reason_map.get(raw, raw)
        return text[:1].upper() + text[1:]


class StepRules:
    def __init__(self, step: dict):
        self.inn = Rule(step["in"]) if step.get("in") else None
        self.out = Rule(step["out"]) if step.get("out") else None
        skips = step.get("skip") or []
        self.skips = [Rule(s) for s in (skips if isinstance(skips, list) else [skips])]
        self.rows = re.compile(step["rows"]) if step.get("rows") else None
        fail = step.get("fail")
        self.fail = re.compile(fail["pattern"] if isinstance(fail, dict) else fail) if fail else None
        self.fail_message = fail.get("message") if isinstance(fail, dict) else None
        self.fail_kind = fail.get("kind") if isinstance(fail, dict) else None  # e.g. auth, transient (nextstep.KINDS)

    @property
    def any(self) -> bool:
        return bool(self.inn or self.out or self.skips or self.rows or self.fail)


def apply_rules(lines: list[str], steps: list[dict], section_re: re.Pattern | None, section_end: re.Pattern | None) -> dict:
    """Run every step's rules over the log once. Returns per-step tallies."""
    rules = {s["id"]: StepRules(s) for s in steps}
    tally = {sid: {"in": None, "out": None, "skip": Counter(), "rows": [], "fail_sections": [], "fail_texts": [], "matched": False}
             for sid in rules}
    section = None
    for text in lines:
        if section_re and (m := section_re.search(text)):
            section = m.groupdict().get("section") or m.group(0)
            continue
        if section_end and section_end.search(text):
            section = None
        for sid, r in rules.items():
            t = tally[sid]
            for key, rule in (("in", r.inn), ("out", r.out)):
                if rule and (hit := rule.apply(text)):
                    t[key] = (t[key] or 0) + hit[0]
                    t["matched"] = True
            for rule in r.skips:
                if hit := rule.apply(text):
                    t["skip"].update(hit[1] if hit[1] else Counter({"Skipped": hit[0]}))
                    t["matched"] = True
            if r.rows and (m := r.rows.search(text)):
                row = {"section": section} if section else {}
                row.update({k: v for k, v in m.groupdict().items()})
                t["rows"].append(row)
                t["matched"] = True
            if r.fail and r.fail.search(text):
                t["fail_sections"].append(section or "")
                t["fail_texts"].append(text.strip())
    for sid, r in rules.items():
        tally[sid]["fail_message"] = r.fail_message
        tally[sid]["fail_kind"] = r.fail_kind
    return tally


# --------------------------------------------------------------------------- adapter


class GitHubActionsAutomation(Automation):
    extra_keys = {"github", "log"}
    step_keys = {"github_step", "in", "out", "skip", "rows", "fail"}
    def __init__(self, config: dict, folder: Path):
        super().__init__(config, folder)
        gh_cfg = config.get("github") or {}
        for key in ("repo", "workflow"):
            if not gh_cfg.get(key):
                raise ValueError(f"github.{key} is required")
        self.repo: str = gh_cfg["repo"]
        self.workflow: str = gh_cfg["workflow"]
        for step in self.steps:
            try:
                StepRules(step)
            except (re.error, ValueError) as exc:
                raise ValueError(f"step '{step['id']}' has an invalid rule: {exc}") from exc
        self.allow_toggle: bool = bool(gh_cfg.get("allow_toggle"))
        self.run_limit: int = int(gh_cfg.get("runs", 25))
        log = config.get("log") or {}
        self.section_re = re.compile(log["section"]) if log.get("section") else None
        self.section_end = re.compile(log.get("section_end", r"^##\[endgroup\]")) if log.get("section") else None
        self.cache_dir = STATE_DIR / slugify(self.id)
        self._lock = threading.Lock()
        self._list: tuple[float, list] = (0.0, [])
        self._runs: dict[str, dict] = {}
        self._state: tuple[float, str | None] = (0.0, None)
        self._cron: tuple[float, str | None] = (0.0, None)
        self._prefetching: set[str] = set()
        self._refreshing = False
        self._checked_at: str | None = None  # last successful read from GitHub
        self._error: str | None = None
        self.uses_log = any(StepRules(s).any for s in self.steps)
        if not self.steps:
            self._auto_map()

    # ---- map -----------------------------------------------------------------------------

    def _auto_map(self) -> None:
        """No map configured: use the workflow's own jobs and steps from the latest run."""
        try:
            runs = self._gh_list()
            latest = next((r for r in runs if r["status"] == "completed"), None)
            jobs = self._jobs(str(latest["databaseId"])) if latest else []
        except GhError:
            jobs = []
        multi = len(jobs) > 1
        for job in jobs:
            if multi:
                self.groups.append({"id": slugify(job["name"]), "label": job["name"], "description": f"Job “{job['name']}”", "parent": None})
            for st in job.get("steps") or []:
                if BOILERPLATE.match(st["name"]):
                    continue
                self.steps.append({"id": slugify(f"{job['name']}-{st['name']}") if multi else slugify(st["name"]),
                                   "label": st["name"], "description": f"Workflow step “{st['name']}”.",
                                   "group": slugify(job["name"]) if multi else None, "app": "GitHub Actions",
                                   "github_step": f"{job['name']}/{st['name']}"})

    def source_label(self) -> str:
        return "GitHub Actions"

    def meta(self) -> dict:
        m = super().meta()
        state = self.workflow_state()
        enabled = state in (None, "active")
        cron = self.cron()
        nxt = next_cron_run(cron) if cron else None
        trigger = self.config.get("trigger") or {}
        if not trigger.get("label"):
            trigger = {"type": "schedule" if cron else "manual",
                       "label": f"{describe_cron(cron)} on GitHub Actions" if cron else "Started on GitHub Actions"}
        m.update({
            "trigger": {"app": "GitHub Actions", **trigger},
            "enabled": enabled,
            "can_toggle": self.allow_toggle and state is not None,
            "state_label": "On in GitHub Actions" if state == "active" else "Turned off in GitHub Actions" if state else "On (GitHub didn't answer)",
            "next_run": (f"{nxt:%a} {nxt.day} {nxt:%b, %H:%M} (your time)" if nxt else self.config.get("next_run") or "When GitHub starts it")
                        if enabled else "None: turned off in GitHub Actions",
            "overdue": overdue_message(cron, (self.list_runs() or [{}])[0].get("started_at")) if enabled and cron else None,
            "toggle_off_hint": "It won't run on its schedule until you turn it back on.",
            "toggle_on_hint": "GitHub will run it again on its schedule.",
            "source": {"label": "GitHub Actions", "repo": self.repo, "workflow": self.workflow, "path": str(self.local_path() or "")},
            "run_url": f"https://github.com/{self.repo}/actions/runs/{{run_id}}",
        })
        return m

    # ---- GitHub reads ----------------------------------------------------------------------

    def _gh_list(self) -> list[dict]:
        return json.loads(gh("run", "list", "-R", self.repo, "--workflow", self.workflow, "--limit", str(self.run_limit),
                             "--json", "databaseId,status,conclusion,createdAt,updatedAt,event"))

    def _jobs(self, run_id: str) -> list[dict]:
        path = self.cache_dir / f"{run_id}.jobs.json"
        if path.exists():
            return json.loads(path.read_text())
        jobs = json.loads(gh("run", "view", run_id, "-R", self.repo, "--json", "jobs")).get("jobs") or []
        if all(j.get("status") == "completed" for j in jobs):
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(jobs))
        return jobs

    def raw_log(self, run_id: str, finished: bool = True) -> str:
        """The run's full log (cached once the run is finished)."""
        path = self.cache_dir / f"{run_id}.log"
        if path.exists():
            return path.read_text()
        text = self._fetch_log(run_id)
        if finished:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return text

    def _fetch_log(self, run_id: str) -> str:
        try:
            return gh("run", "view", run_id, "-R", self.repo, "--log", timeout=180)
        except GhError as exc:
            if "log not found" in str(exc).lower():
                return ""  # e.g. GitHub never started the run: nothing was logged
            raise

    def _log(self, run_id: str, finished: bool) -> list[str]:
        return [r["text"] for r in log_lines(self.raw_log(run_id, finished))]

    def workflow_state(self) -> str | None:
        if time.time() - self._state[0] < 300:
            return self._state[1]
        if self._state[0]:  # known: refresh in the background, answer now
            self._state = (time.time() - 240, self._state[1])  # don't start a second refresh for a minute
            threading.Thread(target=self._read_state, daemon=True).start()
            return self._state[1]
        return self._read_state()

    def _read_state(self) -> str | None:
        try:
            rows = json.loads(gh("workflow", "list", "-R", self.repo, "--all", "--json", "path,state"))
            state = next((r["state"] for r in rows if r["path"].endswith(self.workflow)), None)
        except (GhError, json.JSONDecodeError):
            state = self._state[1]
        self._state = (time.time(), state)
        return state

    def cron(self) -> str | None:
        if time.time() - self._cron[0] < 3600:
            return self._cron[1]
        text = None
        lp = self.local_path()
        local = lp / ".github" / "workflows" / self.workflow if lp else None
        if local and local.exists():
            text = local.read_text()
        else:
            try:
                data = json.loads(gh("api", f"repos/{self.repo}/contents/.github/workflows/{self.workflow}"))
                text = base64.b64decode(data.get("content", "")).decode(errors="replace") if isinstance(data, dict) else None
            except (GhError, json.JSONDecodeError, ValueError, TypeError):
                text = None
        m = re.search(r"cron:\s*['\"]([^'\"]+)['\"]", text or "")
        self._cron = (time.time(), m.group(1) if m else None)
        return self._cron[1]

    # ---- runs --------------------------------------------------------------------------

    def list_runs(self) -> list[dict]:
        """Recent runs. After the first read, pages never wait for GitHub: a stale list is returned at once and
        refreshed in the background (the UI shows when it was read)."""
        with self._lock:
            age, have = time.time() - self._list[0], bool(self._list[0])
            if age < 60:
                return self._list[1]
            if have and not self._refreshing:
                self._refreshing = True
                threading.Thread(target=self._refresh_list, daemon=True).start()
            if have:
                return self._list[1]
        return self._refresh_list()

    def refresh(self) -> None:
        with self._lock:
            if self._refreshing:
                return  # a read is already under way
            self._refreshing = True
        self._refresh_list()

    def _refresh_list(self) -> list[dict]:
        try:
            return self._read_list()
        finally:
            self._refreshing = False

    def _read_list(self) -> list[dict]:
        try:
            raw = self._gh_list()
        except GhError as exc:
            self._error = str(exc)
            with self._lock:
                self._list = (time.time() - 45, self._list[1])  # try again in ~15 s, not on every request
            return self._list[1]
        self._error, self._checked_at = None, datetime.now().isoformat(timespec="seconds")
        out = []
        for r in raw:
            status = "running" if r["status"] != "completed" else "success" if r["conclusion"] == "success" else "failed"
            run = {"run_id": str(r["databaseId"]), "flow_id": self.id, "status": status,
                   "started_at": local_time(r["createdAt"]), "finished_at": local_time(r["updatedAt"]) if status != "running" else None,
                   "input_file": "GitHub Actions", "trigger": "schedule" if r["event"] == "schedule" else "manual",
                   "summary": None, "error": None}
            if cached := self._runs.get(run["run_id"]) or self._from_cache(run):
                run["summary"], run["error"] = cached.get("summary"), cached.get("error")
            out.append(run)
        with self._lock:
            self._list = (time.time(), out)
        self._prefetch([r["run_id"] for r in out if r["status"] != "running"])
        return out

    def freshness(self) -> dict:
        self.list_runs()
        return {"source": "GitHub Actions", "checked_at": self._checked_at, "error": self._error}

    def _summary_for(self, run_id: str) -> dict | None:
        return next((r for r in self.list_runs() if r["run_id"] == run_id), None)

    def _from_cache(self, summary: dict) -> dict | None:
        """Build a run from cached files only (no network)."""
        rid = summary["run_id"]
        if rid in self._runs:
            return self._runs[rid]
        jobs_path, log_path = self.cache_dir / f"{rid}.jobs.json", self.cache_dir / f"{rid}.log"
        if not jobs_path.exists() or (self.uses_log and not log_path.exists()):
            return None
        try:
            run = self._build(summary, json.loads(jobs_path.read_text()), self._log(rid, True) if self.uses_log else [])
        except Exception:
            return None
        self._runs[rid] = run
        return run

    def cached_run(self, run_id: str) -> dict | None:
        summary = next((r for r in self._list[1] if r["run_id"] == run_id), None)
        return self._from_cache({**summary, "summary": None, "error": None}) if summary else None

    def _prefetch(self, run_ids: list[str]) -> None:
        todo = [r for r in run_ids if r not in self._runs and r not in self._prefetching
                and not ((self.cache_dir / f"{r}.jobs.json").exists() and (not self.uses_log or (self.cache_dir / f"{r}.log").exists()))]
        if not todo:
            return
        self._prefetching.update(todo)

        def work():
            for rid in todo:
                try:
                    self._jobs(rid)
                    if self.uses_log:
                        self._log(rid, True)
                except Exception:
                    pass
                self._prefetching.discard(rid)

        threading.Thread(target=work, daemon=True).start()

    def get_run(self, run_id: str) -> dict | None:
        if not RUN_ID.match(run_id):
            return None
        summary = self._summary_for(run_id)
        if summary is None:
            return None
        if run_id in self._runs:
            return self._runs[run_id]
        finished = summary["status"] != "running"
        try:
            jobs = self._jobs(run_id)
            lines = self._log(run_id, finished) if self.uses_log else []
        except GhError as exc:
            nodes = {s["id"]: empty_node(s) for s in self.steps}
            return {**summary, "nodes": nodes, "groups": {}, "contacts": [],
                    "error": {"node_id": None, "message": f"Could not read this run from GitHub: {exc}"}}
        run = self._build({**summary, "summary": None, "error": None}, jobs, lines)
        if finished:
            self._runs[run_id] = run
        return run

    def _build(self, summary: dict, jobs: list[dict], lines: list[str]) -> dict:
        tally = apply_rules(lines, self.steps, self.section_re, self.section_end) if lines else {}
        gh_steps = {}
        for job in jobs:
            for st in job.get("steps") or []:
                gh_steps[f"{job['name']}/{st['name']}"] = st
                gh_steps.setdefault(st["name"], st)
        nodes, first_failed = {}, None
        t0 = summary.get("started_at")
        for step in self.steps:
            n = empty_node(step)
            n["unit"] = step.get("unit")
            log = []
            gst = gh_steps.get(step.get("github_step") or "")
            if gst:
                n["status"] = {"success": "success", "failure": "failed", "skipped": "not_run", "cancelled": "failed"}.get(
                    gst.get("conclusion") or "", "running" if gst.get("status") == "in_progress" else "not_run")
                if gst.get("startedAt") and gst.get("completedAt"):
                    n["duration_ms"] = int((datetime.fromisoformat(gst["completedAt"].replace("Z", "+00:00"))
                                            - datetime.fromisoformat(gst["startedAt"].replace("Z", "+00:00"))).total_seconds() * 1000)
            t = tally.get(step["id"])
            if t and t["matched"]:
                n["status"] = "success" if n["status"] in ("not_run", "success") else n["status"]
                rules = StepRules(step)
                # a rule that exists but never matched means zero, not unknown
                n["rows_in"] = t["in"] if t["in"] is not None else (0 if rules.inn else None)
                n["rows_out"] = t["out"] if t["out"] is not None else (0 if rules.out else None)
                skipped = sum(t["skip"].values())
                n["rows_rejected"] = skipped
                n["reject_reasons"] = dict(t["skip"].most_common())
                if n["rows_in"] is None and n["rows_out"] is not None:
                    n["rows_in"] = n["rows_out"] + skipped
                if n["rows_out"] is None and n["rows_in"] is not None:
                    n["rows_out"] = max(0, n["rows_in"] - skipped)
                n["sample_out"] = [{"_row_id": i + 1, **r} for i, r in enumerate(t["rows"][:200])]
                log.append(("info", f"{n['rows_in']} in → {n['rows_out']} out" + (f", {skipped} skipped" if skipped else "")))
                for reason, k in t["skip"].most_common(5):
                    log.append(("warn", f"Skipped {k}: {reason}"))
            if t and t["fail_sections"]:
                n["status"] = "failed"
                sections = ", ".join(dict.fromkeys(s for s in t["fail_sections"] if s)) or ""
                top = t["skip"].most_common(1)[0][0] if t["skip"] else ""
                n_sections = len([x for x in dict.fromkeys(t["fail_sections"]) if x])
                msg = (t["fail_message"] or "{line}").format(
                    sections=sections, line=t["fail_texts"][0], count=len(t["fail_sections"]), top_reason=top,
                    these="That one was" if n_sections == 1 else "Those were")
                n["error"] = {"message": msg, "type": "RunError", "traceback": "\n".join(t["fail_texts"][:20]),
                              **({"kind": t["fail_kind"]} if t.get("fail_kind") else {})}
                log.append(("error", msg))
            elif n["status"] == "failed" and gst:
                errs = [l for l in lines if l.startswith("##[error]")]
                msg = errs[0].removeprefix("##[error]") if errs else f"The workflow step “{gst['name']}” failed on GitHub Actions."
                n["error"] = {"message": msg, "type": "RunError", "traceback": "\n".join(errs[:20])}
            n["log"] = [{"t": t0, "level": lvl, "text": txt} for lvl, txt in log]
            if n["status"] == "failed" and first_failed is None:
                first_failed = step["id"]
            nodes[step["id"]] = n

        run = {**summary, "nodes": nodes, "contacts": [], "groups": group_results(self.groups, self.steps, nodes)}
        if summary["status"] == "failed":
            msg = (nodes[first_failed]["error"] or {}).get("message") if first_failed else None
            kind = (nodes[first_failed]["error"] or {}).get("kind") if first_failed else None
            run["error"] = {"node_id": first_failed, "message": msg or _job_failure(jobs), **({"kind": kind} if kind else {})}
        io = self.config.get("io") or {}
        with_rows = [s["id"] for s in self.steps if nodes[s["id"]]["sample_out"]]
        in_step = io.get("input_step") or (with_rows[0] if with_rows else None)
        out_step = io.get("output_step") or (with_rows[-1] if with_rows else None)
        run["input_items"] = nodes[in_step]["sample_out"] if in_step else []
        run["output_items"] = (nodes[out_step]["sample_out"] or None) if out_step and summary["status"] == "success" else None
        run["summary"] = run_totals(self.steps, nodes, self.config.get("io"))
        if template := self.config.get("summary"):
            text = render_summary(template, nodes)
            if text:
                run["summary"]["text"] = text
        return run

    def set_enabled(self, enabled: bool) -> None:
        if not self.allow_toggle:
            raise ValueError("Switching this workflow is turned off (set github.allow_toggle: true to allow it).")
        gh("workflow", "enable" if enabled else "disable", self.workflow, "-R", self.repo)
        self._state = (0.0, None)
        state = self._read_state()
        if state is None:
            raise ValueError("GitHub didn't confirm the change; check the workflow on GitHub.")
        if (state == "active") != enabled:
            raise ValueError(f"GitHub still reports the workflow as {state.replace('_', ' ')}.")

    def check(self) -> list[str]:
        problems = super().check()
        from server.automations.base import unknown_keys

        problems += unknown_keys("github", self.config.get("github") or {}, {"repo", "workflow", "allow_toggle", "runs"})
        problems += unknown_keys("log", self.config.get("log") or {}, {"section", "section_end"})
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", self.repo):
            problems.append(f"github.repo should look like owner/name, got '{self.repo}'")
        for s in self.steps:
            try:
                StepRules(s)
            except (re.error, ValueError) as exc:
                problems.append(f"Step '{s['id']}' has an invalid rule: {exc}")
        return problems
