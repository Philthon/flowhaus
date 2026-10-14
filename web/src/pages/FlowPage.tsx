import { AlertTriangle, ArrowLeft, ChevronDown, ChevronRight, ExternalLink, FlaskConical, Loader2, MessageSquare, Play, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ChatPanel, type ChatHandle } from "@/components/chat/ChatPanel";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { FlowCanvas, nodeInfo } from "@/components/flow/FlowCanvas";
import { PreviewPanel } from "@/components/preview/PreviewPanel";
import { Button } from "@/components/ui/button";
import { api, type ContactMatch, type FlowMap, type Run, type RunSummary } from "@/lib/api";
import { Insights } from "@/components/flow/Insights";
import { TestLab } from "@/components/test/TestLab";
import { LevelMiniMap } from "@/components/flow/LevelMiniMap";
import { TermsContext, useTerms } from "@/lib/terms";
import { EnabledToggle } from "@/components/EnabledToggle";
import { timeAgo } from "@/pages/FlowsPage";
import { STATUS_LABEL, STATUS_STYLE } from "@/lib/status";
import { cn } from "@/lib/utils";

const ROOT = "root";

function ancestorsOf(map: FlowMap, id: string): string[] {
  const parent = new Map<string, string | null>();
  for (const g of map.groups) parent.set(g.id, g.parent);
  for (const s of map.steps) parent.set(s.id, s.group);
  const chain: string[] = [];
  let cur = parent.get(id) ?? null;
  while (cur && !chain.includes(cur) && parent.has(cur)) {
    chain.unshift(cur);
    cur = parent.get(cur) ?? null;
  }
  return chain;
}

export function formatRunTime(r: { started_at: string }) {
  const d = new Date(r.started_at);
  const today = new Date().toDateString() === d.toDateString();
  return d.toLocaleString(undefined, today ? { hour: "2-digit", minute: "2-digit", second: "2-digit" } : { dateStyle: "short", timeStyle: "short" });
}

type Props = { flowId: string | null; initialRunId?: string | null; onBack: () => void };

