import { MarkerType, ReactFlowProvider, useReactFlow, type Edge, type Node } from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { Canvas } from "@/components/ai-elements/canvas";
import type { Counts, FlowMap, PrevCounts, Run, Status } from "@/lib/api";
import { layout, sizeOf } from "@/lib/layout";
import { cn } from "@/lib/utils";
import { nodeTypes, type FlowNodeData } from "./nodes";

type Props = {
  map: FlowMap;
  run: Run | null;
  levelId: string;
  direction: "in" | "out";
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onOpen: (groupId: string) => void;
  onGoTo: (nodeId: string) => void;
  /** Pixels at the top covered by overlays (mini map); boxes are fitted below them. */
  topInset?: number;
};

export const INPUT_ID = "__input__";
export const OUTPUT_ID = "__output__";

export function nodeInfo(map: FlowMap, run: Run | null, id: string) {
  if (id === INPUT_ID || id === OUTPUT_ID) {
    const output = id === OUTPUT_ID;
    // In: fine as soon as items were read. Out: follows the run (failed run = nothing came out).
    const status: Status = !run ? "not_run" : output ? run.status : run.input_count ? "success" : run.status;
    return {
      previous: null,
      isGroup: false,
      label: output ? "What came out" : "What came in",
      description: output ? (map.flow.output?.label ?? "The items that made it through") : map.flow.trigger.label,
      status,
      counts: null,
    };
  }
  const group = map.groups.find((g) => g.id === id);
  const step = map.steps.find((s) => s.id === id);
  const counts: (Counts & { failed_step?: string | null }) | null = group
    ? (run?.groups[id] ?? null)
    : (run?.nodes[id] ?? null);
  const previous: PrevCounts | null = (group ? run?.previous?.groups[id] : run?.previous?.nodes[id]) ?? null;
  return {
    previous,
    isGroup: !!group,
    label: group?.label ?? step?.label ?? id,
    description: group?.description ?? step?.description ?? "",
    status: (counts?.status ?? "not_run") as Status,
    counts,
  };
}

export function FlowCanvas(props: Props) {
  return (
    <div className="size-full">
    <ReactFlowProvider key={props.levelId}>
      <div
        className={cn(
          "size-full animate-in fade-in duration-300",
          props.direction === "in" ? "zoom-in-90" : "zoom-out-110",
        )}
      >
        <LevelView {...props} />
      </div>
    </ReactFlowProvider>
    </div>
  );
}

/** Below this zoom the text gets too small to read; the map then scrolls sideways instead of shrinking. */
const MIN_READABLE_ZOOM = 0.6;

