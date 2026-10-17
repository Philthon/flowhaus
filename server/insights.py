"""Insights: what a careful reviewer would notice about an automation from its runs (see docs/practices.md).

Each insight is {level: info|warn|error, kind, title, detail, node_id?, next_step, prompt, evidence}: what happened,
the one thing to do about it, a chat prompt to get help with it, and the numbers it's based on. Actionable, not only
diagnostic. Computed from data already read for the map (no extra calls, except asking GitHub once whether a
proposed change was merged).

  now     a failure streak, a run with nothing (or much less) out, items lost without a reason, a step that suddenly
          skips everything, a missed schedule
  drift   slow changes over the recent runs that no single run shows: output sliding, a step skipping more and
          more, a new skip reason, runs getting slower, much more or less coming in
  ideas   improvements the numbers suggest: one reason behind most skips, the same kind of failure again and again
"""

from __future__ import annotations

from datetime import datetime
from statistics import median

from server import changes, flows, nextstep


def finished_runs(flow_id: str) -> list[dict]:
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
    runs = finished_runs(flow_id)
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
                    "detail": "Same step, same place: this is unlikely to fix itself. Ask the chat what changed.",
                    "fill": {"n": len(streak)}})

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
    out += _drift(flow_id, runs, labels, items)
    out += _ideas(flow_id, runs, labels, items)
    return [_actionable(i, labels, items) for i in out]


# --------------------------------------------------------------------------- what to do about each insight

NEXT = {
    "repeated_failure": "Fix the cause before the next run; it won't pass by itself.",
    "nothing_out": "Open the run and find the step where the {items} stop; check its skip reasons and log.",
    "fewer_than_usual": "Open the run and compare each step's numbers with the run before; the step that dropped is the one to look at.",
    "unexplained_loss": "Make “{step}” say why it drops {items} (a skip reason), or find the code that removes them silently.",
    "skips_everything": "Check what changed upstream of “{step}”: a renamed field or a new format is the usual cause.",
    "missed_schedule": "Check the schedule where the automation runs (cron, GitHub Actions, launchd) and whether it's switched on.",
    "change_waiting": "Nothing to do yet: the comparison appears after the next run.",
    "change_result": "Compare the numbers with what you expected; if they moved the wrong way, ask the chat why.",
    "output_drift": "Look at the oldest run in the slide and the newest: which step's numbers moved first?",
    "skip_drift": "Check the newest skip reasons at “{step}” and what changed upstream of it.",
    "new_skip_reason": "Check whether “{reason}” at “{step}” is expected; if not, find what changed upstream.",
    "slower": "Find the step that got slower (open a recent run) and check its outside app.",
    "input_shift": "Check the source: is this the new normal (then nothing to do) or is something missing or duplicated?",
    "main_skip_reason": "Fix the source of “{reason}” upstream, or accept it: it's {share} of everything “{step}” skips.",
    "failure_pattern": None,  # filled in from the kind of failure (nextstep)
}

PROMPT = {
    "repeated_failure": "This automation failed {n} runs in a row at “{step}”. Find the cause from the logs and code and tell me the fix.",
    "nothing_out": "The last run finished but produced no {items}. Find where they stopped and why.",
    "fewer_than_usual": "The last run produced fewer {items} than usual. Which step lost them, and why?",
    "unexplained_loss": "“{step}” loses {items} without a skip reason. Find where in the code, and suggest a skip reason.",
    "skips_everything": "“{step}” suddenly skips almost everything. What changed upstream?",
    "output_drift": "The output of this automation has been sliding over the last runs. What's driving it?",
    "skip_drift": "“{step}” skips more and more. What's driving it, and what should change?",
    "new_skip_reason": "“{step}” has a new skip reason: “{reason}”. Where does it come from, and is it expected?",
    "slower": "Runs are getting slower. Which step is it, and why?",
    "input_shift": "Much more or fewer {items} come in than before. Is the source changing, and does anything after it need to adapt?",
    "main_skip_reason": "Most of what “{step}” skips is “{reason}”. Where does that come from, and can we fix it upstream?",
    "failure_pattern": "Recent runs keep failing on {what} at “{step}”. What's the lasting fix?",
}


