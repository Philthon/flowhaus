export type Status = "not_run" | "running" | "success" | "failed";

export type Group = { id: string; label: string; description: string; parent: string | null };
export type Step = {
  id: string;
  label: string | null;
  description: string | null;
  group: string | null;
  app: string | null;
  file: string | null;
  line: number | null;
  inputs: string[];
  /** Flowchart shape: action (box), decision (diamond), wait (cut corners), end (pill). */
  kind?: "action" | "decision" | "wait" | "end";
  /** For a decision: the rule it applies, in words. */
  rule?: string | null;
  /** The logic in one or two plain sentences (written by the setup agent), for the quick view and "About". */
  explain?: string | null;
  /** A made-up example, shown when there's no real one from a run. */
  example?: string | null;
  branches?: { label?: string; to: string; when?: string | null }[];
};
export type MapEdge = {
  source: string;
  target: string;
  label?: string | null;
  when?: string | null;
  /** A choice (3+ answers): the order its answers are checked in, and whether this one is the catch-all. */
  order?: number;
  otherwise?: boolean;
};
export type Level = {
  children: string[];
  edges: MapEdge[];
  inbound: { from: string; target: string }[];
  outbound: { source: string; to: string }[];
};
export type FlowMap = {
  groups: Group[];
  steps: Step[];
  edges: MapEdge[];
  title: string;
  flow: FlowMeta;
  levels: Record<string, Level>;
  problems: string[];
};

export type Counts = {
  status: Status;
  rows_in: number | null;
  rows_out: number | null;
  rows_rejected: number;
  rows_changed: number;
  calls_total?: number;
  credits?: number;
};
export type RunError = { node_id: string | null; message: string };
export type RunSummary = {
  run_id: string;
  status: Status;
  started_at: string;
  finished_at: string | null;
  input_file: string;
  trigger: string;
  /** Not a real run: the test lab, the chat's runs and re-runs. Output went to a scratch folder. */
  test_mode?: boolean;
  summary: { rows_read: number | null; rows_written: number | null; rows_rejected: number } | null;
  error: RunError | null;
};
export type Run = RunSummary & {
  input_count?: number;
  output_count?: number | null;
  nodes: Record<string, Counts & { label: string; duration_ms: number | null; error: StepError | null }>;
  groups: Record<string, Counts & { failed_step: string | null }>;
  previous: {
    run_id: string;
    nodes: Record<string, PrevCounts>;
    groups: Record<string, PrevCounts>;
  } | null;
};
export type PrevCounts = { rows_rejected: number | null; rows_out: number | null };

export type Row = Record<string, string | number | null>;
export type StepError = { message: string; type: string; traceback: string };
export type Rejected = { _row_id: number; reason: string; before: Row; after: Row | null };
export type LogLine = { t?: string; level: "info" | "warn" | "error" | "print"; text: string };
export type Preview = Counts & {
  kind: "step" | "group" | "input" | "output";
  paired?: boolean;
  note?: string;
  items?: Row[] | null;
  destination?: string | null;
  node_id: string;
  run_id: string;
  duration_ms?: number | null;
  sample_in: Row[];
  sample_out: Row[];
  rejected_samples: Rejected[];
  reject_reasons: Record<string, number>;
  log: LogLine[];
  error: StepError | null;
  failed_step?: string | null;
  /** For a failed step: what to do first, and what that's based on. */
  next_step?: string | null;
  evidence?: string[];
  unseen?: string | null;
  calls?: ConnectorCall[];
};
/** One step tried on edited items, in test mode ("what if this step got these items?"). */
export type WhatIfFate = {
  n: number;
  outcome: "kept" | "changed" | "skipped" | "failed";
  reason?: string | null;
  changes?: Record<string, [unknown, unknown]>;
  /** At a decision: the answer this item went on with ("Yes", "No"). */
  path?: string | null;
};
export type WhatIf = {
  mode: "run" | "predict";
  step: string;
  note: string;
  steps?: { id: string; label: string; status: Status; error: string | null; items: WhatIfFate[] }[];
  out?: Row[];
  /** A replay: what comes out now against what that run gave. */
  compare?: {
    before: number;
    after: number;
    changed: number;
    now_skipped: number;
    now_kept: number;
    examples: { item: string; changes?: Record<string, [unknown, unknown]>; now?: string }[];
  };
};
/** What's wrong now: the problem to solve first (with why and its next step), and the others. */
export type Problem = {
  id: string;
  node_id: string | null;
  kind: string;
  title: string;
  detail: string;
  next_step: string;
  prompt: string;
  /** What the next step is based on (log lines, numbers), and what Flowhaus couldn't see. */
  evidence?: string[];
  unseen?: string | null;
};
export type NextSteps = { first: (Problem & { why: string | null }) | null; others: Problem[] };
export type ConnectorCall = {
  t: string;
  app: string;
  label: string;
  action: string;
  input: Record<string, unknown>;
  output: unknown;
  error: string | null;
  error_kind?: "item" | "call";
  credits: number;
  ms: number;
};
export type Connection = {
  id: string;
  name: string;
  category: string;
  description: string;
  auth: "demo" | "managed";
  managed_by?: string;
  setup_hint?: string;
  available: boolean;
  dummy: boolean;
  connected: boolean;
  key_hint: string | null;
  connected_at: string | null;
  actions?: string[];
  used_by: string[];
  usage: { calls_24h: number; errors_24h: number; credits_24h: number; last_call: string | null };
};

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json();
}

