# Changelog

All notable changes are listed here. The project uses [semantic versioning](https://semver.org); before 1.0, minor versions may include breaking changes to `automation.yaml`.

## 0.1.0 (unreleased)

First public version.

- **Map automations you already run** in plain English:
  - GitHub Actions workflows (read with `gh`)
  - scripts that write a folder per run
  - anything else through a small Python adapter
- **Per run, per step:** what came in, came out and was skipped (with reasons), and where it failed.
- **Overview:** list and card views, two KPIs per automation, and "didn't run when expected" detection.
- **Insights:** fewer items than usual, silent losses, a step that suddenly skips everything, repeated failures, and before/after numbers for merged changes.
- **Chat (Claude Agent SDK):**
  - explains runs, with read access to the automation's source files
  - prepares changes on a private copy; pull requests open only when you click
  - can use your existing MCP servers, asking before each call
- **Test lab:** generated or hand-written test items with a temperature, test runs wherever the automation lives (in Flowhaus, GitHub Actions, your command, a webhook), and checks on every item.
- **`flowhaus` CLI for agents:** `doctor`, `scan`, `add`, `logs`, `check`, `test`, `mcp`, `start` / `stop` / `status` / `autostart`, `dev`.
- **Local only:** the server listens only on 127.0.0.1, accepts changes only from its own page, and stores no secrets.
