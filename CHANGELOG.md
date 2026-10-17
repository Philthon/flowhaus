# Changelog

All notable changes are listed here. The project uses [semantic versioning](https://semver.org); before 1.0, minor versions may include breaking changes to `automation.yaml`.

## 0.2.0

- **Maps are flowcharts** (Blue Prism style):
  - start and end pills
  - decisions as diamonds with labelled answers ("Yes" / "No") and the rule they apply
  - waits, and an end step for every outcome
  - right-angle lines routed around the boxes (ELK layout), keeping the main path straight, with no tangles
- **Start and end are required:** `flowhaus check` fails without a start and an end, or when a path never reaches an end.
- **The chat can run on Codex:**
  - its own shell is off, and it uses only Flowhaus's tools, with the same checks and approvals
- **A quick view on every shape:**
  - resting on a shape (or focusing it, or a long press) shows what it does and one real sample, or a written example when there's none
  - the panel gets an "About" tab with the full explanation, the code file, and every step a change there can reach
  - the setup agent writes `explain:` (and optionally `example:`) for each step
- **Choices and loops on the map:** a decision with three or more answers is a choice, checked top-down and ending with "Otherwise"; a path back to an earlier step shows as a "Go back to" marker.
- **Test a step with different input:** change a step's items (or type new ones) and run it, plus what comes after, in test mode. Connected automations get the chat's prediction instead.
- **Step through a run:** replay a recorded run one box at a time; nothing runs.
- **Replay a run in test mode:** a past run's items through the flow as it is now, compared item by item with what that run gave. Demo steps now give the same answer for the same item, so an unchanged flow replays identically.
- **The quick view** shows only what the shape doesn't already show, and has a **Test with different input** button.
- **Harness:** a step that wasn't on the path recent runs took is no longer reported as having no numbers.
- **New logo:** the house, built from the three shapes.
- **Nothing real happens unless you press Run:** the chat's runs, re-runs after an edit or undo, the test lab, testing a step and replaying a run are all test-mode runs. They write to a scratch folder and run in an operating-system sandbox (no network, no writes elsewhere). `flowhaus doctor` reports the sandbox.
- **The chat runs under your own setup:** Claude under your Claude Code settings (your permission rules decide what runs without asking; anything else shows an Allow / Deny card in the chat), Codex under your Codex setup. Flowhaus's own file guard and file tools are gone; its rules now cover only its own tools (the builder rule for creating and running flows). MCP servers: only the ones switched on in Flowhaus.
- **One Test menu** on every flow: test a step with different input, step through this run, replay this run, test lab; while stepping, the map pans to each box and dims what's still to come.
- **Dark mode** follows your computer's setting.
- **Readable maps:** the map no longer shrinks text below a readable size; scroll or drag for the rest.
- **Testing a step** keeps numbers as numbers and yes/no as yes/no, and says what to fix (a typo, two fields with the same name).
- **Faster map:** it's laid out again only when its shapes or lines change, not on every run update.
- **New demo flow, "Salesforce accounts from a sheet",** modelled on n8n's template 1792: Google Sheet rows → find or create the Salesforce account (a yes/no decision whose paths join again) → create or update the contact. Demo flows can now use decisions and paths.
- **Codex:** follow-up messages work (`codex exec resume` takes no `-C`), and its errors show as plain text.
- **The chat's labels say "the chat"**, not "Claude", since it can run on Codex.
- **Boxes with steps inside look like a stack** (a second sheet behind them); the small ">" button is gone. Open one by double-clicking, with Enter, or with **Open** in its quick view. A box with only one step inside is shown as that step.
- **The chat opens with what to fix first** when the run you're looking at failed (or there are error-level findings or map problems): the problem, a short next step worked out from the error (expired key, rate limit, missing field, …), a "Solve it with the chat" button, and the other problems below. With several, Flowhaus picks the one to start with (the earliest failure, blockers before hiccups) and says why. No model call: it's ready when the chat opens.
- **Review button** on every flow: everything the harness finds, in two tabs. **Errors:** broken in this run, silent failures, changing over recent runs. **Improvements:** ideas from the numbers, and finishing the setup (gaps, blind spots, the map's problems and conventions, questions). The button shows the worst open error (red for P0, yellow otherwise) or a light bulb when there are only improvements; a P0 also turns **Run** red. Each item has a next step, what it's based on, and actions (solve it with the chat, show the step, not relevant here). The bar above the map sums it up and opens it.
- **Drift and ideas:** output sliding over recent runs, a step skipping more and more, a new skip reason, slower runs, much more or less coming in; and ideas from the numbers (one reason behind most skips, the same kind of failure again and again).
- **Actionable everywhere:** every insight and finding has a next step and a chat prompt; failed steps, the overview's "needs attention", test checks, replays and tests offer "Solve it with the chat".
- **Priorities P0 to P3** on every finding and every point of a change review (P0 critical, P1 high, P2 medium, P3 low). Only P0 blocks: a pull request opens once its critical points (changes to CI, build or install files) are confirmed; the server refuses it otherwise. Everything else is a suggestion. For flows built in Flowhaus, Flowhaus checks the chat's changes itself by replaying the last real run.
- **One status strip** above the map replaces the failure banner, the map-problems banner and the findings bar: the most important thing now and its next step. The Review is a drawer next to the map, and the page asks for the review once, shared by the strip, the chat's opener and the drawer.
- **`fail` rules can declare their kind** (`kind: auth`, `transient`, …), which wins over guessing from the message.
- **Drift is quieter and surer:** the newest runs must all move the same way, by more than the usual run-to-run spread, and skip rates need 20 items a run. On the demo histories (random, no real drift) it raised no false alarms; before, it did in 4 of 11 windows.
- **The overview names the flows that need attention.**
- **Plain language** for a reader with a junior engineer's knowledge: API, JSON or webhook are fine; only the code's own names (DataFrame, node, dict) are flagged.
- **Writing conventions** are checked by `flowhaus check` as warnings with the fix; `--strict` fails on them (for CI). AGENTS.md is shorter, with a "common mistakes" section; the conventions live in docs/practices.md.
- **Fixed:** the start of a map said "0 came in" for automations that count but don't keep their input; the map could open too small to read.
- **Front-end tests** (Vitest) for the layout, stepping through and editing test items; they run in CI.
- **MCP servers from Codex's config** are found too. The Apps page can show which tools each server offers.
- **Back** sits next to the "Where you are" mini map (the path bar is gone), and coming back out of a box keeps that box in view instead of jumping to the start of the flow.
- **Activity has a Refresh button** and refreshes every hour; both read the newest runs from where they run (GitHub included). While a run is going it looks again every 10 seconds until it's done, and it says when it was last updated. It no longer asks every 5 seconds.
- **A failed step opens on Details**, where its error and next step are; "Before → after" shows only the items.
- **Removed:** the unused "request a flow" endpoint; `/api/insights` and `/api/next-steps` (the Review's `/api/checkup` carries both); unused UI components and the `cmdk` package they needed. The front-end lint is clean.

## 0.1.0

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
