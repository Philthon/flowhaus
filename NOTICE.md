# Third-party notices

Flowhaus is MIT licensed (see LICENSE). It includes or adapts code from these projects:

| Code | Where | License |
|---|---|---|
| [AI Elements](https://github.com/vercel/ai-elements) by Vercel | `web/src/components/ai-elements/` (adapted) | Apache-2.0 |
| [shadcn/ui](https://github.com/shadcn-ui/ui) components | `web/src/components/ui/`, `web/src/styles/shadcn-tailwind.css` | MIT |
| [Jost](https://github.com/indestructible-type/Jost) font (via Fontsource) | bundled by the web build | SIL Open Font License 1.1 |

It also depends on these packages, installed separately and not included here:
- **Python:** see `pyproject.toml`. Among them is [Hamilton](https://github.com/apache/hamilton) (Apache-2.0).
- **JavaScript:** see `web/package.json`. Among them is [React Flow](https://reactflow.dev) (MIT).

The map hides React Flow's attribution badge (`proOptions.hideAttribution`). React Flow allows this for non-commercial projects. If you use Flowhaus commercially, please consider [React Flow Pro](https://reactflow.dev/pro).

The chat uses the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python). That package bundles the Claude Code CLI, which is covered by [Anthropic's terms](https://www.anthropic.com/legal), not by this repository's license.

The full license texts ship next to that code: `web/src/components/ai-elements/LICENSE` (Apache-2.0, with a note on what was changed; each adapted file says so at the top) and `web/src/components/ui/LICENSE` (MIT).
