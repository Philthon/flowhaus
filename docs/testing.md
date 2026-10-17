# Testing automations (the test lab)

An automation is only as good as how it handles the items you didn't expect. The test lab lets you pressure-test one, Postman-style:
1. Write or generate test items.
2. Run them through the whole flow in **test mode**.
3. Check what happened to each one.

Open it with **Test** on any flow's page, or from a terminal:

```bash
uv run flowhaus test <id> --generate 20 --temperature 0.8
```

## Test a step, replay a run, step through a run

Everything for testing is under **Test** at the top of a flow's page:

| | What it does | Where else |
|---|---|---|
| **Test a step with different input** | Change the items a step got (or type new ones) and run that step, and if you like everything after it. Shows what happened to each item at each step, and what comes out. | The step's **Test** tab, or **Test with different input** in the quick view |
| **Replay this run** | Sends a past run's items through the flow as it is now and compares what comes out with what that run gave: same result, or which items would come out differently and why. Use it after a change, before it runs for real. | |
| **Test lab** | Many test items through the whole flow, checked one by one (below). | |

**Step through this run** (in the **Test** menu) walks through a recorded run one box at a time (◀ ▶ or the arrow keys). The map pans to each box and shows the run as it stood then, and the panel shows that step's items before and after. Nothing runs.

Testing a step and replaying a run happen in **test mode**, like the test lab: demo connectors only, output to a scratch folder, nothing added to the run history, and inside the test-mode sandbox (no network, no writes outside the scratch folder; see [SECURITY.md](../SECURITY.md)). They work for flows built in Flowhaus and the demos. Connected automations run where they live, so Flowhaus can't run their steps; there the chat predicts the result from the code and says it's a prediction.

## Test items and the temperature

Test items are saved per flow in `state/tests/<flow>/suite.json`. You edit them in a table, or generate them from the flow's sample data (or `test.examples`). The **temperature** decides how tricky generated items are:

| Temperature | What you get |
|---|---|
| Calm (0) | Typical items, like your sample data |
| Tricky (~0.35) | Extra spaces, capitals, accents, non-Latin letters, missing values |
| Edge cases (~0.65) | Broken emails and web addresses, other date formats, dates far in the past, weekend boundaries, very long text, duplicates |
| Wild (~0.85+) | Several problems at once, spreadsheet formulas, HTML, instructions aimed at an AI step, "null", only spaces |

Every generated item says what it tests ("email without @; company is empty"). For each item you set what you **expect**: kept, skipped, or anything.

## Checks

Like Postman tests, every test run is checked:
- **The run finished** and **no step failed**.
- **Numbers add up** at every step (in = out + skipped).
- **Every test item is accounted for**: kept, or skipped with a reason. Nothing disappears silently.
- **Items end up where you expected.**
- **Your own checks**, if your suite has any, e.g. `{"step": "keep", "measure": "out", "op": ">=", "value": 1}`.

For flows built in Flowhaus you also see, per item, the step that skipped it and why. Test runs show up in the run picker as "Test run". They never count toward the overview numbers, KPIs or insights.

## Where the test runs

| The flow lives… | How the test runs | What keeps it out of production |
|---|---|---|
| In Flowhaus (built flows, demos) | Here, on the test items | Demo connectors only; the output goes to `state/tests/<flow>/output/`, never the real output |
| On GitHub Actions | `gh workflow run` with test inputs | Your workflow, e.g. a `dry_run` input that skips publishing |
| As your own script | Your command, with `{items_file}` | Your script's dry-run flag; it also gets `FLOWHAUS_TEST=1` |
| In n8n (or anything with a webhook) | POST `{"test": true, "items": [...]}` to a test URL | The test webhook (n8n's "webhook-test" URL), or your workflow checking `test` |

Remote test runs run **your real code, with your own setup and keys**:
- Flowhaus doesn't hold credentials. Keys live where the automation runs: CI secrets, your shell, its `.env`.
- You write down what keeps the run out of production in `test.non_production`, and the UI shows it before every run.
- Remote runs always need a click on **Run test** in a confirmation (or `--yes` in the terminal).

```yaml
test:
  non_production: "dry_run=true makes the workflow skip publishing to the app"
  github:                         # pick one of github / command / webhook
    ref: main
    inputs: {dry_run: "true"}
    items_input: test_items       # optional: the test items, as JSON in this workflow input
  # command: ["python", "run.py", "--dry-run", "--items", "{items_file}"]   # runs in local_path
  # webhook: "${N8N_TEST_WEBHOOK_URL}"                                       # from your environment
  fields: {city: text, url: url}  # what one item looks like (built flows read this from their sample data)
  examples:
    - {city: Berlin, url: "https://example.com/events"}
```

If an automation has no test mode yet, for example a GitHub workflow without a `dry_run` input, the test lab says so. Ask the chat to prepare one as a pull request: an input that skips publishing and paid calls, plus the `test:` block. You review and merge it like any other change.
