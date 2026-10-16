# Automation practices

Flowhaus is a harness for automations: it maps them, reviews them, and helps change them. This guide is the standard it holds automations and changes to. The in-app chat follows it, and coding agents setting up Flowhaus should too.

The core idea: **an automation is a chain.** Items flow through steps, and every step depends on what the steps before it produced. A one-line change in step 3 can change the numbers in step 4, break step 9, or double the bill in step 12. So we judge every change by what it does to everything after it, not just to the line that changed.

## Principles

1. **Every step has a contract.**
   - Say what comes in, what goes out, and what it skips and why.
   - Name the fields it adds.
   - In the map, each step has a description that starts with "Gives you…", "Adds…", "Keeps…" or "Skips…".
2. **Skip, don't drop.** An item that leaves the flow leaves with a short, stable reason ("No event link", "Already sent"). Silent drops are the most common bug nobody sees.
3. **The numbers add up.** For each step, in = out + skipped. If they don't, items are being lost or duplicated, and `flowhaus check` flags it.
4. **Fail loudly, close to the cause.**
   - A failure names the step and says why in plain words.
   - Partial success is visible ("2 of 3 cities fetched") instead of hidden in a green run.
   - A run that "succeeds" with nothing out is treated as suspicious, not fine.
5. **One source of truth (DRY).** Keep each thing in one place:
   - **Lists, thresholds, prompts, field mappings:** in config.
   - **Shared logic:** in one function.
   - **Variants:** don't copy a step to make one; give it a parameter.

   In automations, copies drift silently: a fix lands in one copy and the other keeps producing wrong items, with no error anywhere.
6. **Safe to run again.** Re-running a step or the whole flow must not publish, email or charge twice. Use stable ids, upserts and duplicate checks at the boundaries.
7. **Narrow doors to the outside.**
   - One step per outside app.
   - Retries with backoff for errors that pass.
   - Clear failure for errors that don't, such as no credits or a bad key.
   - Log what each call cost when the app charges.
8. **Observable by default.**
   - Print countable lines ("Fetched 36 pages", "skip <url> old") and a short summary at the end.
   - Those lines are what the map counts, so they are part of the contract.
9. **Think downstream before changing anything.** Before changing a step, list every step after it that uses its output. Check what changes for each one:
   - fields
   - names
   - formats and units
   - counts
   - cost
10. **Pressure-test before you trust it.**
    - Run the flow on tricky items, not only typical ones: empty fields, odd formats, duplicates, very long or hostile text.
    - Every item must end up kept, or skipped with a reason.
    - Every automation needs a test mode that can't touch production (see [testing.md](testing.md)).
11. **Prove it with numbers.**
    - Before a change, say which numbers should move and roughly how much.
    - After the change has run, compare with the numbers from before (Flowhaus saves this baseline when a change is proposed).

## How a small change becomes a big one

| You change… | What happens downstream |
|---|---|
| A filter threshold (keep score ≥ 3 → ≥ 2) | More items reach every later step. Paid steps (AI, enrichment) cost more, and the final list gets noisier. |
| A field name or format (`date` → `start_date`, "Oct 5" → ISO) | A later step that reads the old name or format skips everything as "missing date", or silently treats all items as outside the window. |
| A log line's wording | The map's counting rule stops matching: the step shows "not run" or zero, though nothing changed. |
| Order of two steps | Duplicates get removed before or after enrichment, which changes counts and costs. |
| Error handling (catch-all `try/except`) | Failures become "success with 0 out", which looks fine until someone notices the empty result. |
| A schedule or time zone | Weekend windows shift. Items fall outside "this weekend" and are skipped. |
| A copy of a step "for one case" | Two versions drift. Fixes land in one, and the other keeps producing the old behaviour. |

## Common mistakes, and how they show on the map

| Mistake | Symptom in Flowhaus |
|---|---|
| Silent filter (items vanish without a reason) | Out drops, skipped stays 0, and the numbers don't add up |
| Upstream format change | A later step suddenly skips nearly everything with one reason |
| Duplicated logic | Two steps with near-identical descriptions; review flags repeated code in the change |
| Swallowed errors | Run succeeds with nothing out: insight "Ran fine but produced nothing" |
| Non-idempotent retries | Out jumps on re-runs; duplicates appear later |
| Schedule silently off | No failures, just no runs: insight "Didn't run when expected" |
| Out of credits or quota | One step fails or skips everything with the same reason; the reason says it |
| Happy-path-only test data | Changes look fine on the sample but behave differently on real runs; compare with the baseline after merging |

## Writing conventions

How a map should read. The ones marked **checked** are tested by `flowhaus check`: it shows them as warnings with the fix, and fails on them only with `--strict` (use that in CI). The rest are judgement, so the harness raises them as findings or leaves them to you.

