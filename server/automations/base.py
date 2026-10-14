"""The contract every connected automation implements, plus shared helpers.

An *automation* is something the user already runs elsewhere (a GitHub Actions workflow, a
script that writes a folder per run, ...). Flowhaus only reads it, except for the optional
on/off switch. Each automation is described by `automations/<id>/automation.yaml`.

Run dicts use the same shape as the rest of the app (see server/runs.py):
    {run_id, status, started_at, finished_at, trigger, summary, error,
     nodes: {step_id: {status, rows_in, rows_out, rows_rejected, reject_reasons, sample_out, log, error, ...}},
     groups: {...}, input_items, output_items}
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from server import maps

SLUG = re.compile(r"[^a-z0-9]+")
ROOT = Path(__file__).resolve().parent.parent.parent


def too_broad(p: Path) -> bool:
    """A code folder the chat may read must be one project, not the home folder, a disk, or a folder holding Flowhaus."""
    home = Path.home().resolve()
    return p == Path(p.anchor) or p == home or p in home.parents or p == ROOT or p in ROOT.parents


def slugify(text: str) -> str:
    return SLUG.sub("-", text.lower()).strip("-")[:60] or "step"


def expand(path: str | None, base: Path | None = None) -> Path | None:
    if not path:
        return None
    p = Path(path).expanduser()
    if not p.is_absolute() and base is not None:
        p = base / p
    return p.resolve()


def empty_node(step: dict) -> dict:
    return {"status": "not_run", "label": step.get("label") or step["id"], "group": step.get("group"),
            "duration_ms": None, "rows_in": None, "rows_out": None, "rows_rejected": 0, "rows_changed": 0,
            "sample_in": [], "sample_out": [], "rejected_samples": [], "reject_reasons": {}, "log": [],
            "error": None, "paired": False}


def _span(members: list[str], nodes: dict, first: str | None = None, last: str | None = None) -> dict:
    """In/out/skipped across a run of steps: in from the first step that counted something coming in, out from the
    last step that counted something going out. Skipped is in − out when that adds up (same kind of item);
    otherwise the steps' own skip counts are added up."""
    with_in = [m for m in members if nodes[m].get("rows_in") is not None]
    with_out = [m for m in members if nodes[m].get("rows_out") is not None]
    first = first or (with_in[0] if with_in else None)
    last = last or (with_out[-1] if with_out else None)
    rows_in = nodes[first]["rows_in"] if first else None
    rows_out = nodes[last]["rows_out"] if last else None
    if rows_in is not None and rows_out is not None and rows_in >= rows_out:
        skipped = rows_in - rows_out
    else:
        skipped = sum(nodes[m].get("rows_rejected") or 0 for m in members)
    return {"rows_in": rows_in, "rows_out": rows_out, "rows_rejected": skipped}


def run_totals(steps: list[dict], nodes: dict, io: dict | None = None) -> dict:
    """The run's summary numbers. `io: {input_step, output_step}` in automation.yaml picks the steps explicitly."""
    io = io or {}
    ids = [s["id"] for s in steps if s["id"] in nodes]
    t = _span(ids, nodes, io.get("input_step"), io.get("output_step"))
    return {"rows_read": t["rows_in"], "rows_written": t["rows_out"], "rows_rejected": t["rows_rejected"]}


def group_results(groups: list[dict], steps: list[dict], nodes: dict) -> dict:
    """Roll step results up into their groups (counts, reasons, last step's table)."""
    out = {}
    for g in groups:
        members = [s["id"] for s in steps if s.get("group") == g["id"] and s["id"] in nodes
                   and nodes[s["id"]]["status"] != "not_run"]
        if not members:
            continue
        last = nodes[members[-1]]
        reasons: Counter = Counter()
        for m in members:
            reasons.update(nodes[m]["reject_reasons"])
        out[g["id"]] = {**_span(members, nodes), "rows_changed": 0,
                        "sample_in": [], "sample_out": last["sample_out"],
                        "rejected_samples": [r for m in members for r in nodes[m]["rejected_samples"]][:200],
                        "reject_reasons": dict(reasons), "paired": False}
    return out


