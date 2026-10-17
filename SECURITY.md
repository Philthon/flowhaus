# Security model

**Flowhaus stores no secrets.**
- **GitHub:** read through your `gh` login.
- **The chat:** uses your Claude Code login or `ANTHROPIC_API_KEY`.
- **MCP servers:** come from your existing setup.
- **Your automations:** keep their keys where they already live.

What Flowhaus writes is limited to the `state/` folder (caches, settings, change copies) and your automation configs.

Flowhaus is a **local, single-user tool**. It runs on your computer with your permissions, on demand (`flowhaus start`), or from login if you turn on `flowhaus autostart`. Please read this before you use the chat or the builder.

## What is protected, and how

| Risk | What Flowhaus does |
|---|---|
| Another website calling the local API (CSRF, DNS rebinding) | The server binds to `127.0.0.1` and only answers `Host: localhost / 127.0.0.1`. Changes (non-GET) are accepted only from Flowhaus's own page, matched by exact origin (scheme, host and port), and are refused when `Sec-Fetch-Site` says another site. (`server/app.py`) |
| What the chat may read, run or change | The chat runs under **your own Claude Code setup** (or your Codex setup, below): your Claude Code permission rules decide what it may do without asking, exactly as when you use Claude Code yourself, and anything they don't allow shows an **Allow / Deny** card in the chat and waits. On top, Flowhaus keeps only the two promises below: it never reads private folders (`private_paths`, and a folder-runs automation's run outputs) and never edits a connected automation's real code (`check_tool_use` in `server/agent.py`). What the chat reads is sent to Anthropic as part of the conversation, as with Claude Code. |
| The chat creating or running flows | Flowhaus's own flow tools work only in the **builder**, which needs demo flows turned on and a flow built in Flowhaus (or the "new flow" page). While you look at a connected automation, they're off, even if text in a log or source file asks for them. Runs the chat starts are test-mode runs (below). |
| The chat changing your real automations | Never directly. For automations with `pull_requests: {enabled: true}` it edits a private clone under `state/changes/`, and only source files there. Commit, push and `gh pr create` happen only when you click **Open pull request**; the chat has no tool for it. git hooks are off for those commands. Changes to CI, build and install files are flagged. |
| The chat running on Codex | Codex runs with **your own Codex setup**: your config, sandbox, approval policy, rules and MCP servers decide what it may read, run or change, exactly as when you use Codex yourself. Flowhaus adds its own tools through a local bridge with a per-run token, with the same builder rule and approvals as in the Claude chat. Flowhaus can't check Codex's own shell and file tools, so the private-folder and read-only-code rules above don't reach them: keep private folders out of Codex's sandbox. See docs/codex.md. |
| Tools from your MCP servers | Flowhaus reads the servers you set up for Claude Code, Claude Desktop or Cursor (never copying their keys), and the chat uses only the ones you switch on in Flowhaus (`--strict-mcp-config`). Calls your Claude Code permission rules don't allow show an Allow / Deny card. Only your own `~/.claude/settings.json` counts, never a project's or a connected repo's settings. |
| What Flowhaus itself hands the chat | For connected automations, Flowhaus's own tools give the chat counts, skip reasons and errors (`agent_context`), not item tables or file previews. What the chat reads beyond that with its own tools is up to your Claude Code or Codex permissions. |
| A chat reply sending data out | Chat replies can't load images (renderer override plus `Content-Security-Policy: img-src 'self'`). Links only open when you click them. |
| Your API keys in code the builder writes | Built flows run in a subprocess with a minimal environment (`PATH`, `HOME`, locale, temp dirs). `ANTHROPIC_API_KEY`, `GH_TOKEN` and the rest of your shell's variables are not passed. |
| Test runs touching production | Only a click on **Run** (or `python -m server.runs` in a terminal) is a real run. Everything else runs in **test mode**: Try it, Replay, the test lab, and the chat's runs and re-runs after an edit or undo. Test-mode runs write to `state/tests/` and run inside an operating-system sandbox (`sandbox-exec` on macOS, `bwrap` on Linux): they can write only to their scratch folder and the run record, and can't reach the network, even if a step ignores the folder it's given. `flowhaus doctor` says when this computer has no sandbox. Remote test runs (GitHub, your command, a webhook) need a `test.non_production` statement, shown before every run, plus your confirmation. Flowhaus passes no keys; they run with your own setup. |
| Switching your GitHub workflows by accident | Off unless `github.allow_toggle: true`. Each switch asks for confirmation in the UI and is logged. |

If you want the chat kept out of certain files or folders (secrets, customer exports, `~/.ssh`), say so in your Claude Code permission rules (`permissions.deny` in `~/.claude/settings.json`, e.g. `Read(./.env)`) or in your Codex sandbox settings. A `local_path` that is your home folder, a disk, or a folder that contains Flowhaus is still refused as an automation's code folder.

## What is not protected

- **Files your permission rules allow.** Apart from the private folders above, the chat can read whatever your Claude Code or Codex setup lets it read, and what it reads goes to the model provider. Deny secrets and personal data there if they're within its reach. The private-folder rule covers Claude Code's file tools (Read, Grep, Glob, edits), not its shell: keep Bash on "ask".
- **Real runs of built flows run real code.** When you click **Run**, the step code runs as you. It doesn't get your API keys, but it can still:
  - read and write anything your user account can, including `~/.ssh`
  - use your GitHub CLI login (`gh auth token`)
  - use the network

  Real runs are not sandboxed (test-mode runs are, see above). The builder is off unless you turn on demo flows; only use it where that's acceptable.
- **Prompt injection.** Text the chat reads could try to steer it: logs, error messages, source files, and pages fetched by connectors. With the builder off, Flowhaus's own tools can only read and answer; what the chat's own tools may do is up to your permission rules, so keep risky ones (shell, edits) on "ask". Treat its answers about untrusted automations with care.
- **Remote test runs are only as safe as your test mode.** Flowhaus can't verify that a `dry_run` input really skips publishing. That's what the `non_production` statement is for: read it before you confirm.
- **Pull requests run CI.** Once you open a pull request, your repository's CI may run its code with the repository's secrets. Read the diff first, and especially the flagged files.
- **MCP servers** run with your permissions and receive what the chat sends them. Tools you allow without asking run without a question.
- **Python adapters** (`type: python`) are ordinary code that the app loads. Treat them like any dependency you install.
- **The chat sends data to Anthropic:**
  - your messages
  - the map
  - recent run counts, reasons and errors
  - source files it decides to read

  Don't use the chat with code or logs you may not share with Anthropic.
- **Network use.** Don't expose the server on a network interface or behind a proxy. `FLOWHAUS_ALLOWED_HOSTS` exists for unusual local setups and weakens the host check.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting: the repository's "Security" tab, then "Report a vulnerability". Don't open a public issue.