const q = (flowId: string) => `flow_id=${encodeURIComponent(flowId)}`;

export type Settings = {
  show_demo: boolean;
  /** Which agent runs the chat. Same tools and rules either way. */
  chat_engine: "claude" | "codex";
  codex: { available: boolean; signed_in: boolean; path: string | null; why: string | null };
  automations: number;
  automation_errors: Record<string, string>;
  project_dir: string;
  automations_dir: string;
};

/** A code change the chat prepared for a connected automation. Nothing leaves this computer until the user opens the PR. */
/** An MCP server found in your existing setup (Claude Code, Claude Desktop, Cursor, .mcp.json). */
export type McpServer = {
  name: string;
  source: string;
  type: string;
  where: string;
  enabled: boolean;
  problem: string | null;
  also_in: string[];
  allowed_without_asking: string[];
};

/** Something a reviewer would notice from the runs (see docs/practices.md). */

/** The harness's big-picture view of a connected automation (server/harness.py). */
export type HarnessFinding = {
  id: string;
  kind: "gap" | "blind_spot";
  level: "info" | "warn" | "error";
  title: string;
  detail: string;
  practice?: string | null;
  node_id?: string | null;
  ask?: string | null;
};
export type HarnessQuestion = {
  id: string;
  title: string;
  detail: string;
  node_id?: string | null;
  options: { value: string; label: string }[];
  free_text?: string;
};
export type Harness = {
  findings: HarnessFinding[];
  questions: HarnessQuestion[];
  dismissed: { id: string; title: string; reason: string; at: string }[];
  answered: { id: string; title: string; answer: string; note?: string | null; at: string }[];
  coverage: { steps: number; with_numbers: number | null; linked_to_code: number; questions_answered: number; questions: number } | null;
  context_file: string | null;
};

/** One thing the review found, with what to do about it. `finding`s can be dismissed with a reason. */
/** P0 critical (broken now), P1 high (likely wrong unnoticed), P2 medium (worth improving), P3 low (polish).
 *  Only P0 ever blocks anything; the rest are suggestions. */
export type Priority = "P0" | "P1" | "P2" | "P3";
export const PRIORITY_LABEL: Record<Priority, string> = { P0: "Critical", P1: "High", P2: "Medium", P3: "Low" };

export type ReviewItem = {
  id: string;
  source: "run" | "insight" | "finding" | "map" | "convention";
  priority: Priority;
  level: "info" | "warn" | "error";
  title: string;
  detail: string;
  next_step?: string | null;
  prompt?: string | null;
  node_id?: string | null;
  evidence: string[];
  why?: string | null;
  unseen?: string | null;
  practice?: string | null;
};
export type Checkup = {
  /** The problem to solve first and the others: the chat's opener reads this. */
  plan: NextSteps;
  /** Errors: what's broken in the run you're looking at, what fails silently, what drifts. */
  fix_now: ReviewItem[];
  silent: ReviewItem[];
  drift: ReviewItem[];
  ideas: ReviewItem[];
  /** Improvements: ideas, and finishing the setup (gaps, blind spots, the map's problems and conventions; with `questions`). */
  setup: ReviewItem[];
  questions: HarnessQuestion[];
  coverage: Harness["coverage"];
  dismissed: Harness["dismissed"];
  answered: Harness["answered"];
  context_file: string | null;
  /** fix_now + silent + drift */
  errors: number;
  /** ideas + setup + questions */
  improvements: number;
  total: number;
  runs_checked: number;
};

