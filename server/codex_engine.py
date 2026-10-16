"""Run the chat on Codex instead of Claude.

Flowhaus starts `codex exec` for each message (resuming the same Codex thread, so the conversation continues), and
reads its JSON event stream.

Codex runs with your own Codex setup: your config, sandbox, approval policy, rules and MCP servers apply, exactly as
when you use Codex yourself. What Codex may read, run or change is managed there, not by Flowhaus. Flowhaus adds one
thing: its own tools (the map and runs, the builder, change copies and proposals), reached through
server/codex_bridge.py. Calls to those go through the same checks as in the Claude chat (agent.call_codex_tool).

Needs the Codex CLI (`codex`) on PATH, or FLOWHAUS_CODEX pointing at it, and a Codex sign-in (`codex login`).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from server import runtime

WORKDIR = runtime.ROOT  # like the Claude chat: Codex starts in the Flowhaus project


def codex_path() -> str | None:
    return os.environ.get("FLOWHAUS_CODEX") or shutil.which("codex")


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def status() -> dict:
    """Can the chat run on Codex here? {available, signed_in, path, why}."""
    path = codex_path()
    signed_in = (codex_home() / "auth.json").exists() or bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("CODEX_API_KEY"))
    why = None if path and signed_in else (
        "Install the Codex CLI (npm install -g @openai/codex), then sign in with `codex login`." if not path
        else "Sign in to Codex first: run `codex login` in a terminal.")
    return {"available": bool(path), "signed_in": signed_in, "path": path, "why": why}


def command(prompt: str, thread_id: str | None, url: str, model: str | None = None) -> list[str]:
    """The `codex exec` call for one message."""
    exe = codex_path() or "codex"
    bridge = {
        "command": sys.executable,
        "args": ["-m", "server.codex_bridge"],
        "cwd": str(runtime.ROOT),
        "env_vars": ["FLOWHAUS_URL", "FLOWHAUS_TOKEN"],  # forwarded from Codex's environment; never on the command line
        "default_tools_approval_mode": "auto",  # Flowhaus does the asking (Allow / Deny cards), not Codex
        "startup_timeout_sec": 30,
        "tool_timeout_sec": 900,  # a call may wait for the user's Allow / Deny
        "required": True,
    }
    args = [exe, "exec"]
    if thread_id:
        args += ["resume", thread_id]
    # your own Codex config (sandbox, approvals, rules, MCP servers) applies; Flowhaus only adds its tools
    # (it starts in WORKDIR as its working folder; `resume` doesn't take -C)
    args += ["--json", "--skip-git-repo-check", "-c", f"mcp_servers.flowhaus={_toml_inline(bridge)}"]
    if model:
        args += ["-m", model]
    return args + [prompt]


def _toml_inline(value) -> str:
    """A Python value as an inline TOML value (for `-c key=value`)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_inline(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {_toml_inline(v)}" for k, v in value.items()) + " }"
    raise TypeError(type(value))


def plain_error(message: str) -> str:
    """Codex often reports the service's error as a JSON string: keep only its message."""
    for _ in range(3):  # it can be nested: {"message": "{\"error\": {\"message\": ...}}"}
        try:
            data = json.loads(message)
        except (TypeError, ValueError):
            break
        if not isinstance(data, dict):
            break
        inner = data.get("error") if isinstance(data.get("error"), dict) else data
        message = str(inner.get("message") or message)
    return message


def _item_type(item: dict) -> str:
    # older Codex versions used item_type / assistant_message
    t = item.get("type") or item.get("item_type") or ""
    return "agent_message" if t == "assistant_message" else t


async def run(prompt: str, thread_id: str | None, url: str, token: str, on_text: Callable[[str], None],
              model: str | None = None, timeout: float = 1800,
              on_start: Callable[[asyncio.subprocess.Process], None] | None = None) -> tuple[str | None, str | None]:
    """Run one message. Streams the answer through on_text. Returns (thread_id, error or None)."""
    env = {**os.environ, "FLOWHAUS_URL": url, "FLOWHAUS_TOKEN": token}
    proc = await asyncio.create_subprocess_exec(*command(prompt, thread_id, url, model), cwd=str(WORKDIR), env=env,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                stdin=asyncio.subprocess.DEVNULL, limit=16 * 1024 * 1024)
    if on_start:
        on_start(proc)  # lets the chat's Stop button end it
    stderr_lines: list[str] = []

    async def drain() -> None:  # keep stderr flowing, so a chatty Codex can't block on a full pipe
        assert proc.stderr is not None
        async for line in proc.stderr:
            stderr_lines.append(line.decode(errors="replace").rstrip())
            del stderr_lines[:-20]

    drainer = asyncio.create_task(drain())
    error: str | None = None
    wrote = False
    try:
        async with asyncio.timeout(timeout):
            assert proc.stdout is not None
            async for raw in proc.stdout:
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                kind = ev.get("type")
                if kind == "thread.started":
                    thread_id = ev.get("thread_id") or thread_id
                elif kind == "item.completed" and _item_type(ev.get("item") or {}) == "agent_message":
                    text = (ev["item"].get("text") or "").strip()
                    if text:
                        on_text(("\n\n" if wrote else "") + text)
                        wrote = True
                elif kind in ("turn.failed", "error"):
                    err = ev.get("error") or {}
                    error = plain_error((err.get("message") if isinstance(err, dict) else str(err)) or ev.get("message")
                                        or "Codex stopped.")
            await proc.wait()
    except TimeoutError:
        proc.kill()
        error = "Codex took too long and was stopped."
    await asyncio.gather(drainer, return_exceptions=True)
    if proc.returncode not in (0, None) and not error:
        tail = [x for x in stderr_lines if x.strip()]
        error = (tail[-1] if tail else f"Codex exited with code {proc.returncode}")[:400]
    return thread_id, error
