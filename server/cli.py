"""flowhaus: set up and check Flowhaus from the command line. Written to be driven by a coding agent.

    uv run flowhaus doctor                 is everything installed? (exit 1 if something required is missing)
    uv run flowhaus scan [DIR ...]         find automations you already run (workflows, cron, launchd, run folders)
    uv run flowhaus add github-actions ID --repo owner/name --workflow file.yml [--local-path DIR]
    uv run flowhaus add folder-runs ID --path DIR
    uv run flowhaus logs ID [--run RUN_ID] [--grep REGEX]    the run log, to write counting rules from
    uv run flowhaus check [ID] [--run RUN_ID]                config problems + what the map shows for a run
    uv run flowhaus list                   configured automations
    uv run flowhaus test ID [--generate 20 --temperature 0.8]   pressure-test it in test mode
    uv run flowhaus mcp [enable|disable NAME]   MCP servers from your Claude Code/Desktop/Cursor setup, for the chat
    uv run flowhaus start                  start Flowhaus in the background and open it (http://localhost:8765)
    uv run flowhaus stop | status          stop it / is it running?
    uv run flowhaus autostart on|off       macOS: start it at login, so a bookmark always works
    uv run flowhaus dev                    for development: API with reload on :8000, Vite on :5173

Every command takes --json for machine-readable output. See AGENTS.md for the full onboarding flow.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import yaml

from server import automations
from server.automations.base import slugify
from server.automations import github_actions as ga
from server.automations.github_actions import BOILERPLATE, GhError

ROOT = Path(__file__).resolve().parent.parent
DATED = re.compile(r"\d{4}-\d\d-\d\d")
SKIP_DIRS = {"node_modules", ".venv", "venv", ".git", "Library", "Applications", ".Trash", ".cache", "__pycache__",
             "dist", "build", ".npm", ".cargo", ".rustup", "Pictures", "Music", "Movies", ".local", "site-packages"}


def out(data, as_json: bool, text: str) -> None:
    print(json.dumps(data, indent=2, default=str) if as_json else text)


def run_cmd(*args: str, timeout: int = 15) -> tuple[int, str]:
    try:
        p = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or p.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


# --------------------------------------------------------------------------- doctor


def doctor(args) -> int:
    checks = []

    def add(name, ok, detail, fix="", required=True):
        checks.append({"check": name, "ok": ok, "required": required, "detail": detail, "fix": fix})

    add("python", sys.version_info >= (3, 12), sys.version.split()[0], "Install Python 3.12+ (uv python install 3.12)")
    code, node = run_cmd("node", "--version")
    ver = tuple(int(x) for x in re.findall(r"\d+", node)[:2]) if code == 0 else (0, 0)
    add("node", ver >= (20, 19), node if code == 0 else "not found", "Install Node.js 20.19+ or 22.12+")
    add("web dependencies", (ROOT / "web" / "node_modules").is_dir(), str(ROOT / "web" / "node_modules"),
        "npm --prefix web install")
    if os.environ.get("ANTHROPIC_API_KEY"):
        add("chat (Claude)", True, "ANTHROPIC_API_KEY is set", required=False)
    else:
        has_claude = shutil.which("claude") is not None
        add("chat (Claude)", has_claude,
            "will use your Claude Code login (if the chat says it isn't signed in: run `claude`, then /login)"
            if has_claude else "no ANTHROPIC_API_KEY and no `claude` CLI found",
            "Set ANTHROPIC_API_KEY, or install Claude Code and run `claude` then /login. The map works without chat.",
            required=False)
    code, msg = run_cmd("gh", "auth", "status")
    add("GitHub CLI", code == 0, "signed in" if code == 0 else (msg.splitlines() or ["not found"])[-1][:200],
        "Install gh (https://cli.github.com) and run `gh auth login`. Only needed for GitHub Actions automations.",
        required=False)
    found, errors = automations.load_all()
    add("automations folder", True, f"{automations.automations_dir()} ({len(found)} configured)", required=False)
    for folder, err in errors.items():
        add(f"automation {folder}", False, err, f"Fix automations/{folder}/automation.yaml, then `uv run flowhaus check {folder}`")
    for a in found.values():
        problems = a.check()
        add(f"automation {a.id}", not problems, "; ".join(problems) or "ok", f"uv run flowhaus check {a.id}", required=False)

    from server import mcp

    found = mcp.discover()
    servers, mcp_errors = mcp.load()
    if found:
        add("chat tools (MCP)", not mcp_errors,
            f"{len(found)} found in your Claude Code / Claude Desktop / Cursor / project settings, {len(servers)} in use"
            + "".join(f"; {k}: {v}" for k, v in mcp_errors.items()), "uv run flowhaus mcp list", required=False)
    failed = [c for c in checks if c["required"] and not c["ok"]]
    lines = [f"{'ok ' if c['ok'] else ('!! ' if c['required'] else '-  ')} {c['check']}: {c['detail']}"
             + ("" if c["ok"] or not c["fix"] else f"\n      fix: {c['fix']}") for c in checks]
    out({"ok": not failed, "checks": checks}, args.json, "\n".join(lines))
    return 1 if failed else 0


# --------------------------------------------------------------------------- scan


def _walk(roots: list[Path], max_depth: int):
    for root in roots:
        root = root.expanduser().resolve()
        if not root.is_dir():
            continue
        stack = [(root, 0)]
        while stack:
            d, depth = stack.pop()
            yield d
            if depth >= max_depth:
                continue
            try:
                children = sorted(p for p in d.iterdir() if p.is_dir() and not p.is_symlink())
            except OSError:
                continue
            for c in children:
                if c.name in SKIP_DIRS or (c.name.startswith(".") and c.name != ".github"):
                    continue
                stack.append((c, depth + 1))


def _git_repo(folder: Path) -> str | None:
    code, url = run_cmd("git", "-C", str(folder), "remote", "get-url", "origin", timeout=5)
    m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(\.git)?$", url) if code == 0 else None
    return m.group(1) if m else None


def _safe_path(tokens: list[str]) -> str | None:
    """The first plain file path in a command line. Never URLs, KEY=value pairs or query strings (they hold tokens)."""
    paths = [t.strip("'\"") for t in tokens]
    paths = [t for t in paths if t.startswith(("/", "~/")) and not any(c in t for c in ("=", "?", "://", "@"))]
    runners = re.compile(r"^(/usr)?(/local)?(/opt/homebrew)?/s?bin/|/(python[\d.]*|bash|sh|zsh|node|uv|env|ruby|perl)$")
    return next((t for t in paths if not runners.search(t)), paths[0] if paths else None)


GENERIC = {"out", "output", "outputs", "runs", "data", "logs", "results", "exports", "archive"}


def _suggest_id(folder: Path) -> str:
    return slugify(f"{folder.parent.name}-{folder.name}" if folder.name.lower() in GENERIC else folder.name)


def scan(args) -> int:
    roots = [Path(p) for p in args.dirs] or [Path.home()]
    found = []
    for d in _walk(roots, args.depth):
        wf = d / ".github" / "workflows"
        if wf.is_dir():
            repo = _git_repo(d)
            for f in sorted([*wf.glob("*.yml"), *wf.glob("*.yaml")]):
                text = f.read_text(errors="replace")
                cron = re.findall(r"cron:\s*['\"]([^'\"]+)['\"]", text)
                name = re.search(r"^name:\s*(.+)$", text, re.M)
                found.append({"type": "github_actions", "name": name.group(1).strip().strip("'\"") if name else f.stem,
                              "repo": repo, "workflow": f.name, "local_path": str(d), "schedule": cron,
                              "add": f"uv run flowhaus add github-actions {slugify(f.stem)} --repo {repo or 'OWNER/NAME'} "
                                     f"--workflow {f.name} --local-path '{d}'"})
        try:
            subdirs = [p for p in d.iterdir() if p.is_dir()]
        except OSError:
            continue
        dated = [p for p in subdirs if DATED.search(p.name)]
        if len(dated) >= 3 and len(dated) >= len(subdirs) / 2:
            names = Counter(f.name for p in dated[-20:] for f in p.iterdir() if f.is_file())
            found.append({"type": "folder_runs", "path": str(d), "runs": len(dated),
                          "latest": max(p.name for p in dated), "files_in_runs": [n for n, _ in names.most_common(8)],
                          "add": f"uv run flowhaus add folder-runs {_suggest_id(d)} --path '{d}'"})
    if not args.no_system:
        code, tab = run_cmd("crontab", "-l", timeout=5)
        for line in tab.splitlines() if code == 0 else []:
            parts = line.split()
            if not parts or parts[0].startswith("#") or re.match(r"^\w+=", parts[0]):
                continue  # comments and variable lines (which often hold tokens)
            schedule, cmd = (parts[0], parts[1:]) if parts[0].startswith("@") else (" ".join(parts[:5]), parts[5:])
            if not cmd:
                continue
            found.append({"type": "cron", "schedule": schedule, "script": _safe_path(cmd),
                          "add": "No built-in adapter: if it writes a folder per run use folder-runs, "
                                 "otherwise write a python adapter (see docs/automations.md)."})
        agents = Path.home() / "Library" / "LaunchAgents"
        for p in sorted(agents.glob("*.plist")) if agents.is_dir() else []:
            try:
                data = plistlib.loads(p.read_bytes())
            except Exception:
                continue
            label = str(data.get("Label", p.stem))
            if label.startswith(("com.apple.", "com.google.", "com.microsoft.", "homebrew.")):
                continue
            prog = data.get("ProgramArguments") or [data.get("Program")]
            found.append({"type": "launchd", "label": label,
                          "script": _safe_path([str(a) for a in prog if a]),
                          "schedule": data.get("StartCalendarInterval") or data.get("StartInterval"),
                          "add": "No built-in adapter: if it writes a folder per run use folder-runs, "
                                 "otherwise write a python adapter (see docs/automations.md)."})
    text = "\n".join(f"[{c['type']}] {c.get('name') or c.get('label') or c.get('path') or c.get('script')}"
                     + (f"  ({c['repo'] or 'no GitHub remote found'}: {c['workflow']}, schedule {', '.join(c['schedule']) or 'none'})"
                        if c["type"] == "github_actions" else "")
                     + (f"  ({c['runs']} runs, files: {', '.join(c['files_in_runs'])})" if c["type"] == "folder_runs" else "")
                     + (f"  (schedule {c['schedule']})" if c["type"] in ("cron", "launchd") else "")
                     + f"\n    {c['add']}" for c in found) or "Nothing found. Try `uv run flowhaus scan ~/code ~/projects --depth 5`."
    out({"candidates": found}, args.json, text)
    return 0


# --------------------------------------------------------------------------- add


def _target(id_: str) -> Path:
    if not automations.ID.match(id_):
        raise SystemExit(f"id must be lowercase letters, digits and dashes: {id_!r}")
    folder = automations.automations_dir() / id_
    if (folder / "automation.yaml").exists():
        raise SystemExit(f"{folder / 'automation.yaml'} already exists; edit it instead.")
    return folder


def _write(folder: Path, header: str, config: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "automation.yaml"
    path.write_text(header + yaml.safe_dump(config, sort_keys=False, allow_unicode=True, width=120))
    return path


def add_github(args) -> int:
    folder = _target(args.id)
    steps = []
    try:
        runs = json.loads(ga.gh("run", "list", "-R", args.repo, "--workflow", args.workflow, "--limit", "10",
                             "--json", "databaseId,status"))
        latest = next((r for r in runs if r["status"] == "completed"), None)
        jobs = json.loads(ga.gh("run", "view", str(latest["databaseId"]), "-R", args.repo, "--json", "jobs"))["jobs"] if latest else []
    except (GhError, json.JSONDecodeError) as exc:
        if not args.force:
            raise SystemExit(f"Couldn't read {args.repo} / {args.workflow} from GitHub: {exc}\n"
                             "Check the repo (owner/name) and the workflow file name, and `gh auth status`. "
                             "Use --force to write the config anyway.")
        print(f"note: couldn't read runs from GitHub ({exc}); writing a config without a map.", file=sys.stderr)
        jobs = []
    multi = len(jobs) > 1
    for job in jobs:
        for st in job.get("steps") or []:
            if not BOILERPLATE.match(st["name"]):
                steps.append({"id": slugify(f"{job['name']}-{st['name']}" if multi else st["name"]).replace("-", "_"),
                              "label": st["name"], "description": "TODO: what this step gives you, in plain English.",
                              "github_step": f"{job['name']}/{st['name']}"})
    config = {"type": "github_actions", "name": args.name or args.workflow.rsplit(".", 1)[0].replace("-", " ").capitalize(),
              "description": "TODO: one sentence about what comes out of this automation.",
              **({"local_path": args.local_path} if args.local_path else {}),
              "github": {"repo": args.repo, "workflow": args.workflow, "allow_toggle": False},
              **({"map": {"steps": steps}} if steps else {})}
    path = _write(folder, "# Generated by `flowhaus add github-actions`. Next: replace the TODOs, group the steps, and add\n"
                          "# counting rules from `uv run flowhaus logs " + args.id + "`. Reference: docs/automations.md\n", config)
    out({"path": str(path), "steps": len(steps)}, args.json,
        f"Wrote {path} with {len(steps)} steps from the latest run.\n"
        f"Next: uv run flowhaus logs {args.id} --tail 200   then   uv run flowhaus check {args.id}")
    return 0


def add_folder(args) -> int:
    folder = _target(args.id)
    runs_dir = Path(args.path).expanduser().resolve()
    if not runs_dir.is_dir():
        raise SystemExit(f"Not a folder: {runs_dir}")
    subdirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    names = [p.name for p in subdirs]
    pattern, time_format = r".+", None
    for pat, fmt in ((r"^\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d$", "%Y-%m-%d_%H-%M-%S"), (r"^\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d$", "%Y-%m-%dT%H-%M-%S"),
                     (r"^\d{4}-\d\d-\d\d_\d\d-\d\d$", "%Y-%m-%d_%H-%M"), (r"^\d{4}-\d\d-\d\d$", "%Y-%m-%d"),
                     (r"^\d{8}-\d{6}$", "%Y%m%d-%H%M%S"), (r"^\d{4}-\d\d-\d\d", None)):
        if names and sum(bool(re.match(pat, n)) for n in names) >= len(names) / 2:
            pattern, time_format = pat, fmt
            break
    runs = [p for p in subdirs if re.match(pattern, p.name)]
    # file names, with dates and numbers turned into * so next month's files still match
    generic = lambda n: re.sub(r"\d+", "*", n)  # noqa: E731
    files = Counter(generic(f.name) for p in runs[-30:] for f in p.iterdir() if f.is_file())
    is_log = lambda n: n.endswith(".log") or n.lower().startswith(("log.", "log-", "log_"))  # noqa: E731

    def first_seen(n: str) -> float:
        times = [f.stat().st_mtime - p.stat().st_ctime for p in runs[-30:] for f in p.glob(n) if f.is_file()]
        return min(times) if times else 0.0

    order = sorted((n for n in files if not is_log(n)), key=first_seen)
    logs = [n for n in files if is_log(n)]
    steps = [{"id": slugify(Path(n).stem.replace("*", "")).replace("-", "_") or f"step_{i + 1}",
              "label": f"TODO: what makes {n}", "description": "TODO: what this step gives you, in plain English.",
              "produces": n,
              **({"count": "rows"} if Path(n).suffix.lower() in (".csv", ".tsv") else {}),
              "show": ["size", "modified"]}
             for i, n in enumerate(order[:8])]
    name_from = runs_dir.parent if runs_dir.name.lower() in GENERIC else runs_dir
    config = {"type": "folder_runs", "name": args.name or f"TODO: name ({name_from.name})",
              "description": "TODO: one sentence about what comes out of this automation.",
              "folder_runs": {"path": str(runs_dir), "pattern": pattern, **({"time_format": time_format} if time_format else {}),
                              **({"input": order[0]} if order else {}), **({"output": order[-1]} if len(order) > 1 else {}),
                              **({"log": logs[0]} if logs else {}), "preview_words": 0},
              "map": {"steps": steps}}
    path = _write(folder, "# Generated by `flowhaus add folder-runs`. Steps are guessed from the files each run leaves,\n"
                          "# oldest first. Replace the TODOs; merge or drop steps as needed. Reference: docs/automations.md\n"
                          "# The run folders are private: the chat agent can never read them.\n", config)
    out({"path": str(path), "runs": len(runs), "steps": len(steps)}, args.json,
        f"Wrote {path}: {len(runs)} runs, {len(steps)} steps guessed from file names.\nNext: uv run flowhaus check {args.id}")
    return 0


# --------------------------------------------------------------------------- logs / check / list


def _get(id_: str):
    found, errors = automations.load_all()
    if id_ in errors:
        raise SystemExit(f"{id_}: {errors[id_]}")
    if id_ not in found:
        raise SystemExit(f"No automation '{id_}'. Configured: {', '.join(found) or 'none'}")
    return found[id_]


def logs(args) -> int:
    a = _get(args.id)
    if a.config.get("type") != "github_actions":
        raise SystemExit("logs is for github_actions automations.")
    runs = a.list_runs()
    run_id = args.run or next((r["run_id"] for r in runs if r["status"] != "running"), None)
    if not run_id:
        raise SystemExit("No finished runs yet.")
    rows = [r for r in ga.log_lines(a.raw_log(run_id)) if not BOILERPLATE.match(r["step"])]
    total = len(rows)
    if args.grep:
        rows = [r for r in rows if re.search(args.grep, r["text"])]
    matched = len(rows)
    rows = rows[-args.tail:] if args.tail else rows[: args.limit]
    note = "" if len(rows) == matched else (
        f"\n# showing {len(rows)} of {matched} lines{' matching' if args.grep else ''} "
        f"({'last' if args.tail else 'first'} ones). Use --grep REGEX, --tail N or --limit N to see others.")
    out({"run_id": run_id, "total_lines": total, "matched": matched, "lines": rows}, args.json,
        f"# run {run_id}: job/step | log text, colour codes removed (rules match the text after the |)\n"
        + "\n".join(f"{r['job']}/{r['step']} | {r['text']}" for r in rows) + note)
    return 0


def check(args) -> int:
    found, errors = automations.load_all()
    ids = [args.id] if args.id else [*errors, *found]
    report, bad = [], False
    for id_ in ids:
        if id_ in errors:
            report.append({"id": id_, "ok": False, "problems": [errors[id_]]})
            bad = True
            continue
        a = _get(id_)
        problems = a.check()
        entry = {"id": id_, "ok": not problems, "problems": problems, "runs": 0, "run": None}
        try:
            runs = a.list_runs()
            entry["runs"] = len(runs)
            if not runs and a.config.get("type") == "github_actions":
                a._gh_list()  # surfaces the GitHub error (repo not found, not signed in, ...)
            run_id = args.run or next((r["run_id"] for r in runs if r["status"] != "running"), None)
            run = a.get_run(run_id) if run_id else None
            if args.run and run is None:
                problems.append(f"No run '{args.run}'")
        except Exception as exc:  # report, don't crash: this is a diagnostic
            problems.append(f"Reading runs failed: {type(exc).__name__}: {exc}")
            run = None
        if run:
            steps = []
            for s in a.steps:
                n = run["nodes"].get(s["id"]) or {}
                kind = a.config.get("type")
                has_rules = kind == "python" or any(
                    s.get(k) for k in ("in", "out", "skip", "rows", "fail", "produces", "github_step"))
                missing = "`produces`" if kind == "folder_runs" else "a counting rule (in/out/skip/rows) or `github_step`"
                n_in, n_out, n_skip = n.get("rows_in"), n.get("rows_out"), n.get("rows_rejected") or 0
                warning = (f"no {missing}: always shows 'not run'" if not has_rules else
                           "rules matched nothing in this run" if n.get("status") == "not_run" and run["status"] == "success" else
                           f"numbers don't add up: {n_in} in ≠ {n_out} out + {n_skip} skipped (a rule may count twice)"
                           if kind != "python" and None not in (n_in, n_out) and n_skip and n_in != n_out + n_skip else None)
                steps.append({"id": s["id"], "label": s.get("label"), "status": n.get("status"), "in": n_in,
                              "out": n_out, "skipped": n_skip, "reasons": n.get("reject_reasons"), "warning": warning})
            entry["run"] = {"run_id": run["run_id"], "status": run["status"], "started_at": run.get("started_at"),
                            "summary": run.get("summary"), "error": run.get("error"), "steps": steps}
        elif not problems and entry["runs"] == 0:
            problems.append("No runs found yet.")
        if run:
            problems += [f"Step '{st['id']}': {st['warning']}" for st in entry["run"]["steps"] if st["warning"]]
            if "Could not read this run" in str((run.get("error") or {}).get("message")):
                problems.append(run["error"]["message"])
        try:
            from server import insights

            entry["insights"] = insights.insights(id_)
        except Exception:
            entry["insights"] = []
        try:  # big picture: shown, never failing the check (the user decides; see docs/practices.md)
            from server import harness

            entry["harness"] = harness.review(id_)
        except Exception:
            entry["harness"] = None
        entry["ok"] = not problems
        bad = bad or bool(problems)
        report.append(entry)

    def fmt(e):
        lines = [f"{'ok' if e['ok'] else '!!'} {e['id']}" + (f"  ({e.get('runs', 0)} runs)" if "runs" in e else "")]
        lines += [f"   problem: {p}" for p in e["problems"]]
        if e.get("run"):
            r = e["run"]
            lines.append(f"   run {r['run_id']} {r['status']} {r['started_at']}"
                         + (f"  summary: {r['summary'].get('text')}" if (r["summary"] or {}).get("text") else ""))
            if r["error"]:
                lines.append(f"   error at {r['error'].get('node_id')}: {r['error'].get('message')}")
            for i in e.get("insights") or []:
                lines.append(f"   note ({i['level']}): {i['title']}. {i['detail']}")
            for s in r["steps"]:
                lines.append(f"   - {s['id']:<22} {str(s['status']):<8} in={s['in']} out={s['out']} skipped={s['skipped']}"
                             + (f" {s['reasons']}" if s["reasons"] else "") + (f"   <- {s['warning']}" if s["warning"] else ""))
        h = e.get("harness") or {}
        for f in h.get("findings") or []:
            lines.append(f"   {'gap' if f['kind'] == 'gap' else 'blind spot'} ({f['level']}): {f['title']}. {f['detail']}")
        for q in h.get("questions") or []:
            lines.append(f"   ask the user: {q['title']}")
        return "\n".join(lines)

    out({"ok": not bad, "automations": report}, args.json, "\n".join(map(fmt, report)) or "No automations configured.")
    return 1 if bad else 0


def list_cmd(args) -> int:
    found, errors = automations.load_all()
    rows = [{"id": a.id, "type": a.config.get("type"), "name": a.meta()["name"], "folder": str(a.folder)} for a in found.values()]
    rows += [{"id": k, "error": v} for k, v in errors.items()]
    out({"automations_dir": str(automations.automations_dir()), "automations": rows}, args.json,
        f"{automations.automations_dir()}\n" + ("\n".join(f"  {r['id']}: {r.get('name') or 'ERROR ' + r['error']}" for r in rows) or "  (none)"))
    return 0


# --------------------------------------------------------------------------- mcp


def mcp_cmd(args) -> int:
    """List the MCP servers already set up on this computer, and choose which the chat may use."""
    from server import mcp

    if args.action in ("enable", "disable"):
        try:
            mcp.set_enabled(args.name, args.action == "enable")
        except KeyError:
            raise SystemExit(f"No MCP server '{args.name}'. See: uv run flowhaus mcp list")
    data = mcp.summary()
    lines = [f"{'on ' if s['enabled'] else 'off'} {s['name']:<22} {s['type']:<5} {s['where']:<28} from {s['source']}"
             + (f"  (can't start: {s['problem']})" if s["problem"] else "")
             + (f"  (no question for: {', '.join(s['allowed_without_asking'])})" if s["allowed_without_asking"] else "")
             for s in data["servers"]]
    out(data, args.json, "\n".join(lines) or "No MCP servers found in Claude Code, Claude Desktop, Cursor or .mcp.json files.")
    return 0


# --------------------------------------------------------------------------- test


def test_cmd(args) -> int:
    """Pressure-test an automation: generate items (optional), run them in test mode, print the checks."""
    from server import flows, testlab

    if args.id not in flows.all_flow_ids():
        raise SystemExit(f"No flow or automation '{args.id}'.")
    how = testlab.mode(args.id)
    if not how["ready"]:
        raise SystemExit(f"{how['label']}\n{how.get('setup') or ''}")
    if args.generate:
        suite = testlab.get_suite(args.id)
        cases = testlab.generate(args.id, args.generate, args.temperature, seed=args.seed)
        testlab.save_suite(args.id, {**suite, "cases": cases if args.replace else suite["cases"] + cases})
    if how["kind"] != "local" and not args.yes:
        raise SystemExit(f"This runs your real automation in test mode: {how['non_production']}\nAdd --yes to go ahead.")
    rec = testlab.start(args.id, confirmed=args.yes)
    while rec["status"] == "running":
        time.sleep(15)
        rec = testlab.refresh(args.id, rec["id"])
    lines = [f"test {rec['id']} ({rec['mode']}) {rec['status']}" + (f", run {rec['run_id']}" if rec.get("run_id") else "")]
    lines += [f"  {'PASS' if c['ok'] else 'FAIL'}  {c['name']}" + (f"  ({c['detail']})" if c["detail"] and not c["ok"] else "")
              for c in rec["checks"]]
    lines += [f"    {r['got']:<8} {('at ' + str(r['step'])) if r['step'] else '':<24} {r['reason'] or '':<34} {r['note']}"
              + ("" if r["ok"] else f"   <- expected {r['expect']}") for r in rec["results"]]
    out({k: v for k, v in rec.items() if k != "run"}, args.json, "\n".join(lines))
    return 0 if rec["checks"] and all(c["ok"] for c in rec["checks"]) else 1


# --------------------------------------------------------------------------- dev


def dev(args) -> int:
    """Development: API with reload + Vite. Both stop together on Ctrl+C or SIGTERM."""
    web = ROOT / "web"
    if not (web / "node_modules").is_dir():
        subprocess.run(["npm", "--prefix", str(web), "install"], check=True)
    env = {**os.environ, "FLOWHAUS_API_PORT": str(args.port), "FLOWHAUS_WEB_PORT": str(args.web_port)}
    group = {"start_new_session": True} if os.name == "posix" else {}
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", str(args.port),
                            "--reload", "--reload-dir", "server"], cwd=ROOT, env=env, **group)
    ui = subprocess.Popen(["npm", "--prefix", str(web), "run", "dev"], cwd=ROOT, env=env, **group)
    print(f"Flowhaus (dev): http://localhost:{args.web_port}  (API http://127.0.0.1:{args.port})  Ctrl+C to stop", flush=True)

    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        while api.poll() is None and ui.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in (api, ui):
            _kill_tree(p.pid)
    return 0


def _kill_tree(pid: int) -> None:
    try:
        if os.name == "posix":
            os.killpg(pid, signal.SIGTERM)  # the child and everything it started (uvicorn reloader, vite)
        else:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    except (ProcessLookupError, PermissionError, OSError):
        pass


# --------------------------------------------------------------------------- start / stop: the on-demand app

PID_FILE = ROOT / "state" / "maps.pid"
LOG_FILE = ROOT / "state" / "maps.log"
DEFAULT_PORT = 8765


def _ui_outdated() -> bool:
    built = ROOT / "web" / "dist" / "index.html"
    if not built.exists():
        return True
    newest = max((f.stat().st_mtime for f in (ROOT / "web" / "src").rglob("*") if f.is_file()), default=0)
    return newest > built.stat().st_mtime


def _alive(port: int) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/settings", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def _running() -> tuple[int, int] | None:
    """(pid, port) of a Flowhaus started with `flowhaus start`, if it still answers."""
    try:
        pid, port = (int(x) for x in PID_FILE.read_text().split())
    except (OSError, ValueError):
        return None
    return (pid, port) if _alive(port) else None


def start(args) -> int:
    """Start Flowhaus in the background (one small local server: API + built UI) and open it."""
    url = f"http://localhost:{args.port}"
    if running := _running():
        url = f"http://localhost:{running[1]}"
        out({"url": url, "pid": running[0], "already_running": True}, args.json, f"Flowhaus is already running: {url}")
    else:
        if _ui_outdated():
            print("Building the web UI (once, ~10 s)...", file=sys.stderr, flush=True)
            if not (ROOT / "web" / "node_modules").is_dir():
                subprocess.run(["npm", "--prefix", str(ROOT / "web"), "install"], check=True, stdout=sys.stderr)
            subprocess.run(["npm", "--prefix", str(ROOT / "web"), "run", "build"], check=True, stdout=subprocess.DEVNULL)
        env = {**os.environ, "FLOWHAUS_SERVE_UI": "1", "FLOWHAUS_API_PORT": str(args.port), "FLOWHAUS_WEB_PORT": str(args.port)}
        LOG_FILE.parent.mkdir(exist_ok=True)
        detach = {"start_new_session": True} if os.name == "posix" else {"creationflags": 0x00000008}  # DETACHED_PROCESS
        with open(LOG_FILE, "ab") as log:
            proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1",
                                     "--port", str(args.port)], cwd=ROOT, env=env, stdout=log, stderr=log,
                                    stdin=subprocess.DEVNULL, **detach)
        for _ in range(60):
            if _alive(args.port):
                break
            if proc.poll() is not None:
                raise SystemExit(f"Flowhaus didn't start (port {args.port} taken?). See {LOG_FILE}")
            time.sleep(0.25)
        PID_FILE.write_text(f"{proc.pid} {args.port}")
        out({"url": url, "pid": proc.pid, "already_running": False}, args.json,
            f"Flowhaus is running: {url}  (bookmark it; `flowhaus stop` to stop)")
    if not args.no_open:
        import webbrowser

        webbrowser.open(url)
    return 0


def stop(args) -> int:
    running = _running()
    if not running:
        PID_FILE.unlink(missing_ok=True)
        out({"stopped": False}, args.json, "Flowhaus isn't running.")
        return 0
    _kill_tree(running[0])
    PID_FILE.unlink(missing_ok=True)
    out({"stopped": True, "pid": running[0]}, args.json, "Stopped Flowhaus.")
    return 0


def status(args) -> int:
    running = _running()
    data = {"running": bool(running), "url": f"http://localhost:{running[1]}" if running else None,
            "pid": running[0] if running else None, "autostart": _agent_plist().exists()}
    out(data, args.json, (f"Running at {data['url']}" if running else "Not running. Start it with: uv run flowhaus start")
        + ("  (starts at login)" if data["autostart"] else ""))
    return 0


def _agent_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "dev.maps.plist"


def autostart(args) -> int:
    """Optional: keep a small Flowhaus server running from login (macOS launchd), so the bookmark always works."""
    if sys.platform != "darwin":
        print("Autostart is built in for macOS only. On Linux, a systemd user service running\n"
              f"  {sys.executable} -m server.cli start --no-open\nfrom {ROOT} does the same.")
        return 1
    plist = _agent_plist()
    if args.state == "off":
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        plist.unlink(missing_ok=True)
        out({"autostart": False}, args.json, "Flowhaus won't start at login anymore.")
        return 0
    if _ui_outdated():
        start(argparse.Namespace(port=args.port, no_open=True, json=False))
        stop(argparse.Namespace(json=True))
    env = {"FLOWHAUS_SERVE_UI": "1", "FLOWHAUS_API_PORT": str(args.port), "FLOWHAUS_WEB_PORT": str(args.port),
           "PATH": os.environ.get("PATH", "")}
    data = {"Label": "dev.flowhaus", "ProgramArguments": [sys.executable, "-m", "uvicorn", "server.app:app", "--host",
                                                          "127.0.0.1", "--port", str(args.port)],
            "WorkingDirectory": str(ROOT), "EnvironmentVariables": env, "RunAtLoad": True, "KeepAlive": False,
            "StandardOutPath": str(LOG_FILE), "StandardErrorPath": str(LOG_FILE)}
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(plistlib.dumps(data))
    if not args.no_load:
        subprocess.run(["launchctl", "load", str(plist)], capture_output=True)
    out({"autostart": True, "plist": str(plist), "url": f"http://localhost:{args.port}"}, args.json,
        f"Flowhaus now starts at login: http://localhost:{args.port}  (undo: flowhaus autostart off)")
    return 0


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="flowhaus", description="Set up and check Flowhaus. See AGENTS.md.")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="check prerequisites and configured automations")
    s = sub.add_parser("scan", help="find automations you already run (prints paths and names only)")
    s.add_argument("dirs", nargs="*", help="folders to search (default: your home folder)")
    s.add_argument("--depth", type=int, default=4)
    s.add_argument("--no-system", action="store_true", help="skip crontab and launchd")
    a = sub.add_parser("add", help="write automations/<id>/automation.yaml")
    asub = a.add_subparsers(dest="kind", required=True)
    g = asub.add_parser("github-actions")
    g.add_argument("id")
    g.add_argument("--repo", required=True, help="owner/name")
    g.add_argument("--workflow", required=True, help="file name in .github/workflows/")
    g.add_argument("--local-path", help="local clone; the chat may read its source (never write)")
    g.add_argument("--name")
    g.add_argument("--force", action="store_true", help="write the config even if GitHub can't be read")
    f = asub.add_parser("folder-runs")
    f.add_argument("id")
    f.add_argument("--path", required=True, help="the folder that holds one sub-folder per run")
    f.add_argument("--name")
    lg = sub.add_parser("logs", help="print a GitHub Actions run log (to write counting rules from)")
    lg.add_argument("id")
    lg.add_argument("--run")
    lg.add_argument("--grep")
    lg.add_argument("--limit", type=int, default=400, help="first N lines")
    lg.add_argument("--tail", type=int, help="last N lines instead (counts are often printed at the end)")
    c = sub.add_parser("check", help="validate configs and show what the map shows for a run")
    c.add_argument("id", nargs="?")
    c.add_argument("--run")
    sub.add_parser("list", help="configured automations")
    t = sub.add_parser("test", help="pressure-test an automation in test mode (see docs/testing.md)")
    t.add_argument("id")
    t.add_argument("--generate", type=int, default=0, help="add N generated test items first")
    t.add_argument("--temperature", type=float, default=0.5, help="0 = typical items … 1 = wild edge cases")
    t.add_argument("--seed", type=int, help="repeat the same generated items")
    t.add_argument("--replace", action="store_true", help="replace the saved items instead of adding to them")
    t.add_argument("--yes", action="store_true", help="confirm a remote test run (it runs your real automation in test mode)")
    m = sub.add_parser("mcp", help="MCP servers from your existing setup: list, enable or disable for the chat")
    m.add_argument("action", choices=["list", "enable", "disable"], nargs="?", default="list")
    m.add_argument("name", nargs="?")
    d = sub.add_parser("dev", help="start the app for development (API with reload + Vite)")
    d.add_argument("--port", type=int, default=8000, help="API port")
    d.add_argument("--web-port", type=int, default=5173, help="web UI port")
    st = sub.add_parser("start", help="start Flowhaus in the background and open it (one local server)")
    st.add_argument("--port", type=int, default=DEFAULT_PORT)
    st.add_argument("--no-open", action="store_true", help="don't open the browser")
    sub.add_parser("stop", help="stop a Flowhaus started with `flowhaus start`")
    sub.add_parser("status", help="is Flowhaus running, and where")
    au = sub.add_parser("autostart", help="macOS: start Flowhaus at login (on) or not (off)")
    au.add_argument("state", choices=["on", "off"])
    au.add_argument("--port", type=int, default=DEFAULT_PORT)
    au.add_argument("--no-load", action="store_true", help=argparse.SUPPRESS)
    for sp in (*sub.choices.values(), g, f):
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")
    args = p.parse_args(argv)
    handlers = {"doctor": doctor, "scan": scan, "logs": logs, "check": check, "list": list_cmd, "dev": dev,
                "start": start, "stop": stop, "status": status, "autostart": autostart, "mcp": mcp_cmd, "test": test_cmd,
                "add": lambda a: add_github(a) if a.kind == "github-actions" else add_folder(a)}
    try:
        return handlers[args.cmd](args)
    except GhError as exc:
        print(f"GitHub CLI: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
