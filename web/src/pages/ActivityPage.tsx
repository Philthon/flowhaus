import { ChevronDown, Loader2, MessageSquarePlus, PencilLine } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { go } from "@/App";
import { PageTitle } from "@/components/PageTitle";
import { api, type ActivityEvent, type FlowCard } from "@/lib/api";
import { STATUS_STYLE } from "@/lib/status";
import { cn } from "@/lib/utils";

type Filter = "all" | "problems" | "changes";

/** One line in the log: either a whole run, or a change/request. */
type Entry =
  | { kind: "run"; t: string; flowId: string; flowName: string; runId: string; status: "success" | "failed" | "running"; summary: string; details: ActivityEvent[] }
  | { kind: "change"; t: string; flowId: string | null; flowName: string; text: string; request: boolean };

const FILTERS: { id: Filter; label: string; hint: string }[] = [
  { id: "all", label: "All", hint: "Every run and change" },
  { id: "problems", label: "Problems", hint: "Runs that failed" },
  { id: "changes", label: "Changes", hint: "Flows turned on or off, edits by Claude, apps connected" },
];

/** The API returns separate lines per run (started, skipped items, finished); merge them into one entry. */
function toEntries(events: ActivityEvent[]): Entry[] {
  const runs = new Map<string, Entry & { kind: "run" }>();
  const entries: Entry[] = [];
  for (const e of events) {
    if (e.run_id && e.flow_id) {
      let run = runs.get(e.run_id);
      if (!run) {
        run = { kind: "run", t: e.t, flowId: e.flow_id, flowName: e.flow_name, runId: e.run_id, status: "running", summary: "Running…", details: [] };
        runs.set(e.run_id, run);
        entries.push(run);
      }
      if (e.t > run.t) run.t = e.t;
      if (e.level === "success") {
        run.status = "success";
        run.summary = e.text.replace(/^Finished: /, "");
      } else if (e.level === "error") {
        run.status = "failed";
        run.summary = e.text;
      } else if (e.level === "warn") run.details.push(e);
    } else if (e.level === "change" || e.level === "request") {
      entries.push({ kind: "change", t: e.t, flowId: e.flow_id, flowName: e.flow_name, text: e.text, request: e.level === "request" });
    }
  }
  return entries.sort((a, b) => b.t.localeCompare(a.t));
}