/** One flow: chat on the left, map + details on the right. flowId null = the "new flow" builder. */
export function FlowPage({ flowId: initialFlowId, initialRunId, onBack }: Props) {
  const [flowId, setFlowId] = useState<string | null>(initialFlowId);
  const [map, setMap] = useState<FlowMap | null>(null);
  const [mapVersion, setMapVersion] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runId, setRunId] = useState<string | null>(initialRunId ?? null);
  const [run, setRun] = useState<Run | null>(null);
  const [inputs, setInputs] = useState<string[]>([]);
  const [inputFile, setInputFile] = useState<string | null>(null);
  const [levelPath, setLevelPath] = useState<string[]>([]);
  const [direction, setDirection] = useState<"in" | "out">("in");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [focusRowId, setFocusRowId] = useState<number | null>(null);
  const [agentBusy, setAgentBusy] = useState(false);
  const [miniMapHeight, setMiniMapHeight] = useState(0);
  const chatRef = useRef<ChatHandle>(null);
  const narrow = useNarrow();
  const [chatOpen, setChatOpenState] = useState(() => {
    if (window.matchMedia?.(NARROW).matches) return false; // small screens: the map first, the chat on demand
    try {
      return localStorage.getItem("flow.chatOpen") !== "false";
    } catch {
      return true;
    }
  });
  const setChatOpen = (v: boolean) => {
    setChatOpenState(v);
    if (narrow) return; // an overlay on small screens: don't change the wide-screen preference
    try {
      localStorage.setItem("flow.chatOpen", String(v));
    } catch {
      /* per-viewer convenience only */
    }
  };
  const ask = (t: string) => {
    setChatOpen(true);
    chatRef.current?.ask(t);
  };

  const levelId = levelPath.at(-1) ?? ROOT;

  useEffect(() => {
    if (map) document.title = `${map.title} · Flowhaus`;
  }, [map]);

  const refreshMap = useCallback(() => {
    if (!flowId) return;
    api
      .map(flowId)
      .then((m) => {
        setMap(m);
        setMapVersion((v) => v + 1);
        setLoadError(null);
      })
      .catch((e) => setLoadError(`Could not load the map: ${e.message}. Is the server running on port 8000?`));
  }, [flowId]);

  const refreshRuns = useCallback(async () => {
    if (!flowId) return [];
    const { runs } = await api.runs(flowId);
    setRuns(runs);
    return runs;
  }, [flowId]);

  useEffect(() => {
    if (!flowId) {
      document.title = "New flow · Flowhaus";
      return;
    }
    refreshMap();
    refreshRuns().then((rs) => setRunId((cur) => cur ?? latestReal(rs)?.run_id ?? null)).catch(() => {});
    api.inputs(flowId).then((i) => {
      setInputs(i.inputs);
      setInputFile(i.default);
    }).catch(() => {});
  }, [refreshMap, refreshRuns, flowId]);

  // Follow new runs (e.g. started elsewhere) if you were looking at the latest one.
  const latestRef = useRef<string | null>(null);
  useEffect(() => {
    latestRef.current = latestReal(runs)?.run_id ?? null;
  }, [runs]);
  useEffect(() => {
    if (!flowId) return;
    const t = window.setInterval(async () => {
      const before = latestRef.current;
      const rs = await refreshRuns().catch(() => null);
      const newest = rs ? latestReal(rs)?.run_id : undefined;
      if (newest && newest !== before) setRunId((cur) => (cur === before || cur == null ? newest : cur));
    }, 5000);
    return () => window.clearInterval(t);
  }, [flowId, refreshRuns]);

  // While Claude works, refresh the map so the flow can be watched as it is built.
  useEffect(() => {
    if (!agentBusy || !flowId) return;
    const t = window.setInterval(refreshMap, 2500);
    return () => window.clearInterval(t);
  }, [agentBusy, flowId, refreshMap]);

  // Load the selected run; poll while it is running.
  useEffect(() => {
    if (!runId || !flowId) return;
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const r = await api.run(flowId, runId);
        if (!alive) return;
        setRun(r);
        if (r.status === "running") timer = window.setTimeout(tick, 400);
        else refreshRuns().catch(() => {});
      } catch {
        if (alive) timer = window.setTimeout(tick, 1000);
      }
    };
    tick();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [runId, refreshRuns, flowId]);

  // If the level we are on disappeared after a map change, walk back up.
  useEffect(() => {
    if (!map) return;
    const valid = levelPath.filter((id) => map.levels[id]);
    if (valid.length !== levelPath.length) setLevelPath(valid);
    if (selectedId && !selectedId.startsWith("__") && !map.groups.some((g) => g.id === selectedId) && !map.steps.some((s) => s.id === selectedId))
      setSelectedId(null);
  }, [map, levelPath, selectedId]);

  const startRun = async () => {
    if (!flowId) return;
    const { run_id } = await api.startRun(flowId, inputFile);
    setRunId(run_id);
    refreshRuns();
  };

  const open = useCallback(
    (groupId: string) => {
      if (!map) return;
      setDirection("in");
      setLevelPath([...ancestorsOf(map, groupId), groupId]);
      setSelectedId(null);
    },
    [map],
  );

  const goUpTo = (index: number) => {
    setDirection("out");
    const leaving = levelPath[index + 1] ?? null;
    setLevelPath(levelPath.slice(0, index + 1));
    setSelectedId(leaving);
  };

  /** Navigate so that nodeId is visible on the canvas and select it. */
  const reveal = useCallback(
    (nodeId: string) => {
      if (!map) return;
      const path = ancestorsOf(map, nodeId);
      setDirection(path.length >= levelPath.length ? "in" : "out");
      setLevelPath(path);
      setSelectedId(nodeId);
    },
    [map, levelPath.length],
  );

  const goToBoundary = useCallback(
    (nodeId: string) => {
      if (!map) return;
      if (map.levels[nodeId]?.children.length) open(nodeId);
      else reveal(nodeId);
    },
    [map, open, reveal],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || (e.target as HTMLElement)?.closest("textarea,input")) return;
      if (selectedId) setSelectedId(null);
      else if (levelPath.length) goUpTo(levelPath.length - 2);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const selected = map && selectedId ? nodeInfo(map, run, selectedId) : null;
  const failedStepId = run?.status === "failed" ? run.error?.node_id ?? null : null;

  const onChatRun = useCallback(
    (id: string, runFlowId?: string) => {
      if (runFlowId && runFlowId !== flowId) return; // the agent ran another flow
      setRunId(id);
      refreshRuns();
    },
    [refreshRuns, flowId],
  );

  /** The agent created a flow from the builder: switch to it without losing the conversation. */
  const onFlowCreated = useCallback((id: string) => {
    setFlowId(id);
    setMap(null);
    setRun(null);
    setRunId(null);
    setRuns([]);
    setLevelPath([]);
    setSelectedId(null);
    window.history.replaceState(null, "", `#/flow/${id}`);
  }, []);

  const chat = (
    <ChatPanel
      onBusyChange={setAgentBusy}
      ref={chatRef}
      flowId={flowId}
      isSample={map?.flow.kind === "sample"}
      isConnected={map?.flow.kind === "connected"}
      selected={selected && selectedId ? { id: selectedId, label: selected.label } : null}
      runId={runId}
      onClearSelection={() => setSelectedId(null)}
      onRun={onChatRun}
      onMapChanged={refreshMap}
      onFlowCreated={onFlowCreated}
      onCollapse={flowId ? () => setChatOpen(false) : undefined}
    />
  );

  let placeholder: React.ReactNode = null;
  if (!flowId) placeholder = <BuilderWelcome onBack={onBack} onAsk={ask} />;
  else if (loadError && !map) placeholder = <div className="flex h-full items-center justify-center p-8 text-center text-muted-foreground">{loadError}</div>;
  else if (!map)
    placeholder = (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 animate-spin" /> Loading the map…
      </div>
    );

  // One stable tree: the chat must never remount (e.g. when the builder turns into the new flow).
  return (
    <TermsContext.Provider value={map?.flow.terms ?? DEFAULT_TERMS}>
      <div
        className={cn(
          "relative grid h-full bg-background text-foreground",
          (chatOpen && !narrow) || !flowId ? "grid-cols-[clamp(280px,24vw,360px)_1fr]" : "grid-cols-[2.75rem_1fr]",
        )}
      >
        {/* The chat stays mounted when folded, so the conversation is kept. On small screens it opens over the map. */}
        <div
          className={cn(
            "min-h-0",
            !chatOpen && flowId && "hidden",
            chatOpen && narrow && flowId && "absolute inset-y-0 left-0 z-30 w-[min(100%,420px)] border-r bg-background",
          )}
        >
          {chat}
        </div>
        {!chatOpen && flowId && (
          <button
            onClick={() => setChatOpen(true)}
            className="flex flex-col items-center gap-2 border-r pt-3 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
            title="Open the chat"
            aria-label="Open the chat"
          >
            <MessageSquare className="size-4" />
            <span className="[writing-mode:vertical-rl]">Chat</span>
          </button>
        )}
        {placeholder || !map || !flowId ? (
          <main className="min-h-0 min-w-0">{placeholder}</main>
        ) : (
        <main className="flex min-h-0 min-w-0 flex-col">
          <TopBar
            map={map}
            flowId={flowId}
            onBack={onBack}
            onToggled={refreshMap}
            runs={runs}
            runId={runId}
            run={run}
            onPickRun={setRunId}
            inputs={inputs}
            inputFile={inputFile}
            onPickInput={setInputFile}
            onRun={startRun}
            testing={testing}
            onToggleTest={() => setTesting((t) => !t)}
            onFound={(m) => {
              if (m.step_id) {
                reveal(m.step_id);
                setFocusRowId(m.row_id);
              }
            }}
          />

          {run?.status === "failed" && run.error && (
            <FailureBanner map={map} run={run} failedStepId={failedStepId} onShow={() => failedStepId && reveal(failedStepId)} />
          )}
          {agentBusy && (
            <div className="flex items-center gap-2 border-b border-sky-100 bg-sky-50 px-4 py-2 text-sm text-sky-800">
              <Loader2 className="size-4 animate-spin" /> Claude is working on this flow. The map updates as it goes.
            </div>
          )}
          {!agentBusy && map.problems.length > 0 && (
            <div className="flex items-start gap-2 border-b bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <div>
                <b>The map is out of date with the code:</b> {map.problems.join(" · ")}
              </div>
            </div>
          )}

          {testing ? (
            <TestLab
              flowId={flowId}
              onOpenRun={(id) => {
                setTesting(false);
                refreshRuns().then(() => setRunId(id));
              }}
            />
          ) : (
          <>
          {flowId && <Insights flowId={flowId} refreshKey={`${runs.length}-${runs[0]?.run_id}-${runs[0]?.status}`} onShowStep={reveal} onAsk={ask} />}

          <div className={cn("relative min-h-0", selectedId ? "flex-[1_1_50%]" : "flex-1")}>
            <ErrorBoundary resetKey={`${levelId}-${runId}-${mapVersion}`}>
            <FlowCanvas
              map={map}
              run={run}
              levelId={levelId}
              direction={direction}
              selectedId={selectedId}
              onSelect={(id) => {
                setSelectedId(id);
                setFocusRowId(null);
              }}
              onOpen={open}
              onGoTo={goToBoundary}
              topInset={levelPath.length > 0 ? miniMapHeight + 12 : 0}
            />
            </ErrorBoundary>
            {levelPath.length > 0 && <Breadcrumb map={map} levelPath={levelPath} onCrumb={goUpTo} />}
            {levelPath.length > 0 && (
            <LevelMiniMap
              map={map}
              run={run}
              levelPath={levelPath}
              selectedId={selectedId}
              onOpen={open}
              onReveal={reveal}
              onRoot={() => goUpTo(-1)}
              onHeight={setMiniMapHeight}
            />
            )}
            <Legend />
          </div>

          {selectedId && selected && (
            <div className="min-h-0 flex-[1_1_50%]">
              <ErrorBoundary resetKey={`${selectedId}-${runId}-${run?.status}`}>
              <PreviewPanel
                nodeId={selectedId}
                label={selected.label}
                description={selected.description}
                isGroup={selected.isGroup}
                flowId={flowId}
                hasCode={map.flow.kind !== "sample" && map.flow.kind !== "connected"}
                inputTerms={map.flow.input_terms}
                runId={runId}
                runStatus={run?.status ?? null}
                refreshKey={`${run?.status}-${run?.finished_at}-${mapVersion}-${Object.values(run?.nodes ?? {}).filter((n) => n.status === "success" || n.status === "failed").length}`}
                onClose={() => setSelectedId(null)}
                onAsk={ask}
                onGoToStep={reveal}
                focusRowId={focusRowId}
              />
              </ErrorBoundary>
            </div>
          )}
          </>
          )}
        </main>
        )}
      </div>
    </TermsContext.Provider>
  );
}