export type TestCase = { id: string; item: Record<string, unknown>; note: string; expect: "kept" | "skipped" | "any"; generated?: boolean };
export type TestCheck = { name: string; ok: boolean; detail: string };
export type TestRun = {
  id: string;
  flow_id: string;
  mode: string;
  status: "running" | "done" | "failed";
  started_at: string;
  run_id: string | null;
  checks: TestCheck[];
  results: { case_id: string; note: string; expect: string; got: string; step: string | null; reason: string | null; ok: boolean }[];
  output: string | null;
};
export type TestLabState = {
  mode: { kind: string; ready: boolean; label: string; non_production?: string; setup?: string | null };
  fields: { name: string; kind: string }[];
  suite: { cases: TestCase[]; checks: Record<string, unknown>[] };
  runs: TestRun[];
};

export type Change = {
  id: string;
  flow_id: string;
  repo: string;
  base: string;
  branch: string;
  title: string;
  summary: string;
  status: "editing" | "proposed" | "opened" | "discarded";
  diff?: string;
  files: string[];
  warnings: string[];
  /** What the user confirms before the pull request opens (from the review, not the chat). */
  gate?: { id: string; priority: Priority; text: string }[];
  impact?: string;
  review?: {
    touched?: { id: string; label: string }[];
    downstream?: { id: string; label: string }[];
    unmapped_files?: string[];
    repeats?: { file: string; same_as: string; code: string }[];
    log_lines?: { step: string; label: string; line: string }[];
  };
  pr_url: string | null;
  created_at: string;
};

async function postJson<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: body === undefined ? {} : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r.json().then((b) => b.detail).catch(() => null);
    throw new Error(typeof detail === "string" ? detail : `the server answered ${r.status}`);
  }
  return r.json() as Promise<T>;
}