def _actionable(item: dict, labels: dict, items: str) -> dict:
    """Give an insight its next step and a chat prompt (unless it already has them)."""
    fill = {"step": labels.get(item.get("node_id") or "", "this step"), "items": items, **item.get("fill", {})}
    kind = item["kind"]
    if not item.get("next_step") and NEXT.get(kind):
        item["next_step"] = NEXT[kind].format(**fill)
    if not item.get("prompt") and PROMPT.get(kind):
        item["prompt"] = PROMPT[kind].format(**fill)
    item.setdefault("evidence", [])
    item.pop("fill", None)
    return item


# --------------------------------------------------------------------------- drift: slow changes over recent runs


def _seconds(run: dict) -> float | None:
    try:
        return (datetime.fromisoformat(run["finished_at"]) - datetime.fromisoformat(run["started_at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return None


# Drift must be real, not noise: the three newest runs all sit on the same side of what was usual, and the move is
# bigger than both a minimum (MIN_*) and the usual run-to-run spread (twice the median absolute deviation). Tested
# against the demo histories (random runs, no real drift): this keeps false alarms rare while a steady 25% slide shows.
MIN_RUNS = 7  # three newest + at least four before
MIN_DROP = 0.25  # output or input: a quarter less (or 50% more / half for input)
MIN_SKIP_POINTS = 0.15  # skip rate: 15 percentage points more
MIN_ITEMS = 20  # skip rates on fewer items per run are too noisy to read
SLOWER = 1.5


def _shift(values: list, minimum: float, relative: bool = True) -> tuple[float, float] | None:
    """(now, before) when the newest three runs moved consistently and clearly away from the usual; else None.
    `values` are newest first; `minimum` is relative to the usual (or absolute when `relative` is False)."""
    vals = [v for v in values if v is not None]
    if len(vals) < MIN_RUNS:
        return None
    recent, base = vals[:3], vals[3:9]
    usual = median(base)
    spread = 1.4826 * median([abs(b - usual) for b in base])  # robust standard deviation
    now = median(recent)
    move = abs(now - usual)
    side = all(r < usual for r in recent) or all(r > usual for r in recent)
    big = move >= (minimum * usual if relative else minimum) and move >= 2 * spread
    return (now, usual) if side and big else None


def _drift(flow_id: str, runs: list[dict], labels: dict, items: str) -> list[dict]:
    ok = [r for r in runs if r["status"] == "success"][:9]
    out: list[dict] = []
    outs = [(r.get("summary") or {}).get("rows_written") for r in ok]
    if (pair := _shift(outs, MIN_DROP)) and pair[1] >= 10 and pair[0] < pair[1]:
        now, before = pair
        out.append({"level": "warn", "kind": "output_drift", "title": f"Output is sliding: about {now:,.0f} {items} a run, down from {before:,.0f}",
                    "detail": "No single run looks broken, but the last three gave clearly less than the five before.",
                    "evidence": [f"newest first: {', '.join(str(o) for o in outs if o is not None)}"]})
    ins = [(r.get("summary") or {}).get("rows_read") for r in ok]
    if (pair := _shift(ins, 0.5)) and pair[1] >= 10:
        out.append({"level": "info", "kind": "input_shift", "title": f"{'More' if pair[0] > pair[1] else 'Fewer'} {items} come in: about {pair[0]:,.0f} a run, was {pair[1]:,.0f}",
                    "detail": "A change at the source shows up in every step after it, including costs.",
                    "evidence": [f"in, newest first: {', '.join(str(i) for i in ins if i is not None)}"]})
    secs = [_seconds(r) for r in ok]
    if (pair := _shift(secs, SLOWER - 1)) and pair[1] >= 10 and pair[0] > pair[1]:
        out.append({"level": "info", "kind": "slower", "title": f"Runs are getting slower: about {pair[0]:,.0f}s, was {pair[1]:,.0f}s",
                    "detail": "Slow drift usually comes from one step: an outside app slowing down, or more items reaching a paid step."})

    full = [f for r in ok if (f := _full(flow_id, r))]
    if len(full) >= MIN_RUNS:
        for sid in labels:
            rates, reasons, sizes = [], [], []
            for f in full:
                n = (f.get("nodes") or {}).get(sid) or {}
                rates.append(n["rows_rejected"] / n["rows_in"] if n.get("rows_in") and n.get("rows_rejected") is not None else None)
                reasons.append(set((n.get("reject_reasons") or {}).keys()))
                sizes.append(n.get("rows_in") or 0)
            enough = median(sizes) >= MIN_ITEMS
            if enough and (pair := _shift(rates, MIN_SKIP_POINTS, relative=False)) and pair[0] > pair[1]:
                out.append({"level": "warn", "kind": "skip_drift", "node_id": sid,
                            "title": f"“{labels[sid]}” skips more and more: {pair[0]:.0%} lately, was {pair[1]:.0%}",
                            "detail": "Each run looks fine on its own; together they show a step letting less through.",
                            "evidence": [f"skip rate, newest first: {', '.join(f'{r:.0%}' for r in rates if r is not None)}"]})
            older = set().union(*reasons[1:6]) if len(reasons) > 1 else set()
            new = sorted(reasons[0] - older) if older and enough else []
            if new:
                out.append({"level": "info", "kind": "new_skip_reason", "node_id": sid,
                            "title": f"New skip reason at “{labels[sid]}”: “{new[0]}”",
                            "detail": "It didn't appear in the five runs before. New reasons often follow a change upstream or at the source.",
                            "fill": {"reason": new[0]}})
    return out


# --------------------------------------------------------------------------- improvement ideas


def _ideas(flow_id: str, runs: list[dict], labels: dict, items: str) -> list[dict]:
    out: list[dict] = []
    ok = [r for r in runs if r["status"] == "success"][:5]
    full = [f for r in ok if (f := _full(flow_id, r))]
    if full:
        last = full[0].get("nodes") or {}
        # one reason behind most of a step's skips (not for steps whose job is to choose: that's them working)
        from server.harness import FILTERING

        for sid, n in last.items():
            if FILTERING.search(labels.get(sid, "")):
                continue
            reasons, n_in = n.get("reject_reasons") or {}, n.get("rows_in") or 0
            total = sum(reasons.values())
            if n_in >= 10 and total >= 0.3 * n_in and reasons:
                reason, count = max(reasons.items(), key=lambda kv: kv[1])
                if count >= 0.6 * total and sid in labels:
                    out.append({"level": "info", "kind": "main_skip_reason", "node_id": sid,
                                "title": f"Idea: most of what “{labels[sid]}” skips is “{reason}”",
                                "detail": f"{count:,} of {total:,} skipped in the last run. Fixing it upstream would keep them.",
                                "evidence": [f"{k}: {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:3]],
                                "fill": {"reason": reason, "share": f"{count / total:.0%}"}})
    # the same kind of failure again and again
    failed = [r for r in runs[:10] if r["status"] == "failed" and r.get("error")]
    kinds: dict[tuple, int] = {}
    for r in failed:
        declared = r["error"].get("kind")  # a `fail` rule's kind wins over guessing from the words
        key = (declared if declared in nextstep.KINDS else nextstep.classify(r["error"].get("message") or ""),
               r["error"].get("node_id"))
        kinds[key] = kinds.get(key, 0) + 1
    for (kind, sid), n in kinds.items():
        if n >= 2 and kind != "other":
            what = {"transient": "an app not answering or rate limits", "auth": "an expired key or login",
                    "credits": "running out of credits", "data": "missing fields", "file": "missing files",
                    "connect": "something not connected", "gone": "something that no longer exists",
                    "code": "errors in the code", "duplicate": "duplicates"}.get(kind, kind)
            fix = {"transient": "Add retries with a growing pause to “{step}”, so a busy app doesn't fail the run.",
                   "auth": "Move the key to a place that renews (a token that doesn't expire, or a reminder before it does).",
                   "credits": "Raise the plan limit, or add a check that stops early with a clear message when credits run low.",
                   "data": "Skip items without the field earlier, with a reason, so one item can't fail the run.",
                   "connect": "Make the run check for it first and stop with a clear message, or wait and retry.",
                   }.get(kind, "Fix the cause once, so it stops coming back.")
            out.append({"id": f"failure_pattern:{kind}:{sid or ''}", "level": "warn", "kind": "failure_pattern", "node_id": sid,
                        "title": f"{n} of the last {len(runs[:10])} runs failed on {what}" + (f" at “{labels.get(sid, sid)}”" if sid else ""),
                        "detail": "The same kind of failure keeps coming back: worth a lasting fix rather than another re-run.",
                        "next_step": fix.format(step=labels.get(sid or "", "this step")),
                        "evidence": [(r["error"].get("message") or "")[:200] for r in failed if (r["error"].get("node_id") == sid)][:2],
                        "fill": {"what": what}})
    return out
