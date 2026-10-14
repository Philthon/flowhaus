import { Handle, Position, type NodeProps, type Node as RFNode } from "@xyflow/react";
import { AlertTriangle, ArrowRight, ChevronRight } from "lucide-react";

import { Node, NodeContent, NodeDescription, NodeFooter, NodeHeader, NodeTitle } from "@/components/ai-elements/node";
import type { Counts, PrevCounts, Status, Trigger } from "@/lib/api";
import { AppBadge } from "@/lib/apps";
import { NODE_WIDTH } from "@/lib/layout";
import { STATUS_LABEL, STATUS_STYLE } from "@/lib/status";
import { cn } from "@/lib/utils";

export type FlowNodeData = {
  label: string;
  description: string;
  status: Status;
  counts: Counts | null;
  previous?: PrevCounts | null;
  apps: string[];
  childCount: number; // > 0 means it can be opened
  failedChildLabel?: string | null;
  errorMessage?: string | null;
  onOpen?: () => void;
  vertical?: boolean;
};

export type FlowNodeType = RFNode<FlowNodeData, "flow">;

export function FlowNode({ data, selected }: NodeProps<FlowNodeType>) {
  const style = STATUS_STYLE[data.status];
  const canOpen = data.childCount > 0;
  const apps = data.apps.slice(0, 2);
  return (
    <Node
      handles={{ target: true, source: true }}
      vertical={data.vertical}
      style={{ width: NODE_WIDTH }}
      className={cn("gap-0 border bg-card ring-0", style.card, selected && "outline-2 outline-offset-2 outline-sky-500")}
      data-testid={`node-${data.label}`}
    >
      <NodeHeader className={cn("flex flex-row items-center justify-between gap-2", style.header)}>
        <div className="flex min-w-0 items-center gap-2">
          <span className={cn("size-2.5 shrink-0 rounded-full", style.dot)} aria-label={STATUS_LABEL[data.status]} />
          <NodeTitle className="line-clamp-2 text-[15px] leading-tight" title={data.label}>
            {data.label}
          </NodeTitle>
        </div>
        {canOpen && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              data.onOpen?.();
            }}
            className="nodrag -mr-1 shrink-0 rounded-md p-0.5 text-muted-foreground hover:bg-background hover:text-foreground"
            title="Look inside (or double-click the box)"
            aria-label={`Open ${data.label}`}
          >
            <ChevronRight className="size-4" />
          </button>
        )}
      </NodeHeader>
      <NodeContent className="space-y-2">
        <NodeDescription className="line-clamp-3 text-[13px] leading-snug">{data.description}</NodeDescription>
        {data.status === "failed" && (data.failedChildLabel || data.errorMessage) && (
          <div className="flex items-start gap-1.5 bg-red-50 px-2 py-1 text-xs text-red-700">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
            <span className="line-clamp-2">
              {data.failedChildLabel ? <>Failed in <b>{data.failedChildLabel}</b></> : data.errorMessage}
            </span>
          </div>
        )}
      </NodeContent>
      <NodeFooter className="flex items-center justify-between gap-2 py-1.5! text-xs">
        <CountLine counts={data.counts} previous={data.previous ?? null} />
        <span className="flex shrink-0 gap-1">
          {apps.map((a) => (
            <AppBadge key={a} app={a} />
          ))}
          {data.apps.length > 2 && <span className="text-muted-foreground" title={data.apps.slice(2).join(", ")}>+{data.apps.length - 2}</span>}
        </span>
      </NodeFooter>
    </Node>
  );
}

function Was({ now, before }: { now: number | null; before: number | null | undefined }) {
  if (before == null || now == null || before === now) return null;
  const diff = now - before;
  return (
    <span
      className="ml-0.5 rounded bg-sky-100 px-1 text-[10px] font-semibold text-sky-900 dark:bg-sky-900 dark:text-sky-100"
      title={`Was ${before} in the previous run`}
    >
      {diff > 0 ? "+" : "−"}
      {Math.abs(diff)}
    </span>
  );
}

/** Just what matters at a glance: how many came out, and how many were skipped. */
function CountLine({ counts, previous }: { counts: Counts | null; previous: PrevCounts | null }) {
  if (!counts || counts.rows_in == null) {
    const done: Record<string, string> = { success: "Done", failed: "Failed", running: "Running…" };
    const text = done[counts?.status ?? ""] ?? "No data yet";
    return <span className="text-muted-foreground">{text}</span>;
  }
  const skipped = counts.rows_rejected > 0 || (previous?.rows_rejected ?? 0) > 0;
  return (
    <span className="tabular-nums text-muted-foreground">
      {counts.rows_out != null && (
        <>
          <b className="text-foreground">{counts.rows_out}</b> out
          <Was now={counts.rows_out} before={previous?.rows_out} />
        </>
      )}
      {skipped && (
        <>
          {counts.rows_out != null && " · "}
          <b className="text-amber-700 dark:text-amber-400">{counts.rows_rejected}</b> skipped
          <Was now={counts.rows_rejected} before={previous?.rows_rejected} />
        </>
      )}
    </span>
  );
}