export const api = {
  openPullRequest: (id: string, confirmed: string[]) => postJson<Change>(`/api/changes/${id}/pull-request`, { confirmed }),
  discardChange: (id: string) => postJson<Change>(`/api/changes/${id}/discard`),
  answerApproval: (id: string, allow: boolean) => postJson<{ ok: boolean }>(`/api/chat/approvals/${id}`, { allow }),
  tests: (flowId: string) => fetch(`/api/tests/${encodeURIComponent(flowId)}`).then((r) => json<TestLabState>(r)),
  saveSuite: (flowId: string, suite: TestLabState["suite"]) =>
    fetch(`/api/tests/${encodeURIComponent(flowId)}/suite`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(suite),
    }).then((r) => json<TestLabState["suite"]>(r)),
  generateTests: (flowId: string, count: number, temperature: number) =>
    postJson<{ cases: TestCase[] }>(`/api/tests/${encodeURIComponent(flowId)}/generate`, { count, temperature }),
  runTests: (flowId: string, confirmed: boolean) => postJson<TestRun>(`/api/tests/${encodeURIComponent(flowId)}/run`, { confirmed }),
  testRun: (flowId: string, testId: string) =>
    fetch(`/api/tests/${encodeURIComponent(flowId)}/runs/${testId}`).then((r) => json<TestRun>(r)),
  whatIf: (flowId: string, stepId: string, items: Record<string, unknown>[], downstream: boolean) =>
    postJson<WhatIf>("/api/whatif", { flow_id: flowId, step_id: stepId, items, downstream }),
  replay: (flowId: string, runId: string) => postJson<WhatIf>("/api/whatif/replay", { flow_id: flowId, run_id: runId }),
  checkup: (flowId: string, runId?: string | null) =>
    fetch(`/api/checkup?flow_id=${encodeURIComponent(flowId)}${runId ? `&run_id=${encodeURIComponent(runId)}` : ""}`).then((r) =>
      json<Checkup>(r),
    ),
  answerQuestion: (flowId: string, question_id: string, answer: string) =>
    postJson<Harness>(`/api/harness/${encodeURIComponent(flowId)}/answer`, { question_id, answer }),
  dismissFinding: (flowId: string, finding_id: string, reason: string) =>
    postJson<Harness>(`/api/harness/${encodeURIComponent(flowId)}/dismiss`, { finding_id, reason }),
  restoreHarness: (flowId: string, id: string) => postJson<Harness>(`/api/harness/${encodeURIComponent(flowId)}/restore`, { id }),
  mcp: () => fetch("/api/mcp").then((r) => json<{ servers: McpServer[] }>(r)),
  mcpTools: (name: string) =>
    postJson<{ tools: { name: string; description: string; asks_first: boolean }[] }>(`/api/mcp/${encodeURIComponent(name)}/tools`),
  setMcp: (name: string, enabled: boolean) =>
    fetch(`/api/mcp/${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ enabled }),
    }).then((r) => json<{ servers: McpServer[] }>(r)),
  flows: () => fetch("/api/flows").then((r) => json<{ flows: FlowCard[] }>(r)),
  settings: () => fetch("/api/settings").then((r) => json<Settings>(r)),
  setShowDemo: (show_demo: boolean) =>
    fetch("/api/settings", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ show_demo }) }).then((r) =>
      json<Settings>(r),
    ),
  setChatEngine: (chat_engine: "claude" | "codex") =>
    fetch("/api/settings", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ chat_engine }) }).then(
      (r) => json<Settings>(r),
    ),
  setEnabled: (flowId: string, enabled: boolean) =>
    fetch(`/api/flows/${flowId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ enabled }),
    }).then((r) => json<{ enabled: boolean }>(r)),
  connections: () => fetch("/api/connections").then((r) => json<{ connections: Connection[] }>(r)),
  /** `refresh`: read connected automations' newest runs now, instead of a list read in the last minute. */
  activity: (flowId?: string, refresh = false) =>
    fetch(`/api/activity?${[flowId && q(flowId), refresh && "refresh=true"].filter(Boolean).join("&")}`).then((r) =>
      json<{ events: ActivityEvent[] }>(r),
    ),
  map: (flowId: string) => fetch(`/api/map?${q(flowId)}`).then((r) => json<FlowMap>(r)),
  inputs: (flowId: string) => fetch(`/api/inputs?${q(flowId)}`).then((r) => json<{ inputs: string[]; default: string | null }>(r)),
  runs: (flowId: string) => fetch(`/api/runs?${q(flowId)}`).then((r) => json<{ runs: RunSummary[] }>(r)),
  run: (flowId: string, id: string) => fetch(`/api/runs/${id}?${q(flowId)}`).then((r) => json<Run>(r)),
  startRun: (flowId: string, input_file: string | null) =>
    fetch(`/api/runs?${q(flowId)}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ input_file }),
    }).then((r) => json<{ run_id: string }>(r)),
  preview: (flowId: string, nodeId: string, runId: string) =>
    fetch(`/api/nodes/${nodeId}/preview?run_id=${encodeURIComponent(runId)}&${q(flowId)}`).then((r) => json<Preview>(r)),
  itemsCsvUrl: (flowId: string, runId: string, which: "input" | "output") =>
    `/api/runs/${encodeURIComponent(runId)}/items.csv?which=${which}&${q(flowId)}`,
  code: (flowId: string, nodeId: string) => fetch(`/api/nodes/${nodeId}/code?${q(flowId)}`).then((r) => json<{ code: string }>(r)),
  findContact: (flowId: string, runId: string, text: string) =>
    fetch(`/api/runs/${runId}/contacts?q=${encodeURIComponent(text)}&${q(flowId)}`).then((r) => json<{ matches: ContactMatch[] }>(r)),
};

export type Trigger = { type: string; label: string; app?: string };
export type Terms = { item: string; items: string };
export type FlowMeta = {
  id: string;
  name: string;
  description: string;
  trigger: Trigger;
  terms: Terms;
  next_run: string | null;
  output?: { label: string };
  input_terms?: Terms;
  read_only?: boolean;
  can_toggle?: boolean;
  toggle_off_hint?: string;
  toggle_on_hint?: string;
  state_label?: string;
  /** Set when a scheduled automation didn't run when it should have. */
  overdue?: string | null;
  kind: "live" | "sample" | "built" | "connected";
  source?: { label: string; repo?: string; workflow?: string; path?: string };
  enabled: boolean;
};
export type FlowCard = FlowMeta & {
  /** What to do about it, when the flow needs attention. */
  next_step?: string | null;
  apps: string[];
  step_count: number;
  problems: string[];
  last_run: RunSummary | null;
  recent: { run_id: string; status: Status; started_at: string }[];
  stats_7d: { runs: number; success_rate: number | null; items_in: number; items_out: number };
  kpis: Kpi[];
  freshness: Freshness;
};
/** One number on a flow's card, e.g. "417 events published (last finished run)". */
export type Kpi = { value: string; label: string; hint: string; delta: number | null; good: "up" | "down"; tone?: "good" | "bad" | null };
/** Where a flow's data came from and when it was read. Flowhaus reads on demand; it is not a live feed. */
export type Freshness = { source: string; checked_at: string | null; error: string | null };
export type ActivityEvent = {
  t: string;
  flow_id: string | null;
  flow_name: string;
  run_id?: string;
  node_id?: string | null;
  level: "info" | "warn" | "error" | "success" | "running" | "change" | "request";
  text: string;
};

export type ContactMatch = {
  row_id: number;
  name: string | null;
  email: string | null;
  outcome: "rejected" | "kept" | "unknown";
  step_id: string | null;
  reason: string | null;
};
