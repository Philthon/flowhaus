import { LayoutGrid, Plug, ScrollText } from "lucide-react";
import { useEffect, useState } from "react";

import { TooltipProvider } from "@/components/ui/tooltip";
import { ActivityPage } from "@/pages/ActivityPage";
import { ConnectionsPage } from "@/pages/ConnectionsPage";
import { FlowPage } from "@/pages/FlowPage";
import { FlowsPage } from "@/pages/FlowsPage";
import { go, href, parse, type Route } from "@/lib/route";
import { cn } from "@/lib/utils";


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

/** Flowhaus's mark: a house built from the three Bauhaus shapes, a triangle roof over a circle and a square. */
function LogoMark() {
  return (
    <a href="#/flows" className="mb-4 block" title="Flowhaus" aria-label="Flowhaus home">
      <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
        <path d="M16 2 L30 15 L2 15 Z" fill="var(--bauhaus-yellow)" />
        <circle cx="9" cy="23.5" r="6.5" fill="var(--bauhaus-blue)" />
        <rect x="17" y="17" width="13" height="13" fill="var(--bauhaus-red)" />
      </svg>
    </a>
  );
}
