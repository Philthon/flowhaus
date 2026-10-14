import { ChevronDown, FlaskConical, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { go } from "@/App";
import { PageTitle } from "@/components/PageTitle";
import { api, type Connection, type McpServer } from "@/lib/api";
import { AppBadge } from "@/lib/apps";
import { cn } from "@/lib/utils";
import { timeAgo } from "./FlowsPage";

export function ConnectionsPage() {
  const [list, setList] = useState<Connection[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSoon, setShowSoon] = useState(false);

  const [mcpInfo, setMcpInfo] = useState<{ servers: McpServer[] } | null>(null);
  useEffect(() => {
    api.mcp().then(setMcpInfo).catch(() => setMcpInfo(null));
  }, []);

  const load = useCallback(() => {
    api
      .connections()
      .then((r) => {
        setList(r.connections);
        setError(null);
      })
      .catch((e) => setError(`Could not load apps: ${e.message}`));
  }, []);

  useEffect(() => {
    document.title = "Apps · Flowhaus";
    load();
  }, [load]);

  const empty = list?.length === 0;
  const managed = empty || (!!list?.length && list.every((c) => c.auth === "managed"));
  const available = list?.filter((c) => c.available) ?? [];
  const soon = list?.filter((c) => !c.available) ?? [];
  const shown = available;

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto max-w-4xl space-y-5 px-6 py-8">
        <header className="space-y-1">
          <PageTitle shape="triangle">Apps</PageTitle>
          {managed ? (
            <p className="text-xs text-muted-foreground">
              The apps your automations use. They stay connected in each automation's own project; nothing is connected or stored here.
            </p>
          ) : (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <FlaskConical className="size-3.5" /> Demo flows use demo Clay and Firecrawl connectors: made-up answers, no network, nothing
              to set up. Flowhaus never stores keys; your real apps are set up in your own tools.
            </p>
          )}
        </header>

        {error && <p className="text-sm text-red-700">{error}</p>}
        {!list && !error && (
          <p className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Loading…
          </p>
        )}

        <ul className="divide-y divide-border border border-border bg-card">
          {shown.map((c) => (
            <AppRow key={c.id} conn={c} />
          ))}
          {empty && (
            <li className="space-y-2 p-8 text-center text-sm text-muted-foreground">
              <p>No apps yet. The apps your automations use, like GitHub Actions, Firecrawl or Slack, show up here once you connect one.</p>
              <button className="underline underline-offset-2 hover:text-foreground" onClick={() => go({ page: "flows" })}>
                Connect your first automation
              </button>
            </li>
          )}
          {list && !empty && shown.length === 0 && <li className="p-6 text-center text-sm text-muted-foreground">Nothing here.</li>}
        </ul>

        {mcpInfo && <McpServers info={mcpInfo} onChange={setMcpInfo} />}

        {soon.length > 0 && (
          <div className="space-y-2 text-center">
            <button className="text-sm text-muted-foreground underline hover:text-foreground" onClick={() => setShowSoon((s) => !s)}>
              {showSoon ? "Hide" : `${soon.length} more apps coming soon`}
            </button>
            {showSoon && (
              <ul className="divide-y rounded-xl border text-left opacity-80">
                {soon.map((c) => (
                  <li key={c.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                    <AppBadge app={c.name} />
                    <span className="min-w-0 flex-1 truncate text-muted-foreground">{c.description}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">Coming soon</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function AppRow({ conn }: { conn: Connection }) {
  const [open, setOpen] = useState(false);
  const u = conn.usage;
  return (
    <li>
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => e.key === "Enter" && setOpen((o) => !o)}
        aria-expanded={open}
        className="flex cursor-pointer items-center gap-3 px-4 py-3.5 hover:bg-muted/40"
      >
        <AppBadge app={conn.name} className="text-sm" />
        <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{conn.description}</span>
        <span className="shrink-0 truncate text-xs text-muted-foreground">
          {conn.auth === "demo" ? "Demo" : conn.used_by.join(", ")}
        </span>
        <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </div>
      {open && (
        <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-1.5 border-t bg-muted/20 px-4 py-3 text-sm">
          <dt className="text-muted-foreground">Used by</dt>
          <dd>{conn.used_by.length ? conn.used_by.join(", ") : "No flows yet"}</dd>
          <dt className="text-muted-foreground">Set up</dt>
          <dd>{conn.managed_by}</dd>
          {conn.setup_hint && (
            <>
              <dt className="text-muted-foreground">To set it up</dt>
              <dd className="text-xs">
                <span className="font-mono">{conn.setup_hint}</span>
                <span className="block text-muted-foreground">You run this in your own tools; Flowhaus never stores keys.</span>
              </dd>
            </>
          )}
          {conn.auth === "demo" && (
            <>
              <dt className="text-muted-foreground">Last 24 hours</dt>
              <dd>
                {u.calls_24h} {u.calls_24h === 1 ? "call" : "calls"}, {u.credits_24h} demo credits · last call {timeAgo(u.last_call)}
              </dd>
            </>
          )}
        </dl>
      )}
    </li>
  );
}

/** MCP servers you already set up elsewhere. You only choose which ones the chat may use; every call asks first. */
function McpServers({ info, onChange }: { info: { servers: McpServer[] }; onChange: (next: { servers: McpServer[] }) => void }) {
  const [error, setError] = useState<string | null>(null);
  const toggle = async (s: McpServer) => {
    try {
      onChange(await api.setMcp(s.name, !s.enabled));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <section className="space-y-2">
      <div>
        <h2 className="text-sm font-medium">Tools for the chat (MCP)</h2>
        <p className="text-xs text-muted-foreground">
          Found in your Claude Code, Claude Desktop, Cursor and project settings. Flowhaus keeps no copy of them or their keys; switch
          on the ones the chat may use. It asks you before each call, unless your Claude Code permissions already allow the tool.
        </p>
      </div>
      {info.servers.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          None found. Add MCP servers the way you normally do (for example <code className="font-mono">claude mcp add</code>) and they
          show up here.
        </p>
      ) : (
        <ul className="divide-y divide-border border border-border bg-card text-sm">
          {info.servers.map((s) => (
            <li key={s.name} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{s.name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {s.type === "stdio" ? `runs ${s.where} on this computer` : s.where} · from {s.source}
                  {s.allowed_without_asking.length > 0 && <> · no question for {s.allowed_without_asking.join(", ")}</>}
                </p>
                {s.problem && <p className="text-xs text-red-800">Can't start: {s.problem}</p>}
              </div>
              <button
                role="switch"
                aria-checked={s.enabled}
                aria-label={`Let the chat use ${s.name}`}
                disabled={!!s.problem && !s.enabled}
                onClick={() => toggle(s)}
                className={cn(
                  "relative h-5 w-9 shrink-0 border transition-colors disabled:opacity-40",
                  s.enabled ? "border-emerald-700 bg-emerald-600" : "border-border bg-muted",
                )}
              >
                <span className={cn("absolute top-0.5 size-3.5 bg-white transition-all", s.enabled ? "left-[18px]" : "left-0.5")} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="text-xs text-red-800">{error}</p>}
    </section>
  );
}
