import { AlertTriangle, ArrowRight, ChevronDown, CloudOff, LayoutGrid, List, Loader2, Plug, Plus, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { go } from "@/lib/route";
import { timeAgo } from "@/lib/time";
import { EnabledToggle } from "@/components/EnabledToggle";
import { OnboardingGuide } from "@/components/Onboarding";
import { PageTitle } from "@/components/PageTitle";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { api, type FlowCard, type Kpi, type Settings } from "@/lib/api";
import { AppBadge, TriggerIcon } from "@/lib/apps";
import { STATUS_LABEL, STATUS_STYLE } from "@/lib/status";
import { cn } from "@/lib/utils";


type Filter = "active" | "attention" | "manual" | "paused" | "all";

const isManual = (f: FlowCard) => f.trigger.type === "manual";
const attentionReason = (f: FlowCard): string | null =>
  f.last_run?.status === "failed"
    ? (f.last_run.error?.message ?? "The last run failed")
    : f.overdue
      ? f.overdue
      : f.problems.length
      ? `The map needs attention: ${f.problems[0]}`
      : null;

const FILTERS: { id: Filter; label: string; test: (f: FlowCard) => boolean; hint: string }[] = [
  { id: "active", label: "Active", test: (f) => f.enabled && !isManual(f), hint: "Flows that are on and start by themselves" },
  { id: "attention", label: "Needs attention", test: (f) => !!attentionReason(f), hint: "The last run failed or the flow has a problem" },
  { id: "manual", label: "Manual", test: (f) => isManual(f), hint: "Flows you start by hand" },
  { id: "paused", label: "Paused", test: (f) => !f.enabled, hint: "Flows that are turned off" },
  { id: "all", label: "All", test: () => true, hint: "Every flow" },
];

function loadFilter(): Filter {
  try {
    const v = localStorage.getItem("flows.filter");
    return FILTERS.some((f) => f.id === v) ? (v as Filter) : "active";
  } catch {
    return "active";
  }
}

type View = "list" | "cards";

function loadView(): View {
  try {
    return localStorage.getItem("flows.view") === "cards" ? "cards" : "list";
  } catch {
    return "list";
  }
}

export function FlowsPage() {
  const [view, setViewState] = useState<View>(loadView);
  const setView = (v: View) => {
    setViewState(v);
    try {
      localStorage.setItem("flows.view", v);
    } catch {
      /* per-viewer convenience only */
    }
  };
  const [flows, setFlows] = useState<FlowCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilterState] = useState<Filter>(loadFilter);
  const [query, setQuery] = useState("");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [connectOpen, setConnectOpen] = useState(false);
  const showDemo = settings ? settings.show_demo : null;
  const toggleDemo = async () => {
    setFlows(null); // show "Loading…" instead of the old list while the other set loads
    setSettings(await api.updateSettings({ show_demo: !showDemo }));
    load();
  };

  const setFilter = (f: Filter) => {
    setFilterState(f);
    try {
      localStorage.setItem("flows.filter", f);
    } catch {
      /* per-viewer convenience only */
    }
  };

  const load = useCallback(() => {
    api
      .flows()
      .then((r) => {
        setFlows(r.flows);
        setError(null);
      })
      .catch((e) => setError(`Could not load flows: ${e.message}. Is the API running? Start it with: uv run flowhaus dev`));
    api
      .settings()
      .then(setSettings)
      .catch(() => {});
  }, []);

  useEffect(() => {
    document.title = "Flows";
    load();
    // poll: automations an agent connects appear without a reload (faster while onboarding)
    const t = window.setInterval(load, settings?.automations === 0 ? 3000 : 10000);
    return () => window.clearInterval(t);
  }, [load, settings?.automations]);

  const counts = useMemo(
    () => Object.fromEntries(FILTERS.map((f) => [f.id, flows?.filter(f.test).length ?? 0])) as Record<Filter, number>,
    [flows],
  );
  const needAttention = useMemo(() => (flows ?? []).filter((f) => !!attentionReason(f)), [flows]);

  const shown = useMemo(() => {
    const test = FILTERS.find((f) => f.id === filter)!.test;
    const q = query.trim().toLowerCase();
    return (flows ?? [])
      .filter(test)
      .filter((f) => !q || `${f.name} ${f.description}`.toLowerCase().includes(q))
      .sort((a, b) => Number(!!attentionReason(b)) - Number(!!attentionReason(a)));
  }, [flows, filter, query]);

  const onboarding = settings != null && settings.automations === 0 && !settings.show_demo;
  const hidden = (flows?.length ?? 0) - (flows?.filter(FILTERS.find((f) => f.id === filter)!.test).length ?? 0);

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto max-w-4xl space-y-5 px-6 py-8">
        <header className="flex items-center justify-between gap-4">
          <PageTitle shape="square">Flows</PageTitle>
          {!onboarding && settings && (
            <div className="flex items-center gap-2">
              <Button variant="outline" onClick={() => setConnectOpen(true)} aria-label="Connect automation" title="Connect automation">
                <Plug /> <span className="hidden sm:inline">Connect automation</span>
              </Button>
              {showDemo && (
                <Button onClick={() => go({ page: "new" })}>
                  <Plus /> New flow
                </Button>
              )}
            </div>
          )}
        </header>

        <Dialog open={connectOpen} onOpenChange={setConnectOpen}>
          <DialogContent className="max-h-[90vh] overflow-auto p-6 sm:max-w-xl">
            <DialogTitle className="sr-only">Connect an automation</DialogTitle>
            <OnboardingGuide settings={settings} waiting={false} />
          </DialogContent>
        </Dialog>

        {onboarding ? (
          <section className="border border-border bg-card p-6 sm:p-8">
            <OnboardingGuide settings={settings} waiting onExploreDemo={toggleDemo} />
          </section>
        ) : (
          <>
            {counts.attention > 0 && filter !== "attention" && (
              // name them: some may be hidden by the current filter (a manual or paused flow), so a count alone confuses
              <div className="flex w-full items-start gap-2 border tone-error px-3 py-2 text-sm">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                <p className="min-w-0 flex-1">
                  <b className="font-medium">
                    {counts.attention} {counts.attention === 1 ? "flow needs" : "flows need"} attention:
                  </b>{" "}
                  {needAttention.slice(0, 4).map((f, i) => (
                    <span key={f.id}>
                      {i > 0 && ", "}
                      <a className="underline underline-offset-2" href={`#/flow/${f.id}`}>
                        {f.name}
                      </a>
                    </span>
                  ))}
                  {needAttention.length > 4 && ` and ${needAttention.length - 4} more`}
                </p>
                <button type="button" onClick={() => setFilter("attention")} className="shrink-0 text-xs underline">
                  Show them all
                </button>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <div className="flex flex-wrap gap-1" role="group" aria-label="Show flows">
                {FILTERS.map((f) => (
                  <button
                    key={f.id}
                    onClick={() => setFilter(f.id)}
                    aria-pressed={filter === f.id}
                    title={f.hint}
                    className={cn(
                      "flex items-center gap-1.5 border px-3 py-1 text-sm",
                      filter === f.id
                        ? "border-foreground/60 bg-card text-foreground"
                        : "border-border text-muted-foreground hover:text-foreground",
                      f.id === "attention" && counts.attention > 0 && filter !== f.id && "border-red-300 text-red-700 dark:text-red-400",
                    )}
                  >
                    {f.label}
                    <span className="tabular-nums opacity-70">{counts[f.id]}</span>
                  </button>
                ))}
              </div>
              <label className="ml-auto flex h-8 items-center gap-1.5 border border-border bg-card px-3 text-sm focus-within:ring-2 focus-within:ring-ring/50">
                <Search className="size-3.5 text-muted-foreground" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search"
                  className="w-36 bg-transparent outline-none"
                  aria-label="Search flows"
                />
              </label>
              <div className="flex border border-border bg-card" role="group" aria-label="View">
                {(
                  [
                    ["list", List, "List"],
                    ["cards", LayoutGrid, "Cards with key numbers"],
                  ] as const
                ).map(([v, Icon, label]) => (
                  <button
                    key={v}
                    onClick={() => setView(v)}
                    aria-pressed={view === v}
                    title={label}
                    aria-label={label}
                    className={cn(
                      "flex h-8 w-8 items-center justify-center",
                      view === v ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    <Icon className="size-4" />
                  </button>
                ))}
              </div>
            </div>

            {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-900 dark:bg-red-950 dark:text-red-100">{error}</p>}
            {!flows && !error && (
              <p className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> Loading flows…
              </p>
            )}

            {view === "cards" && shown.length > 0 && (
              <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {shown.map((f) => (
                  <FlowTile key={f.id} flow={f} />
                ))}
              </ul>
            )}
            <ul className={cn("divide-y divide-border border border-border bg-card", view === "cards" && shown.length > 0 && "hidden")}>
              {view === "list" && shown.map((f) => <FlowRow key={f.id} flow={f} onChanged={load} />)}
              {flows && shown.length === 0 && (
                <li className="p-6 text-center text-sm text-muted-foreground">
                  {query ? (
                    "No flow matches your search."
                  ) : counts.all === 0 ? (
                    <>
                      No automations connected yet.{" "}
                      <button className="underline underline-offset-2 hover:text-foreground" onClick={() => setConnectOpen(true)}>
                        Connect your first one
                      </button>
                    </>
                  ) : (
                    <>
                      Nothing here.{" "}
                      <button className="underline underline-offset-2 hover:text-foreground" onClick={() => setFilter("all")}>
                        Show all ({counts.all})
                      </button>
                    </>
                  )}
                </li>
              )}
            </ul>

            {flows && flows.length > 0 && <Freshness flows={flows} onRefresh={load} />}

            {showDemo != null && (
              <p className="text-center text-xs text-muted-foreground">
                {showDemo ? "Showing demo flows. " : "Only your real automations are shown. "}
                <button className="underline hover:text-foreground" onClick={toggleDemo}>
                  {showDemo ? "Hide them" : "Show demo flows"}
                </button>
              </p>
            )}

            {flows && filter === "active" && hidden > 0 && (
              <p className="text-center text-sm text-muted-foreground">
                {counts.manual > 0 && `${counts.manual} manual`}
                {counts.manual > 0 && counts.paused > 0 && " and "}
                {counts.paused > 0 && `${counts.paused} paused`} {hidden === 1 ? "flow is" : "flows are"} hidden.{" "}
                <button className="underline hover:text-foreground" onClick={() => setFilter("all")}>
                  Show all
                </button>
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function FlowRow({ flow, onChanged }: { flow: FlowCard; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const attention = attentionReason(flow);
  const open_ = () => go({ page: "flow", flowId: flow.id });
  return (
    <li>
      <div
        role="link"
        tabIndex={0}
        onClick={open_}
        onKeyDown={(e) => e.key === "Enter" && open_()}
        className="group flex cursor-pointer items-center gap-4 px-4 py-3.5 hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none"
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className={cn("truncate font-medium group-hover:underline", !flow.enabled && "text-muted-foreground")}>{flow.name}</h2>
            {attention && (
              <span className="flex shrink-0 items-center gap-1 text-[11px] font-medium text-red-600" title={attention}>
                <AlertTriangle className="size-3" /> Needs attention
              </span>
            )}
          </div>
          <p className="truncate text-sm text-muted-foreground">{flow.description}</p>
        </div>
        <span className="hidden sm:block">
          <RunStrip flow={flow} />
        </span>
        <button
          onClick={(e) => {
            e.stopPropagation();
            setOpen((o) => !o);
          }}
          aria-expanded={open}
          aria-label={open ? "Hide details" : "Show details"}
          title={open ? "Hide details" : "Details"}
          className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
        </button>
      </div>
      {open && <FlowDetails flow={flow} attention={attention} onChanged={onChanged} />}
    </li>
  );
}

/** The drill-down: everything that isn't needed at a glance. */
function FlowDetails({ flow, attention, onChanged }: { flow: FlowCard; attention: string | null; onChanged: () => void }) {
  const last = flow.last_run;
  const s = flow.stats_7d;
  return (
    <div className="space-y-3 border-t bg-muted/20 px-4 py-3 text-sm">
      {attention && (
        <div className="space-y-0.5">
          <p className="text-red-800 dark:text-red-300">{attention}</p>
          {flow.next_step && (
            <p>
              <b className="font-medium">Next step: </b>
              {flow.next_step} <a className="underline underline-offset-2" href={`#/flow/${flow.id}`}>Open the flow</a>
            </p>
          )}
        </div>
      )}
      <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-1.5">
        <dt className="text-muted-foreground">Starts when</dt>
        <dd className="flex items-center gap-1.5">
          <TriggerIcon type={flow.trigger.type} className="size-3.5" /> {flow.trigger.label}
        </dd>
        <dt className="text-muted-foreground">Uses</dt>
        <dd className="flex flex-wrap gap-1">
          {flow.apps.map((a) => (
            <AppBadge key={a} app={a} />
          ))}
        </dd>
        <dt className="text-muted-foreground">Last run</dt>
        <dd className={cn(last && STATUS_STYLE[last.status].text)}>
          {last ? `${STATUS_LABEL[last.status]} ${timeAgo(last.started_at)}` : "No runs yet"}
        </dd>
        <dt className="text-muted-foreground">Last 7 days</dt>
        <dd>
          {s.runs} {s.runs === 1 ? "run" : "runs"}
          {s.success_rate != null && `, ${s.success_rate}% succeeded`} · {s.items_in} {flow.terms.items} in, {s.items_out} out
        </dd>
        <dt className="text-muted-foreground">Status</dt>
        <dd className="flex items-center gap-2">
          {flow.read_only && flow.can_toggle ? (
            <>
              <EnabledToggle
                flowId={flow.id}
                enabled={flow.enabled}
                onChange={onChanged}
                size="sm"
                confirm={{ where: flow.source?.label ?? "the place it runs", offHint: flow.toggle_off_hint, onHint: flow.toggle_on_hint }}
              />
              <span className="text-muted-foreground">{flow.state_label}</span>
            </>
          ) : flow.read_only ? (
            <span className="flex items-center gap-1.5" title="Read-only: switch it on or off where it runs">
              <span className={cn("size-2 rounded-full", flow.enabled ? "bg-emerald-500" : "bg-muted-foreground/40")} />
              {flow.state_label}
            </span>
          ) : (
            <>
              <EnabledToggle flowId={flow.id} enabled={flow.enabled} onChange={onChanged} size="sm" />
              <span className="text-muted-foreground">{flow.enabled ? "On" : "Paused"}</span>
            </>
          )}
        </dd>
        <dt className="text-muted-foreground">Next run</dt>
        <dd>{flow.enabled ? flow.next_run : "None while it's off"}</dd>
      </dl>
      <Button size="sm" variant="outline" onClick={() => go({ page: "flow", flowId: flow.id })}>
        Open flow <ArrowRight />
      </Button>
    </div>
  );
}

/** Last runs as green/red pills, oldest left. Click one to open that run. */
const fmtTime = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/** Says where the numbers came from and how old they are. Flowhaus reads on demand; it doesn't watch in the background. */
function Freshness({ flows, onRefresh }: { flows: FlowCard[]; onRefresh: () => void }) {
  const sources = [...new Set(flows.map((f) => f.freshness?.source).filter(Boolean))];
  const times = flows
    .map((f) => f.freshness?.checked_at)
    .filter((t): t is string => !!t)
    .sort();
  const failed = flows.filter((f) => f.freshness?.error);
  return (
    <p className="flex flex-wrap items-center justify-center gap-x-1.5 gap-y-1 text-center text-xs text-muted-foreground">
      <span>
        Read from {sources.join(" and ") || "your automations"}
        {times.length > 0 && <> {timeAgo(times[0])}</>}.
      </span>
      {failed.length > 0 && (
        <span className="text-red-700 dark:text-red-400">
          {failed.length === 1 ? `Couldn't read “${failed[0].name}” just now` : `Couldn't read ${failed.length} automations just now`};
          showing what was read before.
        </span>
      )}
      <span>Flowhaus reads when it's open; it doesn't watch in the background.</span>
      <button onClick={onRefresh} className="inline-flex items-center gap-1 underline underline-offset-2 hover:text-foreground">
        <RefreshCw className="size-3" /> Refresh
      </button>
    </p>
  );
}

function KpiValue({ kpi }: { kpi: Kpi }) {
  const better = kpi.delta != null && kpi.delta !== 0 && kpi.delta > 0 === (kpi.good === "up");
  return (
    <div className="min-w-0" title={kpi.hint}>
      <div className={cn("text-2xl font-medium tabular-nums tracking-tight", kpi.tone === "bad" && "text-red-700 dark:text-red-400")}>{kpi.value}</div>
      <div className="truncate text-xs text-muted-foreground">
        {kpi.label}
        {kpi.delta != null && kpi.delta !== 0 && (
          <span className={cn("ml-1 tabular-nums", better ? "text-emerald-700 dark:text-emerald-400" : "text-red-700 dark:text-red-400")}>
            {kpi.delta > 0 ? "▲" : "▼"} {Math.abs(kpi.delta).toLocaleString()}
          </span>
        )}
      </div>
    </div>
  );
}

/** Card view: one tile per flow with its two key numbers. */
function FlowTile({ flow }: { flow: FlowCard }) {
  const attention = attentionReason(flow);
  const last = flow.last_run;
  const open = () => go({ page: "flow", flowId: flow.id });
  return (
    <li
      role="link"
      tabIndex={0}
      onClick={open}
      onKeyDown={(e) => e.key === "Enter" && open()}
      className={cn(
        "group flex cursor-pointer flex-col gap-4 border border-border bg-card p-4 hover:border-foreground/30 focus-visible:outline-2 focus-visible:outline-ring",
        STATUS_STYLE[last?.status ?? "not_run"].header,
      )}
    >
      <div className="min-w-0 space-y-0.5">
        <h2 className={cn("truncate font-medium group-hover:underline", !flow.enabled && "text-muted-foreground")}>{flow.name}</h2>
        <p className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
          {attention ? (
            <span className="flex items-center gap-1 font-medium text-red-600" title={attention}>
              <AlertTriangle className="size-3" /> Needs attention
            </span>
          ) : last ? (
            <span className={STATUS_STYLE[last.status].text}>{STATUS_LABEL[last.status]}</span>
          ) : (
            <span>No runs yet</span>
          )}
          {last && <span>· {timeAgo(last.started_at)}</span>}
          {!flow.enabled && <span>· off</span>}
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {(flow.kpis ?? []).map((k, i) => (
          <KpiValue key={i} kpi={k} />
        ))}
      </div>
      <div className="mt-auto flex items-center justify-between gap-2">
        <RunStrip flow={flow} />
        {flow.freshness?.error && (
          <span className="flex items-center gap-1 text-[11px] text-red-700 dark:text-red-400" title={flow.freshness.error}>
            <CloudOff className="size-3" />
            {flow.freshness.checked_at ? `as of ${fmtTime(flow.freshness.checked_at)}` : "couldn't read"}
          </span>
        )}
      </div>
    </li>
  );
}

function RunStrip({ flow }: { flow: FlowCard }) {
  const recent = [...flow.recent].reverse();
  if (!recent.length) return <span className="text-xs text-muted-foreground">No runs yet</span>;
  return (
    <div className="flex shrink-0 gap-0.5" aria-label="Recent runs, oldest first">
      {recent.map((r) => (
        <a
          key={r.run_id}
          href={`#/flow/${flow.id}?run=${encodeURIComponent(r.run_id)}`}
          onClick={(e) => e.stopPropagation()}
          title={`${STATUS_LABEL[r.status]} · ${new Date(r.started_at).toLocaleString()}`}
          aria-label={`${STATUS_LABEL[r.status]} run, ${new Date(r.started_at).toLocaleString()}`}
          className={cn(
            "h-5 w-2 hover:outline-2 hover:outline-offset-1 hover:outline-sky-500",
            STATUS_STYLE[r.status].dot.replace("animate-pulse", ""),
          )}
        />
      ))}
    </div>
  );
}
