"""What's wrong right now, and the next step for each problem: the chat's first message when a flow has errors.

Gathered from what Flowhaus already knows (no model call, so it's ready the moment the chat opens):
  - the run you're looking at failed, or one of its steps did
  - error-level insights about recent runs, and error-level harness findings
  - problems in the map's config

Each problem gets a short next step from its error message: an expired key, a rate limit, an app that didn't answer, a
missing field, a missing file, broken code, ... (the usual failure classes of automations: classify, then act). The
step is a suggestion, worded as one, and the chat prompt behind "Solve it" asks the chat to check it against the log
and the code before changing anything.

Each problem: {id, title, detail, next_step, prompt, node_id, kind, evidence, unseen}: `evidence` is what the next step
is based on (the log lines, or the numbers), `unseen` says what Flowhaus couldn't see, so a guess reads as one.
"""

from __future__ import annotations

import re

from server import flows

MAX_PROBLEMS = 5

# (kind, pattern in the error message, next step); {app}, {step}, {file} and {what} are filled in. First match wins.
RULES: list[tuple[str, re.Pattern, str]] = [
    ("auth", re.compile(r"\b(401|403)\b|unauthori[sz]ed|forbidden|invalid (api )?key|expired|revoked|oauth|credential|"
                r"not (logged|signed) in|authenticat|permission denied|access denied", re.I),
     "Renew {app}'s key or login where the automation keeps it (it expired or lacks access), then run it again."),
    ("transient", re.compile(r"\b429\b|rate.?limit|too many requests|quota|throttl", re.I),
     "{app} turned away too many requests. Run it again later, and add retries with a pause so this passes by itself."),
    ("credits", re.compile(r"credit|billing|payment required|\b402\b|insufficient (funds|balance)", re.I),
     "{app} is out of credits. Top up the account or raise the plan limit, then run it again."),
    ("transient", re.compile(r"\b5\d\d\b|timed? ?out|timeout|unavailable|connection (refused|reset|error)|could not connect|"
                r"network|ECONN|ETIMEDOUT|bad gateway", re.I),
     "{app} didn't answer. Run it again; if it keeps happening, add retries with a pause."),
    ("connect", re.compile(r"(?:(?P<what>[A-Za-z][\w -]{1,40}?) (?:is |was )?)?(?:not mounted|not connected|unplugged|offline)", re.I),
     "Connect {what}, then run it again."),
    ("gone", re.compile(r"no longer exists|_not_found|unknown (channel|sheet|list|table|board)|archived|has been deleted", re.I),
     "“{step}” points at something that no longer exists in {app}. Point it at one that does (a channel, sheet, list, "
     "...), in the automation's settings."),
    ("file", re.compile(r"no such file|file not found|FileNotFoundError|does not exist|cannot find|not found", re.I),
     "Check the input of “{step}”: something it reads isn't there. Point it at the right file, or add a check that "
     "skips with a reason when it's missing."),
    ("data", re.compile(r"REQUIRED_FIELD_MISSING|KeyError|missing|is empty|\bnull\b|no column|required field|is required", re.I),
     "An item reached “{step}” without a field it needs. Skip such items with a reason earlier in the flow, or fill "
     "the field before this step."),
    ("duplicate", re.compile(r"duplicate|already exists|unique|conflict|\b409\b", re.I),
     "“{step}” tried to create something that already exists. Make it update instead of create (match on a stable "
     "id), so a run can safely happen twice."),
    ("code", re.compile(r"SyntaxError|NameError|TypeError|AttributeError|ImportError|ModuleNotFoundError|ValueError|"
                r"IndexError|Traceback|could not be loaded", re.I),
     "The code behind “{step}” broke ({kind}). Fix it in {file}; the chat can find the line."),
]
DEFAULT = "Read the log of “{step}” for the cause; the chat can trace it in {file}."
# How urgent each kind is (lower first): blockers stop every run until fixed, hiccups often pass by themselves.
URGENCY = {"auth": 0, "credits": 0, "gone": 0, "code": 0, "connect": 1, "file": 1, "data": 2, "duplicate": 2,
           "other": 2, "transient": 3}