const DEFAULT_TERMS = { item: "item", items: "items" };

const NARROW = "(max-width: 900px)";

/** True on small screens and narrow windows, where the chat and the map can't sit side by side. */
function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => !!window.matchMedia?.(NARROW).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(NARROW);
    if (!mq) return;
    const on = () => setNarrow(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return narrow;
}

/** The newest run that isn't a test run: what the map shows by default. Test runs are opened from the test lab. */
const latestReal = (rs: RunSummary[]) => rs.find((r) => r.trigger !== "test") ?? rs[0];

function FailureBanner({ map, run, failedStepId, onShow }: { map: FlowMap; run: Run; failedStepId: string | null; onShow: () => void }) {
  const path = failedStepId ? [...ancestorsOf(map, failedStepId), failedStepId].map((id) => nodeInfo(map, run, id).label) : [];
  return (
    <div className="flex items-center gap-3 border-b border-red-100 bg-red-50 px-4 py-2 text-sm text-red-800">
      <AlertTriangle className="size-4 shrink-0" />
      <p className="line-clamp-2 min-w-0 flex-1" title={run.error?.message}>
        <b>This run failed{path.length ? ` in ${path.join(" › ")}` : ""}.</b> {run.error?.message}
      </p>
      {failedStepId && (
        <Button size="sm" variant="outline" className="shrink-0 border-red-200 bg-card text-red-800 hover:bg-red-100" onClick={onShow}>
          Show me
        </Button>
      )}
    </div>
  );
}

