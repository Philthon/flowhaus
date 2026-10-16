"""The Review: everything wrong with a flow and how to make it better, judged against docs/practices.md, every item
with what to do about it. Two tabs:

Errors (what's wrong)
  fix_now    broken in the run you're looking at: the run failed, error-level findings (nextstep.py)
  silent     silent failures: runs that look fine but aren't, items lost or appearing between steps without a reason
             (insights.py, harness.py)
  drift      slow changes over the recent runs that no single run shows, and the same failure coming back (insights.py)
Improvements (how to make it better)
  ideas      what the numbers suggest: one reason behind most skips (insights.py)
  setup      finish setting it up: gaps against the practices, blind spots, the map's problems and conventions
             (harness.py, maps.py); with `questions`, what only you can answer

Each item: {id, source, priority, level, title, detail, next_step, prompt, node_id, evidence}; `source` is run,
insight, finding (these can be dismissed with a reason), map or convention.

Priorities follow the usual incident scale:
  P0  critical  broken now, or about to do harm: a failed run, an error-level finding
  P1  high      likely wrong without anyone noticing: silent losses, drift the wrong way, map problems
  P2  medium    worth improving: gaps against the practices, ideas from the numbers
  P3  low       polish: writing conventions
Only P0 ever blocks anything (see changes.gate); the rest are suggestions. The Review button shows the worst open
error (red for P0, yellow otherwise), or a light bulb when there are only improvements; a P0 also turns Run red.

The page asks for this once and shares it: the status strip above the map, the chat's opener (`plan`), the Review
button, the Run button and the Review all read the same answer. Nothing runs and nothing is sent: it reads the runs
and the config, like the map does.
"""

from __future__ import annotations

from server import flows, harness, insights, maps, nextstep

SILENT = {"nothing_out", "fewer_than_usual", "unexplained_loss", "skips_everything", "missed_schedule"}
DRIFT = {"output_drift", "skip_drift", "new_skip_reason", "slower", "input_shift", "failure_pattern"}
SKIP = {"repeated_failure"}  # already in fix_now, from the run itself
# findings read from the runs' numbers (how it's doing); every other finding is about how it's set up
HEALTH_FINDINGS = {"lost_between", "appear_between", "outside_expected", "skips_too_many"}
_BY_LEVEL = {"error": "P0", "warn": "P1", "info": "P2"}


def _item(x: dict, **extra) -> dict:
    level = x.get("level", "info")
    return {"id": x.get("id") or f"{x.get('kind')}:{x.get('node_id') or ''}", "level": level,
            "priority": x.get("priority") or _BY_LEVEL.get(level, "P2"),
            "title": x["title"], "detail": x.get("detail") or "", "next_step": x.get("next_step"),
            "prompt": x.get("prompt") or x.get("ask"), "node_id": x.get("node_id"),
            "evidence": x.get("evidence") or [], **extra}


def checkup(flow_id: str, run_id: str | None = None) -> dict:
    found = insights.insights(flow_id)
    h = harness.review(flow_id)
    plan = nextstep.plan(flow_id, run_id, found, h)  # worked out once, shared with the chat's opener
    fix_now = []
    for p in ([plan["first"]] if plan["first"] else []) + plan["others"]:
        if p["id"].startswith("map"):
            continue  # shown under "map"
        finding = p["id"].startswith("finding:")
        fix_now.append(_item({**p, "level": "error", "id": p["id"].split(":", 1)[1] if finding else p["id"]},
                             why=p.get("why"), unseen=p.get("unseen"), source="finding" if finding else "run"))
    silent, drift, ideas, setup = [], [], [], []
    for i in found:
        if i["kind"] in SKIP or i.get("level") == "error":
            continue
        (silent if i["kind"] in SILENT else drift if i["kind"] in DRIFT else ideas).append(_item(i, source="insight"))

    for f in h.get("findings", []):
        if f["level"] == "error":
            continue  # in fix_now already (nextstep reads error-level findings)
        (silent if f["kind"] in HEALTH_FINDINGS else setup).append(_item(f, source="finding", practice=f.get("practice")))
    questions = h.get("questions", [])

    fmap = flows.get_map(flow_id)
    if flows.kind(flow_id) == "connected":
        conv = flows.connected()[flow_id].conventions()
    else:
        conv = maps.conventions(fmap["steps"], fmap["groups"])
    setup += [_item({"id": f"map:{n}", "level": "warn", "priority": "P1", "title": p, "next_step": "Fix it in the map's config.",
                     "prompt": f"The map has this problem: {p}\nFix it, or tell me how."}, source="map")
              for n, p in enumerate(fmap.get("problems") or [])]
    setup += [_item({"id": c["id"], "level": "info", "priority": "P3", "title": c["message"], "next_step": c["fix"],
                     "node_id": c["step"],
                     "prompt": f"{c['message']}. {c['fix']} Suggest the new wording."}, source="convention") for c in conv]
    for section in (silent, drift, ideas, setup):
        section.sort(key=lambda x: x["priority"])
    return {"plan": plan, "fix_now": fix_now, "silent": silent, "drift": drift, "ideas": ideas, "setup": setup,
            "questions": questions, "coverage": h.get("coverage"), "dismissed": h.get("dismissed", []),
            "answered": h.get("answered", []), "context_file": h.get("context_file"),
            "runs_checked": len(insights.finished_runs(flow_id)),
            "errors": len(fix_now) + len(silent) + len(drift), "improvements": len(ideas) + len(setup) + len(questions),
            "total": len(fix_now) + len(silent) + len(drift) + len(ideas) + len(setup) + len(questions)}