BLOCKERS = {"auth", "credits", "gone", "code", "connect", "file"}


def classify(message: str) -> str:
    """The kind of failure: auth, credits, transient, connect, gone, file, data, duplicate, code, or other."""
    return next((kind for kind, pattern, _ in RULES if pattern.search(message or "")), "other")


KINDS = tuple(dict.fromkeys(kind for kind, _, _ in [*RULES])) + ("other",)


def next_step(message: str, step: dict | None, kind: str | None = None) -> str:
    """One sentence: what to do about this error first. `kind`, when the automation declared it (a `fail` rule's
    `kind:`), wins over guessing from the message's words."""
    step = step or {}
    error_name = next((m.group(0) for m in [re.search(r"\b[A-Z][A-Za-z]+Error\b", message or "")] if m), "an error")
    fill = {"app": step.get("app") or "The outside app", "step": step.get("label") or step.get("id") or "this step",
            "file": f"`{step['file']}`" if step.get("file") else "its code", "kind": error_name}
    if kind and kind != "other":
        text = next((t for k, _, t in RULES if k == kind), None)
        if text:
            return text.format(**fill, what="what's missing")
    for _, pattern, text in RULES:
        if m := pattern.search(message or ""):
            what = (m.groupdict().get("what") or "").strip()
            return text.format(**fill, what=f"the {what[0].lower()}{what[1:]}" if what else "what's missing")
    return DEFAULT.format(**fill)


def evidence(node: dict | None, run: dict | None) -> tuple[list[str], str | None]:
    """The log lines a failure's next step rests on (errors and warnings, last ones first), or what's missing."""
    log = list((node or {}).get("log") or []) or list((run or {}).get("log") or [])
    message = ((node or {}).get("error") or {}).get("message") or ""
    # lines that only repeat the error message add nothing
    lines = [t for ln in log if ln.get("level") in ("error", "warn") and (t := ln.get("text") or "")
             and message not in t]
    if lines:
        return [ln[:300] for ln in lines[-2:]], None
    return [], "Based on the error message only: there are no log lines for this step."


