"""The bridge Codex uses to reach Flowhaus's tools when it runs the chat.

Codex starts this as a stdio MCP server (see server/codex_engine.py). It only forwards: it asks the running Flowhaus
which tools exist and passes each call on. Flowhaus checks every call to its own tools like in the Claude chat: the
builder rule, and the Allow / Deny question for tools of the MCP servers switched on in Flowhaus. Codex's own tools
(its shell, file edits, its own MCP servers) follow your Codex setup, not Flowhaus: see docs/codex.md.

    FLOWHAUS_URL    where Flowhaus runs (http://127.0.0.1:<port>)
    FLOWHAUS_TOKEN  the per-start token that proves the call comes from the chat Flowhaus started
"""

from __future__ import annotations

import os

import anyio
import httpx
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

URL = os.environ.get("FLOWHAUS_URL", "http://127.0.0.1:8000").rstrip("/")
HEADERS = {"X-Flowhaus-Token": os.environ.get("FLOWHAUS_TOKEN", "")}
# a call can wait for the user's Allow / Deny click
TIMEOUT = httpx.Timeout(connect=10, read=900, write=30, pool=10)


async def list_tools(ctx, params) -> types.ListToolsResult:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(f"{URL}/api/agent/tools", headers=HEADERS)
        r.raise_for_status()
    return types.ListToolsResult(tools=[types.Tool(name=t["name"], description=t["description"], input_schema=t["input_schema"])
                                        for t in r.json()["tools"]])


async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(f"{URL}/api/agent/call", headers=HEADERS,
                                  json={"name": params.name, "arguments": params.arguments or {}})
            r.raise_for_status()
            body = r.json()
    except httpx.HTTPError as exc:
        body = {"text": f"Flowhaus didn't answer: {exc}", "is_error": True}
    return types.CallToolResult(content=[types.TextContent(type="text", text=body["text"])], is_error=bool(body.get("is_error")))


server = Server("flowhaus", version="1", on_list_tools=list_tools, on_call_tool=call_tool)


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
