"""Hierarchy builder: turns pipeline steps + flow_map.yaml groups into map levels.

Steps have a kind, drawn as flowchart shapes (Blue Prism style):
  action    (default) a box that does something
  decision  a diamond with a question; `branches: [{label: "Yes", to: step_id, when: "the rule in words"}]`.
            With three or more answers it's a choice: the answers are checked top-down and the first that fits
            wins, so the last one is usually `{label: Otherwise, otherwise: true}` for everything else
  wait      a step that holds items: "Held for review", "Waiting for provider"
  end       a pill that says how a path ends: "Published", "Skipped: coaching not requested"
The flow's trigger is its start. A step goes to the next listed step unless it says `next:` (or `branches:`);
steps never fall through into an `end` step: ends are reached on purpose.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from server import runtime

FLOW_MAP_PATH = runtime.ROOT / "flow_map.yaml"
ROOT_LEVEL = "root"
_HEADER = (
    "# Concept groups shown on the map. Steps (Hamilton functions in pipeline/)\n"
    "# point at a group through their `group` tag. `parent` empty = top level.\n"
)


def read_title(path: Path = FLOW_MAP_PATH) -> str:
    data = read_yaml(path)
    return data.get("title") or data.get("name") or "Flow"


def read_groups(path: Path = FLOW_MAP_PATH) -> list[dict]:
    data = read_yaml(path)
    groups = []
    for g in data.get("groups") or []:
        groups.append(
            {
                "id": str(g["id"]),
                "label": g.get("label") or str(g["id"]),
                "description": g.get("description") or "",
                "parent": g.get("parent") or None,
            }
        )
    return groups


def read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text()) if path.exists() else None
    except yaml.YAMLError:
        data = None
    return data if isinstance(data, dict) else {}


def write_yaml(data: dict, path: Path) -> None:
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    path.write_text((_HEADER if path == FLOW_MAP_PATH else "") + body)


def write_groups(groups: list[dict], path: Path = FLOW_MAP_PATH) -> None:
    """Replace the groups, keeping every other key in the file (title, trigger, terms, ...)."""
    data = read_yaml(path)
    data.setdefault("title", read_title(path))
    data["groups"] = [{k: g.get(k) for k in ("id", "label", "description", "parent")} for g in groups]
    write_yaml(data, path)


def update_group(group_id: str, label=None, description=None, parent=None, create=False,
                 path: Path = FLOW_MAP_PATH) -> dict:
    groups = read_groups(path)
    match = next((g for g in groups if g["id"] == group_id), None)
    if match is None:
        if not create:
            raise KeyError(f"No group with id '{group_id}'")
        match = {"id": group_id, "label": group_id, "description": "", "parent": None}
        groups.append(match)
    if label is not None:
        match["label"] = label
    if description is not None:
        match["description"] = description
    if parent is not None:
        match["parent"] = parent or None
    write_groups(groups, path)
    return match


def build_map(path: Path = FLOW_MAP_PATH, pipeline_dir: Path | None = None) -> dict:
    """Groups, steps, edges and the pre-computed levels the canvas renders."""
    try:
        steps, edges, inputs = runtime.describe_steps(pipeline_dir)
        load_error = None
    except Exception as exc:  # broken code must not take the UI down
        steps, edges, inputs = [], [], []
        load_error = f"{type(exc).__name__}: {exc}"
    groups = read_groups(path)
    problems = validate(groups, steps)
    if load_error:
        problems.insert(0, f"The pipeline code could not be loaded: {load_error}")
    return {
        "title": read_title(path),
        "groups": groups,
        "steps": steps,
        "edges": edges,
        "inputs": inputs,
        "levels": build_levels(groups, steps, edges),
        "problems": problems,
    }


KINDS = ("action", "decision", "wait", "end")


def kind_of(step: dict) -> str:
    return step.get("kind") if step.get("kind") in KINDS else "action"


def is_otherwise(branch: dict) -> bool:
    """The catch-all answer of a choice: `otherwise: true`, or labelled "Otherwise"/"Else"."""
    return branch.get("otherwise") is True or str(branch.get("label") or "").strip().lower() in ("otherwise", "else", "anything else")


def chain_edges(steps: list[dict]) -> list[dict]:
    """The paths between steps: next in the list, `next:`, or a decision's labelled `branches:`."""
    edges: list[dict] = []
    for i, s in enumerate(steps):
        kind = kind_of(s)
        if kind == "end":
            continue
        if kind == "decision" and s.get("branches"):
            answers = [b for b in s["branches"] if isinstance(b, dict) and b.get("to")]
            for n, b in enumerate(answers, 1):
                edge = {"source": s["id"], "target": str(b["to"]), "label": b.get("label"), "when": b.get("when")}
                if len(answers) > 2:  # a choice: answers are checked in this order
                    edge.update(order=n, otherwise=is_otherwise(b))
                edges.append(edge)
            continue
        if s.get("next"):
            for t in s["next"] if isinstance(s["next"], list) else [s["next"]]:
                edges.append({"source": s["id"], "target": str(t)})
            continue
        if i + 1 < len(steps) and kind_of(steps[i + 1]) != "end":  # otherwise this path ends at the flow's result
            edges.append({"source": s["id"], "target": steps[i + 1]["id"]})
    return edges


