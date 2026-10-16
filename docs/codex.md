# Running the chat on Codex

The in-app chat runs on **Claude** (through the Claude Agent SDK) or on **Codex** (through the Codex CLI). Pick one with the switch next to "Chat" ("Chat with Claude / Codex"). Both engines get the same tools and the same rules.

## Setup

Flowhaus doesn't install or sign in to Codex for you; you set it up in your own tools:

```bash
npm install -g @openai/codex     # or: brew install codex
codex login
uv run flowhaus doctor           # "chat on Codex: ok"
```

Set `FLOWHAUS_CODEX=/path/to/codex` if the CLI isn't on your PATH, and `CODEX_MODEL` to choose a model.

## How it works

For each message, Flowhaus runs `codex exec` in the Flowhaus project folder and resumes the same Codex thread, so the conversation continues. "New chat" starts a fresh thread.

**Codex runs with your own Codex setup.** Your `~/.codex/config.toml` (sandbox mode, approval policy, rules, MCP servers) applies exactly as when you use Codex yourself, and so does your sign-in. What Codex may read, run or change is managed there, not by Flowhaus. To make the chat stricter or looser, change your Codex setup.

**Flowhaus adds its own tools** through `server/codex_bridge.py`, a local MCP server. Each run gets a fresh token that only that Codex process receives. Calls to these tools get the same checks as in the Claude chat (`agent.call_codex_tool` → `check_tool_use`):
- **Flows** (`create_flow`, `run_flow`, …) work only in the builder, as in the Claude chat. Codex reads and edits files with its own tools.
- **Changes** (`start_change`, `review_change`, `propose_change`) still become a pull request only when you click **Open pull request**.
- **Runs** the chat starts are test-mode runs, in the sandbox (see [testing.md](testing.md)).
- **Your MCP servers through Flowhaus** (`list_connected_tools`, `use_connected_tool`): only the ones you switched on, with the same **Allow once / Deny** question. Servers in your Codex config are also available to Codex directly, under your Codex settings.

Undo, the automatic re-run after a change, and the activity log work the same as with Claude.

## If Codex answers with an error

The chat shows Codex's own error. The usual one is a model your account can't use: "The '…' model is not supported when using Codex with a ChatGPT account." Codex takes its model from your `~/.codex/config.toml` (`model = …`), so pick one your account supports there (in the Codex app, `/model` does it for you). To change it only for Flowhaus, start Flowhaus with `CODEX_MODEL=<model>`.

## Limits

- **Answer streaming:** the answer appears when Codex finishes a message, not word by word.
- **Version differences:** Codex's command-line options change between versions. If a run fails right away, run `codex --version` and `codex exec --help`, then open an issue with the output.
