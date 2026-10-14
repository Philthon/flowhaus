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
};
export type Level = {
  children: string[];
  edges: { source: string; target: string }[];
  inbound: { from: string; target: string }[];
  outbound: { source: string; to: string }[];
};
export type FlowMap = {
  groups: Group[];
  steps: Step[];
  edges: { source: string; target: string }[];
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
  calls?: ConnectorCall[];
};
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
export type Insight = { level: "info" | "warn" | "error"; kind: string; title: string; detail: string; node_id?: string | null };

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
  openPullRequest: (id: string) => postJson<Change>(`/api/changes/${id}/pull-request`),
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
  insights: (flowId: string) =>
    fetch(`/api/insights?flow_id=${encodeURIComponent(flowId)}`).then((r) => json<{ insights: Insight[] }>(r)),
  harness: (flowId: string) => fetch(`/api/harness?flow_id=${encodeURIComponent(flowId)}`).then((r) => json<Harness>(r)),
  answerQuestion: (flowId: string, question_id: string, answer: string) =>
    postJson<Harness>(`/api/harness/${encodeURIComponent(flowId)}/answer`, { question_id, answer }),
  dismissFinding: (flowId: string, finding_id: string, reason: string) =>
    postJson<Harness>(`/api/harness/${encodeURIComponent(flowId)}/dismiss`, { finding_id, reason }),
  restoreHarness: (flowId: string, id: string) => postJson<Harness>(`/api/harness/${encodeURIComponent(flowId)}/restore`, { id }),
  mcp: () => fetch("/api/mcp").then((r) => json<{ servers: McpServer[] }>(r)),
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
  setEnabled: (flowId: string, enabled: boolean) =>
    fetch(`/api/flows/${flowId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ enabled }),
    }).then((r) => json<{ enabled: boolean }>(r)),
  requestFlow: (text: string) =>
    fetch("/api/flow-requests", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text }),
    }).then((r) => json<{ t: string }>(r)),
  connections: () => fetch("/api/connections").then((r) => json<{ connections: Connection[] }>(r)),
  activity: (flowId?: string) =>
    fetch(`/api/activity${flowId ? `?${q(flowId)}` : ""}`).then((r) => json<{ events: ActivityEvent[] }>(r)),
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
