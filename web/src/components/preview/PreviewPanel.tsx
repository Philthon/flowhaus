import { AlertTriangle, ChevronDown, Code2, Download, MessageSquare, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, type ConnectorCall, type Preview, type Row } from "@/lib/api";
import { AppBadge } from "@/lib/apps";
import { STATUS_LABEL, STATUS_STYLE, plural } from "@/lib/status";
import { useTerms } from "@/lib/terms";
import { cn } from "@/lib/utils";
import { DiffText } from "./DiffText";
import { TryIt } from "./TryIt";
import { Evidence } from "@/components/chat/NextStepCard";

type Props = {
  /** The longer explanation for the "About" tab. */
  about?: { explain?: string | null; example?: string | null; file?: string | null; app?: string | null; after: string[] } | null;
  /** For a decision: the rule it applies and where each answer leads. */
  decision?: { rule?: string | null; paths: { label: string; to: string; when?: string | null }[] } | null;
  flowId: string;
  inputTerms?: { item: string; items: string };
  hasCode: boolean;
  nodeId: string;
  label: string;
  description: string;
  isGroup: boolean;
  runId: string | null;
  runStatus: string | null;
  refreshKey: string;
  onClose: () => void;
  onAsk: (text: string) => void;
  onGoToStep: (stepId: string) => void;
  focusRowId: number | null;
  /** Show the "Test" tab (steps that can be tried on edited items); `connected` ones are predicted by the chat. */
  tryable?: "run" | "predict" | null;
  /** Open a tab from outside (the quick view's "Test with different input", or the Test menu); `n` changes on every request. */
  openTab?: { tab: string; n: number } | null;
};

const HIDDEN = new Set(["_row_id", "_rejected_reason"]);