TOP_KEYS = {"id", "type", "name", "description", "trigger", "terms", "input_terms", "output", "next_run", "state_label",
            "local_path", "private_paths", "apps", "map", "summary", "io", "kpis", "module", "pull_requests",
            "test"}
STEP_KEYS = {"id", "label", "description", "group", "app", "file", "unit"}
GROUP_KEYS = {"id", "label", "description", "parent"}


def unknown_keys(where: str, given: dict, known: set[str]) -> list[str]:
    return [f"{where}: unknown setting `{k}` (a typo? known: {', '.join(sorted(known))})" for k in given if k not in known]


class Automation:
    """Base class. Subclasses implement list_runs() and get_run(); the rest has sensible defaults."""

    kind_label = "connected"
    extra_keys: set[str] = set()  # top-level settings a type adds (e.g. github, folder_runs)
    step_keys: set[str] | None = None  # settings a type adds to steps; None = any (python adapters)

    def __init__(self, config: dict, folder: Path):
        self.config = config
        self.folder = folder
        self.id: str = config["id"]
        self.steps: list[dict] = [dict(s) for s in (config.get("map") or {}).get("steps") or []]
        self.groups: list[dict] = [{"parent": None, "description": "", **g} for g in (config.get("map") or {}).get("groups") or []]
        for s in self.steps:
            s.setdefault("group", None)
            s.setdefault("description", "")

    # ---- what the app shows ------------------------------------------------------------

    def source_label(self) -> str:
        return "this computer"

    def meta(self) -> dict:
        c = self.config
        return {
            "id": self.id,
            "name": c.get("name") or self.id,
            "description": c.get("description") or "",
            "trigger": {"type": "manual", "label": "Runs where it lives", **(c.get("trigger") or {})},
            "terms": {"item": "item", "items": "items", **(c.get("terms") or {})},
            "input_terms": c.get("input_terms"),
            "output": c.get("output") or {"label": "What came out"},
            "next_run": c.get("next_run") or "When it next runs",
            "kind": "connected",
            "enabled": True,
            "read_only": True,
            "can_toggle": False,
            "state_label": c.get("state_label") or "Runs where it lives",
            "source": {"label": self.source_label(), "path": str(self.local_path() or "")},
        }

    def get_map(self) -> dict:
        steps = [{**s, "line": None, "inputs": [], "file": s.get("file")} for s in self.steps]
        edges = [{"source": a["id"], "target": b["id"]} for a, b in zip(steps, steps[1:])]
        return {"title": self.meta()["name"], "groups": self.groups, "steps": steps, "edges": edges, "inputs": [],
                "levels": maps.build_levels(self.groups, steps, edges),
                "problems": maps.validate(self.groups, steps) if self.groups else []}

    # ---- runs --------------------------------------------------------------------------

    def list_runs(self) -> list[dict]:
        raise NotImplementedError

    def get_run(self, run_id: str) -> dict | None:
        raise NotImplementedError

    def cached_run(self, run_id: str) -> dict | None:
        """Details only if cheap to get (used by the activity feed). Default: same as get_run."""
        return self.get_run(run_id)

    def freshness(self) -> dict:
        """When the runs shown were read, and whether reading failed. Flowhaus is not a live service:
        it reads when the app asks, so the UI says how old the data is instead of pretending."""
        from datetime import datetime

        return {"source": self.source_label(), "checked_at": datetime.now().isoformat(timespec="seconds"), "error": None}

    # ---- optional ----------------------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        raise ValueError("This automation can't be switched on or off from here.")

    def local_path(self) -> Path | None:
        """The automation's own code folder. The chat agent may READ it (never write)."""
        return expand(self.config.get("local_path"))

    def readable_code_path(self) -> Path | None:
        """local_path, if it is narrow enough for the chat to read."""
        p = self.local_path()
        return None if p is None or too_broad(p) else p

    def private_paths(self) -> list[Path]:
        """Folders the chat agent must never read (personal data), relative to local_path or absolute."""
        base = self.local_path()
        return [p for p in (expand(x, base) for x in self.config.get("private_paths") or []) if p]

    def agent_context(self, run: dict | None) -> dict:
        runs = self.list_runs()[:12]
        return {
            "automation": {k: self.meta()[k] for k in ("name", "description", "trigger", "output", "source")},
            "groups": self.groups, "steps": self.steps,
            "recent_runs": [{k: r.get(k) for k in ("run_id", "status", "started_at", "trigger", "summary", "error")} for r in runs],
            "run_being_viewed": None if not run else {
                "run_id": run["run_id"], "status": run["status"], "error": run.get("error"),
                "steps": {nid: {k: n.get(k) for k in ("status", "rows_in", "rows_out", "rows_rejected", "reject_reasons", "log", "error")}
                          for nid, n in run["nodes"].items()}},
        }

    def check(self) -> list[str]:
        """Problems a human or agent should fix in the config (empty = fine)."""
        problems = []
        if not self.steps:
            problems.append("The map has no steps (add map.steps to automation.yaml)")
        ids = [s["id"] for s in self.steps]
        problems += [f"Step id '{i}' is used twice" for i in {i for i in ids if ids.count(i) > 1}]
        for key in ("name", "description"):
            if "TODO" in str(self.config.get(key) or ""):
                problems.append(f"`{key}` still has a TODO")
        for g in self.groups:
            if "TODO" in f"{g.get('label')} {g.get('description')}":
                problems.append(f"Group '{g['id']}' still has a TODO")
        group_ids = {g["id"] for g in self.groups}
        for s in self.steps:
            if not s.get("label"):
                problems.append(f"Step '{s['id']}' has no label")
            if not s.get("description"):
                problems.append(f"Step '{s['id']}' has no description")
            if "TODO" in f"{s.get('label')} {s.get('description')}":
                problems.append(f"Step '{s['id']}' still has a TODO in its label or description")
            if s.get("group") and s["group"] not in group_ids:
                problems.append(f"Step '{s['id']}' points at unknown group '{s['group']}'")
        if self.step_keys is not None:  # built-in types: catch typos like `outptu:` or `produce:`
            problems += unknown_keys("automation.yaml", self.config, TOP_KEYS | self.extra_keys)
            for s in self.steps:
                problems += unknown_keys(f"step '{s['id']}'", s, STEP_KEYS | self.step_keys)
            for g in (self.config.get("map") or {}).get("groups") or []:
                problems += unknown_keys(f"group '{g.get('id')}'", g, GROUP_KEYS)
        if self.groups:  # same rules the app uses to draw the map
            problems += [p.replace("flow_map.yaml", "the map").replace("tag", "field")
                         for p in maps.validate(self.groups, self.steps) if "has no 'label'" not in p
                         and "has no 'description'" not in p and "which is not in" not in p]
        lp = self.local_path()
        if self.config.get("local_path") and (lp is None or not lp.exists()):
            problems.append(f"local_path does not exist: {self.config.get('local_path')}")
        elif lp is not None and too_broad(lp):
            problems.append(f"local_path is too broad ({lp}): point it at the automation's own project folder")
        return problems


TEMPLATE = re.compile(r"\{([\w-]+)\.(in|out|skipped)\}")


def render_summary(template: str, nodes: dict) -> str | None:
    """'{extract.out} found → {publish.out} published' → filled in, or None if a value is missing."""
    missing = False

    def sub(m: re.Match) -> str:
        nonlocal missing
        node = nodes.get(m.group(1))
        key = {"in": "rows_in", "out": "rows_out", "skipped": "rows_rejected"}[m.group(2)]
        value = node.get(key) if node else None
        if value is None:
            missing = True
            return "?"
        return str(value)

    text = TEMPLATE.sub(sub, template)
    return None if missing else text


def as_int(value: Any) -> int | None:
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
