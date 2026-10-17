"""Proposed code changes to a connected automation, opened as a pull request only after the user approves.

How it stays safe:
- The chat never edits the user's own folder. A change gets its own clone in state/changes/<id>/repo,
  checked out from the repo's base branch on GitHub.
- The chat can only edit source files in that clone (the same file rules as reading), and it can't run anything.
- Opening the pull request (commit, push, `gh pr create`) happens only through the API endpoint the UI calls
  when the user clicks "Open pull request". The chat has no tool for it.
- git hooks are switched off for every git command, so files the chat wrote can't run on commit or push.

Opt in per automation in automation.yaml:   pull_requests: {enabled: true, base: main, repo: owner/name}
(base defaults to the repo's default branch; repo to github.repo or local_path's GitHub remote)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from server import runtime

CHANGES_DIR = runtime.ROOT / "state" / "changes"
CHANGE_ID = re.compile(r"^[a-z0-9]{12}$")
NO_HOOKS = ["-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false"]
# Files whose changes run with the repository's secrets or on other people's machines: flagged for the user.
SENSITIVE = re.compile(r"^(\.github/|\.gitlab-ci|\.circleci/|Dockerfile|docker-compose|Makefile$|package\.json$|"
                       r"pyproject\.toml$|setup\.py$|requirements.*\.txt$|\.husky/|\.pre-commit)", re.I)


class ChangeError(Exception):
    pass


def _git(cwd: Path, *args: str, timeout: int = 120) -> str:
    try:
        p = subprocess.run(["git", *NO_HOOKS, *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ChangeError(f"git failed: {exc}") from exc
    if p.returncode != 0:
        raise ChangeError((p.stderr or p.stdout or "git failed").strip().splitlines()[-1][:300])
    return p.stdout


def _path(change_id: str) -> Path:
    if not CHANGE_ID.match(change_id):
        raise KeyError(change_id)
    return CHANGES_DIR / change_id


def _save(meta: dict) -> dict:
    (_path(meta["id"]) / "change.json").write_text(json.dumps(meta, indent=2))
    return meta


def get(change_id: str) -> dict:
    try:
        return json.loads((_path(change_id) / "change.json").read_text())
    except FileNotFoundError as exc:
        raise KeyError(change_id) from exc


def list_changes(flow_id: str | None = None) -> list[dict]:
    out = []
    for f in sorted(CHANGES_DIR.glob("*/change.json"), reverse=True) if CHANGES_DIR.is_dir() else []:
        meta = json.loads(f.read_text())
        if flow_id is None or meta["flow_id"] == flow_id:
            out.append(meta)
    return sorted(out, key=lambda m: m["created_at"], reverse=True)


def workspace(change_id: str) -> Path:
    return _path(change_id) / "repo"


def open_workspaces() -> list[Path]:
    """Clones the chat may read and edit: changes that are still being written or waiting for review."""
    return [workspace(m["id"]) for m in list_changes() if m["status"] in ("editing", "proposed")]


def settings(adapter) -> dict | None:
    """The automation's pull request settings, or None if changes are off for it."""
    pr = adapter.config.get("pull_requests") or {}
    return pr if pr.get("enabled") else None


def repo_of(adapter) -> str | None:
    if repo := (adapter.config.get("pull_requests") or {}).get("repo") or (adapter.config.get("github") or {}).get("repo"):
        return repo
    lp = adapter.local_path()
    if lp and (lp / ".git").exists():
        try:
            url = _git(lp, "remote", "get-url", "origin").strip()
        except ChangeError:
            return None
        m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(\.git)?$", url)
        return m.group(1) if m else None
    return None