def always_reached(steps: list[dict], edges: list[dict]) -> set[str]:
    """Steps every run reaches: from the first step, along lines that don't go through a decision's answers. A step
    only one answer leads to (or that comes after one) may rightly not run."""
    kinds = {s["id"]: kind_of(s) for s in steps}
    out: dict[str, list[dict]] = {}
    for e in edges:
        out.setdefault(e["source"], []).append(e)
    seen: set[str] = set()
    todo = [steps[0]["id"]] if steps else []
    while todo:
        sid = todo.pop()
        if sid in seen or sid not in kinds:
            continue
        seen.add(sid)
        if kinds[sid] != "decision":
            todo += [e["target"] for e in out.get(sid, [])]
    return seen


def path_problems(steps: list[dict], edges: list[dict], has_start: bool, has_end: bool) -> list[str]:
    """Start, ends and branches: every path starts at the trigger and reaches an end."""
    problems = []
    ids = {s["id"] for s in steps}
    if not has_start:
        problems.append("The map has no start: say what starts it in `trigger.label` (e.g. \"Weekdays at 7:00\")")
    if not has_end and not any(kind_of(s) == "end" for s in steps):
        problems.append("The map has no end: add `output.label` (where results go) or steps with `kind: end`")
    out: dict[str, list[dict]] = {}
    for e in edges:
        out.setdefault(e["source"], []).append(e)
        if e["target"] not in ids:
            problems.append(f"Step '{e['source']}' goes to '{e['target']}', which isn't a step")
    for s in steps:
        kind = kind_of(s)
        if s.get("kind") and s["kind"] not in KINDS:
            problems.append(f"Step '{s['id']}': kind must be one of {', '.join(KINDS)}")
        if kind == "decision":
            branches = [b for b in s.get("branches") or [] if isinstance(b, dict)]
            if len(branches) < 2:
                problems.append(f"Decision '{s['id']}' needs at least two `branches` (e.g. Yes and No)")
            for b in branches:
                if not b.get("label"):
                    problems.append(f"Decision '{s['id']}': every branch needs a `label` (e.g. \"Yes\")")
            fallbacks = [i for i, b in enumerate(branches) if is_otherwise(b)]
            if len(fallbacks) > 1:
                problems.append(f"Decision '{s['id']}' has more than one \"Otherwise\" answer")
            elif fallbacks and fallbacks[0] != len(branches) - 1:
                problems.append(f"Decision '{s['id']}': \"Otherwise\" must be the last answer (answers are checked top-down)")
        if kind == "end" and (s.get("next") or s.get("branches")):
            problems.append(f"End '{s['id']}' can't go anywhere after it")
    reached = {e["target"] for e in edges}
    for s in steps[1:]:
        if s["id"] not in reached:
            problems.append(f"Nothing leads to '{s['id']}': give the step before it `next: {s['id']}`, or a branch")
    return problems


