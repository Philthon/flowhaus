# Tools for the chat (MCP)

The chat can use the [MCP](https://modelcontextprotocol.io) servers **you already set up** for Claude Code, Claude Desktop, Cursor or Codex: n8n, a database, your issue tracker and so on. Flowhaus keeps no MCP configuration and no keys of its own. It reads your existing setup and you choose which servers the chat may use.

## Where servers are found

Flowhaus only reads these files; it never writes them:

| Where | File |
|---|---|
| A project's MCP file | `.mcp.json` in this folder, or in a connected automation's `local_path` |
| Claude Code, per project ("local" scope) | `~/.claude.json` → `projects.<path>.mcpServers` |
| Claude Code, for you ("user" scope) | `~/.claude.json` → `mcpServers` |
| Claude Desktop | `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`) |
| Cursor | `~/.cursor/mcp.json` |
| Codex | `~/.codex/config.toml` (or `$CODEX_HOME`) → `[mcp_servers.<name>]`, and `.codex/config.toml` in a project |

If two files define the same name, the most specific one wins (top of the table first). `${VAR}` and `${VAR:-default}` in those files are filled in from the environment Flowhaus was started in, the same way Claude Code does it.

A server named like one of Flowhaus's own demo tool servers (`clay`, `firecrawl`, …) shows up with `_local` added, e.g. `firecrawl_local`.

## Choosing servers for the chat

Nothing is used until you switch it on:
- **Apps page:** "Tools for the chat (MCP)", one switch per server.
- **Terminal:** `uv run flowhaus mcp` lists them. `uv run flowhaus mcp enable n8n` and `uv run flowhaus mcp disable n8n` switch one on or off.

The only thing Flowhaus stores is the list of names you switched on, in `state/mcp.json`. Changes apply from your next chat message.

To see what a server can do, click **Show its tools** on the Apps page. Flowhaus starts the server briefly with your settings, lists each tool, and says whether it asks you first.

For servers that come from Codex:
- `env_vars` are forwarded from your environment, and `bearer_token_env_var` becomes the `Authorization` header.
- Servers that sign in through Codex's own OAuth can't be reused; Flowhaus says so.

## Every call asks first

When the chat wants to use one of these tools, it shows the tool and its input with **Allow once** / **Deny** and waits up to 10 minutes.

Tools your **Claude Code permission rules** already allow run without the question. These are `permissions.allow` entries such as `mcp__n8n__list_workflows`, `mcp__n8n__get_*` or `mcp__n8n` (the whole server), in `~/.claude/settings.json` or a project's `.claude/settings.json`. Keep changing tools (activate, run, write) off that list.

## n8n

Set n8n up for Claude Code the way its docs describe, then switch it on in Flowhaus. For example, with the community server [`n8n-mcp`](https://github.com/czlonkowski/n8n-mcp):

```bash
claude mcp add n8n --scope user -e MCP_MODE=stdio -e N8N_API_URL=http://homeserver:5678 \
  -e N8N_API_KEY=your-key -- npx -y n8n-mcp
uv run flowhaus mcp enable n8n
```

If your n8n has built-in MCP support, add its URL as a remote (`--transport http`) server in the same way.

Then ask the chat things like:
- "Which n8n workflow sends the Monday report, and did it run?"
- "Turn off the old lead-sync workflow." You'll be asked before that call runs.

Showing n8n workflows as maps on the Flows page needs an n8n adapter, planned for later. Until then, a `type: python` adapter can read n8n's executions API (see docs/automations.md).

## Notes

- **Remote servers that sign in with OAuth** in Claude Code (no key in the config) may need signing in again when the chat first uses them, or may not connect from Flowhaus at all. Servers with a key or token in their config work like they do elsewhere.
- **Your permissions:** MCP servers run with your permissions, and their results go to Claude like any other chat content. Only switch on servers you trust.