type TopBarProps = {
  testing: boolean;
  onToggleTest: () => void;
  map: FlowMap;
  flowId: string;
  onBack: () => void;
  onToggled: () => void;
  runs: RunSummary[];
  runId: string | null;
  run: Run | null;
  onPickRun: (id: string) => void;
  inputs: string[];
  inputFile: string | null;
  onPickInput: (f: string) => void;
  onRun: () => void;
  onFound: (m: ContactMatch) => void;
};

function TopBar(p: TopBarProps) {
  const running = p.run?.status === "running";
  const latest = latestReal(p.runs)?.run_id;
  return (
    <div className="@container flex items-center gap-2 border-b px-3 py-2">
      <Button variant="ghost" size="icon" onClick={p.onBack} title="All flows" aria-label="Back to all flows" className="shrink-0">
        <ArrowLeft />
      </Button>
      <div className="min-w-24 flex-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <h1 className="min-w-0 truncate font-semibold" title={p.map.flow.name}>
            {p.map.flow.name}
          </h1>
          {p.map.flow.kind === "sample" && (
            <span className="flex shrink-0 items-center gap-1 bg-muted px-1.5 text-[10px] font-medium text-muted-foreground" title="Sample data for validating the idea; no real integrations are called">
              <FlaskConical className="size-3" /> Sample
            </span>
          )}
          {!p.map.flow.enabled && (
            <span className="shrink-0 bg-amber-100 px-1.5 text-[10px] font-medium text-amber-900">Off</span>
          )}
        </div>
        {/* Second line: which run you're looking at (doubles as the run picker), and where it lives */}
        <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
          <label className="relative flex min-w-0 items-center gap-1 hover:text-foreground">
            {p.run && <span className={cn("size-1.5 shrink-0 rounded-full", STATUS_STYLE[p.run.status].dot)} />}
            <span className="truncate">
              {p.runs.length === 0
                ? "No runs yet"
                : `${p.run?.trigger === "test" ? "Test run" : p.runId === latest ? "Latest run" : "Earlier run"} · ${p.run ? STATUS_LABEL[p.run.status] : "…"} ${p.run ? timeAgo(p.run.started_at) : ""}`}
            </span>
            {p.runs.length > 1 && <ChevronDown className="size-3 shrink-0" />}
            {p.runs.length > 0 && (
              <select
                value={p.runId ?? ""}
                onChange={(e) => p.onPickRun(e.target.value)}
                className="absolute inset-0 h-full w-full cursor-pointer appearance-none opacity-0"
                aria-label="Choose which run to look at"
              >
                {p.runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id === latest ? "Latest · " : ""}
                    {r.trigger === "test" ? "Test run · " : ""}
                    {formatRunTime(r)} · {STATUS_LABEL[r.status]}
                    {p.inputs.length > 1 && r.trigger !== "test" ? ` · ${r.input_file.split("/").pop()}` : ""}
                  </option>
                ))}
              </select>
            )}
          </label>
          {p.map.flow.kind === "connected" && (
            <span
              className="hidden shrink-0 items-center gap-1 @lg:flex"
              title={`Your real automation. It runs on ${p.map.flow.source?.label}.`}
            >
              <span className="size-1.5 rounded-full bg-sky-500" /> {p.map.flow.source?.label}
            </span>
          )}
        </div>
      </div>

      {p.map.flow.kind !== "sample" && (
        <Button
          variant={p.testing ? "default" : "outline"}
          size="sm"
          onClick={p.onToggleTest}
          aria-pressed={p.testing}
          title={p.testing ? "Back to the map" : "Test lab: pressure-test this flow with test items"}
          className="shrink-0"
        >
          <FlaskConical /> <span className="hidden @md:inline">{p.testing ? "Back to map" : "Test"}</span>
        </Button>
      )}
      <span className="hidden @lg:contents">
        <ContactFinder flowId={p.flowId} runId={p.runId} map={p.map} onFound={p.onFound} />
      </span>
      {p.map.flow.kind !== "connected" ? (
        <EnabledToggle flowId={p.flowId} enabled={p.map.flow.enabled} onChange={p.onToggled} showLabel />
      ) : (
        p.map.flow.can_toggle && (
          <EnabledToggle
            flowId={p.flowId}
            enabled={p.map.flow.enabled}
            onChange={p.onToggled}
            showLabel
            confirm={{ where: p.map.flow.source?.label ?? "the place it runs", offHint: p.map.flow.toggle_off_hint, onHint: p.map.flow.toggle_on_hint }}
          />
        )
      )}
      {p.map.flow.kind !== "sample" && p.inputs.length > 1 && (
        <select
          value={p.inputFile ?? ""}
          onChange={(e) => p.onPickInput(e.target.value)}
          className="h-8 max-w-36 rounded-md border bg-background px-2 text-sm"
          aria-label="Which file the next run reads"
          title="Which file the next run reads"
        >
          {p.inputs.map((f) => (
            <option key={f} value={f}>
              {f.split("/").pop()}
            </option>
          ))}
        </select>
      )}
      {p.map.flow.kind === "connected" ? (
        p.map.flow.source?.repo &&
        p.runId && (
          <a
            href={`https://github.com/${p.map.flow.source.repo}/actions/runs/${p.runId}`}
            target="_blank"
            rel="noreferrer"
            className="flex h-8 shrink-0 items-center gap-1.5 border border-border bg-card px-2 text-sm hover:border-input"
            title="Open this run on GitHub"
            aria-label="Open this run on GitHub"
          >
            <span className="hidden @md:inline">GitHub</span> <ExternalLink className="size-3.5" />
          </a>
        )
      ) : (
        <Button size="sm" onClick={p.onRun} disabled={running}>
          {running ? <Loader2 className="animate-spin" /> : <Play />} Run
        </Button>
      )}
    </div>
  );
}

