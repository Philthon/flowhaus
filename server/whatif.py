"""What if: run one step (and optionally everything after it) on items you edit, without side effects.

  "What would happen if this step got this item instead?" Answered by really running the step:

  built in Flowhaus  the step's code runs in a subprocess (minimal environment, like every run): Hamilton replaces
                     the step's input with your items (`overrides`), so nothing before it runs. Outside apps are the
                     demo connectors; output files go to a scratch folder.
  demo flows         the demo step's own function runs on your items.
  connected          the step's code runs where the automation lives (GitHub, n8n, ...), so it can't run here.
                     The answer says so, and the UI offers the chat's prediction from the code instead.

`replay` sends a past run's items through the flow as it is now, the same way, and compares what comes out with what
that run gave: after a change, you see which items would come out differently before it runs for real.

Nothing is published, pushed, saved to the flow's output or added to its run history. Built steps run in the test-mode
sandbox (server/runtime.py: `sandboxed`): they can write only to a scratch folder of their own and can't reach the network.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from server import flows, review, runtime

MAX_ITEMS = 50
MAX_REPLAY = 500
TIMEOUT_S = 120


def _plain(v):
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            v = v.item()  # numpy scalar -> python
        except (ValueError, TypeError):
            pass
    if isinstance(v, float) and v != v:  # NaN means "empty"
        return None
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def _why(exc: BaseException, fields) -> str:
    """The step's failure in plain words; a missing field is the usual one when you edit items by hand."""
    if type(exc).__name__ == "StepFailure":  # a demo app's own error message
        return str(exc)
    if isinstance(exc, KeyError) and exc.args:
        have = ", ".join(str(f) for f in fields if not str(f).startswith("_"))
        return f"This step needs a field called \u201c{exc.args[0]}\u201d. Add it and try again." + (f" Fields given: {have}." if have else "")
    from server import runs

    return runs.explain_error(exc, None)


def _fates(before: list[dict], after: list[dict] | None, error: str | None, numbers: dict | None = None) -> list[dict]:
    """What happened to each item in one step: kept (maybe changed) or skipped with a reason.
    `numbers`: each item's number as you entered it (by its row id), when `before` is only some of the items."""
    out_by = {r.get("_row_id"): r for r in after or []}
    fates = []
    for pos, b in enumerate(before, 1):
        i = (numbers or {}).get(b.get("_row_id"), pos)
        if _plain(b.get("_rejected_reason")):
            continue  # already out before this step
        a = out_by.get(b.get("_row_id"))
        if error and a is None:
            fates.append({"n": i, "outcome": "failed", "reason": error})
        elif a is None:
            fates.append({"n": i, "outcome": "skipped", "reason": "Left out by this step without a reason"})
        elif _plain(a.get("_rejected_reason")):
            fates.append({"n": i, "outcome": "skipped", "reason": str(_plain(a["_rejected_reason"]))})
        else:
            changes = {k: [_plain(b.get(k)), _plain(a.get(k))] for k in a
                       if not k.startswith("_") and str(_plain(a.get(k))) != str(_plain(b.get(k)))}
            fates.append({"n": i, "outcome": "changed" if changes else "kept", "changes": changes})
    return fates


def _final(rows: list[dict] | None) -> list[dict]:
    return [{k: _plain(v) for k, v in r.items() if not k.startswith("_")} for r in rows or []
            if not _plain(r.get("_rejected_reason"))]


def _numbered(items: list[dict], limit: int = MAX_ITEMS) -> list[dict]:
    """Items ready for a step. Items from a run keep their numbers (so a replay can be compared with that run);
    otherwise, or when only some have one, they're numbered by position, so two items never share a number."""
    items = items[:limit]
    ids = [it.get("_row_id") for it in items]
    keep = all(i is not None for i in ids) and len(set(map(str, ids))) == len(ids)
    return [{**{k: v for k, v in it.items() if not str(k).startswith("_")}, "_row_id": it["_row_id"] if keep else n,
             "_rejected_reason": None} for n, it in enumerate(items, 1)]