def ancestors(node_id: str, groups: list[dict], steps: list[dict]) -> list[str]:
    """Chain of group ids from the top level down to (not including) node_id."""
    parent_of = {g["id"]: g["parent"] for g in groups}
    parent_of.update({s["id"]: s["group"] for s in steps})
    chain, seen = [], set()
    current = parent_of.get(node_id)
    while current and current not in seen and current in parent_of:
        seen.add(current)
        chain.append(current)
        current = parent_of.get(current)
    return list(reversed(chain))


def descendant_steps(group_id: str, groups: list[dict], steps: list[dict]) -> list[str]:
    return [s["id"] for s in steps if group_id in ancestors(s["id"], groups, steps)]


# Readers are assumed to know what a junior software engineer knows (API, JSON, webhook, cron, query are fine), so only
# names from inside the code are flagged: they mean nothing to someone who hasn't read it.
CODE_WORDS = re.compile(r"\b(DataFrame|dataframe|node|dict|kwargs|args|stdout|stderr|traceback|NoneType|lambda|"
                        r"self|df)\b")
NOT_VERBS = {"This", "Its", "Is", "Has", "Was", "Does", "Gets", "Lets"}


def conventions(steps: list[dict], groups: list[dict], config: dict | None = None) -> list[dict]:
    """How well the map follows the writing conventions (AGENTS.md, docs/automations.md). Warnings, not errors:
    `flowhaus check` shows them and fails on them only with --strict (for CI). Each: {id, step, message, fix}."""
    out: list[dict] = []

    def warn(id_: str, step: str | None, message: str, fix: str) -> None:
        out.append({"id": id_, "step": step, "message": message, "fix": fix})

    for s in steps:
        sid, label, desc = s["id"], (s.get("label") or "").strip(), (s.get("description") or "").strip()
        if desc and kind_of(s) in ("action", "wait"):
            first = desc.split()[0].strip(".,:;")
            if not (re.fullmatch(r"[A-Z][a-z]+s", first) and first not in NOT_VERBS):
                warn(f"description_verb:{sid}", sid, f"“{label or sid}”: the description doesn't start with what the "
                     "step gives you", "Start with a verb: “Gives you …”, “Adds …”, “Keeps …”, “Skips …”.")
        if len(label.split()) > 6:
            warn(f"label_long:{sid}", sid, f"“{label}” is a long label ({len(label.split())} words)",
                 "Use a short verb phrase (2 to 5 words); put the rest in the description.")
        if m := CODE_WORDS.search(f"{label} {desc}"):
            warn(f"code_word:{sid}", sid, f"“{label or sid}” uses the code name “{m.group(0)}”",
                 "Say what it means in plain words; readers know common technical terms, not the code's names.")
        if kind_of(s) == "decision" and not s.get("rule"):
            warn(f"decision_rule:{sid}", sid, f"Decision “{label or sid}” doesn't say its rule",
                 "Add `rule:` with the actual rule in words, e.g. “The coaching date is filled in”.")
    if config is not None and not (config.get("terms") or {}).get("items"):
        warn("no_terms", None, "The map calls everything “items”",
             "Add `terms: {item: …, items: …}` (e.g. lead/leads), so every number reads naturally.")
    return out


def without_single_child_groups(fmap: dict) -> dict:
    """A box with only one thing inside has nothing to open: show that thing in its place.

    Repeats until none is left (a box whose only child was such a box goes too), then lays out the levels again.
    """
    groups = [dict(g) for g in fmap["groups"]]
    steps = [dict(s) for s in fmap["steps"]]
    while True:
        def inside(gid: str) -> list[dict]:
            return [g for g in groups if g.get("parent") == gid] + [s for s in steps if s.get("group") == gid]

        lone = next((g for g in groups if len(inside(g["id"])) == 1), None)
        if lone is None:
            break
        child = inside(lone["id"])[0]
        child["parent" if child in groups else "group"] = lone.get("parent")
        groups = [g for g in groups if g["id"] != lone["id"]]
    if len(groups) == len(fmap["groups"]):
        return fmap
    return {**fmap, "groups": groups, "steps": steps, "levels": build_levels(groups, steps, fmap["edges"])}