function LevelView({ map, run, levelId, selectedId, onSelect, onOpen, onGoTo, topInset = 0 }: Props) {
  const level = map.levels[levelId];
  const wrapper = useRef<HTMLDivElement>(null);
  const { fitView, setViewport } = useReactFlow();
  const paddingRef = useRef(fitPadding(topInset));
  paddingRef.current = fitPadding(topInset);
  const nodesRef = useRef<Node[]>([]);
  const fitRef = useRef<() => void>(() => {});

  /** Fit the whole flow; if that would make the text too small, keep a readable zoom, start at the left and scroll sideways. */
  const fit = useCallback(
    (duration = 200) => {
      const el = wrapper.current;
      const placed = nodesRef.current;
      if (!el || !placed.length) {
        fitView({ padding: paddingRef.current, maxZoom: 1.15, duration });
        return;
      }
      const box = placed.map((n) => ({ ...n.position, ...sizeOf(n) }));
      const left = Math.min(...box.map((b) => b.x));
      const top = Math.min(...box.map((b) => b.y));
      const width = Math.max(...box.map((b) => b.x + b.width)) - left;
      const height = Math.max(...box.map((b) => b.y + b.height)) - top;
      const usableH = el.clientHeight - topInset - 32;
      const readable = el.clientWidth < 600 ? 0.85 : MIN_READABLE_ZOOM; // phones: bigger text, scroll sideways
      const fitsAll = Math.min((el.clientWidth * 0.92) / width, (usableH * 0.9) / height, 1.15);
      if (fitsAll >= readable) {
        fitView({ padding: paddingRef.current, maxZoom: 1.15, duration });
        return;
      }
      const zoom = Math.min(readable, (usableH * 0.9) / height);
      setViewport(
        { x: 16 - left * zoom, y: topInset + 16 + Math.max(0, (usableH - height * zoom) / 2) - top * zoom, zoom },
        { duration },
      );
    },
    [fitView, setViewport, topInset],
  );
  fitRef.current = () => fit();

  // Re-fit when the overlay at the top grows or shrinks, or the layout turns.
  useEffect(() => {
    const t = window.setTimeout(() => fit(), 30);
    return () => window.clearTimeout(t);
  }, [fit]);

  // Keep the whole level in view when the panel below opens/closes or the window resizes.
  useEffect(() => {
    const el = wrapper.current;
    if (!el) return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => fitRef.current());
    });
    observer.observe(el);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, []);

  const { nodes, edges } = useMemo(() => {
    if (!level) return { nodes: [] as Node[], edges: [] as Edge[] };
    const nodes: Node[] = level.children.map((id) => {
      const info = nodeInfo(map, run, id);
      const inner = map.levels[id]?.children ?? [];
      let failedChildLabel: string | null = null;
      if (info.isGroup && info.status === "failed") {
        const failedChild = inner.find((c) => nodeInfo(map, run, c).status === "failed");
        failedChildLabel = failedChild ? nodeInfo(map, run, failedChild).label : null;
      }
      const data: FlowNodeData = {
        apps: appsOf(map, id),
        label: info.label,
        description: info.description,
        status: info.status,
        counts: info.counts,
        previous: info.status === "success" ? info.previous : null,
        childCount: info.isGroup ? inner.length : 0,
        failedChildLabel,
        errorMessage: !info.isGroup ? run?.nodes[id]?.error?.message : null,
        onOpen: info.isGroup ? () => onOpen(id) : undefined,
      };
      const aria = [info.label, info.status.replace("_", " "), inner.length ? `contains ${inner.length} steps, press Enter twice to open` : ""]
        .filter(Boolean)
        .join(", ");
      return { id, type: "flow", data, position: { x: 0, y: 0 }, selected: id === selectedId, ariaLabel: aria };
    });
    const edges: Edge[] = level.edges.map((e) => edgeFor(e.source, e.target, map, run));

    if (levelId === "root" && map.flow) {
      const terms = map.flow.terms;
      nodes.unshift({
        id: INPUT_ID,
        type: "trigger",
        position: { x: 0, y: 0 },
        selected: selectedId === INPUT_ID,
        ariaLabel: `Starts when: ${map.flow.trigger.label}. Click to see what came in`,
        data: { trigger: map.flow.trigger, nextRun: map.flow.next_run, enabled: map.flow.enabled,
                count: run?.input_count ?? null, items: (map.flow.input_terms ?? terms).items, item: (map.flow.input_terms ?? terms).item },
      });
      nodes.push({
        id: OUTPUT_ID,
        type: "result",
        position: { x: 0, y: 0 },
        selected: selectedId === OUTPUT_ID,
        ariaLabel: `Result: ${map.flow.output?.label ?? ""}. Click to see what came out`,
        data: { label: map.flow.output?.label ?? `The ${terms.items} that made it through`, status: nodeInfo(map, run, OUTPUT_ID).status,
                count: run?.output_count ?? null, items: terms.items, item: terms.item },
      });
      const targets = new Set(level.edges.map((e) => e.target));
      const sources = new Set(level.edges.map((e) => e.source));
      for (const c of level.children.filter((c) => !targets.has(c)))
        edges.unshift({ ...edgeFor(INPUT_ID, c, map, run), style: { stroke: "var(--input)", strokeWidth: 1.25, strokeDasharray: "4 4" } });
      const ends = level.edges.length ? level.children.filter((c) => !sources.has(c)) : level.children.slice(-1);
      for (const c of ends) edges.push(edgeFor(c, OUTPUT_ID, map, run));
    }

    for (const b of level.inbound) {
      const id = `in:${b.from}`;
      if (!nodes.some((n) => n.id === id))
        nodes.push({
          id,
          type: "boundary",
          position: { x: 0, y: 0 },
          ariaLabel: `Comes from ${nodeInfo(map, run, b.from).label}`,
          data: { label: nodeInfo(map, run, b.from).label, direction: "in", onOpen: () => onGoTo(b.from) },
        });
      edges.push(dashed(edgeFor(id, b.target, map, run)));
    }
    for (const b of level.outbound) {
      const id = `out:${b.to}`;
      if (!nodes.some((n) => n.id === id))
        nodes.push({
          id,
          type: "boundary",
          position: { x: 0, y: 0 },
          ariaLabel: `Goes to ${nodeInfo(map, run, b.to).label}`,
          data: { label: nodeInfo(map, run, b.to).label, direction: "out", onOpen: () => onGoTo(b.to) },
        });
      edges.push(dashed(edgeFor(b.source, id, map, run)));
    }
    // Nothing connected yet (e.g. a flow still being built): lay the boxes out in order, left to right.
    const layoutEdges = level.edges.length
      ? edges
      : [...edges, ...level.children.slice(1).map((c, i) => ({ id: `order:${i}`, source: level.children[i], target: c }))];
    const laidOut = layout(nodes, layoutEdges);
    nodesRef.current = laidOut;
    return { nodes: laidOut, edges };
  }, [level, map, run, selectedId, onOpen, onGoTo]);

  if (!level) return <div className="p-8 text-muted-foreground">This part of the map no longer exists.</div>;

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const id = (document.activeElement as HTMLElement | null)?.closest(".react-flow__node")?.getAttribute("data-id");
    const node = nodes.find((n) => n.id === id);
    if (!node) return;
    e.preventDefault();
    if (node.type === "boundary") (node.data as { onOpen?: () => void }).onOpen?.();
    else if (node.type === "trigger" || node.type === "result") onSelect(node.id);
    else if (e.key === "Enter" && (node.data as FlowNodeData).childCount > 0 && selectedId === node.id) onOpen(node.id);
    else onSelect(node.id);
  };

  return (
    <div ref={wrapper} className="size-full" onKeyDown={onKeyDown}>
    <Canvas
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      nodesDraggable={false}
      nodesConnectable={false}
      deleteKeyCode={null}
      panOnDrag
      selectionOnDrag={false}
      fitView
      fitViewOptions={{ padding: fitPadding(topInset), maxZoom: 1.15 }}
      minZoom={0.2}
      proOptions={{ hideAttribution: true }}
      onNodeClick={(_, n) => (n.type === "flow" || n.type === "trigger" || n.type === "result") && onSelect(n.id)}
      onNodeDoubleClick={(_, n) => {
        if (n.type === "flow" && (n.data as FlowNodeData).childCount > 0) onOpen(n.id);
      }}
      onPaneClick={() => onSelect(null)}
    >
    </Canvas>
    </div>
  );
}

