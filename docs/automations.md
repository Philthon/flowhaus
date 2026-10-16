# Connecting automations: `automation.yaml` reference

Each automation is a folder `automations/<id>/` with an `automation.yaml`.
- **Location:** the folder is git-ignored. Set `FLOWHAUS_AUTOMATIONS_DIR` to keep your configs somewhere else.
- **Reloading:** files are re-read when they change, so no restart is needed.
- **Validating:** `uv run flowhaus check <id>` validates a config and shows what the map shows for a real run.

Working examples are in [`examples/automations/`](../examples/automations).

- [Common fields](#common-fields)
- [The map](#the-map)
- [`github_actions`](#github_actions)
- [`folder_runs`](#folder_runs)
- [`python` (custom adapter)](#python-custom-adapter)
- [What the app reads and writes](#what-the-app-reads-and-writes)

## Common fields

| Field | Required | Meaning |
|---|---|---|
| `type` | yes | `github_actions`, `folder_runs` or `python` |
| `id` | no | Defaults to the folder name. Lowercase letters, digits, dashes. |
| `name` | yes | 2 to 5 words, shown as the title. |
| `description` | yes | One sentence about what comes out. |
| `trigger` | no | `{type: schedule \| manual \| webhook \| event, label: "Mondays at 7:00", app: GitHub Actions}` |
| `terms` | no | What one item is called: `{item: invoice, items: invoices}`. Default `item`/`items`. |
| `input_terms` | no | Same, for what comes in, if it's different (`{item: feed, items: feeds}`). |
| `output` | no | `{label: "Emailed to subscribers"}`, shown on the result box. |
| `next_run` | no | Text for "next run" when it can't be computed. |
| `state_label` | no | Text for the on/off state when it can't be read. |
| `local_path` | no | The automation's own code folder. The in-app chat may **read** source files there, never write. `~` is expanded. |
| `private_paths` | no | Folders (absolute, or relative to `local_path`) the chat must never read. Run folders of `folder_runs` are always private. |
| `apps` | no | Text for the Apps page: `{Mailgun: {does: "Sends the email.", connected: "Key in the repo's GitHub secrets"}}` |
| `summary` | no | One line per run: `"{fetch.out} pages read → {publish.out} published"`. Placeholders: `{<step>.in}`, `{<step>.out}`, `{<step>.skipped}`. Left out when a value is missing. |
| `kpis` | no | Up to two numbers for the overview cards: `[{label: events published, value: "{publish.out}"}, {label: skipped, value: "{filter.skipped}", good: down}]`. They are taken from the last finished run and compared with the run before. `good: down` means a drop is good news. Default: items out of the last run, and runs that went fine in the last 7 days. |
| `io` | no | `{input_step, output_step}`: which steps' tables show as "what came in" / "what came out", and which steps the run totals come from. |
| `pull_requests` | no | Let the chat prepare code changes as pull requests you approve: `{enabled: true, base: main, repo: owner/name}`. Off by default. See [Changes through pull requests](#changes-through-pull-requests). |
| `test` | no | Test mode for the test lab: how to run it without production effects, and what one item looks like. See [testing.md](testing.md). |
| `map` | see below | Groups and steps. |

**How totals are worked out.** Run and group totals are worked out the same way:
- **In** comes from the first step that counted something coming in.
- **Out** comes from the last step that counted something going out.
- **Skipped** is in − out when that adds up, because it's the same kind of item.

  Otherwise it is the sum of the steps' own skips, for example when pages come in and events go out.

Set `io` to pick the steps for the run totals.

Setting names are checked: `uv run flowhaus check` reports typos such as `outptu:` or `produce:`.

## The map

```yaml
map:
  groups:                       # optional; 3-6 top-level boxes read best
    - {id: collect, label: Collect articles, description: "Gives you every new article from your feeds."}
    - {id: details, label: ..., description: ..., parent: collect}   # nested box (up to 4 levels)
  steps:                        # in the order they run
    - id: fetch_feeds           # unique
      label: Read the feeds     # short verb phrase
      description: Gives you every article published in your feeds this week.
      group: collect            # required for every step once you use groups
      app: RSS                  # optional badge: the outside service this step talks to
      file: bot/feeds.py        # optional: the code behind it, relative to local_path
      unit: pages               # optional: what this step counts, if not `terms.items`
      explain: Reads each feed and keeps articles published since last Monday.   # the logic, in plain words
      example: "“How we cut our build time in half” from example.com/rss"        # shown when no real item is
```

A box with steps inside is drawn with a second sheet behind it, like a stack: double-click it (or use **Open** in its quick view) to see the steps. A group with only one step inside has nothing to open, so the map shows that step in its place.

When you rest on a shape, a quick view shows:
- `explain`, or the description if there's none
- the last run in one line
- one sample: a real item from the last run (what it changed, or one it skipped and why), otherwise `example`

The step's "About" tab shows all of it, plus the code file and every step a change here can reach.

Write descriptions about **what the step gives you**, not how it works. Name the fields it adds and what it skips:
- **Good:** "Adds each page's text from Firecrawl; skips pages that can't be fetched."
- **Bad:** "Calls the scrape API in a loop."

### Start, end, decisions and waits

The map is drawn as a flowchart, with shapes in the style of Blue Prism:

| Shape | What it is | Where it comes from |
|---|---|---|
| Pill, "Start" | What starts the automation | `trigger.label`, required |
| Box | A step that does something | a step (`kind: action` is the default) |
| Diamond | A decision: a question with labelled answers | `kind: decision` |
| Pointed on the left, flat on the right | A choice: a decision with three or more answers | `kind: decision` with 3+ `branches` |
| Box with cut corners | A wait: items held until something happens | `kind: wait` |
| Pill, "End" | How a path finishes | `kind: end`, or the flow's result (`output.label`) |

```yaml
trigger: {label: "Weekdays at 7:00"}          # the start (required)
output: {label: "Booked with a coach"}        # the end of the main path (or use `kind: end` steps)
map:
  steps:
    - {id: read_requests, label: Read new sign-ups, description: "Gives you every sign-up from today."}
    - id: wants_coaching
      kind: decision
      label: Coaching requested?
      description: Checks whether the person asked for coaching.
      rule: "The coaching date is filled in and in the future"   # the actual rule, in words
      file: src/coaching.py
      branches:                                 # the first answer goes straight on, the second down, a third up
        - {label: "Yes", to: book_coach}
        - {label: "No", to: not_requested, when: "No coaching date, or one in the past"}
    - {id: book_coach, label: Book a coach, description: "Adds a booked slot with a coach."}
    - {id: confirm, label: Send the confirmation, description: "Emails the booked slot to the person."}
    - {id: not_requested, kind: end, label: "Skipped: coaching not requested", description: "Nothing is booked."}
```

How the paths are worked out:
- **Next in the list.** A step goes to the next listed step, unless it has `next: <step id>` (or a list of ids) or, for a decision, `branches:`.
- **Ends are never fallen into.** An `end` is reached only through `next:` or a branch. A path that runs out of steps ends at the flow's result (`output.label`).
- **Write ends as outcomes.** For example: "Published", "Skipped: coaching not requested", "Held for review". "Not requested" and "Declined" are different ends.
- **Counts are optional.** A decision needs no counts. Which answer a run took shows from which steps ran: the path not taken stays grey.
- **Choices are checked top-down.** With three or more answers, the first that fits wins, and the map numbers them in that order ("1. Enterprise", "2. Mid-market"). End with a catch-all: `{label: Otherwise, otherwise: true, to: ...}`.
- **Loops show as "Go back to".** A path back to an earlier step ("wait 10 minutes and look again") is drawn as a marker next to where it leaves, not as a line running backwards. Click the marker to see the step it goes back to.

```yaml
    - id: drive_ok
      kind: decision
      label: Backup drive connected?
      branches:                                 # three or more answers: a choice, checked top-down
        - {label: "Yes", to: copy}
        - {label: "Not yet", to: retry, when: "Fewer than 3 tries so far"}
        - {label: Otherwise, otherwise: true, to: stopped, when: "Still missing after 3 tries"}
    - {id: retry, kind: wait, label: Wait and look again, description: "Waits 10 minutes.", next: drive_ok}   # a loop
```

`flowhaus check` fails until all of these hold:
- The map has a start (`trigger.label`) and an end (`output.label` or an `end` step).
- Every decision has at least two labelled answers.
- A choice has at most one "Otherwise", and it's the last answer.
- Every step is reached from the start.

## `github_actions`

The app reads the workflow through the [GitHub CLI](https://cli.github.com), using your `gh auth login`. It never needs a token in the config.

```yaml
type: github_actions
github:
  repo: owner/name
  workflow: digest.yml          # file name in .github/workflows/
  allow_toggle: false           # true: the app may run `gh workflow enable/disable` (asks for confirmation)
  runs: 25                      # how many recent runs to show
```

**With no `map`,** the map is built from the latest run's own jobs and steps. Setup steps such as checkout are hidden.

**With a map,** each step gets its status and numbers from one or both of these sources:

**`github_step: "<job>/<step name>"`** takes the status and duration from that workflow step.

**Log rules** run over the run log, line by line. Write them against the text that `uv run flowhaus logs <id>` prints after the `|`:
- Colour codes are removed first, so `Processed items: (\d+)` works even when the action colours the number.
- A step's rules see **the whole log**, not only its `github_step`. Make each pattern specific to that step's lines.
- `flowhaus logs` shows the first 400 lines. Counts are often at the end, so use `--tail 200`, or `--grep REGEX` to find them.

| Rule | Meaning |
|---|---|
| `in: {sum: 'Fetched (\d+) pages'}` | Items in: sum of capture group 1 over matching lines. |
| `out: {count: '^✓ '}` | Items out: number of matching lines. A bare string means `count`. |
| `skip: [...]` | Skipped items with a reason. A list of rules (see below). |
| `rows: '✓ fetched (?P<page>\S+)'` | Each match becomes a row in the step's table. Named groups become columns. |
| `fail: {pattern: '✗ all .* failed', message: "Nothing fetched for {sections}", kind: transient}` | A matching line fails the step, with this message. `kind` (optional) says what kind of failure it is (`auth`, `credits`, `transient`, `connect`, `gone`, `file`, `data`, `duplicate` or `code`), so the next step Flowhaus suggests fits; without it, Flowhaus guesses from the message. |

Skip rules:

```yaml
skip:
  - {count: '^skip (?P<url>\S+) (?P<reason>\w+)$', reason_map: {old: Older than a week, dup: Already sent}}
  - {sum: 'merged (\d+) duplicates', reason: Duplicate}
  - {json_counts: 'dropped: (\{.*\})'}      # a {"reason": count} object printed in the log
```

- A `(?P<reason>…)` group sets the reason per line, and `reason_map` turns raw values into plain words.
- A rule that exists but matches nothing counts as 0, not unknown.
- If only `in` or only `out` is known, the other is derived as in = out + skipped.

Fail messages can use these placeholders:
- `{line}`: the matching line
- `{sections}`: the names of the log sections where it matched
- `{count}`
- `{top_reason}`: the most common skip reason
- `{these}`: "That one was" or "Those were"

If the workflow failed and no `fail` rule matched, the first `##[error]` line is used.

Other options:

```yaml
log:
  section: '^##\[group\](?P<section>New York|Toronto)$'   # optional: names blocks of the log (e.g. one per city)
  section_end: '^##\[endgroup\]'                          # default shown
summary: "{fetch.out} pages read → {publish.out} published ({filter.skipped} skipped)"   # one line per run
io: {input_step: fetch, output_step: publish}             # whose table to show as "what came in" / "what came out"
```

- **Sections:** rows get a `section` column, and fail messages can name the sections.
- **Logs cache:** logs of finished runs are cached in `state/automations/<id>/`.
- **Runs that never started:** GitHub sometimes can't find a machine, so nothing ran and there is no log. Those runs say so in plain words.
- **Schedules:** the cron is described in words ("Weekdays at 07:30 UTC") unless you set `trigger.label`.

## `folder_runs`

This type is for a script that leaves one folder per run, like `exports/2026-10-01_09-00-00/`.

```yaml
type: folder_runs
folder_runs:
  path: ~/scripts/exports           # relative to local_path, or to the automation folder if there is none
  pattern: '^\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d$'   # which sub-folders are runs
  time_format: '%Y-%m-%d_%H-%M-%S'  # start time from the folder name (else the folder's time)
  input: orders.csv                 # glob: shown as "what came in"
  output: 'invoices*.csv'           # glob: shown as "what came out"
  preview_words: 0                  # opening words of text outputs to show in the app (0 = never)
  log: run.log                      # optional: the script's own log; its last error line explains a failure
map:
  steps:
    - {id: pull_orders, label: Pull orders, description: ..., produces: orders.csv, count: rows}
    - {id: make_invoices, label: Make invoices, description: ..., produces: 'invoices*.csv', count: rows, show: [size]}
```

`count` says what a step's number means:
- `files` (default): how many files matched
- `rows`: CSV/TSV lines minus the header
- `lines`
- `words`

Use `*` for dates in file names (`expenses_*.csv`), so next month's files still match.

A step succeeded when its `produces` glob matches a file in the run folder.

A run failed when a step produced nothing. That step is marked failed, and later steps are marked not run. With `log`, the failure message quotes the log's last error line.

`show` picks the columns in the step's table:
- `size`
- `lines`
- `words`
- `duration` (for `.wav` files)
- `modified`

Only file metadata is read. File contents are read only for `lines`/`words` counts and for `preview_words`, and they are never sent to the chat model.

## `python` (custom adapter)

Use this for anything else: a cron job that appends to a log, a table of runs in a database, an n8n instance, and so on.

```yaml
type: python
module: adapter.py        # in the automation folder
# ...common fields and map; any extra keys are yours (read them from config)
```

```python
from pathlib import Path
from server.automations.base import Automation, empty_node, group_results

class MyAutomation(Automation):
    def list_runs(self) -> list[dict]: ...          # newest first, summaries
    def get_run(self, run_id: str) -> dict | None: ...   # one run with per-step nodes; None if unknown

def create(config: dict, folder: Path) -> Automation:
    return MyAutomation(config, folder)
```

The adapter code runs inside the app with your permissions, so only use adapters you wrote or have read.

Rules for adapters:
- `get_run` must return a node for **every** step in the map. Use `empty_node(step)` for steps that didn't run.
- `run_id` must be safe in a URL: letters, digits, `-`, `_` and `.`, with no `/`.
- Return `None` from `get_run` for unknown ids, and don't raise for a failed run. A crash in `list_runs` shows as an error on that automation only.
- `summary.text` is the one-line summary. Alternatively, set `summary:` in the YAML; it works for every type.
- `run_totals(self.steps, nodes, self.config.get("io"))` from `base.py` works out the run totals for you.

A run summary looks like this:

```python
{"run_id": "2026-10-01T02-00-00", "status": "success" | "failed" | "running",
 "started_at": "2026-10-01T02:00:00", "finished_at": "...", "trigger": "schedule" | "manual",
 "error": None | {"node_id": "<step id>", "message": "Plain-English reason"},
 "summary": {"rows_read": 120, "rows_written": 118, "rows_rejected": 2, "text": "optional one-liner"}}
```

`get_run` adds the following to the summary:

```python
{"nodes": {"<step id>": {**empty_node(step), "status": "success", "rows_in": 120, "rows_out": 118,
                          "rows_rejected": 2, "reject_reasons": {"Can't be read": 2},
                          "sample_out": [{"_row_id": 1, "file": "a.jpg"}],   # table shown for the step
                          "log": [{"level": "info", "text": "..."}],
                          "error": None | {"message": "...", "type": "RunError", "traceback": ""}}},
 "groups": group_results(self.groups, self.steps, nodes),
 "input_items": [...], "output_items": [...] | None}
```

Optional overrides:
- `cached_run(run_id)`: cheap details for the activity feed.
- `set_enabled(enabled)`, together with `"can_toggle": True` from `meta()`: an on/off switch.
- `source_label()`: where it runs, for example "this computer".
- `agent_context(run)`: what the chat model sees. Remove personal data here.
- `check()`: extra config checks.
- `private_paths()`: folders the chat must never read.

See [`examples/automations/backup-log/adapter.py`](../examples/automations/backup-log/adapter.py).

## What the app reads and writes

**Reads:**
- your configs
- the GitHub CLI's output, through `gh run list`, `gh run view`, `gh workflow list` and `gh api` (GET only)
- run folders (metadata)
- source files under `local_path`, by the chat (its own tools, under your Claude Code or Codex permissions)
- file names (never contents) in the folders that mapped steps' `file`s live in, to spot code that isn't on the map

**Writes:**
- `state/`, the local cache and settings
- `automations/<id>/context.yaml`: your answers to the harness's questions, findings you marked not relevant (with your reason), and notes the chat kept. See [practices.md](practices.md#how-flowhaus-speaks-up).
- only if `allow_toggle: true` and you confirm in the UI: `gh workflow enable` / `gh workflow disable`

It never runs, deploys or edits a connected automation.

## Changes through pull requests

With `pull_requests: {enabled: true}`, the chat can do more than explain. When you ask for a change, it works in four steps:

1. **Explains** what it would change and the effect on the numbers.
2. **Works on a private copy.** It edits a clone of the automation's repository in `state/changes/<id>/`, never your own folder. It can only edit source files there, and it can't run anything.
3. **Shows you the change** in the chat: a summary, the diff, and warnings for files that run with your repository's secrets, such as `.github/workflows` and build files.
4. **Waits for you.** Only your click on **Open pull request** commits, pushes a branch `flowhaus/…` and opens the pull request with `gh`. **Discard** throws it away.

Requirements:
- `gh` signed in, and git able to push to the repo (SSH or `gh auth setup-git`).
- Either `local_path` (a git clone of the repo) or `github.repo` / `pull_requests.repo`.
- `base` defaults to the repo's default branch.

git hooks are switched off for these commits and pushes, so files the chat wrote can't run during them. CI in your repository may still run the pull request's code, so review the diff before you open it.

