import {
  BaseEdge,
  EdgeLabelRenderer,
  Handle,
  Position,
  getSmoothStepPath,
  type Edge,
  type EdgeProps,
  type NodeProps,
  type Node as RFNode,
} from "@xyflow/react";
import { AlertTriangle, ArrowRight, CornerUpLeft, Hourglass } from "lucide-react";

import { Node, NodeContent, NodeDescription, NodeFooter, NodeHeader, NodeTitle } from "@/components/ai-elements/node";
import type { Counts, PrevCounts, Status, Trigger } from "@/lib/api";
import { AppBadge } from "@/lib/apps";
import { CHOICE_POINT, isChoice, sizeOf, type RoutedEdgeData } from "@/lib/layout";
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
  /** A decision's number of answers on this level: 3 or more draws it as a choice. */
  answers?: number;
};

export type FlowNodeType = RFNode<FlowNodeData, "flow">;

export function FlowNode({ data, selected }: NodeProps<FlowNodeType>) {
  const style = STATUS_STYLE[data.status];
  const canOpen = data.childCount > 0;
  const apps = data.apps.slice(0, 2);
  return (
    <Node
      handles={{ target: true, source: true }}
      style={sizeOf({ type: "flow", data })}
      className={cn("relative gap-0 border bg-card ring-0", canOpen && "overflow-visible", style.card, selected && "outline-2 outline-offset-2 outline-sky-500")}
      data-testid={`node-${data.label}`}
    >
      {/* steps inside: a second sheet behind the box, like a stack (double-click or Enter opens it) */}
      {canOpen && <span aria-hidden className="pointer-events-none absolute inset-0 -z-10 translate-x-[6px] translate-y-[6px] border border-foreground/35 bg-muted" />}
      <NodeHeader className={cn("flex flex-row items-center justify-between gap-2", style.header)}>
        <div className="flex min-w-0 items-center gap-2">
          <span className={cn("size-2.5 shrink-0 rounded-full", style.dot)} aria-label={STATUS_LABEL[data.status]} />
          <NodeTitle className="text-[15px] leading-tight">
            {data.label}
          </NodeTitle>
        </div>
      </NodeHeader>
      <NodeContent className="flex-1 space-y-2">
        <NodeDescription className="text-[13px] leading-snug">{data.description}</NodeDescription>
        {data.status === "failed" && (data.failedChildLabel || data.errorMessage) && (
          <div className="flex items-start gap-1.5 tone-error px-2 py-1 text-xs">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
            <span className="line-clamp-4">
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

export type BoundaryData = { label: string; direction: "in" | "out"; onOpen?: () => void };
export type BoundaryNodeType = RFNode<BoundaryData, "boundary">;

/** Ghost node at the edge of a drilled-in level: where data comes from / goes next. */
export function BoundaryNode({ data }: NodeProps<BoundaryNodeType>) {
  return (
    <div
      className="flex h-16 w-[132px] cursor-pointer flex-col justify-center border border-dashed border-input bg-transparent px-3 text-xs text-muted-foreground hover:border-muted-foreground"
      onClick={data.onOpen}
      title={`Go to ${data.label}`}
    >
      {data.direction === "out" && <Handle type="target" position={Position.Left} />}
      <span className="text-[10px] font-medium tracking-[0.12em] uppercase">{data.direction === "in" ? "Comes from" : "Goes to"}</span>
      <span className="flex items-center gap-1 font-medium text-foreground">
        {data.label}
        <ArrowRight className="size-3" />
      </span>
      {data.direction === "in" && <Handle type="source" position={Position.Right} />}
    </div>
  );
}

/** Bauhaus marker: the flow starts at a blue circle. */
export function Circle({ className }: { className?: string }) {
  return <span className={cn("inline-block size-3.5 shrink-0 rounded-full bg-sky-500", className)} aria-hidden />;
}
export function Square({ className }: { className?: string }) {
  return <span className={cn("inline-block size-3 shrink-0 bg-red-500", className)} aria-hidden />;
}

export type TriggerData = { trigger: Trigger; nextRun: string | null; enabled: boolean; count: number | null; items: string; item?: string };
export type TriggerNodeType = RFNode<TriggerData, "trigger">;

/** First box on the overview: what starts the flow. */
export function TriggerNode({ data, selected }: NodeProps<TriggerNodeType>) {
  return (
    <div
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-1 rounded-full border border-foreground/25 bg-card px-10 hover:border-foreground/50",
        selected && "outline-2 outline-offset-2 outline-sky-500",
      )}
      style={sizeOf({ type: "trigger", data })}
      title="Start: click to see everything that came in"
    >
      <span className="flex items-center justify-center gap-1.5 text-[10px] font-medium tracking-[0.12em] text-muted-foreground uppercase">
        <Circle className="size-2.5" /> Start
      </span>
      <span className="text-center text-[15px] leading-tight font-medium">{data.trigger.label}</span>
      {!data.enabled ? (
        <span className="text-xs font-medium text-amber-700 dark:text-amber-400">Paused</span>
      ) : (
        data.count != null && (
          <span className="text-xs text-muted-foreground tabular-nums">
            {data.count} {data.count === 1 && data.item ? data.item : data.items} came in ›
          </span>
        )
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

export type OutputData = { label: string; status: Status; count: number | null; items: string; item: string };
export type OutputNodeType = RFNode<OutputData, "result">;

/** Last box on the overview: where the results go, and how many made it. Click to see them. */
export function OutputNode({ data, selected }: NodeProps<OutputNodeType>) {
  const style = STATUS_STYLE[data.status];
  return (
    <div
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-1 rounded-full border bg-card px-10 hover:border-foreground/50",
        data.status === "failed" ? "border-red-300" : "border-foreground/25",
        selected && "outline-2 outline-offset-2 outline-sky-500",
      )}
      style={sizeOf({ type: "result", data })}
      title="End: click to see everything that came out"
    >
      <Handle type="target" position={Position.Left} />
      <span className="flex items-center justify-center gap-1.5 text-[10px] font-medium tracking-[0.12em] text-muted-foreground uppercase">
        End · result
      </span>
      <span className="text-center text-[15px] leading-tight font-medium">{data.label}</span>
      <span className={cn("text-xs tabular-nums", data.status === "success" ? style.text : "text-muted-foreground")}>
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

// ---------------------------------------------------------------------------- flowchart shapes (Blue Prism style)

/** Line colour for a shape's outline, by how the run went. */
const OUTLINE: Record<Status, string> = {
  not_run: "color-mix(in srgb, var(--foreground) 25%, transparent)",
  running: "var(--color-sky-500)",
  success: "var(--color-emerald-600)",
  failed: "var(--color-red-500)",
};

const hidden = "!opacity-0 !pointer-events-none";

export type ShapeNodeType = RFNode<FlowNodeData, "decision" | "wait" | "end">;

/** A decision: a diamond with the question. Its lines out carry the answers ("Yes", "No").
 *  With three or more answers it's a choice: pointed on the left, answers leave in order down the flat right edge. */
export function DecisionNode({ data, selected, type }: NodeProps<ShapeNodeType>) {
  const { width: w, height: h } = sizeOf({ type, data });
  const choice = isChoice({ type, data });
  const p = CHOICE_POINT;
  const points = choice ? `1,${h / 2} ${p},1 ${w - 1},1 ${w - 1},${h - 1} ${p},${h - 1}` : `${w / 2},1 ${w - 1},${h / 2} ${w / 2},${h - 1} 1,${h / 2}`;
  return (
    <div className="relative cursor-pointer" style={{ width: w, height: h }}>
      <svg width={w} height={h} className="absolute inset-0 overflow-visible" aria-hidden>
        <polygon
          points={points}
          fill="var(--card)"
          stroke={selected ? "var(--color-sky-500)" : OUTLINE[data.status]}
          strokeWidth={selected ? 2.5 : data.status === "not_run" ? 1 : 1.75}
        />
      </svg>
      <div className={cn("absolute inset-0 flex flex-col justify-center", choice ? "items-start gap-1 pr-4 pl-9 text-left" : "items-center px-12 text-center")}>
        <span className="text-[9px] font-medium tracking-[0.14em] text-muted-foreground uppercase">{choice ? `Choice · ${data.answers} ways` : "Decision"}</span>
        <span className={cn("leading-tight font-medium", choice ? "text-[13px]" : "text-[12.5px]")}>{data.label}</span>
      </div>
      <Handle type="target" position={Position.Left} className={hidden} />
      <Handle type="source" position={Position.Right} className={hidden} />
    </div>
  );
}

/** A wait: items held until something happens ("Held for review", "Waiting for provider"). Cut corners. */
export function WaitNode({ data, selected, type }: NodeProps<ShapeNodeType>) {
  const { width: w, height: h } = sizeOf({ type, data });
  const c = 16;
  return (
    <div className="relative cursor-pointer" style={{ width: w, height: h }}>
      <svg width={w} height={h} className="absolute inset-0" aria-hidden>
        <polygon
          points={`${c},1 ${w - c},1 ${w - 1},${h / 2} ${w - c},${h - 1} ${c},${h - 1} 1,${h / 2}`}
          fill="var(--card)"
          stroke={selected ? "var(--color-sky-500)" : OUTLINE[data.status]}
          strokeWidth={selected ? 2.5 : data.status === "not_run" ? 1 : 1.75}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col justify-center gap-1 px-7">
        <span className="flex items-center gap-1 text-[9px] font-medium tracking-[0.14em] text-muted-foreground uppercase">
          <Hourglass className="size-3" /> Waits
        </span>
        <span className="text-[14px] leading-tight font-medium">{data.label}</span>
        <span className="text-[12px] leading-snug text-muted-foreground">{data.description}</span>
        <span className="text-xs">
          <CountLine counts={data.counts} previous={data.previous ?? null} />
        </span>
      </div>
      <Handle type="target" position={Position.Left} className={hidden} />
      <Handle type="source" position={Position.Right} className={hidden} />
    </div>
  );
}

/** An end: how a path finishes ("Published", "Skipped: coaching not requested"). A pill, like the start. */
export function EndNode({ data, selected }: NodeProps<ShapeNodeType>) {
  const reached = data.status === "success" || data.status === "failed";
  return (
    <div
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-1 rounded-full border bg-card px-10",
        reached ? "border-foreground/50" : "border-dashed border-foreground/25",
        selected && "outline-2 outline-offset-2 outline-sky-500",
      )}
      style={sizeOf({ type: "end", data })}
    >
      <Handle type="target" position={Position.Left} className={hidden} />
      <span className="flex items-center justify-center gap-1.5 text-[9px] font-medium tracking-[0.14em] text-muted-foreground uppercase">
        End{reached ? " · reached" : ""}
      </span>
      <span className="text-center text-[15px] leading-tight font-medium">{data.label}</span>
    </div>
  );
}

export type GotoNodeType = RFNode<{ label: string; target: string; status: Status }, "goto">;

/** Where a loop goes back to ("try again"): a marker instead of a line running backwards across the map. */
export function GotoNode({ data, type }: NodeProps<GotoNodeType>) {
  return (
    <div
      className={cn(
        "flex cursor-pointer items-center gap-2 border bg-card px-3 hover:border-foreground/60",
        data.status === "success" ? "border-foreground/50" : "border-dashed border-foreground/25",
      )}
      style={sizeOf({ type, data })}
      title={`Show “${data.label}”`}
    >
      <Handle type="target" position={Position.Left} className={hidden} />
      <CornerUpLeft className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <span className="flex flex-col leading-tight">
        <span className="text-[9px] font-medium tracking-[0.14em] text-muted-foreground uppercase">Go back to</span>
        <span className="text-[12.5px] font-medium">{data.label}</span>
      </span>
    </div>
  );
}

/** A right-angle line routed by the layout (around boxes, never through them), with its branch label. */
export function RoutedEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd, style }: EdgeProps<Edge<RoutedEdgeData>>) {
  const pts = data?.points;
  const path = pts?.length
    ? `M ${pts.map((p) => `${p.x} ${p.y}`).join(" L ")}`
    : getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: 0 })[0];
  const at = data?.labelAt ?? (pts && pts.length > 1 ? { x: (pts[0].x + pts[1].x) / 2 + 18, y: pts[1].y } : null);
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />
      {data?.label && at && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan pointer-events-auto absolute border border-foreground/20 bg-card px-1.5 py-px text-[11px] leading-4 font-medium"
            style={{ transform: `translate(-50%, -50%) translate(${at.x}px, ${at.y}px)` }}
            title={data.when ?? undefined}
          >
            {data.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

