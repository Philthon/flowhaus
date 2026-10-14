import { LayoutGrid, Plug, ScrollText } from "lucide-react";
import { useEffect, useState } from "react";

import { TooltipProvider } from "@/components/ui/tooltip";
import { ActivityPage } from "@/pages/ActivityPage";
import { ConnectionsPage } from "@/pages/ConnectionsPage";
import { FlowPage } from "@/pages/FlowPage";
import { FlowsPage } from "@/pages/FlowsPage";
import { cn } from "@/lib/utils";

export type Route =
  | { page: "flows" }
  | { page: "activity"; flowId?: string }
  | { page: "connections" }
  | { page: "new" }
  | { page: "flow"; flowId: string; runId?: string };

function parse(hash: string): Route {
  const [path, query] = hash.replace(/^#\/?/, "").split("?");
  const params = new URLSearchParams(query ?? "");
  const [page, id] = path.split("/");
  if (page === "flow" && id) return { page: "flow", flowId: id, runId: params.get("run") ?? undefined };
  if (page === "activity") return { page: "activity", flowId: params.get("flow") ?? undefined };
  if (page === "connections") return { page: "connections" };
  if (page === "new") return { page: "new" };
  return { page: "flows" };
}

export function href(route: Route): string {
  if (route.page === "flow") return `#/flow/${route.flowId}${route.runId ? `?run=${encodeURIComponent(route.runId)}` : ""}`;
  if (route.page === "activity") return `#/activity${route.flowId ? `?flow=${route.flowId}` : ""}`;
  if (route.page === "connections") return "#/connections";
  if (route.page === "new") return "#/new";
  return "#/flows";
}

export const go = (route: Route) => {
  window.location.hash = href(route);
};

export default function App() {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));
  useEffect(() => {
    const onHash = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return (
    <TooltipProvider>
      <div className="flex h-screen bg-background text-foreground">
        <nav aria-label="Main" className="flex w-16 shrink-0 flex-col items-center gap-1 border-r border-border bg-background py-3">
          <LogoMark />
          <RailLink active={route.page === "flows" || route.page === "flow" || route.page === "new"} to={{ page: "flows" }} label="Flows">
            <LayoutGrid className="size-5" />
          </RailLink>
          <RailLink active={route.page === "activity"} to={{ page: "activity" }} label="Activity">
            <ScrollText className="size-5" />
          </RailLink>
          <RailLink active={route.page === "connections"} to={{ page: "connections" }} label="Apps">
            <Plug className="size-5" />
          </RailLink>
        </nav>
        <div className="min-w-0 flex-1">
          {route.page === "flows" && <FlowsPage />}
          {route.page === "activity" && <ActivityPage flowId={route.flowId} />}
          {route.page === "connections" && <ConnectionsPage />}
          {route.page === "flow" && (
            <FlowPage key={route.flowId} flowId={route.flowId} initialRunId={route.runId} onBack={() => go({ page: "flows" })} />
          )}
          {route.page === "new" && <FlowPage key="new" flowId={null} onBack={() => go({ page: "flows" })} />}
        </div>
      </div>
    </TooltipProvider>
  );
}

function RailLink({ active, to, label, children }: { active: boolean; to: Route; label: string; children: React.ReactNode }) {
  return (
    <a
      href={href(to)}
      title={label}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex w-12 flex-col items-center gap-0.5 py-1.5 text-[10px] font-medium tracking-[0.08em] text-muted-foreground uppercase hover:text-foreground",
        active && "bg-muted text-foreground",
      )}
    >
      {children}
      {label}
    </a>
  );
}

/** Bauhaus mark: circle, square, triangle in the three primaries. */
/** Flowhaus's mark: a start (circle) that branches into two steps (triangle, square), like a tiny map. */
function LogoMark() {
  return (
    <a href="#/flows" className="mb-4 block" title="Flowhaus" aria-label="Flowhaus home">
      <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
        <path d="M9 9 H23 V23 M9 9 V23" fill="none" stroke="var(--foreground)" strokeWidth="1.5" />
        <circle cx="9" cy="9" r="6" fill="var(--bauhaus-blue)" />
        <path d="M9 17 L15 29 L3 29 Z" fill="var(--bauhaus-yellow)" />
        <rect x="17" y="17" width="12" height="12" fill="var(--bauhaus-red)" />
      </svg>
    </a>
  );
}