def _resolve(fmap: dict, step_id: str) -> str:
    if any(s["id"] == step_id for s in fmap["steps"]):
        return step_id
    inside = [s["id"] for s in fmap["steps"] if s.get("group") == step_id]  # a group: start at its first step
    if not inside:
        raise KeyError(step_id)
    return inside[0]


def _execute(flow_id: str, fmap: dict, step_id: str, rows: list[dict], downstream: bool) -> tuple[list[dict], list[dict]]:
    """(what happened at each step, every item after the last step that ran, skipped ones with their reason)."""
    labels = {s["id"]: s.get("label") or s["id"] for s in fmap["steps"]}
    order = [step_id, *(review.downstream(fmap, [step_id]) if downstream else [])]
    steps = _sample(flow_id, order, rows, labels) if flows.kind(flow_id) == "sample" else _run_built(flow_id, order, rows, labels)
    last_ok = next((s for s in reversed(steps) if s.get("after") is not None), None)
    after = last_ok["after"] if last_ok else []
    for s in steps:
        s.pop("after", None)
    return steps, after


NOTE = "Ran in test mode: nothing was published, saved to the flow's output or added to its run history."


def try_step(flow_id: str, step_id: str, items: list[dict], downstream: bool = True) -> dict:
    """{mode: run|predict, steps: [{id, label, status, error, items: [fates]}], out: [items], note}."""
    kind = flows.kind(flow_id)
    fmap = flows.get_map(flow_id)
    step_id = _resolve(fmap, step_id)
    if not items:
        raise ValueError("Give at least one item to try.")
    if kind == "connected":
        return {"mode": "predict", "step": step_id, "note": "This step runs where the automation lives, so Flowhaus can't run "
                "it here. Ask the chat to predict the result from the code."}
    steps, after = _execute(flow_id, fmap, step_id, _numbered(items), downstream)
    return {"mode": "run", "step": step_id, "steps": steps, "out": _final(after), "note": NOTE}


# --------------------------------------------------------------------------- replaying a past run


def _name(row: dict) -> str:
    """What to call an item in a sentence: its first text field."""
    return next((str(v) for k, v in row.items() if not k.startswith("_") and isinstance(v, str) and v.strip()), f"#{row.get('_row_id')}")


def _compare(before: list[dict], after: list[dict]) -> dict:
    """What came out of the run then, against what comes out now, item by item."""
    from server import runs

    then = {r.get("_row_id"): r for r in before}
    now = {r.get("_row_id"): r for r in after if not _plain(r.get("_rejected_reason"))}
    skipped_now = {r.get("_row_id"): str(_plain(r["_rejected_reason"])) for r in after if _plain(r.get("_rejected_reason"))}
    changed, examples = 0, []
    for rid, r in now.items():
        if rid not in then:
            if len(examples) < 5:
                examples.append({"item": _name(r), "now": "comes out (it didn't before)"})
            continue
        diff = {k: [_plain(then[rid].get(k)), _plain(r.get(k))] for k in sorted(set(r) | set(then[rid]))
                if not k.startswith("_") and not runs.same_value(r.get(k), then[rid].get(k))}
        if diff:
            changed += 1
            if len(examples) < 5:
                examples.append({"item": _name(r), "changes": diff})
    gone = [rid for rid in then if rid not in now]
    for rid in gone[: max(0, 5 - len(examples))]:
        examples.append({"item": _name(then[rid]), "now": f"skipped: {skipped_now.get(rid, 'left out')}"})
    return {"before": len(then), "after": len(now), "changed": changed, "now_skipped": len(gone),
            "now_kept": len([rid for rid in now if rid not in then]), "examples": examples}


