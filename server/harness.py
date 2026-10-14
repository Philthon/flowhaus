"""The harness's opinions about a connected automation: big-picture gaps, blind spots, and questions for the user.

Insights (server/insights.py) say what happened in the recent runs. This module says what the automation as a whole is
missing, judged against docs/practices.md, and what Flowhaus can't see:

  gap         something the automation or its map lacks (no safe test mode, re-runs that publish twice, ...)
  blind_spot  a part of the automation Flowhaus can't see (steps with no numbers, items lost between steps, code that
              isn't on the map, costs nobody counts)
  question    something only the user knows, asked when the answer changes the judgement ("is skipping most items
              here expected?"). Answers become checks or context for the chat.

Opinionated, not stubborn: every finding can be dismissed with a reason and stays quiet after that, and every answer
is kept. Both live in a context.yaml next to the flow's config (plain YAML, git-ignored): automations/<id>/ for
automations you connected, flows/<id>/ for flows built in Flowhaus.

Each finding is {id, kind, level: info|warn|error, title, detail, practice?, node_id?, ask?}; `ask` is a prompt for the
chat. Ids are stable, so dismissals and answers stick across runs.
"""

from __future__ import annotations

import hashlib
import re
import threading
from datetime import datetime
from pathlib import Path
from statistics import median

import yaml

from server import flows, maps

CONTEXT_FILE = "context.yaml"
MAX_TEXT = 500
_lock = threading.Lock()

# Steps whose job is to choose: they should count what they skip, with a reason.
FILTERING = re.compile(r"^(keep|skip|filter|pick|select|remove|drop|exclude|only)\b", re.I)
# Steps that reach the outside world: running them twice may publish, send or charge twice.
PUBLISHING = re.compile(r"\b(publish|send|post|email|e-mail|notify|upload|push|charge|pay|invoice|tweet|message|sync)\w*",
                        re.I)
# Apps that usually charge per call. Practice 7: log what each call cost.
PAID_APPS = re.compile(r"openai|anthropic|claude|gpt|gemini|mistral|cohere|firecrawl|clay|apify|serp|scrapingbee|"
                       r"browserless|perplexity|deepgram|assemblyai|elevenlabs|replicate|twilio|apollo|hunter", re.I)
# Code that is rarely a step of its own: helpers, tests, packaging.
NOT_A_STEP = re.compile(r"(^|/)(tests?|__pycache__|migrations?|scripts?/dev|docs?)/|(^|/)(test_[^/]*|[^/]*_test\.\w+|"
                        r"__init__\.py|conftest\.py|setup\.py|utils?\.\w+|helpers?\.\w+|common\.\w+|shared\.\w+|config\.\w+|settings\.\w+|"
                        r"constants?\.\w+|types?\.\w+|models?\.\w+|logging\.\w+|log\.\w+)$", re.I)
CODE = {".py", ".js", ".mjs", ".ts", ".rb", ".go", ".rs", ".sh", ".sql"}


# --------------------------------------------------------------------------- context.yaml (answers, dismissals)


def reviewed(flow_id: str) -> bool:
    """The harness reviews the user's own automations: connected (imported) ones and flows built in Flowhaus."""
    try:
        return flows.kind(flow_id) in ("connected", "built")
    except KeyError:
        return False


def _context_path(flow_id: str) -> Path | None:
    if not reviewed(flow_id):
        return None
    a = flows.connected().get(flow_id)
    return a.folder / CONTEXT_FILE if a else flows.FLOWS_DIR / flow_id / CONTEXT_FILE


def read_context(flow_id: str) -> dict:
    path = _context_path(flow_id)
    try:
        data = yaml.safe_load(path.read_text()) if path else None
    except (OSError, yaml.YAMLError):
        data = None
    data = data if isinstance(data, dict) else {}
    return {"answers": data.get("answers") or {}, "dismissed": data.get("dismissed") or {}, "notes": data.get("notes") or {}}


def _write_context(flow_id: str, ctx: dict) -> None:
    path = _context_path(flow_id)
    if path is None:
        raise ValueError("Only your own automations keep context (connected or built in Flowhaus).")
    header = ("# What you told Flowhaus about this automation: answers to its questions, findings you dismissed and why,\n"
              "# and notes from the chat. Edit freely; Flowhaus and its chat read it.\n")
    path.write_text(header + yaml.safe_dump({k: v for k, v in ctx.items() if v}, sort_keys=False, allow_unicode=True))


