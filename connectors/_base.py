"""Shared plumbing for the dummy connectors.

Every call is recorded twice:
- in CALLS (in memory), so the runner can attach "what this step sent and got back" to each step;
- in state/calls.jsonl, so the Connections page can show usage.

They are demo connectors: no keys, no network, nothing to set up. Flowhaus never stores credentials; real apps
are set up in your own tools (their CLI, .env files, CI secrets) and used by your automations where they run.
These connectors are DUMMIES: no network calls are made, responses are
generated deterministically from the input.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
CALLS_PATH = STATE_DIR / "calls.jsonl"

CALLS: list[dict] = []  # calls made in this process, in order


class ConnectorError(Exception):
    """The whole call failed (not connected, rate limited, service down): the step should fail."""


class ItemError(Exception):
    """This one item can't be processed (e.g. page not found): skip the item, keep going."""


def seed(*parts: Any) -> int:
    return int(hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)


def require(app: str, label: str) -> dict:
    """Demo connectors are always available: they need no key and make no network calls."""
    return {"demo": True}


def call(app: str, label: str, action: str, payload: dict, fn: Callable[[], Any], credits: int = 1) -> Any:
    """Run one dummy API call and record it."""
    started = time.time()
    entry = {"t": datetime.now().isoformat(timespec="seconds"), "app": app, "label": label, "action": action,
             "input": payload, "output": None, "error": None, "credits": 0}
    try:
        require(app, label)
        result = fn()
        entry["output"] = result
        entry["credits"] = credits
        return result
    except (ConnectorError, ItemError) as exc:
        entry["error"] = str(exc)
        entry["error_kind"] = "item" if isinstance(exc, ItemError) else "call"
        raise
    finally:
        entry["ms"] = int((time.time() - started) * 1000) + seed(app, action, json.dumps(payload, sort_keys=True)) % 400 + 80
        CALLS.append(entry)
        try:
            STATE_DIR.mkdir(exist_ok=True)
            with CALLS_PATH.open("a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except OSError:
            pass
