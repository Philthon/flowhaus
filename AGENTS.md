# AGENTS.md

For coding agents (Claude Code, Codex, Cursor, ...) that set up or work on Flowhaus.

Flowhaus shows automations a person already runs (a GitHub Actions workflow, a script that writes a folder per run, anything with a small adapter) as a **plain-English map**, and reviews them against [docs/practices.md](docs/practices.md). Your job during onboarding: connect the user's automations and write a map a non-technical person understands.

## Ground rules

1. **Read-only toward the user's automations.** Never run, deploy, push to or edit the projects you connect: running them can cost money or publish things. You only write under `automations/` (git-ignored on purpose: don't commit it or move it).
2. **No secrets in Flowhaus.** `automation.yaml` holds paths, repo names and regexes, never keys. GitHub goes through `gh auth login`, the chat through the user's Claude Code or Codex sign-in, MCP servers through their existing setup. Don't create key files or MCP configs.
3. **Personal data stays private.** Don't open run outputs (recordings, exports, customer files). File names, sizes and the automation's own log (`flowhaus logs`, a run's `log.txt`) are fine. Keep `preview_words: 0` unless the user asks.
4. **Ask before:** scanning outside the folders the user named; `github.allow_toggle: true`; adding `local_path` (the chat can then read that code); `pull_requests: {enabled: true}`; switching on MCP servers (`flowhaus mcp enable`); `flowhaus autostart on`; running any remote test.

## Onboarding

Run from the repo root; every command takes `--json`.

```bash
uv sync && npm --prefix web install
uv run flowhaus doctor                         # exits 1 with the fix if something required is missing
uv run flowhaus scan ~/code ~/projects --json  # candidates; ask which folders first, and which to connect
uv run flowhaus add github-actions <id> --repo owner/name --workflow file.yml [--local-path ~/code/project]
uv run flowhaus add folder-runs <id> --path /path/to/runs
uv run flowhaus logs <id> --grep 'fetched|skipped|error'   # lines to count
uv run flowhaus check <id>                     # repeat until it prints ok
uv run flowhaus start                          # http://localhost:8765
```

Anything else (cron writing one log, a database of runs, n8n): a `type: python` adapter; copy `examples/automations/backup-log/`.

**Write the map** in `automations/<id>/automation.yaml` (reference: [docs/automations.md](docs/automations.md)). Follow the [writing conventions](docs/practices.md#writing-conventions). In short:
- `name` (2 to 5 words), `description` (what comes out), `terms` (what one item is called), `trigger.label` and `output.label` (start and end: required).
- 3 to 6 groups a person would name; every step then has a `group`.
- Each step:
  - `label`: a short verb phrase.
  - `description`: starts with "Gives you…", "Adds…", "Keeps…" or "Skips…".
  - `explain`: the logic in plain words, written from the code.
  - `file`: the code behind it.
  - `app`: the outside service, if any.
- Decisions get `kind: decision`, a `rule:` and labelled `branches:`. Three or more answers are checked top-down and end with `otherwise: true`. Waits get `kind: wait`, and every path ends somewhere.
- Write simply, for a reader with a junior engineer's knowledge. API, JSON and webhook are fine; the code's own names (DataFrame, node, dict) aren't.
- Counting rules (`in` / `out` / `skip` / `rows` / `fail`) match lines the automation already prints. A `fail` rule can say what kind of failure it is (`kind: auth`, `credits`, `transient`, `data`, …), which sharpens the next step Flowhaus suggests. If nothing countable is printed, tell the user and suggest a log line; don't add it yourself (rule 1).
- `kpis`: the two numbers the user cares about most.

**Verify.** `flowhaus check` fails on config errors, TODOs, rules that match nothing, numbers that don't add up, and unreadable runs. It also shows:
- **Conventions:** they fail only with `--strict`.
- **The harness's findings (`gap`, `blind spot`)**, each with a `next:` step. Fix what's yours in `automation.yaml`.
- **`ask the user:` questions.** Ask them, and record the answers in the app or in `automations/<id>/context.yaml` under `answers:`.

Compare the step table with the log, and check a failed run too: its error should name the step and say why.

**Test mode** ([docs/testing.md](docs/testing.md)): only if the automation has a real non-production switch (a `dry_run` input, a script flag, an n8n test webhook). Describe it truthfully in `test.non_production`. If there's none, say so; don't invent one.

Flowhaus is on-demand and local: it reads when a page asks and sends no alerts. Don't call it monitoring. Without automations, try `FLOWHAUS_AUTOMATIONS_DIR=examples/automations uv run flowhaus start`.

## Common mistakes

These happened before; avoid them.
- **A counting rule that matches nothing**, so the step shows "not run". Copy the exact line from `flowhaus logs`, and mind the escaping in YAML.
- **Two rules counting the same line**, so in ≠ out + skipped. One line, one rule.
- **A filtering step without a `skip` rule.** Its drops become silent. If the log says why items are skipped, count it with the reason.
- **Describing the code instead of the outcome:** "Calls the scrape API" instead of "Adds each page's text; skips pages that can't be fetched".
- **Inventing a test mode** or a `non_production` claim the automation doesn't have.
- **Real personal data in `example:`.** Examples are made up.
- **Opening run outputs** to understand the data. Read the log and the code instead.
- **(Working on Flowhaus)**
  - **Wrong words in the UI:** "rows", "node" or "DataFrame". Say "items" or the flow's `terms`.
  - **Forgetting the sandbox:** only Run is real, and everything else must stay in test mode (`runs.is_test`).
  - **Changing security-sensitive code without a test.**

## Working on the code

| Path | What |
|---|---|
| `server/app.py` | FastAPI, local only (host and origin checks) |
| `server/flows.py` | everything shown: connected automations, demo and built flows |
| `server/automations/` | connected automations: `base.py` (contract), `github_actions.py`, `folder_runs.py` |
| `server/maps.py` | map shapes, paths, conventions |
| `server/insights.py`, `harness.py`, `review.py`, `nextstep.py`, `checkup.py` | the harness: runs, the big picture, changes, what to do next, the Review |
| `server/agent.py`, `codex_engine.py` | the in-app chat (Claude Agent SDK, or Codex) |
| `server/runs.py`, `runtime.py`, `whatif.py` | running flows built in Flowhaus, test mode and its sandbox, Try / Replay |
| `server/sample_flows.py` | demo flows with generated history |
| `web/src` | React 19, Vite, Tailwind 4, React Flow: pages in `pages/`, map in `components/flow/` |

Run it while you work: `uv run flowhaus dev` (API with reload on :8000, the UI on :5173).

Before you finish a change:

```bash
uv run pytest -q && npm --prefix web run build && npm --prefix web run lint && npm --prefix web test
```

Conventions:
- **Harness first:** features help people see downstream effects, keep one source of truth, and prove changes with numbers. Every finding says what to do next, not only what's wrong.
- **UI text:** plain English, about outcomes: what came in, what came out, what was skipped and why.
- **Errors are data:** adapters return a failed run with a message; they never raise for a bad run.
- **Design:** flat, quiet Bauhaus (tokens in `web/src/index.css`): hairline borders, no shadows, zero radius, colour only for status. Light and dark.
- **Security-sensitive code** has tests in `tests/test_api.py`, `test_automations.py`, `test_flows_and_connectors.py`, `test_whatif.py` and `test_pipeline.py` (host and origin checks, the builder rule for the chat's flow tools, the step environment, the test-mode sandbox). Add a case when you touch it.
