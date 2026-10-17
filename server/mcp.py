"""MCP servers for the chat, reused from the tools you already set up on this computer.

Flowhaus keeps no MCP config and no keys of its own. It reads (never writes) the MCP servers configured in:
  - Claude Code:     ~/.claude.json (user scope, and per-project "local" scope)
  - project files:   .mcp.json in this folder and in each connected automation's local_path
  - Claude Desktop:  claude_desktop_config.json
  - Cursor:          ~/.cursor/mcp.json
  - Codex:           ~/.codex/config.toml (or $CODEX_HOME), and .codex/config.toml in a project
You choose which ones the chat may use (Apps page, or `flowhaus mcp enable <name>`); that choice is the only
thing Flowhaus stores (state/mcp.json: names, no settings). Keys stay in the original files or your environment.

Every call to one of these tools asks you in the chat first, unless your Claude Code permission rules already
allow it (an `mcp__<server>` or `mcp__<server>__<tool>` entry in permissions.allow of ~/.claude/settings.json or
the project's .claude/settings.json).
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
import threading
import tomllib
from pathlib import Path

from server import automations, runtime

RESERVED = {"flow", "clay", "firecrawl", "files", "changes"}  # Flowhaus's own tool servers
VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
STATE_PATH = runtime.ROOT / "state" / "mcp.json"
_lock = threading.Lock()


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _desktop_config() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _read_toml(path: Path) -> dict:
    try:
        data = tomllib.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _from_codex(servers: dict) -> dict:
    """Codex's [mcp_servers.<name>] tables in the common shape (keys stay where they are: env names, not values)."""
    out = {}
    for name, cfg in servers.items():
        if not isinstance(cfg, dict) or cfg.get("enabled") is False:
            continue
        if cfg.get("command"):
            env = {k: str(v) for k, v in (cfg.get("env") or {}).items()}
            for var in cfg.get("env_vars") or []:  # names Codex forwards from its environment
                name_ = var.get("name") if isinstance(var, dict) else var
                if name_:
                    env[str(name_)] = "${" + str(name_) + "}"
            out[name] = {"type": "stdio", "command": cfg["command"], "args": cfg.get("args") or [], "env": env}
        elif cfg.get("url"):
            headers = {k: str(v) for k, v in (cfg.get("http_headers") or {}).items()}
            headers.update({k: "${" + str(v) + "}" for k, v in (cfg.get("env_http_headers") or {}).items()})
            if cfg.get("bearer_token_env_var"):
                headers["Authorization"] = "Bearer ${" + str(cfg["bearer_token_env_var"]) + "}"
            entry = {"type": "http", "url": cfg["url"], "headers": headers}
            if not headers and cfg.get("auth", "oauth") in ("oauth", "chatgpt"):
                entry["problem"] = "signs in through Codex (OAuth); Flowhaus can't reuse that sign-in"
            out[name] = entry
    return out


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def sources() -> list[tuple[str, Path, dict]]:
    """(label, file, {name: server config}) for every place MCP servers are configured, most specific first."""
    out: list[tuple[str, Path, dict]] = []
    project_dirs = [runtime.ROOT, *[p for a in automations.all_automations().values() if (p := a.local_path())]]
    for d in project_dirs:
        f = d / ".mcp.json"
        if f.exists():
            out.append((f"project file in {d.name}", f, _read_json(f).get("mcpServers") or {}))
    claude = Path.home() / ".claude.json"
    data = _read_json(claude)
    for proj, cfg in (data.get("projects") or {}).items():
        if isinstance(cfg, dict) and cfg.get("mcpServers"):
            out.append((f"Claude Code (project {Path(proj).name or proj})", claude, cfg["mcpServers"]))
    if data.get("mcpServers"):
        out.append(("Claude Code", claude, data["mcpServers"]))
    desktop = _desktop_config()
    if desktop.exists():
        out.append(("Claude Desktop", desktop, _read_json(desktop).get("mcpServers") or {}))
    cursor = Path.home() / ".cursor" / "mcp.json"
    if cursor.exists():
        out.append(("Cursor", cursor, _read_json(cursor).get("mcpServers") or {}))
    for d in project_dirs:
        f = d / ".codex" / "config.toml"
        if f.exists():
            out.append((f"Codex project file in {d.name}", f, _from_codex(_read_toml(f).get("mcp_servers") or {})))
    codex = _codex_home() / "config.toml"
    if codex.exists():
        out.append(("Codex", codex, _from_codex(_read_toml(codex).get("mcp_servers") or {})))
    return out


def _expand(value: str, missing: list[str]) -> str:
    def sub(m: re.Match) -> str:
        if m.group(1) in os.environ:
            return os.environ[m.group(1)]
        if m.group(2) is not None:
            return m.group(2)
        missing.append(m.group(1))
        return ""

    return VAR.sub(sub, value)