function ContactFinder({ flowId, runId, map, onFound }: { flowId: string; runId: string | null; map: FlowMap; onFound: (m: ContactMatch) => void }) {
  const terms = useTerms();
  const [q, setQ] = useState("");
  const [matches, setMatches] = useState<ContactMatch[] | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!runId || q.trim().length < 2) {
      setMatches(null);
      return;
    }
    const t = window.setTimeout(() => api.findContact(flowId, runId, q).then((r) => setMatches(r.matches)).catch(() => {}), 150);
    return () => window.clearTimeout(t);
  }, [q, runId, flowId]);

  const stepLabel = useMemo(() => new Map(map.steps.map((s) => [s.id, s.label ?? s.id])), [map]);

  const [expanded, setExpanded] = useState(false);
  if (!expanded)
    return (
      <Button variant="ghost" size="icon" onClick={() => setExpanded(true)} title={`Find a ${terms.item}`} aria-label={`Find a ${terms.item}`}>
        <Search />
      </Button>
    );
  return (
    <div className="relative">
      <label className="flex h-8 items-center gap-1.5 rounded-md border px-2 text-sm focus-within:ring-2 focus-within:ring-ring/50">
        <Search className="size-3.5 text-muted-foreground" />
        <input
          autoFocus
          onKeyDown={(e) => e.key === "Escape" && (setQ(""), setExpanded(false))}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => {
            setOpen(false);
            if (!q) setExpanded(false);
          }, 150)}
          placeholder={`Find a ${terms.item}…`}
          className="w-28 bg-transparent outline-none"
          aria-label={`Find a ${terms.item} in this run`}
        />
      </label>
      {open && matches && (
        <div className="absolute right-0 z-50 mt-1 max-h-80 w-96 overflow-auto rounded-md border bg-popover p-1 text-sm shadow-lg">
          {matches.length === 0 && <p className="p-2 text-muted-foreground">No {terms.item} matches “{q}” in this run.</p>}
          {matches.map((m) => (
            <button
              key={m.row_id}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                onFound(m);
                setOpen(false);
              }}
              disabled={!m.step_id}
              className="block w-full rounded px-2 py-1.5 text-left hover:bg-muted disabled:hover:bg-transparent"
            >
              <div className="flex justify-between gap-2">
                <span className="truncate font-medium">{m.name || "(no title)"}</span>
                <span className="shrink-0 text-xs text-muted-foreground">row {m.row_id}</span>
              </div>
              <div className="truncate font-mono text-xs text-muted-foreground">{m.email || ""}</div>
              <div
                className={cn(
                  "text-xs",
                  m.outcome === "rejected" ? "text-amber-800 dark:text-amber-300" : m.outcome === "kept" ? "text-emerald-700 dark:text-emerald-300" : "text-muted-foreground",
                )}
              >
                {m.outcome === "rejected"
                  ? `Skipped in “${stepLabel.get(m.step_id!) ?? m.step_id}”: ${m.reason}`
                  : m.outcome === "kept"
                    ? "Went all the way through the flow"
                    : "The run did not finish, so its outcome is unknown"}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Breadcrumb({ map, levelPath, onCrumb }: { map: FlowMap; levelPath: string[]; onCrumb: (i: number) => void }) {
  const labelOf = (id: string) => map.groups.find((g) => g.id === id)?.label ?? id;
  return (
    <nav
      aria-label="Where you are in the map"
      className="absolute top-3 left-3 z-10 flex max-w-[calc(100%-1.5rem)] items-center gap-1 border border-border bg-card p-1 text-sm"
    >
      {levelPath.length > 0 && (
        <Button variant="ghost" size="sm" onClick={() => onCrumb(levelPath.length - 2)} title="Back up one level (Esc)">
          <ArrowLeft /> Back
        </Button>
      )}
      <button
        onClick={() => onCrumb(-1)}
        className={cn("truncate rounded px-2 py-1 hover:bg-muted", levelPath.length === 0 ? "font-semibold" : "text-muted-foreground")}
      >
        {map.title}
      </button>
      {levelPath.map((id, i) => (
        <span key={id} className="flex min-w-0 items-center gap-1">
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
          <button
            onClick={() => onCrumb(i)}
            className={cn("truncate rounded px-2 py-1 hover:bg-muted", i === levelPath.length - 1 ? "font-semibold" : "text-muted-foreground")}
          >
            {labelOf(id)}
          </button>
        </span>
      ))}
    </nav>
  );
}

function Legend() {
  const [open, setOpen] = useState(false);
  const { items } = useTerms();
  return (
    <div className="absolute bottom-3 left-3 z-10 text-xs">
      {open ? (
        <div className="w-72 space-y-2 border border-border bg-card p-3">
          <div className="flex items-center justify-between">
            <b>How to read the map</b>
            <button onClick={() => setOpen(false)} className="text-muted-foreground hover:text-foreground" aria-label="Close">
              ✕
            </button>
          </div>
          <ul className="space-y-1">
            {(["success", "failed", "running", "not_run"] as const).map((s) => (
              <li key={s} className="flex items-center gap-2">
                <span className={cn("size-2.5 rounded-full", STATUS_STYLE[s].dot)} /> {STATUS_LABEL[s]}
                {s === "failed" && <span className="text-muted-foreground">— also shown on every box that contains it</span>}
              </li>
            ))}
          </ul>
          <p className="text-muted-foreground">
            <b className="text-foreground">out</b> = {items} passed on. <b className="text-amber-700 dark:text-amber-400">skipped</b> = held back
            with a reason; they don't go further. Click a box to see its {items}, double-click to look inside.{" "}
            <span className="rounded bg-sky-100 px-1 font-semibold text-sky-900 dark:bg-sky-900 dark:text-sky-100">+4</span> = change since the
            previous run.
          </p>
        </div>
      ) : (
        <button
          onClick={() => setOpen(true)}
          className="flex size-7 items-center justify-center rounded-full border border-border bg-card font-medium text-muted-foreground hover:text-foreground"
          title="How to read the map"
          aria-label="How to read the map"
        >
          ?
        </button>
      )}
    </div>
  );
}

const BUILDER_IDEAS = [
  "When a new lead comes in, read their company website with Firecrawl, look the company up in Clay, and skip companies with fewer than 50 employees.",
  "For a list of competitor websites, scrape each one with Firecrawl and flag the ones without a pricing page.",
  "Enrich a list of event attendees with Clay (job title and seniority) and keep only managers and above.",
];

function BuilderWelcome({ onBack, onAsk }: { onBack: () => void; onAsk: (t: string) => void }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b px-3 py-2">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft /> Flows
        </Button>
        <h1 className="text-sm font-semibold">New flow</h1>
      </div>
      <div className="flex flex-1 items-center justify-center p-8">
        <div className="max-w-xl space-y-4 text-center">
          <h2 className="text-lg font-semibold">Describe what you want to automate</h2>
          <p className="text-sm text-muted-foreground">
            Tell Claude in the chat what should happen, in your own words. It sets up the steps, connects the apps (Clay and
            Firecrawl are available as dummies), makes sample data and runs it once so you can check what goes in and out.
          </p>
          <div className="space-y-2 text-left">
            {BUILDER_IDEAS.map((idea) => (
              <button
                key={idea}
                onClick={() => onAsk(idea)}
                className="block w-full rounded-lg border p-3 text-left text-sm hover:bg-muted"
              >
                {idea}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            Check the <a className="underline" href="#/connections">Apps</a> page first: Clay and Firecrawl need to be connected.
          </p>
        </div>
      </div>
    </div>
  );
}
