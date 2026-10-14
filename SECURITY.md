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
| The chat reading secrets or personal data | The chat has **no shell**. It reads with `Read`, `find_files` and `search_files`, and every single file is checked by `check_tool_use` / `_read_denied` in `server/agent.py`. See below. |
| The chat writing code, or getting code run | Running code: only in the **builder**, which needs demo flows turned on and a flow built in Flowhaus (or the "new flow" page). Writing: there, or in the private copy of a connected automation's repo when `pull_requests` is enabled, where nothing runs. While you look at a connected automation, nothing is run, even if text in a log or source file asks for it. |
| The chat changing your real automations | Never directly. For automations with `pull_requests: {enabled: true}` it edits a private clone under `state/changes/`, and only source files there. Commit, push and `gh pr create` happen only when you click **Open pull request**; the chat has no tool for it. git hooks are off for those commands. Changes to CI, build and install files are flagged. |
| Tools from your MCP servers | Flowhaus reads the servers you set up for Claude Code, Claude Desktop or Cursor (never copying their keys) and uses only the ones you switch on. Every call shows an Allow / Deny card and waits, unless your Claude Code permission rules already allow that tool. |
| Your personal data reaching the model | Run folders (`folder_runs`) and `private_paths` are never readable. For connected automations the chat only gets counts, reasons and errors (`agent_context`), not item tables or file previews. |
| A chat reply sending data out | Chat replies can't load images (renderer override plus `Content-Security-Policy: img-src 'self'`). Links only open when you click them. |
| Your API keys in code the builder writes | Built flows run in a subprocess with a minimal environment (`PATH`, `HOME`, locale, temp dirs). `ANTHROPIC_API_KEY`, `GH_TOKEN` and the rest of your shell's variables are not passed. |
| Test runs touching production | Built flows run on test items with demo connectors, and their output goes to `state/tests/`. Remote test runs (GitHub, your command, a webhook) need a `test.non_production` statement, shown before every run, plus your confirmation. Flowhaus passes no keys; they run with your own setup. |
| Switching your GitHub workflows by accident | Off unless `github.allow_toggle: true`. Each switch asks for confirmation in the UI and is logged. |

The chat may read files only:
- inside this project folder
- inside the `local_path` of a connected automation, and there only source and config file types

A `local_path` that is your home folder, a disk, or a folder that contains Flowhaus is refused.

Always refused:
- `~` paths
- `.git`, `.venv`, `node_modules`, `state/`
- `.ssh`, `.aws`, `.config`, `.docker`, `.kube`
- `.env*`
- keys, certificates, credentials, tokens, password files, `hosts.yml`, `config.json`
- SQLite and other databases

Path checks ignore letter case (macOS disks do), and search tools check every file they open, without relying on `.gitignore`.

## What is not protected

- **Secrets under unusual names.** The guard recognises secrets by name and folder. A token pasted into an ordinary source file (`settings.py`) inside the project or a connected `local_path` can be read by the chat. Keep secrets in `.env` files or a secret manager, where they belong anyway.
- **Built flows run real code.** When the builder runs a step, that code runs as you. It doesn't get your API keys, but it can still:
  - read and write anything your user account can, including `~/.ssh`
  - use your GitHub CLI login (`gh auth token`)
  - use the network

  This is not a sandbox. The builder is off unless you turn on demo flows; only use it where that's acceptable.
- **Prompt injection.** Text the chat reads could try to steer it: logs, error messages, source files, and pages fetched by connectors. With the builder off it can only read (within the rules above) and answer. Treat its answers about untrusted automations with care.
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
