"""Insights: what a careful reviewer would notice about an automation from its runs (see docs/practices.md).

Each insight is {level: info|warn|error, kind, title, detail, node_id?}. They are computed from data already
read for the map (no extra calls, except asking GitHub once whether a proposed change was merged).
"""

from __future__ import annotations

from statistics import median

from server import changes, flows


def _finished(flow_id: str) -> list[dict]:
    return [r for r in flows.production_runs(flow_id, flows.list_runs(flow_id)) if r["status"] in ("success", "failed")]


def _full(flow_id: str, summary: dict) -> dict | None:
    if flow_id in flows.connected():
        return flows._adapter(flow_id, lambda: flows.connected()[flow_id].cached_run(summary["run_id"]), None)
    return flows.get_run(flow_id, summary["run_id"])


def _pct(a: float, b: float) -> str:
    return f"{(a - b) / b * 100:+.0f}%" if b else ""


def insights(flow_id: str) -> list[dict]:
    meta = flows.get_meta(flow_id)
    items, item = meta["terms"]["items"], meta["terms"]["item"]
    runs = _finished(flow_id)
    out: list[dict] = []
    if not runs:
        return out
    last = runs[0]
    labels = {s["id"]: s.get("label") or s["id"] for s in flows.get_map(flow_id)["steps"]}

    # repeated failures at the same step
    streak = []
    for r in runs:
        if r["status"] != "failed":
            break
        streak.append((r.get("error") or {}).get("node_id"))
    if len(streak) >= 3 and len(set(streak)) == 1:
        where = labels.get(streak[0] or "", "the same place")
        out.append({"level": "error", "kind": "repeated_failure", "node_id": streak[0],
                    "title": f"Failed {len(streak)} runs in a row at “{where}”",
                    "detail": "Same step, same place: this is unlikely to fix itself. Ask the chat what changed."})

    # output compared with what's usual
    outs = [(r.get("summary") or {}).get("rows_written") for r in runs[1:8] if r["status"] == "success"]
    usual = median([o for o in outs if o is not None]) if any(o is not None for o in outs) else None
    now = (last.get("summary") or {}).get("rows_written")
    if last["status"] == "success" and now == 0 and usual:
        out.append({"level": "warn", "kind": "nothing_out",
                    "title": f"Ran fine but produced no {items}",
                    "detail": f"Usually about {usual:,.0f}. A run that succeeds with nothing out often hides a skipped "
                              "step or a swallowed error."})
    elif last["status"] == "success" and now is not None and usual and usual >= 10 and now < usual * 0.5:
        out.append({"level": "warn", "kind": "fewer_than_usual",
                    "title": f"Fewer {items} than usual: {now:,} ({_pct(now, usual)})",
                    "detail": f"The last runs usually gave about {usual:,.0f}. Open the run to see which step lost them."})

    # per-step: items that vanish without a reason, and a step that suddenly skips almost everything
    full, before = _full(flow_id, last), _full(flow_id, runs[1]) if len(runs) > 1 else None
    for sid, n in ((full or {}).get("nodes") or {}).items():
        n_in, n_out, n_skip = n.get("rows_in"), n.get("rows_out"), n.get("rows_rejected") or 0
        if n_in is None or n_out is None or n.get("status") != "success":
            continue
        lost = n_in - n_out - n_skip
        if lost > 0 and n_in >= 5 and n.get("unit") in (None, items):
            out.append({"level": "warn", "kind": "unexplained_loss", "node_id": sid,
                        "title": f"{lost:,} {item if lost == 1 else items} left “{labels.get(sid, sid)}” without a reason",
                        "detail": f"{n_in:,} in, {n_out:,} out, {n_skip:,} skipped. Items should leave with a reason "
                                  "(skip, don't drop)."})
        prev = ((before or {}).get("nodes") or {}).get(sid) or {}
        if n_in >= 10 and n_skip >= 0.9 * n_in and prev.get("rows_in") and (prev.get("rows_rejected") or 0) < 0.5 * prev["rows_in"]:
            reason = next(iter(n.get("reject_reasons") or {}), "")
            out.append({"level": "warn", "kind": "skips_everything", "node_id": sid,
                        "title": f"“{labels.get(sid, sid)}” now skips almost everything",
                        "detail": (f"Mostly “{reason}”. " if reason else "") + "In the run before it kept most. Often a "
                                  "change upstream (a renamed field, a new format) or an outside app limit."})

    # changes that were merged: compare the first run after with the baseline saved when it was proposed
    for c in changes.list_changes(flow_id):
        if c["status"] != "opened" or not (c.get("review") or {}).get("baseline"):
            continue
        merged = changes.merged_at(c["id"])
        if not merged:
            continue
        after = next((r for r in reversed(runs) if (r.get("started_at") or "") > merged), None)
        if not after:
            out.append({"level": "info", "kind": "change_waiting", "title": f"“{c['title']}” is merged",
                        "detail": "Its effect shows after the next run; Flowhaus will compare it with the numbers from "
                                  "before the change."})
            continue
        base = c["review"]["baseline"]["steps"]
        nodes = (_full(flow_id, after) or {}).get("nodes") or {}
        moved = []
        for sid, b in base.items():
            a = (nodes.get(sid) or {}).get("rows_out")
            if a is not None and b.get("out") is not None and a != b["out"]:
                moved.append(f"{labels.get(sid, sid)} {b['out']:,} → {a:,} ({_pct(a, b['out'])})")
        out.append({"level": "info", "kind": "change_result", "title": f"After “{c['title']}”",
                    "detail": ("; ".join(moved[:6]) if moved else "No step's output changed.")
                              + f" (first run after the merge vs. the run before the change). Expected: {c.get('impact') or 'not stated'}"})

    if meta.get("overdue"):
        out.append({"level": "warn", "kind": "missed_schedule", "title": "Didn't run when expected", "detail": meta["overdue"]})
    return out
