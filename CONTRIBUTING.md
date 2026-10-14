# Contributing

Thanks for helping. Please follow the [code of conduct](CODE_OF_CONDUCT.md). This is an early prototype, so issues that describe a real automation you'd like to see mapped are as valuable as code.

- **Setup:** `uv sync && npm --prefix web install`, then `uv run flowhaus dev`.
- **Changes worth noting:** add a line to [CHANGELOG.md](CHANGELOG.md).
- **Before a PR:** `uv run pytest -q`, `npm --prefix web run build` and `npm --prefix web run lint`.
- **New automation types:** start as a `type: python` adapter (see docs/automations.md). If it's broadly useful, propose it as a built-in type in `server/automations/`, with tests that fake the outside world (see `tests/test_automations.py`, which fakes `gh`).
- **Text in the UI:** plain English, about outcomes. No "rows", "nodes" or "DataFrame".
- **Never commit** anything from `automations/`, `state/`, `runs/` or `flows/` (except the shipped example). They hold personal data and are git-ignored.

Code layout and conventions: [AGENTS.md](AGENTS.md#working-on-the-code).