def start(adapter, title: str) -> dict:
    """A fresh clone of the automation's repo for the chat to edit."""
    pr = settings(adapter)
    if pr is None:
        raise ChangeError("Changes are off for this automation. To allow them, add `pull_requests: {enabled: true}` "
                          "to its automation.yaml. You'll still approve every pull request.")
    repo = repo_of(adapter)
    if not repo:
        raise ChangeError("Couldn't tell which GitHub repository holds this automation's code "
                          "(set github.repo, or a local_path with a GitHub remote).")
    change_id = uuid.uuid4().hex[:12]
    root = _path(change_id)
    dest = root / "repo"
    root.mkdir(parents=True)
    base = pr.get("base")
    lp = adapter.local_path()
    try:
        if lp and (lp / ".git").exists():  # fast: clone from the local copy, then point at GitHub for the base branch
            _git(root, "clone", "--quiet", "--no-checkout", str(lp), str(dest))
            local_url = _git(lp, "remote", "get-url", "origin").strip()  # keep the user's SSH or HTTPS setup for push
            _git(dest, "remote", "set-url", "origin",
                 local_url if repo.lower() in local_url.lower() else f"https://github.com/{repo}.git")
        else:
            _git(root, "clone", "--quiet", "--no-checkout", "--depth", "50", f"https://github.com/{repo}.git", str(dest),
                 timeout=300)
        if not base:
            head = _git(dest, "ls-remote", "--symref", "origin", "HEAD")
            m = re.search(r"refs/heads/(\S+)\s+HEAD", head)
            base = m.group(1) if m else "main"
        _git(dest, "fetch", "--quiet", "origin", base, timeout=300)
        branch = f"flowhaus/{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40] or 'change'}-{change_id[:6]}"
        _git(dest, "checkout", "--quiet", "-b", branch, "FETCH_HEAD")
    except ChangeError:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return _save({"id": change_id, "flow_id": adapter.id, "repo": repo, "base": base, "branch": branch,
                  "title": title.strip()[:120], "summary": "", "status": "editing", "diff": "", "files": [],
                  "warnings": [], "pr_url": None, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")})


def current_diff(change_id: str) -> tuple[str, list[str]]:
    """(diff, changed files) of the work so far."""
    dest = workspace(change_id)
    _git(dest, "add", "-A")
    diff = _git(dest, "diff", "--cached", "--no-color", "--no-ext-diff")
    files = [f for f in _git(dest, "diff", "--cached", "--name-only").splitlines() if f]
    return diff, files


def propose(change_id: str, summary: str, impact: str = "", review: dict | None = None) -> dict:
    """Freeze the edits as a proposal: the diff the user reviews before anything leaves this computer."""
    meta = get(change_id)
    if meta["status"] != "editing":
        raise ChangeError(f"This change is already {meta['status']}.")
    diff, files = current_diff(change_id)
    if not files:
        raise ChangeError("No files were changed yet. Edit files in the change folder first.")
    warnings = [f"{f} runs with your repository's secrets or on other machines (CI, build or install files): "
                "review it carefully." for f in files if SENSITIVE.search(f)]
    meta.update(status="proposed", summary=summary.strip()[:4000], impact=impact.strip()[:4000], diff=diff[:400_000],
                files=files, warnings=warnings, review=review or {})
    meta["gate"] = gate(meta)
    return _save(meta)


def gate(meta: dict) -> list[dict]:
    """What the review found, for you to check before the pull request opens, with a priority each (P0 to P3).

    Only P0 must be confirmed before it can open: the change touches files that run with your repository's secrets
    or on other machines (CI, workflows, build, install). Everything else is a suggestion: worth a look, not a wall.
    The points come from the harness, not from the chat that wrote the change. Each: {id, priority, text}.
    """
    r = meta.get("review") or {}
    items = [{"id": f"sensitive:{i}", "priority": "P0", "text": w} for i, w in enumerate(meta.get("warnings") or [])]
    for x in r.get("log_lines") or []:
        items.append({"id": f"log_line:{x.get('step')}:{x.get('line')}", "priority": "P1",
                      "text": f"It edits a log line the map counts for “{x.get('label')}”: update the counting rule too, "
                              "or that step will look empty."})
    if r.get("downstream"):
        items.append({"id": "downstream", "priority": "P2", "text": "Check what changes for the steps after it: "
                      + " → ".join(d["label"] for d in r["downstream"][:8]) + "."})
    for x in r.get("repeats") or []:
        items.append({"id": f"repeat:{x.get('file')}:{x.get('same_as')}", "priority": "P2",
                      "text": f"{x.get('file')} repeats code that already exists in {x.get('same_as')}: consider reusing it."})
    if r.get("unmapped_files"):
        items.append({"id": "unmapped", "priority": "P2", "text": "It changes files no step points at "
                      f"({', '.join(r['unmapped_files'][:4])}): check which steps use them."})
    items.append({"id": "untested", "priority": "P3", "text": "It hasn't run yet: Flowhaus compares the first run after "
                                                              "merging with the numbers from before."})
    return items


def required(meta: dict) -> list[dict]:
    """The points that must be confirmed before the pull request opens: the P0 ones."""
    return [g for g in gate(meta) if g["priority"] == "P0"]


class GateError(ChangeError):
    """The pull request can't open yet: something in the review isn't confirmed."""


def open_pull_request(change_id: str, confirmed: list[str] | None = None) -> dict:
    """Only ever called from the UI after the user clicked "Open pull request", with everything in `gate` confirmed."""
    meta = get(change_id)
    if meta["status"] != "proposed":
        raise ChangeError(f"This change is {meta['status']}, not waiting for review.")
    missing = [g["text"] for g in required(meta) if g["id"] not in set(confirmed or [])]
    if missing:
        raise GateError("Confirm the critical points first: " + " / ".join(missing))
    dest = workspace(change_id)
    body = (f"{meta['summary']}\n\n---\nProposed in Flowhaus's chat and approved by you before this pull request was "
            "opened. Please review the diff before merging.")
    _git(dest, "-c", "user.name=Flowhaus", "-c", "user.email=flowhaus@users.noreply.github.com", "commit", "--quiet",
         "--no-verify", "-m", meta["title"], "-m", meta["summary"][:2000])
    # push with your own git/GitHub sign-in; --no-verify: no pre-push hooks from the edited files
    _git(dest, "push", "--quiet", "--no-verify", "origin", f"HEAD:refs/heads/{meta['branch']}", timeout=300)
    try:
        p = subprocess.run(["gh", "pr", "create", "-R", meta["repo"], "--head", meta["branch"], "--base", meta["base"],
                            "--title", meta["title"], "--body", body], capture_output=True, text=True, timeout=120)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ChangeError(f"The branch was pushed, but the pull request couldn't be opened: {exc}") from exc
    if p.returncode != 0:
        raise ChangeError(f"The branch {meta['branch']} was pushed, but GitHub refused the pull request: "
                          f"{(p.stderr or '').strip()[:300]}")
    meta.update(status="opened", pr_url=p.stdout.strip().splitlines()[-1], opened_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    return _save(meta)


def merged_at(change_id: str) -> str | None:
    """When the change's pull request was merged (asks GitHub once, then remembers), or None."""
    meta = get(change_id)
    if meta.get("merged_at") or meta.get("status") != "opened" or not meta.get("pr_url"):
        return meta.get("merged_at")
    if time.time() - meta.get("_checked", 0) < 600:
        return None
    try:
        p = subprocess.run(["gh", "pr", "view", meta["pr_url"], "--json", "mergedAt,state"],
                           capture_output=True, text=True, timeout=30)
        data = json.loads(p.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        data = {}
    meta["_checked"] = time.time()
    if data.get("mergedAt"):
        from server.automations.github_actions import local_time

        meta["merged_at"] = local_time(data["mergedAt"])
    elif data.get("state") == "CLOSED":
        meta["status"] = "closed"
    _save(meta)
    return meta.get("merged_at")


def discard(change_id: str) -> dict:
    meta = get(change_id)
    if meta["status"] == "opened":
        raise ChangeError("The pull request is already open; close it on GitHub.")
    shutil.rmtree(workspace(change_id), ignore_errors=True)
    meta.update(status="discarded")
    return _save(meta)