def build_levels(groups: list[dict], steps: list[dict], edges: list[dict]) -> dict:
    """For every level (root + each group): its child nodes and the edges between them.

    Step edges are lifted to the child of the level that contains each end.
    Edges crossing the level boundary become `inbound`/`outbound` markers so the
    drilled-in view can show where data comes from and goes to.
    """
    group_ids = {g["id"] for g in groups}
    step_ids = [s["id"] for s in steps]
    paths = {s["id"]: ancestors(s["id"], groups, steps) + [s["id"]] for s in steps}
    levels = {}
    for level in [ROOT_LEVEL] + [g["id"] for g in groups]:
        children = [g["id"] for g in groups if (g["parent"] or ROOT_LEVEL) == level]
        children += [s["id"] for s in steps if (s["group"] if s["group"] in group_ids else ROOT_LEVEL) == level]

        def child_for(step_id: str) -> str | None:
            path = paths[step_id]
            if level == ROOT_LEVEL:
                return path[0]
            if level in path:
                idx = path.index(level)
                return path[idx + 1] if idx + 1 < len(path) else None
            return None

        def top_label(step_id: str) -> str:
            return paths[step_id][0]

        level_edges, inbound, outbound = [], [], []
        for e in edges:
            if e["source"] not in paths or e["target"] not in paths:
                continue  # a line to a step that doesn't exist (a typo): path_problems reports it, the map still opens
            a, b = child_for(e["source"]), child_for(e["target"])
            if a and b and a != b:
                item = {"source": a, "target": b}
                if e.get("label") and a == e["source"]:  # a branch label stays on the line that leaves the decision
                    item.update({k: e[k] for k in ("label", "when", "order", "otherwise") if k in e})
                if not any(x["source"] == a and x["target"] == b and x.get("label") == item.get("label") for x in level_edges):
                    level_edges.append(item)
            elif b and not a:
                item = {"from": top_label(e["source"]), "target": b}
                if item not in inbound:
                    inbound.append(item)
            elif a and not b:
                item = {"source": a, "to": top_label(e["target"])}
                if item not in outbound:
                    outbound.append(item)
        # keep children in execution order of their first step
        first_index = {}
        for i, sid in enumerate(step_ids):
            for node in paths[sid]:
                first_index.setdefault(node, i)
        children.sort(key=lambda c: first_index.get(c, len(step_ids)))
        levels[level] = {"children": children, "edges": level_edges, "inbound": inbound, "outbound": outbound}
    return levels


def validate(groups: list[dict], steps: list[dict]) -> list[str]:
    """Plain-English list of problems; empty list means the map is valid."""
    problems = []
    group_ids = [g["id"] for g in groups]
    for dup in {g for g in group_ids if group_ids.count(g) > 1}:
        problems.append(f"Group id '{dup}' is used more than once in flow_map.yaml")
    for s in steps:
        for tag in ("label", "description", "group"):
            if not s.get(tag):
                problems.append(f"Step '{s['id']}' has no '{tag}' tag")
        if s.get("group") and s["group"] not in group_ids:
            problems.append(f"Step '{s['id']}' points at group '{s['group']}', which is not in flow_map.yaml")
    for g in groups:
        if g["parent"] and g["parent"] not in group_ids:
            problems.append(f"Group '{g['id']}' has parent '{g['parent']}', which does not exist")
        has_child = any(s.get("group") == g["id"] for s in steps) or any(x["parent"] == g["id"] for x in groups)
        if not has_child:
            problems.append(f"Group '{g['id']}' has no steps or sub-groups in it")
        chain, current, seen = 0, g["parent"], set()
        while current:
            if current in seen:
                problems.append(f"Group '{g['id']}' is part of a parent loop")
                break
            seen.add(current)
            chain += 1
            current = next((x["parent"] for x in groups if x["id"] == current), None)
        if chain > 3:
            problems.append(f"Group '{g['id']}' is nested more than 4 levels deep")
    return problems
