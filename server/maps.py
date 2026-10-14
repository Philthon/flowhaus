"""Hierarchy builder: turns pipeline steps + flow_map.yaml groups into map levels."""

from __future__ import annotations

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
            a, b = child_for(e["source"]), child_for(e["target"])
            if a and b and a != b:
                item = {"source": a, "target": b}
                if item not in level_edges:
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