| Convention | Checked |
|---|---|
| **Descriptions start with what you get**: "Gives you…", "Adds…", "Keeps…", "Skips…", not how it works | checked |
| **Labels are short verb phrases** ("Pick new articles"), 2 to 5 words | checked (over 6 words) |
| **Plain, simple words.** Assume a reader with a junior software engineer's knowledge: API, JSON, webhook and cron are fine; names from inside the code (DataFrame, node, dict, kwargs) are not | checked (code names) |
| **Every decision says its rule** in words (`rule:`), and every answer has a label | checked |
| **Items have a name** (`terms`: lead/leads, invoice/invoices), so every number reads naturally | checked |
| **Every step names its `file`**, so a change to that file can be traced to its step and everything after it | a finding |
| **Skip reasons are short, plain and stable.** They're grouped and counted: no ids or numbers in them | |
| **One group per stage** a person would name (3 to 6 top-level boxes). Small automations need no groups | |
| **Counting rules and log lines change together.** If a change rewords a log line the map counts, update `automation.yaml` in the same change | flagged in the change review |
| **One change at a time.** A pull request does one thing, so its effect on the numbers can be read | |

## Reviewing a change

The chat answers these before it proposes anything, and Flowhaus's automatic review backs it up:

1. **Which steps does it touch?** Flowhaus maps changed files to steps through `file`.
2. **What comes after them?** Flowhaus lists the downstream steps.
3. **Does the output change shape** (fields, names, types, formats, units)? Who reads it?
4. **What happens to the numbers** in each affected step, to cost, and to run time?
5. **Does it repeat logic that already exists?** Flowhaus flags added code that matches code elsewhere in the repo.
6. **Does it reword log lines the map counts on?** Flowhaus flags it.
7. **Is it still safe to run twice?** What happens when it fails halfway?
8. **Does it touch CI, workflow, build or install files?** Flowhaus flags them; they run with your repository's secrets.
9. **How will we know it worked?** Which number should move, and by how much? Flowhaus compares the first run after the merge with the saved baseline.

Each point the review finds has a priority, and only critical ones (P0) hold the pull request back: you confirm them before it opens, and the server refuses it otherwise. Today that's a change to CI, workflow, build or install files, which run with your repository's secrets. Everything else is shown as a suggestion: a log line the map counts (P1), the steps after it, repeated code, files no step points at (P2), and that it's untested (P3). For flows built in Flowhaus, Flowhaus checks the chat's change itself: it replays the last real run with the change, in test mode, and shows what would come out differently.

## How Flowhaus speaks up

Every finding says **what to do next**, and what that's based on (the log lines, or the numbers): actionable, not only a diagnosis. Every finding also has a priority, on the usual incident scale:

| | | Means | Examples |
|---|---|---|---|
| **P0** | Critical | Broken now, or about to do harm | a failed run, an error-level finding, a change to CI files |
| **P1** | High | Likely wrong, without anyone noticing | items lost without a reason, output sliding, a log line the map counts is edited |
| **P2** | Medium | Worth improving | no test mode, one reason behind most skips, repeated code |
| **P3** | Low | Polish | writing conventions, an untested change |

Only P0 ever blocks anything; the rest are suggestions. Where it shows:
- **The chat's first message** when something is broken: the problem to solve first, why that one, its next step, and a button to solve it with the chat.
- **The status strip above the map**: the most important thing right now (the failed run, else a map problem, else the top finding) with its next step. It opens the **Review**.
- **The Review** (a drawer next to the map; button at the top of every flow): everything at once, with priorities, in two tabs.
  - **Errors:** what's broken in this run, **silent failures** (runs that look fine but aren't, items lost between steps), and what's **changing over recent runs** (output sliding, a step skipping more and more, a new skip reason, slower runs, the same kind of failure again and again).
  - **Improvements:** ideas from the numbers (one reason behind most skips), and **finishing the setup**: the gaps below, blind spots, the map's problems and conventions, and the questions only you can answer.
  - The button shows the worst open error: a red warning for a P0, a yellow one otherwise, and a light bulb when there are only improvements. A P0 also turns **Run** red.
- **A failed step's panel** and **the Flows overview**: the next step next to the error.

The harness has opinions, but it isn't stubborn. It finds:

- **Big picture:** what the automation as a whole is missing against these practices. Examples: no safe test mode, a filter that doesn't count what it skips, a re-run that would publish twice, failures that won't say why.
- **Blind spots:** what Flowhaus can't see. Examples: steps with no numbers, items that vanish between two steps, code next to the steps that isn't on the map, paid calls nobody counts.
- **Questions only you can answer.** It asks only when your answer changes the judgement:
  - what a normal run produces
  - whether a high skip rate is the step's job
  - whether a step is safe to run twice
  - who notices a failed run

  Each answer becomes a check. For example, "normal is 50–80" turns a run with 12 into a warning.

Every finding can be marked **not relevant here, with a reason**. It then stays quiet, and the chat respects the reason. Answers, dismissals and notes from the chat live in `automations/<id>/context.yaml`, which you can read and edit. `flowhaus check` prints the same findings and questions without failing on them.

The chat follows the same stance:
- It points out the one finding that matters for what you're doing.
- It asks one short question when the answer depends on something only you know.
- It remembers your answer.
- It says its view once, then goes with your call.