export function PreviewPanel(props: Props) {
  const { flowId, nodeId, runId, refreshKey } = props;
  // keyed by step and run: a preview of the step you just left is never shown (or handed to Test) for this one
  const key = `${nodeId}|${runId}`;
  const [loaded, setLoaded] = useState<{ key: string; preview: Preview | null; error: string | null } | null>(null);
  const preview = loaded?.key === key ? loaded.preview : null;
  const error = loaded?.key === key ? loaded.error : null;
  // the tab opened from outside: a flagged item to look at, or a tab asked for by name (which wins); adjusted while
  // rendering rather than in an effect, so the panel never paints the old tab first
  const asked = () => props.openTab?.tab ?? (props.focusRowId != null ? "flagged" : null);
  // null: chosen by the step (Details when it failed, otherwise before → after). Moving to another step goes back to
  // that, unless you picked a tab of your own (About, Test, App calls), which stays.
  const [tab, setTab] = useState<string | null>(() => asked());
  const [seen, setSeen] = useState({ focusRowId: props.focusRowId, nodeId, openTab: props.openTab });
  if (seen.focusRowId !== props.focusRowId || seen.nodeId !== nodeId || seen.openTab !== props.openTab) {
    setSeen({ focusRowId: props.focusRowId, nodeId, openTab: props.openTab });
    const next = props.openTab !== seen.openTab && props.openTab ? props.openTab.tab : props.focusRowId != null ? "flagged" : null;
    if (next) setTab(next);
    else if (seen.nodeId !== nodeId && (tab === "preview" || tab === "log" || tab === "flagged")) setTab(null);
  }

  useEffect(() => {
    if (!runId) return;
    let alive = true;
    api
      .preview(flowId, nodeId, runId)
      .then((p) => alive && setLoaded({ key, preview: p, error: null }))
      .catch((e) => alive && setLoaded({ key, preview: null, error: String(e.message ?? e) }));
    return () => {
      alive = false;
    };
  }, [flowId, nodeId, runId, refreshKey, key]);

  const status = preview?.status ?? "not_run";
  const flaggedCount = preview?.rows_rejected ?? 0;

  return (
    <section className="flex h-full min-h-0 flex-col border-t bg-background" aria-label="Step details">
      <header className="flex items-start justify-between gap-4 border-b px-4 py-2.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn("size-2.5 shrink-0 rounded-full", STATUS_STYLE[status].dot)} aria-label={STATUS_LABEL[status]} />
            <h2 className="truncate font-semibold">{props.label}</h2>
            {preview && preview.rows_in != null && preview.kind !== "input" && (
              <span className="text-xs tabular-nums text-muted-foreground">
                {preview.rows_in} in → {preview.rows_out ?? "–"} out
                {preview.rows_rejected > 0 && `, ${preview.rows_rejected} skipped`}
              </span>
            )}
          </div>
          <p className="truncate text-sm text-muted-foreground">{props.description}</p>
          {props.decision && (
            <div className="mt-1 space-y-0.5 text-xs">
              {props.decision.rule && (
                <p>
                  <span className="text-muted-foreground">Rule: </span>
                  {props.decision.rule}
                </p>
              )}
              {props.decision.paths.map((p) => (
                <p key={p.label + p.to}>
                  <b className="border border-foreground/20 px-1 font-medium">{p.label}</b> → {p.to}
                  {p.when && <span className="text-muted-foreground"> ({p.when})</span>}
                </p>
              ))}
            </div>
          )}
        </div>
        <Button variant="ghost" size="icon" onClick={props.onClose} aria-label="Close details">
          <X />
        </Button>
      </header>

      {!runId && props.tryable ? (
        <div className="min-h-0 flex-1 overflow-auto p-3">
          <p className="mb-3 text-sm text-muted-foreground">No run yet, so there's no data to show for this step. You can still try it on input you type in.</p>
          <TryIt key={nodeId} flowId={flowId} stepId={nodeId} label={props.label} start={[]} connected={props.tryable === "predict"} onAsk={props.onAsk} />
        </div>
      ) : !runId ? (
        <Empty>Run the flow to see data for this step.</Empty>
      ) : error ? (
        <Empty>{error}</Empty>
      ) : !preview ? (
        <Empty>Loading…</Empty>
      ) : preview.kind === "input" || preview.kind === "output" ? (
        <ItemsView preview={preview} flowId={flowId} onAsk={props.onAsk} inputTerms={props.inputTerms} />
      ) : (
        <Tabs value={activeTab(tab, preview)} onValueChange={(v) => setTab(String(v))} className="flex min-h-0 flex-1 flex-col gap-0">
          <TabsList variant="line" className="mx-3 mt-1 shrink-0">
            <TabsTrigger value="preview">{preview.paired === false ? "This run" : "Before → after"}</TabsTrigger>
            {flaggedCount > 0 && (
              <TabsTrigger value="flagged">
                Skipped <Badge variant="secondary" className="ml-1 bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100">{flaggedCount}</Badge>
              </TabsTrigger>
            )}
            {props.about && <TabsTrigger value="about">About</TabsTrigger>}
            {props.tryable && (preview.kind === "step" || preview.kind === "group") && <TabsTrigger value="try">Test</TabsTrigger>}
            {(preview.calls?.length ?? 0) > 0 && (
              <TabsTrigger value="calls">
                App calls <Badge variant="secondary" className="ml-1">{preview.calls_total ?? preview.calls!.length}</Badge>
              </TabsTrigger>
            )}
            <TabsTrigger value="log">
              Details {preview.error && <AlertTriangle className="size-3.5 text-red-600" />}
            </TabsTrigger>
          </TabsList>
          <div className="min-h-0 flex-1 overflow-auto">
            <TabsContent value="preview" className="p-3">
              <BeforeAfter preview={preview} isGroup={props.isGroup} />
            </TabsContent>
            <TabsContent value="flagged" className="p-3">
              <Flagged preview={preview} focusRowId={props.focusRowId} />
            </TabsContent>
            <TabsContent value="about" className="p-3">
              {props.about && <About about={props.about} description={props.description} decision={props.decision} />}
            </TabsContent>
            <TabsContent value="try" className="p-3">
              {props.tryable && (
                <TryIt
                  key={`${nodeId}-${runId}`}
                  flowId={flowId}
                  stepId={nodeId}
                  label={props.label}
                  start={preview.sample_in ?? []}
                  connected={props.tryable === "predict"}
                  onAsk={props.onAsk}
                />
              )}
            </TabsContent>
            <TabsContent value="calls" className="p-3">
              <Calls calls={preview.calls ?? []} total={preview.calls_total ?? 0} credits={preview.credits ?? 0} />
            </TabsContent>
            <TabsContent value="log" className="space-y-4 p-3">
              <ErrorBox preview={preview} isGroup={props.isGroup} onGoToStep={props.onGoToStep} onAsk={props.onAsk} />
              <Log preview={preview} />
              <ChatContext {...props} preview={preview} />
            </TabsContent>
          </div>
        </Tabs>
      )}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-1 items-center justify-center p-6 text-sm text-muted-foreground">{children}</div>;
}

function ErrorBox({
  preview,
  isGroup,
  onGoToStep,
  onAsk,
}: {
  preview: Preview;
  isGroup: boolean;
  onGoToStep: (id: string) => void;
  onAsk: (t: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (!preview.error) return null;
  return (
    <div className="mb-3 border tone-error p-3 text-sm">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        <div className="min-w-0 flex-1 space-y-2">
          <p className="font-medium">
            {isGroup && preview.failed_step ? "A step inside failed: " : "This step failed: "}
            {preview.error.message}
          </p>
          {preview.next_step && (
            <p>
              <b className="font-medium">Next step: </b>
              {preview.next_step}
            </p>
          )}
          <Evidence lines={preview.evidence} unseen={preview.unseen} />
          <div className="flex flex-wrap gap-2">
            {isGroup && preview.failed_step && (
              <Button size="sm" variant="outline" onClick={() => onGoToStep(preview.failed_step!)}>
                Show the failing step
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => onAsk(`This step failed: ${preview.error!.message}\nFind the cause from the log and the code, and tell me the shortest fix. Don't change anything yet.`)}>
              <MessageSquare /> Solve it with the chat
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen((o) => !o)}>
              Technical details <ChevronDown className={cn("transition-transform", open && "rotate-180")} />
            </Button>
          </div>
          {open && (
            <pre className="max-h-64 overflow-auto rounded bg-background/80 p-2 font-mono text-[11px] leading-snug text-foreground">
              {preview.error.traceback}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

function columnsOf(rows: Row[]): string[] {
  const cols: string[] = [];
  for (const r of rows) for (const k of Object.keys(r)) if (!HIDDEN.has(k) && !cols.includes(k)) cols.push(k);
  return cols;
}

function BeforeAfter({ preview, isGroup }: { preview: Preview; isGroup: boolean }) {
  const terms = useTerms();
  const sample_in = preview.sample_in ?? [];
  const sample_out = preview.sample_out ?? [];
  if (!sample_in.length && !sample_out.length) {
    return <p className="text-sm text-muted-foreground">No {terms.items} reached this {isGroup ? "part" : "step"} in this run.</p>;
  }
  const outById = new Map(sample_out.map((r) => [r._row_id, r]));
  const firstStep = !sample_in.length;
  const crashed = preview.status === "failed" && !sample_out.length;
  const rows = firstStep ? sample_out : sample_in;
  const allCols = columnsOf([...sample_in, ...sample_out]);
  // Put the columns this step actually changed right after the first (identifying) column.
  const touched = new Set(
    allCols.filter((c) => sample_in.some((r) => outById.has(r._row_id) && String(r[c] ?? "") !== String(outById.get(r._row_id)?.[c] ?? ""))),
  );
  const cols = [allCols[0], ...allCols.slice(1).filter((c) => touched.has(c)), ...allCols.slice(1).filter((c) => !touched.has(c))].filter(Boolean);
  return (
    <div className="space-y-2">
      <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
        {preview.paired === false ? (
          `What this step reported in this run${preview.note ? ` (${preview.note})` : ""}.`
        ) : firstStep ? (
          "The first rows this step produced."
        ) : crashed ? (
          <span>
            The first {plural(rows.length, "row")} this {isGroup ? "part" : "step"} received before it failed. Check which columns are there.
          </span>
        ) : (
          <>
            <span>A sample of {rows.length} {rows.length === 1 ? terms.item : terms.items}. Changed values show old above new:</span>
            <mark className="rounded-sm bg-red-200/80 px-1 line-through dark:bg-red-900/70">removed</mark>
            <mark className="rounded-sm bg-emerald-200/80 px-1 dark:bg-emerald-900/70">added</mark>
          </>
        )}
      </p>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-[13px]">
          <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
            <tr>
              <th className="w-10 px-2 py-1.5 font-medium">#</th>
              {cols.map((c) => (
                <th key={c} className={cn("border-l px-2 py-1.5 font-medium capitalize", touched.has(c) && "text-sky-700 dark:text-sky-300")}>
                  {c.replaceAll("_", " ")}
                  {touched.has(c) && " •"}
                </th>
              ))}
              {preview.paired !== false && <th className="border-l px-2 py-1.5 font-medium">Result</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const after = firstStep ? r : outById.get(r._row_id);
              const reason = !firstStep && after?._rejected_reason && !r._rejected_reason ? String(after._rejected_reason) : null;
              const changedCols = firstStep || !after ? [] : cols.filter((c) => String(r[c] ?? "") !== String(after[c] ?? ""));
              return (
                <tr key={String(r._row_id)} className={cn("border-t align-top", reason && "bg-amber-50/70 dark:bg-amber-950/30")}>
                  <td className="px-2 py-1.5 tabular-nums text-muted-foreground">{r._row_id}</td>
                  {cols.map((c) => {
                    const b = String(r[c] ?? "");
                    const a = String(after?.[c] ?? "");
                    const changed = changedCols.includes(c);
                    return (
                      <td key={c} className="border-l px-2 py-1.5 font-mono text-[12px] whitespace-nowrap">
                        {changed ? (
                          <div className="flex flex-col gap-0.5">
                            <span className="text-muted-foreground"><DiffText before={b} after={a} side="before" /></span>
                            <span><DiffText before={b} after={a} side="after" /></span>
                          </div>
                        ) : (
                          <DiffText before={b} after={b} side="before" />
                        )}
                      </td>
                    );
                  })}
                  {preview.paired !== false && <td className="border-l px-2 py-1.5 text-xs">
                    {reason ? (
                      <span className="font-medium text-amber-800 dark:text-amber-300">Skipped: {reason}</span>
                    ) : crashed ? (
                      <span className="text-red-700 dark:text-red-300">Not processed</span>
                    ) : !after ? (
                      <span className="text-muted-foreground">Left out</span>
                    ) : changedCols.length ? (
                      <span className="text-sky-700 dark:text-sky-300">Changed {changedCols.join(", ")}</span>
                    ) : (
                      <span className="text-muted-foreground">{firstStep ? "Loaded" : "Unchanged"}</span>
                    )}
                  </td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Flagged({ preview, focusRowId }: { preview: Preview; focusRowId: number | null }) {
  const [q, setQ] = useState("");
  const [reason, setReason] = useState<string | null>(null);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (preview.rejected_samples ?? []).filter(
      (r) =>
        (!reason || r.reason === reason) &&
        (!needle || JSON.stringify(r.before).toLowerCase().includes(needle) || String(r._row_id) === needle),
    );
  }, [preview, q, reason]);

  useEffect(() => {
    if (focusRowId == null) return;
    document.getElementById(`flag-${focusRowId}`)?.scrollIntoView({ block: "nearest" });
  }, [focusRowId, rows]);

  if (!preview.rejected_samples?.length) {
    const reasons = Object.entries(preview.reject_reasons ?? {});
    if (!reasons.length) return <p className="text-sm text-muted-foreground">Nothing was skipped here in this run.</p>;
    return <ReasonList reasons={reasons} total={preview.rows_rejected} />;
  }
  const cols = columnsOf(preview.rejected_samples.map((r) => r.before));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {Object.entries(preview.reject_reasons ?? {}).map(([r, n]) => (
          <button
            key={r}
            onClick={() => setReason(reason === r ? null : r)}
            className={cn(
              "border border-border px-2.5 py-0.5 text-xs transition-colors",
              reason === r ? "border-amber-500 bg-amber-100 text-amber-950 dark:bg-amber-900 dark:text-amber-50" : "hover:bg-muted",
            )}
          >
            <b className="tabular-nums">{n}</b> × {r}
          </button>
        ))}
        <label className="ml-auto flex items-center gap-1.5 rounded-md border px-2 py-1 text-sm focus-within:ring-2 focus-within:ring-ring">
          <Search className="size-3.5 text-muted-foreground" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter"
            className="w-48 bg-transparent outline-none"
          />
        </label>
      </div>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-[13px]">
          <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
            <tr>
              <th className="w-10 px-2 py-1.5 font-medium">#</th>
              {cols.map((c) => (
                <th key={c} className="border-l px-2 py-1.5 font-medium">{c}</th>
              ))}
              <th className="border-l px-2 py-1.5 font-medium">Why it was skipped</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r._row_id}
                id={`flag-${r._row_id}`}
                className={cn("border-t align-top", focusRowId === r._row_id && "bg-amber-100 dark:bg-amber-900/50")}
              >
                <td className="px-2 py-1.5 tabular-nums text-muted-foreground">{r._row_id}</td>
                {cols.map((c) => (
                  <td key={c} className="border-l px-2 py-1.5 font-mono text-[12px] whitespace-nowrap">
                    <DiffText before={String(r.before[c] ?? "")} after={String(r.before[c] ?? "")} side="before" />
                  </td>
                ))}
                <td className="border-l px-2 py-1.5 font-medium text-amber-800 dark:text-amber-300">{r.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <p className="p-3 text-sm text-muted-foreground">Nothing matches that filter.</p>}
      </div>
    </div>
  );
}

function Log({ preview }: { preview: Preview }) {
  if (!preview.log?.length) return <p className="text-sm text-muted-foreground">Nothing was logged for this run.</p>;
  return (
    <ol className="space-y-1 font-mono text-[12px]">
      {preview.log.map((l, i) => (
        <li
          key={i}
          className={cn(
            "flex gap-3 rounded px-2 py-1",
            l.level === "error" && "bg-red-50 text-red-900 dark:bg-red-950/40 dark:text-red-100",
            l.level === "warn" && "text-amber-800 dark:text-amber-300",
            l.level === "print" && "text-sky-800 dark:text-sky-300",
          )}
        >
          {l.t && <span className="shrink-0 text-muted-foreground">{l.t.slice(11)}</span>}
          <span>{l.text}</span>
        </li>
      ))}
    </ol>
  );
}

function ChatContext(props: Props & { preview: Preview }) {
  const [code, setCode] = useState<string | null>(null);
  if (props.isGroup || !props.hasCode) return null;
  return (
    <div className="text-sm">
      {(
        <div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => (code == null ? api.code(props.flowId, props.nodeId).then((c) => setCode(c.code)) : setCode(null))}
          >
            <Code2 /> {code == null ? "Show the code (for technical users)" : "Hide code"}
          </Button>
          {code != null && (
            <pre className="mt-2 max-h-72 overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-[12px] leading-snug">{code}</pre>
          )}
        </div>
      )}
    </div>
  );
}

function Calls({ calls, total, credits }: { calls: ConnectorCall[]; total: number; credits: number }) {
  const [open, setOpen] = useState<number | null>(0);
  const failed = calls.filter((c) => c.error).length;
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        What this step sent to outside apps and what came back.{" "}
        <b className="text-foreground">{total}</b> {total === 1 ? "call" : "calls"}, <b className="text-foreground">{credits}</b> credits
        {failed > 0 && <>, {failed} without a result</>}
        {total > calls.length && <> (showing the first {calls.length})</>}. Dummy apps: the answers are made up.
      </p>
      <ol className="divide-y rounded-md border text-[13px]">
        {calls.map((c, i) => (
          <li key={i}>
            <button
              onClick={() => setOpen(open === i ? null : i)}
              className="grid w-full grid-cols-[auto_9rem_1fr_auto] items-center gap-2 px-2 py-1.5 text-left hover:bg-muted/50"
              aria-expanded={open === i}
            >
              <AppBadge app={c.label} />
              <span className="font-mono text-xs">{c.action}</span>
              <span className="truncate font-mono text-xs text-muted-foreground">
                {Object.values(c.input ?? {}).map(String).join(", ")}
              </span>
              <span className={cn("text-xs tabular-nums", c.error ? "text-amber-700 dark:text-amber-400" : "text-muted-foreground")}>
                {c.error ? (c.error_kind === "item" ? "no result" : "failed") : `${c.ms} ms`}
              </span>
            </button>
            {open === i && (
              <div className="grid grid-cols-2 gap-2 bg-muted/30 px-2 py-2 text-[11px]">
                <div>
                  <div className="mb-0.5 font-medium text-muted-foreground">Sent</div>
                  <pre className="overflow-auto rounded border bg-background p-1.5 font-mono whitespace-pre-wrap">{JSON.stringify(c.input, null, 2)}</pre>
                </div>
                <div>
                  <div className="mb-0.5 font-medium text-muted-foreground">{c.error ? "Error" : "Got back"}</div>
                  <pre
                    className={cn(
                      "max-h-56 overflow-auto rounded border bg-background p-1.5 font-mono whitespace-pre-wrap",
                      c.error && "text-amber-800 dark:text-amber-300",
                    )}
                  >
                    {c.error ?? (typeof c.output === "string" ? c.output : JSON.stringify(c.output, null, 2))}
                  </pre>
                </div>
              </div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** The start and end boxes: every item that came in, or every item that came out. */
function ItemsView({ preview, flowId, onAsk, inputTerms }: { preview: Preview; flowId: string; onAsk: (t: string) => void; inputTerms?: { item: string; items: string } }) {
  const outputTerms = useTerms();
  const terms = preview.kind === "input" && inputTerms ? inputTerms : outputTerms;
  const [q, setQ] = useState("");
  const output = preview.kind === "output";
  const items = useMemo(() => preview.items ?? [], [preview.items]);
  const cols = columnsOf(items);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return needle ? items.filter((r) => JSON.stringify(r).toLowerCase().includes(needle)) : items;
  }, [items, q]);

  if (output && preview.items == null) {
    return (
      <div className="space-y-3 p-4 text-sm">
        <p className="text-muted-foreground">
          {preview.status === "running"
            ? "The run is still going; the result appears here when it finishes."
            : preview.status === "success"
              ? "This run is from before results were saved. Run the flow again to see what comes out."
              : "Nothing came out of this run because it failed before the end."}
        </p>
        {preview.error && (
          <Button size="sm" variant="outline" onClick={() => onAsk("Why did this run fail, and how can I fix it?")}>
            <MessageSquare /> Ask chat why
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">
          {output ? (
            <>
              <b className="text-foreground">{items.length}</b> of {preview.rows_in ?? "?"} {terms.items} made it through
              {preview.rows_rejected > 0 && <> · {preview.rows_rejected} skipped on the way</>}
            </>
          ) : (
            <>
              <b className="text-foreground">{items.length}</b> {items.length === 1 ? terms.item : terms.items} came in
            </>
          )}
        </span>
        <label className="ml-auto flex h-8 items-center gap-1.5 rounded-md border px-2 focus-within:ring-2 focus-within:ring-ring/50">
          <Search className="size-3.5 text-muted-foreground" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter" className="w-36 bg-transparent outline-none" />
        </label>
        <a
          href={api.itemsCsvUrl(flowId, preview.run_id, output ? "output" : "input")}
          className="flex h-8 items-center gap-1.5 rounded-md border px-2.5 hover:bg-muted"
          download
        >
          <Download className="size-3.5" /> Download CSV
        </a>
      </div>
      <div className="min-h-0 flex-1 overflow-auto rounded-md border">
        <table className="w-full text-[13px]">
          <thead className="sticky top-0 bg-muted text-left text-xs text-muted-foreground">
            <tr>
              <th className="w-10 px-2 py-1.5 font-medium">#</th>
              {cols.map((c) => (
                <th key={c} className="border-l px-2 py-1.5 font-medium capitalize">
                  {c.replaceAll("_", " ")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={String(r._row_id)} className="border-t align-top">
                <td className="px-2 py-1.5 tabular-nums text-muted-foreground">{r._row_id}</td>
                {cols.map((c) => (
                  <td key={c} className="border-l px-2 py-1.5 whitespace-nowrap">
                    <DiffText before={String(r[c] ?? "")} after={String(r[c] ?? "")} side="before" />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {shown.length === 0 && <p className="p-3 text-sm text-muted-foreground">Nothing matches that filter.</p>}
      </div>
    </div>
  );
}

/** The step explained: what it does, how it decides, an example, its code, and what a change here can reach. */
function About({ about, description, decision }: { about: NonNullable<Props["about"]>; description: string; decision?: Props["decision"] }) {
  const row = (label: string, value: React.ReactNode) => (
    <div className="grid grid-cols-[9rem_1fr] gap-3 border-b border-border py-2 last:border-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
  return (
    <dl className="max-w-3xl text-sm">
      {row("What it does", about.explain || description)}
      {about.explain && description && about.explain !== description && row("In short", description)}
      {decision?.rule && row("Rule", decision.rule)}
      {decision && decision.paths.length > 0 &&
        row(
          "Answers",
          decision.paths.map((p) => (
            <p key={p.label + p.to}>
              <b className="border border-foreground/20 px-1 font-medium">{p.label}</b> → {p.to}
              {p.when && <span className="text-muted-foreground"> ({p.when})</span>}
            </p>
          )),
        )}
      {about.example && row("Example", about.example)}
      {about.app && row("Outside app", about.app)}
      {about.file && row("Code", <code className="font-mono text-xs">{about.file}</code>)}
      {row(
        "A change here can reach",
        about.after.length ? about.after.join(", ") : <span className="text-muted-foreground">Nothing after it: this is where a path ends.</span>,
      )}
    </dl>
  );
}

/** Fall back to the first tab if the chosen one isn't shown for this box (e.g. nothing was skipped). */
function activeTab(tab: string | null, preview: Preview): string {
  if (tab === null) return preview.error ? "log" : "preview";
  if (tab === "flagged" && !preview.rows_rejected) return "preview";
  if (tab === "calls" && !(preview.calls?.length ?? 0)) return "preview";
  if (tab === "context") return "log";
  if ((tab === "about" || tab === "try") && preview.kind !== "step" && preview.kind !== "group") return "preview";
  return tab;
}

/** When only counts per reason are known (e.g. from a run log), show them ranked with a thin bar. */
function ReasonList({ reasons, total }: { reasons: [string, number][]; total: number }) {
  const terms = useTerms();
  const max = Math.max(...reasons.map(([, n]) => n));
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        {total} {total === 1 ? terms.item : terms.items} skipped, by reason. This run only reported counts, not the individual {terms.items}.
      </p>
      <ol className="divide-y divide-border border border-border bg-card text-sm">
        {reasons
          .sort((a, b) => b[1] - a[1])
          .map(([reason, n]) => (
            <li key={reason} className="grid grid-cols-[1fr_3.5rem_8rem] items-center gap-3 px-3 py-1.5">
              <span>{reason}</span>
              <span className="text-right tabular-nums text-amber-700 dark:text-amber-400">{n}</span>
              <span className="h-1.5 bg-muted" aria-hidden>
                <span className="block h-full bg-amber-400" style={{ width: `${(100 * n) / max}%` }} />
              </span>
            </li>
          ))}
      </ol>
    </div>
  );
}