def _sdk_config(cfg: dict) -> tuple[dict | None, str | None]:
    """The server in the Agent SDK's format, or (None, why not)."""
    if cfg.get("problem"):
        return None, cfg["problem"]
    missing: list[str] = []
    kind = cfg.get("type") or ("stdio" if cfg.get("command") else "http" if cfg.get("url") else None)
    if kind == "stdio":
        if not cfg.get("command"):
            return None, "no command"
        sdk = {"type": "stdio", "command": _expand(str(cfg["command"]), missing),
               "args": [_expand(str(a), missing) for a in cfg.get("args") or []],
               "env": {k: _expand(str(v), missing) for k, v in (cfg.get("env") or {}).items()}}
    elif kind in ("http", "sse"):
        sdk = {"type": kind, "url": _expand(str(cfg["url"]), missing),
               "headers": {k: _expand(str(v), missing) for k, v in (cfg.get("headers") or {}).items()}}
    else:
        return None, f"unsupported type {kind!r}"
    if missing:
        return None, f"needs environment variables: {', '.join(sorted(set(missing)))}"
    return sdk, None


def discover() -> dict[str, dict]:
    """Every MCP server found on this computer, by the name the chat would use. First (most specific) one wins."""
    found: dict[str, dict] = {}
    for label, path, servers in sources():
        for raw_name, cfg in servers.items():
            if not isinstance(cfg, dict):
                continue
            name = re.sub(r"[^a-z0-9_-]", "_", str(raw_name).lower())[:40] or "server"
            if name in RESERVED:
                name = f"{name}_local"  # keep Flowhaus's demo tools apart from yours
            if name in found:
                found[name].setdefault("also_in", []).append(label)
                continue
            sdk, problem = _sdk_config(cfg)
            kind = (sdk or {}).get("type") or cfg.get("type") or ("stdio" if cfg.get("command") else "http")
            where = Path(str(cfg.get("command", ""))).name if kind == "stdio" else re.sub(r"[?#].*", "", str(cfg.get("url", "")))
            found[name] = {"name": name, "original_name": raw_name, "source": label, "file": str(path),
                           "type": kind, "where": where, "sdk": sdk, "problem": problem}
    return found


def _enabled_names() -> set[str]:
    return set(_read_json(STATE_PATH).get("enabled") or [])


def set_enabled(name: str, enabled: bool) -> None:
    if name not in discover():
        raise KeyError(name)
    with _lock:
        names = _enabled_names()
        names = names | {name} if enabled else names - {name}
        STATE_PATH.parent.mkdir(exist_ok=True)
        STATE_PATH.write_text(json.dumps({"enabled": sorted(names)}, indent=2))


def _allow_rules() -> list[str]:
    """`mcp__…` entries from your own Claude Code permission rules (~/.claude/settings.json): tools you already let
    run without asking. The same file the Claude chat follows (`setting_sources=["user"]`); never a project's or a
    connected repo's settings, which someone else could have written."""
    rules = (_read_json(Path.home() / ".claude" / "settings.json").get("permissions") or {}).get("allow") or []
    return [r for r in rules if str(r).startswith("mcp__")]


def load() -> tuple[dict[str, dict], dict[str, str]]:
    """({name: {"sdk": ...}} for servers the chat may use, {name: problem} for enabled ones that can't start)."""
    found, servers, errors = discover(), {}, {}
    for name in _enabled_names():
        s = found.get(name)
        if s is None:
            errors[name] = "no longer found in your MCP settings"
        elif s["problem"]:
            errors[name] = s["problem"]
        else:
            servers[name] = s
    return servers, errors


def server_of(tool_name: str) -> tuple[str, str] | None:
    """('n8n', 'list_workflows') for 'mcp__n8n__list_workflows', if it isn't one of Flowhaus's own servers."""
    parts = tool_name.split("__", 2)
    if len(parts) == 3 and parts[0] == "mcp" and parts[1] not in RESERVED:
        return parts[1], parts[2]
    return None


def _allowed_by(rules: list[str], server: str, tool: str, original: str) -> bool:
    for rule in rules:
        r = rule.split("(")[0]
        for name in {server, original}:
            if r in (f"mcp__{name}", f"mcp__{name}__*") or fnmatch.fnmatch(f"mcp__{name}__{tool}", r):
                return True
    return False


def needs_approval(tool_name: str) -> bool:
    found = server_of(tool_name)
    if not found:
        return False
    server = discover().get(found[0])
    return not _allowed_by(_allow_rules(), found[0], found[1], (server or {}).get("original_name", found[0]))


def summary() -> dict:
    enabled, rules = _enabled_names(), _allow_rules()
    return {"servers": [{"name": s["name"], "source": s["source"], "type": s["type"], "where": s["where"],
                         "enabled": s["name"] in enabled, "problem": s["problem"], "also_in": s.get("also_in", []),
                         "allowed_without_asking": [r for r in rules if r.startswith((f"mcp__{s['name']}", f"mcp__{s['original_name']}"))]}
                        for s in discover().values()]}
