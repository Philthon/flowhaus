# Testing automations (the test lab)

An automation is only as good as how it handles the items you didn't expect. The test lab lets you pressure-test one, Postman-style:
1. Write or generate test items.
2. Run them through the whole flow in **test mode**.
3. Check what happened to each one.

Open it with **Test** on any flow's page, or from a terminal:

```bash
uv run flowhaus test <id> --generate 20 --temperature 0.8
```

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