function edgeFor(source: string, target: string, map: FlowMap, run: Run | null): Edge {
  const s = source.includes(":") ? "success" : nodeInfo(map, run, source).status;
  const t = target.includes(":") ? "not_run" : nodeInfo(map, run, target).status;
  const flowed = s === "success";
  const color = t === "failed" ? "var(--color-red-400)" : flowed ? "var(--muted-foreground)" : "var(--input)";
  return {
    id: `${source}->${target}`,
    source,
    target,
    type: "step",
    animated: t === "running",
    markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
    style: { stroke: color, strokeWidth: 1.25 },
  };
}

/** Apps used by a step, or by all steps inside a group. */
function appsOf(map: FlowMap, id: string): string[] {
  const step = map.steps.find((s) => s.id === id);
  if (step) return step.app ? [step.app] : [];
  const parent = new Map<string, string | null>();
  for (const g of map.groups) parent.set(g.id, g.parent);
  const inside = (groupId: string | null): boolean => {
    for (let cur = groupId, i = 0; cur && i < 10; cur = parent.get(cur) ?? null, i++) if (cur === id) return true;
    return false;
  };
  return [...new Set(map.steps.filter((s) => inside(s.group)).map((s) => s.app).filter((a): a is string => !!a))];
}

function dashed(e: Edge): Edge {
  return { ...e, style: { ...e.style, strokeDasharray: "5 5" } };
}

function fitPadding(topInset: number) {
  return { top: `${Math.round(topInset + 16)}px`, bottom: "6%", x: "4%" } as const;
}