export type BoundaryData = { label: string; direction: "in" | "out"; onOpen?: () => void; vertical?: boolean };
export type BoundaryNodeType = RFNode<BoundaryData, "boundary">;

/** Ghost node at the edge of a drilled-in level: where data comes from / goes next. */
export function BoundaryNode({ data }: NodeProps<BoundaryNodeType>) {
  return (
    <div
      className="flex h-16 w-[132px] cursor-pointer flex-col justify-center border border-dashed border-input bg-transparent px-3 text-xs text-muted-foreground hover:border-muted-foreground"
      onClick={data.onOpen}
      title={`Go to ${data.label}`}
    >
      {data.direction === "out" && <Handle type="target" position={data.vertical ? Position.Top : Position.Left} />}
      <span className="text-[10px] font-medium tracking-[0.12em] uppercase">{data.direction === "in" ? "Comes from" : "Goes to"}</span>
      <span className="flex items-center gap-1 font-medium text-foreground">
        {data.label}
        <ArrowRight className="size-3" />
      </span>
      {data.direction === "in" && <Handle type="source" position={data.vertical ? Position.Bottom : Position.Right} />}
    </div>
  );
}

/** Bauhaus markers: the flow starts at a blue circle and ends at a yellow triangle. */
export function Circle({ className }: { className?: string }) {
  return <span className={cn("inline-block size-3.5 shrink-0 rounded-full bg-sky-500", className)} aria-hidden />;
}
export function Triangle({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 14 12" className={cn("size-3.5 shrink-0", className)} aria-hidden>
      <path d="M7 0 L14 12 L0 12 Z" fill="var(--bauhaus-yellow)" />
    </svg>
  );
}
export function Square({ className }: { className?: string }) {
  return <span className={cn("inline-block size-3 shrink-0 bg-red-500", className)} aria-hidden />;
}

export type TriggerData = { trigger: Trigger; nextRun: string | null; enabled: boolean; count: number | null; items: string; item?: string; vertical?: boolean };
export type TriggerNodeType = RFNode<TriggerData, "trigger">;

/** First box on the overview: what starts the flow. */
export function TriggerNode({ data, selected }: NodeProps<TriggerNodeType>) {
  return (
    <div
      className={cn(
        "flex h-[76px] w-[160px] cursor-pointer flex-col justify-center gap-0.5 border border-border bg-card px-3 hover:border-input",
        selected && "outline-2 outline-offset-2 outline-sky-500",
      )}
      title="Click to see everything that came in"
    >
      <span className="flex items-center gap-1.5 text-[10px] font-medium tracking-[0.12em] text-muted-foreground uppercase">
        <Circle className="size-2.5" /> Starts when
      </span>
      <span className="line-clamp-2 text-[13px] leading-tight font-medium">{data.trigger.label}</span>
      {!data.enabled ? (
        <span className="text-[11px] font-medium text-amber-700">Paused</span>
      ) : (
        data.count != null && (
          <span className="text-[11px] text-muted-foreground tabular-nums">
            {data.count} {data.count === 1 && data.item ? data.item : data.items} came in ›
          </span>
        )
      )}
      <Handle type="source" position={data.vertical ? Position.Bottom : Position.Right} />
    </div>
  );
}

export type OutputData = { label: string; status: Status; count: number | null; items: string; item: string; vertical?: boolean };
export type OutputNodeType = RFNode<OutputData, "result">;

/** Last box on the overview: where the results go, and how many made it. Click to see them. */
export function OutputNode({ data, selected }: NodeProps<OutputNodeType>) {
  const style = STATUS_STYLE[data.status];
  return (
    <div
      className={cn(
        "flex h-[76px] w-[160px] cursor-pointer flex-col justify-center gap-0.5 border bg-card px-3 hover:border-input",
        data.status === "failed" ? "border-red-200" : "border-border",
        selected && "outline-2 outline-offset-2 outline-sky-500",
      )}
      title="Click to see everything that came out"
    >
      <Handle type="target" position={data.vertical ? Position.Top : Position.Left} />
      <span className="flex items-center gap-1.5 text-[10px] font-medium tracking-[0.12em] text-muted-foreground uppercase">
        <Triangle className="size-3" /> Result
      </span>
      <span className="line-clamp-2 text-[13px] leading-tight font-medium">{data.label}</span>
      <span className={cn("text-[11px] tabular-nums", data.status === "success" ? style.text : "text-muted-foreground")}>
        {data.status === "failed"
          ? "Nothing came out: the run failed"
          : data.status === "running"
            ? "Running…"
            : data.count != null
              ? `${data.count} ${data.count === 1 ? data.item : data.items} came out ›`
              : "No run yet"}
      </span>
    </div>
  );
}

export const nodeTypes = { flow: FlowNode, boundary: BoundaryNode, trigger: TriggerNode, result: OutputNode };