def replay(flow_id: str, run_id: str) -> dict:
    """Send a past run's items through the flow as it is now, in test mode, and compare with what that run gave.

    The point: after a change, see what would have come out differently, item by item, before it runs for real.
    """
    kind = flows.kind(flow_id)
    run = flows.get_run(flow_id, run_id)
    if run is None:
        raise KeyError(run_id)
    if kind == "connected":
        return {"mode": "predict", "note": "This automation runs where it lives, so Flowhaus can't replay it here. "
                "If it has a test mode, use Test it; or ask the chat what this run would give now."}
    # items the first step skipped back then didn't go on: they don't go on now either
    items = [it for it in run.get("input_items") or [] if not it.get("_rejected_reason")]
    if not items:
        raise ValueError("This run didn't keep the items that came in, so it can't be replayed.")
    fmap = flows.get_map(flow_id)
    steps_in_order = [s["id"] for s in fmap["steps"]]
    first = steps_in_order[0]
    # the run recorded what its first step gave (the items it read), so the replay starts at the step after it
    start = next(iter(review.downstream(fmap, [first])), None)
    if start is None:
        raise ValueError("This flow has only one step, so there's nothing to replay after it.")
    sent = _numbered(items, MAX_REPLAY)
    steps, after = _execute(flow_id, fmap, start, sent, True)
    label = next((s.get("label") or s["id"] for s in fmap["steps"] if s["id"] == first), first)
    result = {"mode": "run", "step": start, "steps": steps, "out": _final(after)[:MAX_ITEMS],
              "note": f"Replayed {min(len(items), MAX_REPLAY)} items from \u201c{label}\u201d through the flow as it is now. {NOTE}"}
    if run.get("output_items") is not None and not any(s["status"] == "failed" for s in steps):
        result["compare"] = _compare(*_comparable(run["output_items"], after, sent))
    return result


def _comparable(before: list[dict], after: list[dict], sent: list[dict]) -> tuple[list[dict], list[dict]]:
    """Only what both sides saw. A run keeps at most MAX_IO_ITEMS items in and out, and a replay sends at most
    MAX_REPLAY: an item that wasn't replayed, or that came out past where the run's record stops, isn't a difference."""
    from server import runs

    order = {it["_row_id"]: n for n, it in enumerate(sent)}
    cut_off = len(before) >= runs.MAX_IO_ITEMS
    before = [r for r in before if r.get("_row_id") in order]
    if cut_off and before:
        last = max(order[r["_row_id"]] for r in before)  # the run's record stops here
        after = [r for r in after if order.get(r.get("_row_id"), len(order)) <= last]
    return before, after


def _sample(flow_id: str, order: list[str], rows: list[dict], labels: dict) -> list[dict]:
    """Demo flows: each step's own function, on the edited items. A decision only routes; a step on one of its
    paths handles only the items that took that path (as in a demo run)."""
    from server import sample_flows

    flow = sample_flows.SAMPLE_FLOWS[flow_id]
    by_id = {s.id: s for s in flow.steps}

    def framed(rs: list[dict]) -> list[dict]:  # items pass between demo steps as a table, as in a demo run
        import pandas as pd

        from server import runs

        return [{k: runs._clean(v) for k, v in r.items()} for r in pd.DataFrame(rs).to_dict(orient="records")]

    def path_of(step, item) -> str | None:  # which answer of a decision an item takes
        for b in step.branches or []:
            target = by_id.get(b.get("to"))
            if target is not None and (target.only is None or target.only(item)):
                return b.get("label")
        return None

    numbers = {r["_row_id"]: n for n, r in enumerate(rows, 1)}
    current, steps = framed(rows), []
    for sid in order:
        step = by_id.get(sid)
        if step is None:
            continue
        before = [dict(r) for r in current]
        on_path = [r for r in before if not r.get("_rejected_reason") and step.handles(r)] if step.only else before
        if step.only and not on_path:
            continue  # no item took this path
        try:
            after = framed([step.fn(dict(r), sample_flows.item_rng(sid, r)) if not r.get("_rejected_reason") and step.handles(r)
                            else r for r in before])
            error = None
        except Exception as exc:  # noqa: BLE001 - show the step's own error
            after, error = None, _why(exc, before[0].keys() if before else [])
        fates = _fates(on_path, after, error, numbers)
        if step.kind == "decision":
            path = {numbers.get(r.get("_row_id")): path_of(step, r) for r in before}
            fates = [{**f, "path": path.get(f["n"])} for f in fates]
        steps.append({"id": sid, "label": labels.get(sid, sid), "status": "failed" if error else "success", "error": error,
                      "items": fates, "after": after})
        if error:
            break
        current = after
    return steps


