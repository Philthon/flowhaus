"""The apps automations use. Flowhaus never connects to them itself and never stores keys.

- Your real automations: the apps they use, how each is set up (in its own project, CLI or CI) and a suggestion
  for setting it up if it isn't. You manage the connections and their secrets; Flowhaus only shows them.
- Demo flows: the demo Clay and Firecrawl connectors, which need no setup (made-up answers, no network).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from connectors import CATALOG
from connectors import _base as base
from server import flows

def _usage() -> dict:
    since = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    usage: dict = {}
    try:
        lines = base.CALLS_PATH.read_text().splitlines()[-5000:]
    except FileNotFoundError:
        lines = []
    for line in lines:
        try:
            c = json.loads(line)
        except json.JSONDecodeError:
            continue
        u = usage.setdefault(c["app"], {"calls_24h": 0, "errors_24h": 0, "credits_24h": 0, "last_call": None})
        if c["t"] >= since:
            u["calls_24h"] += 1
            u["credits_24h"] += c.get("credits") or 0
            u["errors_24h"] += 1 if c.get("error") else 0
        u["last_call"] = c["t"]
    return usage


def used_by() -> dict[str, list[str]]:
    """Which flows use which app (from step `app` tags)."""
    out: dict[str, list[str]] = {}
    for fid in flows.flow_ids():
        try:
            m = flows.get_map(fid)
        except Exception:
            continue
        for app in flows.apps(fid, m):
            out.setdefault(app.lower().replace(" ", "_"), []).append(m["flow"]["name"])
    return out


DEFAULT_HOW = {"GitHub Actions": "Read through the GitHub CLI (your existing `gh` sign-in), read-only"}
# Suggestions for setting an app up yourself. Flowhaus shows them; it never runs them or stores what they produce.
SETUP_HINTS = {
    "GitHub Actions": "gh auth login",
    "Firecrawl": "Keep the key where the automation runs: its .env file, or CI secrets (gh secret set FIRECRAWL_API_KEY -R owner/repo). "
                 "For Claude Code: claude mcp add firecrawl …",
    "OpenAI": "Keep OPENAI_API_KEY where the automation runs: its .env file, or CI secrets (gh secret set OPENAI_API_KEY -R owner/repo)",
    "Supabase": "Keep the Supabase URL and key where the automation runs (its .env file or CI secrets)",
    "n8n": "Set it up in n8n itself; for the chat, add the n8n MCP server to Claude Code (see docs/mcp.md)",
}
GENERIC_HINT = "Set it up where the automation runs (its .env file, your shell, or CI secrets). Flowhaus doesn't store keys."


def real_apps() -> list[dict]:
    """Apps the user's real automations use. They are connected in those projects; nothing is connected here.

    Each automation.yaml may describe its apps:  apps: {Firecrawl: {does: "...", connected: "..."}}
    """
    from server import flows as _flows

    found: dict[str, dict] = {}
    for fid, adapter in _flows.connected().items():
        info = adapter.config.get("apps") or {}
        for app in _flows.apps(fid):
            if app == "Code":
                continue
            entry = found.setdefault(app, {"users": [], "does": "", "connected": ""})
            entry["users"].append(adapter.meta()["name"])
            does = (info.get(app) or {}).get("does", "")
            if does and does not in entry["does"]:
                entry["does"] = f"{entry['does']} {does}".strip()
            entry["connected"] = entry["connected"] or (info.get(app) or {}).get("connected", "")
    return [{"id": app.lower().replace(" ", "_"), "name": app, "category": "", "auth": "managed", "available": True,
             "dummy": False, "connected": True,
             "managed_by": e["connected"] or DEFAULT_HOW.get(app, "Connected in the automation's own project"),
             "setup_hint": SETUP_HINTS.get(app, GENERIC_HINT),
             "description": e["does"], "key_hint": None, "connected_at": None,
             "usage": {"calls_24h": 0, "errors_24h": 0, "credits_24h": 0, "last_call": None}, "used_by": e["users"]}
            for app, e in found.items()]


def list_connections() -> list[dict]:
    from server import flows as _flows

    if not _flows.show_demo():
        return real_apps()
    usage, users = _usage(), used_by()
    result = []
    for app in CATALOG:
        if not app["available"]:
            continue
        result.append({**app, "auth": "demo", "connected": True, "key_hint": None, "connected_at": None, "dummy": True,
                       "managed_by": "Demo connector: made-up answers, no network, nothing to set up",
                       "usage": usage.get(app["id"], {"calls_24h": 0, "errors_24h": 0, "credits_24h": 0, "last_call": None}),
                       "used_by": sorted(set(users.get(app["id"], [])))})
    return result