def _shown_path(path: Path | None) -> str | None:
    """Where the context file is, as the user would find it (relative to Flowhaus's folder when inside it)."""
    if path is None:
        return None
    try:
        return path.resolve().relative_to(flows.runtime.ROOT).as_posix()
    except ValueError:
        return str(path)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:MAX_TEXT]


def answer(flow_id: str, question_id: str, value: str, note: str = "") -> dict:
    """Keep the user's answer to one of the current questions."""
    value = _clean(value)
    if not value:
        raise ValueError("The answer is empty.")
    open_ids = {q["id"] for q in review(flow_id)["questions"]}
    if question_id not in open_ids and question_id not in read_context(flow_id)["answers"]:
        raise ValueError("That question isn't open (it may already be answered).")
    with _lock:
        ctx = read_context(flow_id)
        ctx["answers"][question_id] = {"answer": value, **({"note": _clean(note)} if _clean(note) else {}), "at": _now()}
        _write_context(flow_id, ctx)
    return review(flow_id)


def dismiss(flow_id: str, finding_id: str, reason: str) -> dict:
    """'Not relevant here, because …': the finding stays quiet, and the chat respects the reason."""
    reason = _clean(reason)
    if not reason:
        raise ValueError("Say briefly why it doesn't apply, so the chat knows too.")
    current = {f["id"]: f for f in review(flow_id)["findings"]}
    if finding_id not in current:
        raise ValueError("That finding isn't open.")
    with _lock:
        ctx = read_context(flow_id)
        ctx["dismissed"][finding_id] = {"title": current[finding_id]["title"], "reason": reason, "at": _now()}
        _write_context(flow_id, ctx)
    return review(flow_id)


def restore(flow_id: str, item_id: str) -> dict:
    """Bring back a dismissed finding, or reopen an answered question."""
    with _lock:
        ctx = read_context(flow_id)
        if ctx["dismissed"].pop(item_id, None) is None and ctx["answers"].pop(item_id, None) is None:
            raise ValueError("Nothing to bring back with that id.")
        _write_context(flow_id, ctx)
    return review(flow_id)


def note(flow_id: str, topic: str, text: str) -> None:
    """Context the user gave in the chat ("the Toronto source is seasonal"), kept for next time."""
    topic, text = _clean(topic)[:80], _clean(text)
    if not topic or not text:
        raise ValueError("Give a topic and the note.")
    with _lock:
        ctx = read_context(flow_id)
        ctx["notes"][topic] = {"note": text, "at": _now()}
        _write_context(flow_id, ctx)


# --------------------------------------------------------------------------- reading the automation


def _recent(flow_id: str, n: int = 6) -> list[dict]:
    """Full recent finished production runs, newest first (cheap: adapters cache finished runs)."""
    summaries = [r for r in flows.production_runs(flow_id, flows.list_runs(flow_id)) if r["status"] in ("success", "failed")]
    a = flows.connected().get(flow_id)
    out = []
    for s in summaries[:n]:
        run = flows._adapter(flow_id, lambda: a.cached_run(s["run_id"]), None) if a else flows.get_run(flow_id, s["run_id"])
        if run and run.get("nodes"):
            out.append(run)
    return out


def _short(items: list[str], n: int = 3) -> str:
    return ", ".join(items[:n]) + (f" and {len(items) - n} more" if len(items) > n else "")


def _key(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:8]


def _label(s: dict) -> str:
    return s.get("label") or s["id"]


def _source_files(root: Path, near: set[str], limit: int = 4000) -> list[str]:
    """Code files (names only) in the folders that mapped steps live in. Never opens a file."""
    out, seen = [], 0
    for d in sorted(near):
        folder = (root / d).resolve()
        if not folder.is_dir() or root not in [folder, *folder.parents]:
            continue
        for p in sorted(folder.iterdir()):
            seen += 1
            if seen > limit:
                return out
            rel = p.relative_to(root).as_posix()
            if p.is_file() and p.suffix in CODE and not NOT_A_STEP.search(rel) and not p.name.startswith((".", "_")):
                out.append(rel)
    return out


# --------------------------------------------------------------------------- the review


