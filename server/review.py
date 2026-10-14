"""The harness's view of a change: what it touches, what comes after, and what to watch.

An automation is a chain: a change to one step reaches every step after it. Before a proposed change is shown to
the user, Flowhaus works out (without running anything):
  - touched:    the map steps whose `file` the change edits
  - downstream: every step after those, in order (they may see different items, fields or counts)
  - repeats:    added code that already exists elsewhere in the repo (one source of truth, see docs/practices.md)
  - log_lines:  removed or edited log lines that the map's counting rules match (the map would stop counting)
  - baseline:   each step's numbers in the latest finished run, to compare with after the change is merged
"""

from __future__ import annotations

import re
import subprocess
from collections import deque
from pathlib import Path

SOURCE = {".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".rb", ".go", ".rs", ".java", ".sh", ".sql"}
WINDOW = 4  # lines in a row that count as "the same code"
TRIVIAL = re.compile(r"^[\s\])}{(\[,;:]*$|^(return|pass|break|continue|else:?|try:|finally:|\}|end)$")
PLACEHOLDER = re.compile(r"\{[^}]*\}|%[sdfr]|\$\{[^}]*\}")
STRING = re.compile(r"(?:f|r|b)?(['\"])(.*?)(?<!\\)\1")


def downstream(fmap: dict, step_ids: list[str]) -> list[str]:
    """Steps after the given ones, in map order, following the map's edges."""
    nxt: dict[str, list[str]] = {}
    for e in fmap.get("edges") or []:
        nxt.setdefault(e["source"], []).append(e["target"])
    seen, queue = set(step_ids), deque(step_ids)
    while queue:
        for t in nxt.get(queue.popleft(), []):
            if t not in seen:
                seen.add(t)
                queue.append(t)
    order = [s["id"] for s in fmap.get("steps") or []]
    return [s for s in order if s in seen and s not in step_ids]


def touched_steps(fmap: dict, files: list[str]) -> tuple[list[str], list[str]]:
    """(steps whose `file` is among the changed files, changed source files no step points at)."""
    touched, mapped = [], set()
    for s in fmap.get("steps") or []:
        f = (s.get("file") or "").lstrip("./")
        if f and any(c == f or c.endswith("/" + f) or f.endswith("/" + c) for c in files):
            touched.append(s["id"])
            mapped |= {c for c in files if c == f or c.endswith("/" + f) or f.endswith("/" + c)}
    unmapped = [f for f in files if f not in mapped and Path(f).suffix.lower() in SOURCE]
    return touched, unmapped


def _norm(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())


def _meaningful(line: str) -> bool:
    n = _norm(line)
    return len(n) > 6 and not TRIVIAL.match(n) and not n.startswith(("#", "//", "import ", "from "))


def _added_blocks(diff: str) -> dict[str, list[list[str]]]:
    """{file: [runs of consecutive added, meaningful lines]}."""
    out: dict[str, list[list[str]]] = {}
    current_file, run = None, []
    for line in diff.splitlines() + ["@@"]:
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue
        if line.startswith("+") and not line.startswith("+++") and current_file:
            if _meaningful(line[1:]):
                run.append(_norm(line[1:]))
            continue
        if run and current_file:
            out.setdefault(current_file, []).append(run)
        run = []
    return out


def repeats(repo: Path, diff: str, limit: int = 5) -> list[dict]:
    """Added code that already exists elsewhere in the repo (before this change): a hint to reuse instead of copy."""
    blocks = _added_blocks(diff)
    if not blocks:
        return []
    try:
        tracked = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True, timeout=30).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        return []
    index: dict[tuple, tuple[str, int]] = {}
    for rel in tracked:
        if Path(rel).suffix.lower() not in SOURCE:
            continue
        try:
            text = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=repo, capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        if len(text) > 400_000:
            continue
        lines = [(i + 1, _norm(l)) for i, l in enumerate(text.splitlines()) if _meaningful(l)]
        for k in range(len(lines) - WINDOW + 1):
            index.setdefault(tuple(l for _, l in lines[k:k + WINDOW]), (rel, lines[k][0]))
    found = []
    for file, runs in blocks.items():
        for run in runs:
            for k in range(len(run) - WINDOW + 1):
                hit = index.get(tuple(run[k:k + WINDOW]))
                if hit:
                    found.append({"file": file, "same_as": f"{hit[0]}:{hit[1]}", "code": run[k]})
                    break
            if len(found) >= limit:
                return found
    return found


def _rule_patterns(config: dict) -> list[tuple[str, re.Pattern]]:
    """(step id, regex) for every log counting rule in a github_actions automation.yaml."""
    out = []
    for s in (config.get("map") or {}).get("steps") or []:
        specs = [s.get("in"), s.get("out"), s.get("fail"), *(s.get("skip") if isinstance(s.get("skip"), list) else [s.get("skip")])]
        if s.get("rows"):
            specs.append(s["rows"])
        for spec in specs:
            if not spec:
                continue
            pattern = spec if isinstance(spec, str) else next(
                (spec.get(k) for k in ("count", "sum", "json_counts", "pattern") if spec.get(k)), None)
            if not pattern:
                continue
            try:
                out.append((s["id"], re.compile(pattern)))
            except re.error:
                continue
    return out


def log_line_changes(config: dict, diff: str) -> list[dict]:
    """Removed lines printing text the map counts on: if the wording changes, the map stops counting that step."""
    rules = _rule_patterns(config)
    if not rules:
        return []
    found = []
    for line in diff.splitlines():
        if not line.startswith("-") or line.startswith("---"):
            continue
        for m in STRING.finditer(line[1:]):
            sample = PLACEHOLDER.sub("1", m.group(2))
            for step_id, rx in rules:
                if len(sample) > 3 and (rx.search(sample) or rx.search(sample.strip())):
                    found.append({"step": step_id, "line": line[1:].strip()[:200]})
                    break
    return found[:10]


def baseline(fmap: dict, run: dict | None) -> dict | None:
    """Each step's numbers in a finished run: the 'before' for after the change."""
    if not run or not run.get("nodes"):
        return None
    return {"run_id": run["run_id"], "started_at": run.get("started_at"), "summary": run.get("summary"),
            "steps": {sid: {"in": n.get("rows_in"), "out": n.get("rows_out"), "skipped": n.get("rows_rejected")}
                      for sid, n in run["nodes"].items()}}


def review(fmap: dict, config: dict, repo: Path, diff: str, files: list[str], run: dict | None) -> dict:
    labels = {s["id"]: s.get("label") or s["id"] for s in fmap.get("steps") or []}
    touched, unmapped = touched_steps(fmap, files)
    after = downstream(fmap, touched)
    return {"touched": [{"id": s, "label": labels[s]} for s in touched],
            "downstream": [{"id": s, "label": labels[s]} for s in after],
            "unmapped_files": unmapped,
            "repeats": repeats(repo, diff),
            "log_lines": [{**x, "label": labels.get(x["step"], x["step"])} for x in log_line_changes(config, diff)],
            "baseline": baseline(fmap, run)}