def _first_sentence(text: str, limit: int = 220) -> str:
    text = " ".join((text or "").split())
    end = re.search(r"(?<=[.!?])\s", text)
    text = text[: end.start()] if end else text
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def problems(flow_id: str, run_id: str | None = None, found_insights: list[dict] | None = None,
             review: dict | None = None) -> list[dict]:
    """What's wrong with this flow now, most urgent first: the run (if it failed), then findings, then the map.
    `found_insights` and `review` save working them out again when the caller already has them (the checkup)."""
    from server import harness, insights

    fmap = flows.get_map(flow_id)
    steps = {s["id"]: s for s in fmap["steps"]}
    out: list[dict] = []

    if run_id is None:
        latest = next(iter(flows.list_runs(flow_id)), None)
        run_id = latest["run_id"] if latest else None
    run = flows.get_run(flow_id, run_id) if run_id else None
    if run and run.get("status") == "failed":
        failed = [nid for nid, n in (run.get("nodes") or {}).items() if n.get("status") == "failed"]
        error = run.get("error") or {}
        if error.get("node_id") and error["node_id"] not in failed:
            failed.insert(0, error["node_id"])
        for nid in failed or [None]:
            node = (run.get("nodes") or {}).get(nid) or {}
            message = ((node.get("error") or {}).get("message") if nid else None) or error.get("message") or "The run failed."
            declared = (node.get("error") or {}).get("kind") or (error.get("kind") if nid == error.get("node_id") else None)
            step = steps.get(nid) if nid else None
            where = f"“{step.get('label') or nid}”" if step else "the run"
            seen, unseen = evidence(node, run)
            out.append({
                "id": f"run:{nid or 'run'}", "node_id": nid, "title": f"Failed in {where}",
                "kind": declared if declared in KINDS else classify(message), "priority": "P0",
                "evidence": seen, "unseen": unseen,
                "detail": _first_sentence(message), "next_step": next_step(message, step, declared),
                "prompt": (f"The run failed in {where}: {message}\nFind the cause from the log and the code, and tell "
                           "me the shortest fix. Don't change anything yet."),
            })

    for item in insights.insights(flow_id) if found_insights is None else found_insights:
        if item.get("level") == "error" and not any(p.get("node_id") and p["node_id"] == item.get("node_id") for p in out):
            step = steps.get(item.get("node_id") or "")
            out.append({
                "id": f"insight:{item.get('kind')}:{item.get('node_id') or ''}", "node_id": item.get("node_id"),
                "kind": classify(f"{item['title']} {item.get('detail') or ''}"), "priority": "P0",
                "evidence": item.get("evidence") or [], "unseen": None,
                "title": item["title"], "detail": _first_sentence(item.get("detail") or ""),
                "next_step": item.get("next_step") or next_step(f"{item['title']} {item.get('detail') or ''}", step),
                "prompt": f"{item['title']}. {item.get('detail') or ''}\nWhat's the cause, and what should I do first?",
            })

    if flows.kind(flow_id) == "connected":
        for f in (harness.review(flow_id) if review is None else review).get("findings", []):
            if f.get("level") == "error":
                out.append({
                    "id": f"finding:{f['id']}", "node_id": f.get("node_id"), "title": f["title"], "kind": "other",
                    "priority": "P0",
                    "evidence": [], "unseen": None,
                    "detail": _first_sentence(f.get("detail") or ""),
                    "next_step": f.get("next_step") or _first_sentence(f.get("detail") or ""),
                    "prompt": f.get("ask") or f"{f['title']}. {f.get('detail') or ''}\nHow do I fix this?",
                })

    if fmap.get("problems"):
        first = fmap["problems"][0]
        more = len(fmap["problems"]) - 1
        out.append({
            "id": "map", "node_id": None, "kind": "other", "priority": "P1", "evidence": fmap["problems"][:3], "unseen": None,
            "title": "The map has a problem" if not more else f"The map has {more + 1} problems",
            "detail": _first_sentence(first), "next_step": "Fix the map's config so every step, path and end is described.",
            "prompt": "The map has these problems:\n- " + "\n- ".join(fmap["problems"]) + "\nFix them, or tell me how.",
        })
    order = [s["id"] for s in fmap["steps"]]
    source = {"run": 0, "insight": 1, "finding": 2, "map": 3}

    def urgency(p: dict) -> tuple:
        # the run's failures first, earliest step first (later errors are often its consequences); then blockers
        # before data problems before brief hiccups; then findings about the flow, then the map
        pos = order.index(p["node_id"]) if p.get("node_id") in order else len(order)
        return source[p["id"].split(":")[0]], pos, URGENCY.get(p["kind"], 2)

    return sorted(out, key=urgency)[:MAX_PROBLEMS]


def plan(flow_id: str, run_id: str | None = None, found_insights: list[dict] | None = None,
         review: dict | None = None) -> dict:
    """Which problem to solve first, why, and its next step; the rest as "also". {first, others} (first: None if
    nothing is wrong)."""
    found = problems(flow_id, run_id, found_insights, review)
    if not found:
        return {"first": None, "others": []}
    first, others = found[0], found[1:]
    return {"first": {**first, "why": _why_first(first, others)}, "others": others}


def _why_first(first: dict, others: list[dict]) -> str | None:
    if not others:
        return None
    if first["id"].startswith("run:"):
        if any(o["id"].startswith("run:") for o in others):
            return "It's the earliest failure: the steps after it can't run until it's fixed."
        if first["kind"] in BLOCKERS:
            return "It stops every run until it's fixed; the other problems don't."
        return "It's what made this run fail; the other problems don't stop it."
    return "It's the most serious of the open problems."