def review(flow_id: str) -> dict:
    """{findings, questions, dismissed, context}. Empty for flows that aren't connected automations."""
    empty = {"findings": [], "questions": [], "dismissed": [], "answered": [], "notes": {}, "coverage": None, "context_file": None}
    if not reviewed(flow_id):
        return empty
    a = flows.connected().get(flow_id)
    if a is not None:
        cfg, steps = a.config, a.steps
        edges = list(zip(steps, steps[1:]))  # a connected automation's map is a chain
        kind = cfg.get("type")
    else:  # built in Flowhaus: runs here, counts every item and every paid call, tests locally
        fmap = flows.get_map(flow_id)
        cfg = maps.read_yaml(flows.FLOWS_DIR / flow_id / "flow.yaml")
        steps = fmap["steps"]
        by_id = {s["id"]: s for s in steps}
        sources: dict[str, list[str]] = {}
        for e in fmap.get("edges") or []:
            sources.setdefault(e["target"], []).append(e["source"])
        edges = [(by_id[src[0]], by_id[t]) for t, src in sources.items()  # only single-input steps add up
                 if len(src) == 1 and src[0] in by_id and t in by_id]
        kind = "built"
    ctx = read_context(flow_id)
    answers = {k: v.get("answer") for k, v in ctx["answers"].items()}
    meta = flows.get_meta(flow_id)
    item, items = meta["terms"]["item"], meta["terms"]["items"]
    runs = _recent(flow_id)
    ok_runs = [r for r in runs if r["status"] == "success"]
    last = ok_runs[0] if ok_runs else None
    findings: list[dict] = []
    questions: list[dict] = []  # still open
    asked: dict[str, dict] = {}  # every question that applies (answered ones too)

    def question(q: dict) -> str | None:
        """Ask q unless it's answered; returns the answer."""
        asked[q["id"]] = q
        if q["id"] not in answers:
            questions.append(q)
        return answers.get(q["id"])

    def gap(id_, level, title, detail, practice=None, node_id=None, ask=None, kind_="gap"):
        findings.append({"id": id_, "kind": kind_, "level": level, "title": title, "detail": detail,
                         "practice": practice, "node_id": node_id, "ask": ask})

    def blind(id_, level, title, detail, **kw):
        gap(id_, level, title, detail, kind_="blind_spot", **kw)

    publishing = [s for s in steps if PUBLISHING.search(_label(s)) and (s.get("app") or "Code") != "Code"
                  and "not connected yet" not in _label(s)]  # placeholders send nothing

    # ---- big-picture gaps ------------------------------------------------------------------------------------

    if kind != "built" and not cfg.get("test"):  # built flows always test locally on demo connectors
        risky = [_label(s) for s in publishing] or [_label(s) for s in steps if PAID_APPS.search(s.get("app") or "")]
        gap("no_test_mode", "warn" if publishing else "info", "No safe way to try a change",
            "Every change goes straight to production" + (f" ({_short(risky, 2)})" if risky else "") + ". A test mode "
            "(a dry-run input, a test webhook) lets you run tricky items without publishing or paying.",
            practice="10. Pressure-test before you trust it",
            ask="This automation has no safe test mode. Look at the code and tell me the smallest way to add one "
                "(e.g. a dry_run input that skips publishing and paid calls), and what its `test:` block would be.")

    for s in steps if kind == "github_actions" else []:  # the type whose map counts skips with `skip` rules
        if FILTERING.search(_label(s)) or re.match(r"^(keeps|skips)\b", s.get("description") or "", re.I):
            if not s.get("skip"):
                gap(f"uncounted_skips:{s['id']}", "warn", f"“{_label(s)}” chooses, but doesn't say what it leaves out",
                    f"It keeps some {items} and not others, but nothing counts the ones it skips or why. Silent drops "
                    "are the most common bug nobody sees.", practice="2. Skip, don't drop", node_id=s["id"],
                    ask=f"“{_label(s)}” filters {items} but the map doesn't count what it skips. Does the code print "
                        "why items are skipped? If so, suggest the skip rule for automation.yaml; if not, suggest a "
                        "log line to add.")

    if kind == "github_actions" and steps and not any(s.get("fail") for s in steps):
        gap("no_failure_rules", "info", "Failures won't say why in plain words",
            "When a run fails, the map can point at the GitHub step, but not explain the cause (out of credits, a site "
            "down, a bad key).", practice="4. Fail loudly, close to the cause",
            ask="Look at how this automation fails (failed runs, error messages in the code) and suggest `fail` rules "
                "so the map explains failures in plain words.")
    if kind == "folder_runs" and not (cfg.get("folder_runs") or {}).get("log"):
        gap("no_log", "info", "Failures won't say why",
            "Flowhaus only sees which files a run left behind. Point `folder_runs.log` at the script's own log so a "
            "failed run explains itself.", practice="4. Fail loudly, close to the cause")

    if a and a.local_path() and steps and any(s.get("file") for s in steps):
        missing = [_label(s) for s in steps if not s.get("file")]
        if missing:
            gap("steps_without_file", "info", f"{len(missing)} step{'s' if len(missing) > 1 else ''} not linked to code",
                f"{_short(missing)}: a change to their code can't be traced to them or to what comes after.",
                practice="Every step names its `file`")

    for s in publishing:
        verdict = question({"id": f"rerun_safe:{s['id']}", "node_id": s["id"],
                              "title": f"If “{_label(s)}” runs twice, does it {('publish', 'send')[bool(re.search('send|email|notify|message', _label(s), re.I))]} twice?",
                              "detail": "Retries and re-runs happen. Safe automations update in place instead of "
                                        "creating duplicates.",
                              "options": [{"value": "safe", "label": "No, it updates in place"},
                                          {"value": "duplicates", "label": "Yes, it would duplicate"},
                                          {"value": "unsure", "label": "Not sure"}]})
        if verdict in ("duplicates", "unsure"):
            gap(f"rerun_unsafe:{s['id']}", "warn" if verdict == "duplicates" else "info",
                f"Re-running “{_label(s)}” may {'' if verdict == 'duplicates' else 'possibly '}duplicate what it sends",
                "You said " + ("it would." if verdict == "duplicates" else "you're not sure.") + " A retry after a "
                "half-finished run is exactly when this bites.", practice="6. Safe to run again", node_id=s["id"],
                ask=f"Check whether “{_label(s)}” is safe to run twice (stable ids, upserts, duplicate checks). "
                    "If not, propose the smallest fix.")

    if a and not cfg.get("kpis") and steps:
        gap("no_kpis", "info", "The overview doesn't show what matters most",
            f"Without `kpis`, the card shows {items} out and runs that went fine. Pick the two numbers you'd check "
            "first (e.g. published, skipped as duplicates).", ask="Which two numbers best show whether this "
            "automation is doing its job? Suggest the `kpis` for its automation.yaml.")

    # ---- blind spots -----------------------------------------------------------------------------------------

    if err := flows._read_errors.get(flow_id):
        blind("unreadable", "error", "Flowhaus couldn't read the latest runs", err)

    if ok_runs:
        dark = [s for s in steps if all((r["nodes"].get(s["id"]) or {}).get("rows_out") is None
                                        and (r["nodes"].get(s["id"]) or {}).get("rows_in") is None for r in ok_runs[:3])]
        if dark and len(dark) < len(steps):
            blind("no_numbers:" + _key(*[s["id"] for s in dark]), "warn" if len(dark) > 1 else "info",
                  f"No numbers for {_short([f'“{_label(s)}”' for s in dark], 2)}",
                  f"Flowhaus can't see how many {items} go in or out there, so losses and slowdowns at "
                  f"{'these steps' if len(dark) > 1 else 'this step'} stay invisible.", practice="8. Observable by default",
                  node_id=dark[0]["id"],
                  ask=f"These steps show no numbers: {', '.join(_label(s) for s in dark)}. Does the log print anything "
                      "countable for them? Suggest counting rules, or a log line to add if there's nothing.")
    if last and kind != "folder_runs":  # folder runs count files, not items handed on
        nodes = last["nodes"]
        for prev, nxt in edges:
            if kind == "github_actions" and not nxt.get("in"):
                continue  # without its own `in` rule, a step's "in" is filled in from its neighbours
            p_out, n_in = (nodes.get(prev["id"]) or {}).get("rows_out"), (nodes.get(nxt["id"]) or {}).get("rows_in")
            if p_out is None or n_in is None or (prev.get("unit") or items) != (nxt.get("unit") or items):
                continue
            if n_in < p_out:
                blind(f"lost_between:{prev['id']}:{nxt['id']}", "warn",
                      f"{p_out - n_in:,} {item if p_out - n_in == 1 else items} vanish between “{_label(prev)}” and “{_label(nxt)}”",
                      f"{p_out:,} came out of one, {n_in:,} went into the next, and no step says why. Something in "
                      "between filters without being on the map.", practice="2. Skip, don't drop", node_id=nxt["id"],
                      ask=f"In the last run {p_out} {items} left “{_label(prev)}” but only {n_in} reached "
                          f"“{_label(nxt)}”. Find what removes them in between and whether it should be its own step "
                          "with a skip reason.")
            elif n_in > p_out:
                blind(f"appear_between:{prev['id']}:{nxt['id']}", "info",
                      f"{n_in - p_out:,} more {items} reach “{_label(nxt)}” than left “{_label(prev)}”",
                      "Either another source feeds in, or the steps count different things. Check the counting rules.",
                      node_id=nxt["id"])

    root = a.readable_code_path() if a else None
    mapped = {(s.get("file") or "").lstrip("./") for s in steps if s.get("file")}
    if root and mapped:
        near = {str(Path(f).parent) for f in mapped if Path(f).suffix in CODE}
        unmapped = [f for f in _source_files(root, near) if f not in mapped]
        if unmapped:
            blind("unmapped_code:" + _key(*unmapped), "info",
                  f"{len(unmapped)} code file{'s' if len(unmapped) > 1 else ''} next to the steps "
                  f"{'are' if len(unmapped) > 1 else 'is'}n't on the map",
                  f"{_short(unmapped, 4)}. Helpers can stay off the map; anything that sends, deletes, charges or "
                  "filters should be a step, or changes to it won't show their downstream effect.",
                  ask=f"These files sit next to the mapped steps but no step points at them: {', '.join(unmapped[:10])}. "
                      "Which of them do work a person would care about (sending, filtering, deleting, charging)? "
                      "Suggest how to add those to the map.")

    paid = sorted({s["app"] for s in steps if PAID_APPS.search(s.get("app") or "")})
    if paid and a:  # built flows count every paid call already
        blind("cost_invisible", "info", f"Nothing shows what {_short(paid, 2)} cost per run",
              "Paid calls grow quietly when more items get through a filter. Logging the cost per run turns a "
              "surprise bill into a number on the map.", practice="7. Narrow doors to the outside",
              ask=f"This automation calls {', '.join(paid)}. Where could it log the number of paid calls or their "
                  "cost per run, so the map can count it?")

    # ---- questions: only what the user knows, and only when it changes the judgement -------------------------

    outs = [o for r in ok_runs if (o := (r.get("summary") or {}).get("rows_written")) is not None]
    exp = None
    if outs:
        lo, hi = min(outs), max(outs)
        options = [{"value": f"{max(0, int(lo * 0.5))}-{int(hi * 1.5) + 1}", "label": f"Roughly {lo:,}–{hi:,}, like lately"}
                   ] if hi > 0 else []
        options += [{"value": "1-", "label": f"At least one {item}"}, {"value": "any", "label": "Any number, even none"}]
        exp = question({"id": "expected_output", "title": f"How many {items} should a normal run produce?",
                        "detail": "Then Flowhaus can tell a quiet week from a broken run, instead of guessing.",
                        "options": options, "free_text": "or a range, e.g. 20-100"})
    if exp and exp != "any" and last and (now := (last.get("summary") or {}).get("rows_written")) is not None:
        m = re.match(r"^\s*(\d+)?\s*-\s*(\d+)?\s*$", str(exp))
        lo, hi = (int(m.group(1)) if m and m.group(1) else 0), (int(m.group(2)) if m and m.group(2) else None)
        if m and (now < lo or (hi is not None and now > hi)):
            gap("outside_expected", "warn", f"{now:,} {items} came out; you said normal is {exp}",
                "The last run finished fine, but outside the range you gave. Open it to see which step moved.",
                practice="11. Prove it with numbers")

    for s in steps:
        rates = [n["rows_rejected"] / n["rows_in"] for r in ok_runs[:5]
                 if (n := r["nodes"].get(s["id"]) or {}).get("rows_in") and n.get("rows_rejected") is not None]
        if len(rates) < 3 or median(rates) < 0.5:
            continue
        top = next(iter((last or {}).get("nodes", {}).get(s["id"], {}).get("reject_reasons") or {}), None)
        verdict = question({"id": f"skips_expected:{s['id']}", "node_id": s["id"],
                              "title": f"“{_label(s)}” usually skips {median(rates):.0%} of what comes in. Is that its job?",
                              "detail": ("Mostly “" + top + "”. " if top else "") + "A high skip rate is either the "
                                        "point of a step or a leak; only you know which.",
                              "options": [{"value": "expected", "label": "Yes, that's expected"},
                                          {"value": "too_many", "label": "No, it should keep more"}]})
        if verdict == "too_many":
            gap(f"skips_too_many:{s['id']}", "warn", f"“{_label(s)}” skips more than it should",
                f"You said it should keep more; it skipped {median(rates):.0%} lately.", node_id=s["id"],
                ask=f"“{_label(s)}” skips about {median(rates):.0%} of {items} and that's more than I want. Look at "
                    "the skip reasons and the code, and tell me what drives it and what to change.")

    notices = None
    if (cfg.get("trigger") or {}).get("type") == "schedule":
        notices = question({"id": "who_notices", "title": "If a run fails or doesn't happen, who notices first?",
                          "detail": "Flowhaus only looks when you open it; it doesn't alert anyone. This decides how "
                                    "loudly it should fail.",
                          "options": [{"value": "nobody_soon", "label": "Nobody, for a while"},
                                      {"value": "me", "label": "Me, the same day"},
                                      {"value": "others", "label": "Customers or teammates"}]})
    if notices in ("others", "nobody_soon"):
        gap("failure_unannounced", "warn" if notices == "others" else "info",
            "A failed run may go unnoticed" + (" until someone else notices" if notices == "others" else ""),
            "Flowhaus doesn't send alerts. The automation itself should tell you when it fails or produces nothing "
            "(an email, a Slack message, GitHub's failure notifications).", practice="4. Fail loudly, close to the cause",
            ask="When this automation fails or produces nothing, nobody hears about it soon. What's the simplest way "
                "for it to notify me (GitHub notifications, a Slack or email step)?")

    # ---- dismissed findings stay quiet; answered questions are kept for the chat -----------------------------

    dismissed = [{"id": k, **v} for k, v in ctx["dismissed"].items()]
    order = {"error": 0, "warn": 1, "info": 2}
    findings = sorted((f for f in findings if f["id"] not in ctx["dismissed"]), key=lambda f: order[f["level"]])
    def said(k: str, value: str) -> str:
        return next((o["label"] for o in asked.get(k, {}).get("options", []) if o["value"] == value), value)

    answered = [{"id": k, "answer": said(k, v.get("answer")), "note": v.get("note"), "at": v.get("at"),
                 "title": asked.get(k, {}).get("title", k)} for k, v in ctx["answers"].items()]
    # coverage: how much of the automation Flowhaus can actually see (like test/doc coverage in dbt-project-evaluator)
    seen = sum(1 for s in steps if last and ((n := last["nodes"].get(s["id"]) or {}).get("rows_out") is not None
                                             or n.get("rows_in") is not None))
    coverage = {"steps": len(steps), "with_numbers": seen if last else None,
                "linked_to_code": sum(1 for s in steps if s.get("file")),
                "questions_answered": len([q for q in asked if q in answers]), "questions": len(asked)}
    return {"findings": findings, "questions": questions, "dismissed": dismissed, "answered": answered,
            "notes": ctx["notes"], "coverage": coverage, "context_file": _shown_path(_context_path(flow_id))}


def for_chat(flow_id: str) -> dict:
    """What the chat should know: open findings and questions, plus what the user already said (respect it)."""
    r = review(flow_id)
    return {"open_findings": [{k: f[k] for k in ("id", "kind", "level", "title", "detail", "practice") if f.get(k)}
                              for f in r["findings"]],
            "open_questions": [q["title"] for q in r["questions"]],
            "user_answers": {a["title"]: a["answer"] + (f" ({a['note']})" if a.get("note") else "") for a in r["answered"]},
            "dismissed_by_user": {d["title"]: d["reason"] for d in r["dismissed"]},
            "notes_from_user": {k: v.get("note") for k, v in r["notes"].items()}}
