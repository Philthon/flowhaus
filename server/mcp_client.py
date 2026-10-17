"""Talk to one of your MCP servers directly: see which tools it offers, and call one.

Used by the Apps page ("Show tools") and by the Codex chat engine, which reaches the servers switched on in Flowhaus
through Flowhaus, so those calls get the same Allow / Deny question as in the Claude chat. (Servers in Codex's own
config are Codex's: its approval policy decides.) Servers start only when asked,
with the settings from your own Claude Code / Claude Desktop / Cursor / Codex setup (see server/mcp.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client


@contextlib.asynccontextmanager
async def _session(sdk: dict):
    kind = sdk.get("type", "stdio")
    if kind == "stdio":
        params = StdioServerParameters(command=sdk["command"], args=sdk.get("args") or [],
                                       env={**os.environ, **(sdk.get("env") or {})})
        with open(os.devnull, "w") as quiet:
            async with stdio_client(params, errlog=quiet) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
    elif kind == "sse":
        async with sse_client(sdk["url"], headers=sdk.get("headers") or None) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    else:
        async with create_mcp_http_client(headers=sdk.get("headers") or None) as http:
            async with streamable_http_client(sdk["url"], http_client=http) as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session


def _plain(exc: BaseException) -> str:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:  # anyio wraps errors in groups
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {exc}"[:300]


async def list_tools(sdk: dict, timeout: float = 25) -> list[dict]:
    """[{name, description, input_schema}] the server offers. Raises RuntimeError with a plain reason."""
    try:
        async with asyncio.timeout(timeout):
            async with _session(sdk) as s:
                result = await s.list_tools()
                return [{"name": t.name, "description": (t.description or "").strip(), "input_schema": _field(t, "input_schema", "inputSchema") or {}}
                        for t in result.tools]
    except TimeoutError as exc:
        raise RuntimeError(f"The server didn't answer within {timeout:.0f} seconds") from exc
    except Exception as exc:  # noqa: BLE001 - anything from the server: report it
        raise RuntimeError(f"Couldn't start or reach the server: {_plain(exc)}") from exc


async def call_tool(sdk: dict, tool: str, arguments: dict[str, Any], timeout: float = 120) -> str:
    """Call one tool and return its text result. Raises RuntimeError with a plain reason."""
    try:
        async with asyncio.timeout(timeout):
            async with _session(sdk) as s:
                result = await s.call_tool(tool, arguments or {})
    except TimeoutError as exc:
        raise RuntimeError(f"The tool didn't finish within {timeout:.0f} seconds") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"The call failed: {_plain(exc)}") from exc
    parts = []
    for c in getattr(result, "content", None) or []:
        parts.append(getattr(c, "text", None) or f"[{getattr(c, 'type', 'content')}]")
    text = "\n".join(parts) or "(no text in the result)"
    return ("Error from the tool: " + text) if _field(result, "is_error", "isError") else text


def _field(obj: Any, *names: str) -> Any:
    """MCP SDK 2.x uses snake_case field names, 1.x camelCase: accept both."""
    for n in names:
        try:
            value = getattr(obj, n)
        except AttributeError:
            continue
        if value is not None:
            return value
    return None
