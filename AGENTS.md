# AGENTS.md

Instructions for coding agents (Claude Code, Codex, Cursor, ...) that set up or work on Flowhaus.

Flowhaus shows automations a person already runs (a GitHub Actions workflow, a script that writes a folder per run, anything with a small adapter) as a **plain-English map**. For every run it shows what came in, what came out, what each step skipped and why, and where a failure happened. A chat panel (Claude Agent SDK) explains runs and proposes changes. Your job during onboarding is to connect the user's automations and write a map that a non-technical person understands.

## Ground rules (read first)

1. **Read-only toward the user's automations.** Never run, deploy, push to, or edit the projects you connect. Running them can cost money or publish things. You only write files under `automations/`.
2. **Reuse what's set up; store no secrets.** `automation.yaml` holds paths, repo names and regexes, never keys or tokens.
   - **GitHub** goes through the user's `gh auth login`.
   - **The chat** uses their Claude Code login or `ANTHROPIC_API_KEY`.
   - **MCP servers** come from their existing Claude Code / Claude Desktop / Cursor setup.
   - **Automations** keep their own keys where they already are.

   Don't create new key files or MCP configs for Flowhaus.
3. **Personal data stays private.** Don't open run outputs (recordings, exports, customer files) to write a map. You may read:
   - file names and sizes
   - the workflow's or script's own log (`flowhaus logs`, a run's `log.txt`), which explains what happened

   Set `preview_words: 0` unless the user asks for previews.
4. **Ask before**:
   - scanning outside the folders the user named
   - setting `github.allow_toggle: true` (it lets the app switch the workflow on and off)
   - adding `local_path` (it lets the in-app chat read that code)
   - setting `pull_requests: {enabled: true}` (it lets the in-app chat prepare code changes; the user still approves every pull request)
   - switching on MCP servers for the chat (`uv run flowhaus mcp enable <name>`, [docs/mcp.md](docs/mcp.md))
5. `automations/` is git-ignored on purpose. Don't commit what you write there, and don't move it elsewhere.

## Onboarding flow

Run everything from the repo root. Every `flowhaus` command accepts `--json`.

### 1. Install and check

```bash
uv sync
npm --prefix web install
uv run flowhaus doctor
```

`doctor` exits 1 if something required is missing and prints the fix. Two checks are optional:
- **GitHub CLI**: needed only for GitHub Actions automations.
- **Chat**: needs `ANTHROPIC_API_KEY` or a Claude Code login. The map works without it.

### 2. Find what the user already runs

Ask the user which folders hold their projects, then:

```bash
uv run flowhaus scan ~/code ~/projects --json
```

It lists candidates, using paths, names and schedules only:
- GitHub workflows, with their repo and cron
- folders with dated run sub-folders
- crontab entries
- launchd agents (macOS)

Each candidate has an `add` command. Show the user the list and ask which ones to connect. Without folder arguments it searches the home folder, so ask first.

### 3. Add each automation

```bash
uv run flowhaus add github-actions <id> --repo owner/name --workflow file.yml [--local-path ~/code/project]
uv run flowhaus add folder-runs <id> --path /path/to/runs
```

These commands write `automations/<id>/automation.yaml`:
- **github-actions** reads the steps from the latest run.
- **folder-runs** guesses the steps from the files each run leaves.

Both leave `TODO`s for you.

Neither type fits (cron writing one log, a database table of runs, n8n, ...)? Write a `type: python` adapter. Copy `examples/automations/backup-log/` and see [docs/automations.md](docs/automations.md#python-custom-adapter).

### 4. Write the plain-English map

This is the important part. Edit `automation.yaml` (full reference: [docs/automations.md](docs/automations.md)). Flowhaus is a harness: it reviews automations and changes against [docs/practices.md](docs/practices.md). Read it once, because the map you write is what that review works from. In particular, give every step a `file`, so a change to that file can be traced to its step and everything after it.

- **`name`**: what the automation is, in 2 to 5 words, for example "Weekly newsletter digest".
- **`description`**: one sentence about what comes out. Not how it works.
- **Groups (3 to 6 top-level boxes):** the stages a person would name, like "Collect articles" or "Send the digest". Once you use groups, every step needs a `group`. An automation with 2 to 4 steps needs no groups: leave `map.groups` out.
- **Step `label`:** a short verb phrase, for example "Pick new articles".
- **Step `description`:** says what the step gives you.
  - Start with "Gives you …", "Adds …", "Keeps …" or "Skips …".
  - Name the concrete fields, for example: "Adds each page's text from Firecrawl; skips pages that can't be fetched."
  - No code words (function, API, JSON, regex) unless the user is technical.
- **`terms`**: what one item is called (`event`/`events`, `invoice`/`invoices`). The UI uses it everywhere.
- **`app`** on a step: the outside service it talks to (Firecrawl, OpenAI, Slack, ...). It shows as a badge.
- **`file`** on a step: which source file implements it, relative to `local_path`. It helps the chat answer questions.
- **`trigger.label`**: when it runs, in words ("Weekdays at 7:00"). Schedules are described automatically, but your wording is better.
- **`kpis`**: the two numbers the user cares about most, shown on the overview cards, for example `{label: events published, value: "{publish.out}"}`. Without it, the cards show how many items came out and how many runs went fine.
- **Folder runs:** set `count: rows` (CSV), `lines` or `words` on a step, so the numbers mean items and not files. Point `folder_runs.log` at the script's own log, so failures say why.

Most of the value comes from the numbers, so for GitHub Actions add counting rules from the log:

```bash
uv run flowhaus logs <id> --grep 'fetched|skipped|error'
```

Then add `in` / `out` / `skip` / `rows` / `fail` rules to the steps, plus an optional `summary` line. Match lines the workflow already prints. If it prints nothing countable, say so to the user and suggest adding a log line to their workflow; you can't make that change yourself (rule 1).

### 5. Verify

```bash
uv run flowhaus check <id>            # latest run
uv run flowhaus check <id> --run <run_id>
```

Repeat until it prints `ok`. It fails on any of these:
- config errors, typos in setting names, and TODOs left
- steps whose rules matched nothing
- numbers that don't add up
- runs that can't be read

It also prints the step table for a real run.

It also prints the harness's big-picture findings (`gap`, `blind spot`) and `ask the user:` questions. These don't fail the check:
- Fix what is yours to fix in `automation.yaml`, for example missing `kpis` or a `skip` rule.
- Put the questions to the user. Record their answers in the app, or in `automations/<id>/context.yaml` under `answers:` using the question ids from `--json`.

Compare the numbers with the log. A step showing `in=None out=None` usually means a rule regex didn't match. Check a failed run too, if there is one: the error should name the step that failed and say why in plain words (see `fail` rules).

### 5b. Test mode (optional, ask first)

The test lab ([docs/testing.md](docs/testing.md)) runs an automation on test items without production effects. For automations that run elsewhere, this needs a real non-production switch:
- a GitHub workflow input like `dry_run`
- a script flag
- an n8n test webhook

If one exists, add a `test:` block with `non_production` describing it truthfully, plus `fields` and `examples`. If none exists, don't invent one. Tell the user, and suggest adding it, e.g. a pull request from the in-app chat. Never run a remote test yourself without the user's go-ahead.

### 6. Start the app

```bash
uv run flowhaus start      # background server with the built UI: http://localhost:8765 (opens the browser)
uv run flowhaus start --no-open --port 8770   # without a browser, or if 8765 is taken
uv run flowhaus status     # running? where?
uv run flowhaus stop
```

To check it works without a browser: `curl -s localhost:8765/api/flows`. Each configured automation should be listed there. Tell the user to bookmark the URL. If they want it available without starting it, `uv run flowhaus autostart on` (macOS) starts it at login; ask first, because it adds a login item.

Flowhaus is on-demand and local:
- it reads the automations when a page asks
- it doesn't watch in the background or send alerts

Don't describe it to the user as monitoring.

Configs are re-read when they change, so there's no restart needed after edits. Give the user the URL. With no automation configured, the Flows page shows an onboarding guide, and new automations appear there by themselves. "Explore demo flows" adds the built-in demos.

For working on Flowhaus itself, use `uv run flowhaus dev` instead (API with reload on :8000, Vite on :5173; `--port` and `--web-port` change them).

### Trying it without your own automations

```bash
FLOWHAUS_AUTOMATIONS_DIR=examples/automations uv run flowhaus start
```

Two examples work offline:
- `invoice-export` (folder runs)
- `backup-log` (python adapter)

The two GitHub examples point at placeholder repos and show "no runs".

## Working on the code

| Path | What |
|---|---|
| `server/app.py` | FastAPI, local only (host + origin checks) |
| `server/flows.py` | registry of everything shown: connected automations, demo and built flows |
| `server/automations/` | connected automations: `base.py` (contract), `github_actions.py`, `folder_runs.py`, registry in `__init__.py` |
| `server/cli.py` | the `flowhaus` command |
| `server/agent.py` | in-app chat (Claude Agent SDK): tools, file guard (`check_tool_use`), prompts |
| `server/runs.py`, `runtime.py` | the runner for flows built in the app (Hamilton, in a subprocess with a minimal env) |
| `server/sample_flows.py` | demo flows with generated history |
| `pipeline/`, `flow_map.yaml` | the built-in "Contact list cleaning" demo |
| `connectors/` | dummy Clay and Firecrawl (no network) |
| `web/src` | React 19 + Vite + Tailwind 4 + React Flow. Pages in `pages/`, map in `components/flow/` |

Checks before you finish a change:

```bash
uv run pytest -q
npm --prefix web run build      # includes the TypeScript check
npm --prefix web run lint
```

Conventions:
- **Harness first:** Flowhaus reviews automations and changes against [docs/practices.md](docs/practices.md). Features should help users see downstream effects, keep one source of truth, and prove changes with numbers. `server/review.py` covers changes and `server/insights.py` covers runs.
- **User-facing text** is plain English, focused on outcomes: what came in, what came out, what was skipped and why. Never say "rows", "DataFrame" or "node" in the UI.
- **Errors are data:** adapters never raise for a bad run; they return a failed run with a message.
- **Design:** flat, quiet Bauhaus.
  - tokens in `web/src/index.css`
  - hairline borders, no shadows, zero radius
  - colour only for status
- **Security-sensitive code** has tests in `tests/test_api.py`, `tests/test_automations.py` and `tests/test_flows_and_connectors.py`. These cover the file guard, the host/origin checks and the step environment. Keep them passing, and add a case when you touch them.
