# Flowhaus: see your automations as a plain-English map

[![CI](https://github.com/Philthon/flowhaus/actions/workflows/ci.yml/badge.svg)](https://github.com/Philthon/flowhaus/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Flowhaus is an open-source, local app that turns the automations you already run (GitHub Actions workflows, cron jobs, scripts) into readable flowcharts. For every run it shows what came in, what came out, what was skipped and why, and where a failure happened. An AI chat (Claude or Codex) explains runs and prepares fixes as pull requests you approve.**

> Status: early prototype (v0.2). Built-in support for **GitHub Actions** and **scripts that write a folder per run**; anything else through a ~50-line Python adapter.

![Flowhaus overview of GitHub Actions workflows and scripts: each automation with its recent runs, and the ones that need attention first](docs/images/flows.png)

When an automation goes quiet or half-fails, finding out what happened usually means reading logs. Flowhaus puts a map on top that someone who doesn't code can read:

- **A flowchart of every automation:** a start and an end, decisions with "Yes" / "No" answers, waits, and boxes you can open. Each step says what it gives you ("Adds each page's text; skips pages that can't be fetched").
- **Numbers on every step, for every run:** items in, items out, items skipped and why ("286 merged as duplicates").
- **What to do next, not just what's wrong:** a failed run opens the chat with the problem to fix first and a short next step ("Renew Xero's login, then run it again").
- **A Review of each flow:** errors (failures, silent losses, slow drift) and improvements, each with a priority from P0 to P3 and the log lines it's based on.
- **Try changes before they're real:** test one step on different input, replay a past run, or step through it box by box. All of it runs in a sandbox ([testing](docs/testing.md)).
- **An AI chat that knows your runs and code,** on Claude or Codex ([Codex](docs/codex.md)), with the MCP servers you already use ([MCP](docs/mcp.md)). Code changes become a pull request only when you click.

![A GitHub Actions workflow as a flowchart: steps with their item counts, a choice with three answers, a retry loop, and the chat explaining the failed run](docs/images/map.png)

**What it isn't:** a hosted service or a monitoring tool. Flowhaus runs on your computer (`127.0.0.1` only) and reads your automations' history when you open it. It never runs, deploys or edits them, sends no alerts, and stores no keys: it reuses your `gh` login and your Claude Code or Codex setup.

## Quick start

**With your coding agent** (Claude Code, Codex, Cursor): open this repo and say *"Set up Flowhaus for my automations. Follow AGENTS.md."* [AGENTS.md](AGENTS.md) walks it through finding what you run, connecting it, writing the map and checking it against real runs. It asks you before anything sensitive.

**By hand.** You need [uv](https://docs.astral.sh/uv/) and Node.js 20.19+ or 22.12+. For GitHub Actions you also need the [GitHub CLI](https://cli.github.com) (`gh auth login`). For the chat, use a [Claude Code](https://claude.com/claude-code) login, an `ANTHROPIC_API_KEY`, or the [Codex CLI](https://github.com/openai/codex).

```bash
git clone https://github.com/Philthon/flowhaus && cd flowhaus
uv sync && npm --prefix web install
uv run flowhaus doctor                                   # checks what's missing
uv run flowhaus add github-actions my-scraper --repo you/scraper --workflow scrape.yml
uv run flowhaus check my-scraper                         # repeat until it prints ok
uv run flowhaus start                                    # http://localhost:8765
```

Write the map in `automations/my-scraper/automation.yaml` ([reference](docs/automations.md)). To look around first, use the offline examples: `FLOWHAUS_AUTOMATIONS_DIR=examples/automations uv run flowhaus start`, or click **Explore demo flows**.

`flowhaus start` runs a small local server in the background. You can also use `stop`, `status`, and `autostart on` (macOS: start at login).

## How it works

Adapters read each automation's runs (GitHub Actions logs through `gh`, run folders, or your own Python) and turn them into one shape: steps with items in, out and skipped. A FastAPI server on localhost serves them to a React and React Flow UI. The harness reviews runs and changes against [docs/practices.md](docs/practices.md); `flowhaus check --strict` enforces the map's writing conventions in CI. A map of the code is in [AGENTS.md](AGENTS.md#working-on-the-code).

There's also an experimental **builder**: the chat can create new flows (Python steps run with [Hamilton](https://github.com/apache/hamilton)) using demo connectors. It's off unless demo flows are turned on.

## Security

Flowhaus runs with your permissions, so read [SECURITY.md](SECURITY.md) before you use the chat or the builder. In short:
- The API answers only on localhost.
- The chat follows your own Claude Code or Codex permission rules, and never reads private folders.
- Your automations are changed only through pull requests you open.
- Everything except **Run** runs in an operating-system sandbox.

## FAQ

**Does Flowhaus run or change my workflows?** No. It reads their logs and output folders. Code changes go to a private copy and become a pull request when you click.

**Do I need a server or a cloud account?** No. It's a local app; your automations keep running where they are (GitHub Actions, cron, a server).

**Which automations work?** GitHub Actions workflows and scripts that write one folder per run, out of the box. Anything else (a cron job writing one log, n8n, a database of runs) needs a small Python adapter.

**Is it a monitoring tool?** No. It reads when you open it and says how old its data is. It doesn't watch in the background.

## Development

```bash
uv run flowhaus dev               # API with reload on :8000, UI on :5173
uv run pytest -q && npm --prefix web run build && npm --prefix web run lint && npm --prefix web test
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and the [code of conduct](CODE_OF_CONDUCT.md).

## License

MIT, see [LICENSE](LICENSE). Third-party notices: [NOTICE.md](NOTICE.md). Changes: [CHANGELOG.md](CHANGELOG.md).