function dayLabel(iso: string) {
  const d = new Date(iso);
  if (d.toDateString() === new Date().toDateString()) return "Today";
  if (d.toDateString() === new Date(Date.now() - 86400000).toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
}

export function ActivityPage({ flowId }: { flowId?: string }) {
  const [events, setEvents] = useState<ActivityEvent[] | null>(null);
  const [flows, setFlows] = useState<FlowCard[]>([]);
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    document.title = "Activity · Flowhaus";
    api.flows().then((r) => setFlows(r.flows)).catch(() => {});
  }, []);

  useEffect(() => {
    let alive = true;
    const load = () => api.activity(flowId).then((r) => alive && setEvents(r.events)).catch(() => {});
    load();
    const t = window.setInterval(load, 5000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [flowId]);

  const entries = useMemo(() => toEntries(events ?? []), [events]);
  const counts: Record<Filter, number> = {
    all: entries.length,
    problems: entries.filter((e) => e.kind === "run" && e.status === "failed").length,
    changes: entries.filter((e) => e.kind === "change").length,
  };
  const shown = entries.filter((e) =>
    filter === "problems" ? e.kind === "run" && e.status === "failed" : filter === "changes" ? e.kind === "change" : true,
  );
  const byDay = useMemo(() => {
    const days = new Map<string, Entry[]>();
    for (const e of shown) days.set(dayLabel(e.t), [...(days.get(dayLabel(e.t)) ?? []), e]);
    return [...days.entries()];
  }, [shown]);

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto max-w-4xl space-y-5 px-6 py-8">
        <PageTitle shape="circle">Activity</PageTitle>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap gap-1" role="group" aria-label="Show">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                onClick={() => setFilter(f.id)}
                aria-pressed={filter === f.id}
                title={f.hint}
                className={cn(
                  "flex items-center gap-1.5 border px-3 py-1 text-sm",
                  filter === f.id ? "border-foreground/60 bg-card text-foreground" : "border-border text-muted-foreground hover:text-foreground",
                  f.id === "problems" && counts.problems > 0 && filter !== f.id && "border-red-300 text-red-700 dark:text-red-400",
                )}
              >
                {f.label}
                <span className="tabular-nums opacity-70">{counts[f.id]}</span>
              </button>
            ))}
          </div>
          <select
            value={flowId ?? ""}
            onChange={(e) => go({ page: "activity", flowId: e.target.value || undefined })}
            className="ml-auto h-8 border border-border bg-card px-3 text-sm"
            aria-label="Filter by flow"
          >
            <option value="">All flows</option>
            {flows.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </div>

        {!events && (
          <p className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Loading…
          </p>
        )}
        {events && shown.length === 0 && <p className="text-center text-sm text-muted-foreground">Nothing here.</p>}

        {byDay.map(([day, items]) => (
          <section key={day} className="space-y-1.5">
            <h2 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{day}</h2>
            <ul className="divide-y divide-border border border-border bg-card">
              {items.map((e) => (
                <EntryRow key={e.kind === "run" ? e.runId : `${e.t}-${e.text}`} entry={e} showFlow={!flowId} />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}

function EntryRow({ entry, showFlow }: { entry: Entry; showFlow: boolean }) {
  const [open, setOpen] = useState(false);
  const time = new Date(entry.t).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

  if (entry.kind === "change") {
    const Icon = entry.request ? MessageSquarePlus : PencilLine;
    return (
      <li className="flex items-center gap-3 px-4 py-2.5 text-sm">
        <time className="w-16 shrink-0 text-xs whitespace-nowrap tabular-nums text-muted-foreground">{time}</time>
        <Icon className="size-4 shrink-0 text-violet-600" />
        <span className="min-w-0 flex-1 truncate">{entry.text}</span>
        {showFlow && entry.flowId && <span className="shrink-0 truncate text-xs text-muted-foreground">{entry.flowName}</span>}
      </li>
    );
  }

  const style = STATUS_STYLE[entry.status];
  const openRun = () => go({ page: "flow", flowId: entry.flowId, runId: entry.runId });
  return (
    <li>
      <div
        role="link"
        tabIndex={0}
        onClick={openRun}
        onKeyDown={(e) => e.key === "Enter" && openRun()}
        className="group flex cursor-pointer items-center gap-3 px-4 py-2.5 text-sm hover:bg-muted/40"
        title="Open this run"
      >
        <time className="w-16 shrink-0 text-xs whitespace-nowrap tabular-nums text-muted-foreground">{time}</time>
        <span className={cn("size-2.5 shrink-0 rounded-full", style.dot)} aria-label={entry.status} />
        <span className="min-w-0 flex-1 truncate">
          {showFlow && <b className="font-medium group-hover:underline">{entry.flowName}</b>}
          {showFlow && " · "}
          <span className={cn(entry.status === "failed" ? "text-red-800 dark:text-red-300" : "text-muted-foreground")}>{entry.summary}</span>
        </span>
        {entry.details.length > 0 && (
          <button
            onClick={(ev) => {
              ev.stopPropagation();
              setOpen((o) => !o);
            }}
            aria-expanded={open}
            aria-label={open ? "Hide details" : "Show why items were skipped"}
            title="Why items were skipped"
            className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
          </button>
        )}
      </div>
      {open && (
        <ul className="space-y-1 border-t bg-muted/20 px-4 py-2 pl-[6.25rem] text-xs text-muted-foreground">
          {entry.details.map((d, i) => (
            <li key={i}>{d.text}</li>
          ))}
        </ul>
      )}
    </li>
  );
}