def _run_built(flow_id: str, order: list[str], rows: list[dict], labels: dict) -> list[dict]:
    from server import runs

    # a fresh scratch folder per try, so two tries at once can't overwrite each other's files
    base = runs.test_dir(flow_id)
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="whatif-", dir=base) as tmp:
        scratch = Path(tmp)
        items_file = scratch / "items.json"
        items_file.write_text(json.dumps(rows, default=str))
        cmd = [sys.executable, "-m", "server.whatif", "--flow", flow_id, "--items", str(items_file),
               "--scratch", str(scratch), "--steps", *order]
        cmd, _ = runtime.sandboxed(cmd, [scratch])  # it can write only there, and has no network
        try:
            proc = subprocess.run(cmd, cwd=runtime.ROOT, capture_output=True, text=True, timeout=TIMEOUT_S,
                                  env=runtime.test_env(scratch))
        except subprocess.TimeoutExpired:
            return [{"id": order[0], "label": labels.get(order[0]), "status": "failed",
                     "error": f"Didn't finish within {TIMEOUT_S} seconds", "items": [], "after": None}]
    try:
        result = json.loads((proc.stdout or "").strip().splitlines()[-1])
    except (IndexError, ValueError):
        err = (proc.stderr or "The step couldn't run").strip().splitlines()[-1:]
        return [{"id": order[0], "label": labels.get(order[0]), "status": "failed", "error": err[0][:400] if err else "",
                 "items": [], "after": None}]
    for s in result:
        s["label"] = labels.get(s["id"], s["id"])
    return result


# --------------------------------------------------------------------------- the subprocess (built flows)


def _child(flow_id: str, items_file: str, order: list[str], scratch: Path) -> list[dict]:
    import pandas as pd

    from server import runs

    paths = runs.flow_paths(flow_id)
    runtime.PIPELINE_DIR = paths["code"]
    rows = json.loads(Path(items_file).read_text())
    frame = pd.DataFrame(rows)
    events: dict[str, runtime.NodeEvent] = {}
    capture = runtime._Capture(on_event=lambda ev: events.__setitem__(ev.node_id, ev))
    dr = runtime.build_driver(runtime.load_pipeline_modules(), hooks=[capture])
    steps, edges, needed = runtime.describe_driver(dr)
    first = order[0]
    upstream = [e["source"] for e in edges if e["target"] == first]
    inputs = {"output_dir": str(scratch), "output_path": str(scratch / "result.csv")}
    overrides = {u: frame.copy(deep=True) for u in upstream}
    if not upstream:  # the first step reads the input file: give it the items as one
        csv = scratch / "items.csv"
        frame.drop(columns=["_row_id", "_rejected_reason"], errors="ignore").to_csv(csv, index=False)
        inputs.update(input_path=str(csv), csv_path=str(csv))
    else:  # steps before it don't run, but Hamilton may still ask for the external inputs: give harmless ones
        default = runs.default_input(flow_id)
        if default:
            inputs.update(input_path=str(runtime.ROOT / default), csv_path=str(runtime.ROOT / default))
    error = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            dr.execute(order, inputs={k: v for k, v in inputs.items() if k in needed}, overrides=overrides)
    except BaseException as exc:  # noqa: BLE001 - report the step's own failure
        error = f"{type(exc).__name__}: {exc}"
    out = []
    for sid in order:
        ev = events.get(sid)
        if ev is None:
            continue
        before = ev.input_frame.to_dict(orient="records") if ev.input_frame is not None else rows
        after = ev.output_frame.to_dict(orient="records") if ev.output_frame is not None else None
        err = None
        if ev.status == "failed":
            err = _why(ev.error, ev.input_frame.columns if ev.input_frame is not None else []) if ev.error else (error or "Failed")
        out.append({"id": sid, "status": ev.status, "error": err, "items": _fates(before, after, err),
                    "after": [{k: _plain(v) for k, v in r.items()} for r in after] if after is not None else None})
    if error and not out:
        out.append({"id": first, "status": "failed", "error": error, "items": [], "after": None})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--flow", required=True)
    ap.add_argument("--items", required=True)
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--steps", nargs="+", required=True)
    a = ap.parse_args()
    result = _child(a.flow, a.items, a.steps, Path(a.scratch))
    print(json.dumps(result, default=str))
