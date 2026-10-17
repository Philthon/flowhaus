import { MarkerType, ReactFlowProvider, useReactFlow, type Edge, type Node } from "@xyflow/react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { Canvas } from "@/components/ai-elements/canvas";
import type { FlowMap, MapEdge, Run } from "@/lib/api";
import { loopEdges } from "@/lib/graph";
import { layout, sizeOf, type RoutedEdgeData } from "@/lib/layout";
import { cn } from "@/lib/utils";
import { Glance } from "./Glance";
import { INPUT_ID, nodeInfo, OUTPUT_ID } from "@/lib/mapinfo";
import type { FlowNodeData } from "./nodes";
import { edgeTypes, nodeTypes } from "./registry";

type Props = {
  map: FlowMap;
  run: Run | null;
  levelId: string;
  direction: "in" | "out";
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onOpen: (groupId: string) => void;
  onGoTo: (nodeId: string) => void;
  /** While stepping through a run: boxes still to come (drawn faded), and the box to pan to. */
  dimmed?: Set<string> | null;
  focusId?: string | null;
  /** Open the "Test" tab for a box (from the quick view). */
  onTry?: (nodeId: string) => void;
  /** Pixels at the top covered by overlays (mini map); boxes are fitted below them. */
  topInset?: number;
};


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
const MIN_READABLE_ZOOM = 0.85; // smaller than this and the step text gets too small to read: pan instead

function LevelView({ map, run, levelId, selectedId, onSelect, onOpen, onGoTo, onTry, dimmed, focusId, topInset = 0 }: Props) {
  const level = map.levels[levelId];
  const wrapper = useRef<HTMLDivElement>(null);
  const { fitView, setViewport } = useReactFlow();
  const nodesRef = useRef<Node[]>([]);
  const fitRef = useRef<() => void>(() => {});
  const selectedRef = useRef<string | null>(null);
  useLayoutEffect(() => {
    selectedRef.current = selectedId ?? null;
  }, [selectedId]);
  const [cropped, setCropped] = useState(false); // the map is bigger than the screen at a readable size

  /**
   * Fit the whole flow; if that would make the text too small, keep a readable zoom and scroll sideways: centred on
   * the selected box when there is one (coming back out of a box selects it), otherwise from the start.
   */
  const fit = useCallback(
    (duration = 200) => {
      if (document.hidden) duration = 0; // a hidden tab doesn't animate: jump straight there
      const el = wrapper.current;
      const placed = nodesRef.current;
      // nothing laid out yet: wait (the layout fits the map when it's done). Calling React Flow's fitView now would
      // run later, once the shapes appear, and override the readable zoom chosen below.
      if (!el || !placed.length) return;
      const box = placed.map((n) => ({ ...n.position, ...sizeOf(n) }));
      const left = Math.min(...box.map((b) => b.x));
      const top = Math.min(...box.map((b) => b.y));
      const width = Math.max(...box.map((b) => b.x + b.width)) - left;
      const height = Math.max(...box.map((b) => b.y + b.height)) - top;
      const usableH = el.clientHeight - topInset - 32;
      const readable = el.clientWidth < 600 ? 0.85 : MIN_READABLE_ZOOM; // phones: bigger text, scroll sideways
      const fitsAll = Math.min((el.clientWidth * 0.92) / width, (usableH * 0.9) / height, 1.15);
      setCropped(fitsAll < readable);
      if (fitsAll >= readable) {
        fitView({ padding: fitPadding(topInset), maxZoom: 1.15, duration });
        return;
      }
      const zoom = Math.min(readable, (usableH * 0.9) / height);
      let x = 16 - left * zoom; // the start of the flow at the left edge
      const keep = placed.find((n) => n.id === selectedRef.current);
      if (keep) {
        const centred = el.clientWidth / 2 - (keep.position.x + sizeOf(keep).width / 2) * zoom;
        const end = el.clientWidth - 16 - (left + width) * zoom; // not past the end of the flow
        x = Math.min(x, Math.max(end, centred));
      }
      setViewport({ x, y: topInset + 16 + Math.max(0, (usableH - height * zoom) / 2) - top * zoom, zoom }, { duration });
    },
    [fitView, setViewport, topInset],
  );
  useLayoutEffect(() => {
    fitRef.current = () => fit();
  }, [fit]);

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

  const structure = useMemo(() => {
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
        // every line leaving the decision gets an exit, including an answer that leads out of this box
        answers: info.kind === "decision"
          ? level.edges.filter((e) => e.source === id).length + level.outbound.filter((b) => b.source === id).length
          : undefined,
      };
      const aria = [info.label, info.status.replace("_", " "), inner.length ? `contains ${inner.length} steps, press Enter twice to open` : ""]
        .filter(Boolean)
        .join(", ");
      const type = info.kind === "action" ? "flow" : info.kind;
      return { id, type, data, position: { x: 0, y: 0 }, ariaLabel: `${info.kind === "action" ? "" : info.kind + ": "}${aria}` };
    });
    // A line back to an earlier box (a loop: "try again") becomes a "Go to" marker next to where it leaves, so lines
    // never run backwards across the map. Clicking the marker selects the box it goes to.
    const loops = loopEdges(level.children, level.edges);
    const edges: Edge[] = level.edges.map((e) => {
      const edge = edgeFor(e.source, e.target, map, run, e);
      if (!loops.has(`${e.source}->${e.target}`)) return edge;
      const id = `goto:${e.source}:${e.target}`;
      nodes.push({
        id,
        type: "goto",
        position: { x: 0, y: 0 },
        ariaLabel: `Goes back to ${nodeInfo(map, run, e.target).label}. Click to show it`,
        data: { label: nodeInfo(map, run, e.target).label, target: e.target, status: nodeInfo(map, run, e.source).status === "success" ? "success" : "not_run" },
      });
      return { ...edge, id: `${edge.id}:goto`, target: id };
    });

    if (levelId === "root" && map.flow) {
      const terms = map.flow.terms;
      nodes.unshift({
        id: INPUT_ID,
        type: "trigger",
        position: { x: 0, y: 0 },
        ariaLabel: `Starts when: ${map.flow.trigger.label}. Click to see what came in`,
        data: { trigger: map.flow.trigger, nextRun: map.flow.next_run, enabled: map.flow.enabled,
                count: run?.input_count ?? null, items: (map.flow.input_terms ?? terms).items, item: (map.flow.input_terms ?? terms).item },
      });
      const targets = new Set(level.edges.map((e) => e.target));
      const sources = new Set(level.edges.map((e) => e.source));
      const isEnd = (c: string) => nodeInfo(map, run, c).kind === "end";
      for (const c of level.children.filter((c) => !targets.has(c) && !isEnd(c)))
        edges.unshift({ ...edgeFor(INPUT_ID, c, map, run), style: { stroke: "var(--input)", strokeWidth: 1.25, strokeDasharray: "4 4" } });
      // paths that don't finish in an end of their own finish at the flow's result
      const open = level.edges.length ? level.children.filter((c) => !sources.has(c) && !isEnd(c)) : level.children.slice(-1);
      if (open.length || !level.children.some(isEnd)) {
        nodes.push({
          id: OUTPUT_ID,
          type: "result",
          position: { x: 0, y: 0 },
          ariaLabel: `End, result: ${map.flow.output?.label ?? ""}. Click to see what came out`,
          data: { label: map.flow.output?.label ?? `The ${terms.items} that made it through`, status: nodeInfo(map, run, OUTPUT_ID).status,
                  count: run?.output_count ?? null, items: terms.items, item: terms.item },
        });
        for (const c of open) edges.push(edgeFor(c, OUTPUT_ID, map, run));
      }
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
    if (!level.edges.length)
      for (let i = 1; i < level.children.length; i++)
        edges.push({ id: `order:${i}`, source: level.children[i - 1], target: level.children[i], hidden: true });
    return { nodes, edges };
  }, [level, levelId, map, run, onOpen, onGoTo]);

  // Layout runs in the background (ELK), and only when the shapes, their sizes or the lines change: a new run status
  // or count just updates the shapes where they are. Until a new layout is back, the previous one stays on screen.
  const layoutKey = useMemo(
    () =>
      JSON.stringify([
        structure.nodes.map((n) => [n.id, n.type, sizeOf(n)]),
        structure.edges.map((e) => [e.id, e.source, e.target, (e.data as RoutedEdgeData | undefined)?.label ?? null, !!e.hidden]),
      ]),
    [structure],
  );
  const structureRef = useRef(structure);
  useLayoutEffect(() => {
    structureRef.current = structure; // read by the layout effect below, which runs only when the layout key changes
  }, [structure]);
  const [geometry, setGeometry] = useState<{ nodes: Map<string, Node>; edges: Map<string, Edge> } | null>(null);
  useEffect(() => {
    let live = true;
    const { nodes: n, edges: e } = structureRef.current;
    layout(n, e)
      .then((r) => live && setGeometry({ nodes: new Map(r.nodes.map((x) => [x.id, x])), edges: new Map(r.edges.map((x) => [x.id, x])) }))
      .catch(() => live && setGeometry({ nodes: new Map(n.map((x) => [x.id, x])), edges: new Map(e.map((x) => [x.id, x])) }));
    return () => {
      live = false;
    };
  }, [layoutKey]);
  // the current shapes and lines (status, counts), placed where the last layout put them
  const laid = useMemo(() => {
    if (!geometry) return null;
    const nodes = structure.nodes.map((n) => {
      const g = geometry.nodes.get(n.id);
      return g ? { ...n, position: g.position, initialWidth: g.initialWidth, initialHeight: g.initialHeight } : n;
    });
    const edges = structure.edges.map((e) => {
      const g = geometry.edges.get(e.id);
      return g ? { ...e, type: g.type, data: { ...(e.data as RoutedEdgeData | undefined), ...pick(g.data as RoutedEdgeData) } } : e;
    });
    return { nodes, edges };
  }, [structure, geometry]);
  useEffect(() => {
    if (!geometry) return;
    nodesRef.current = [...geometry.nodes.values()];
    const t = window.setTimeout(() => fitRef.current(), 30);
    return () => window.clearTimeout(t);
  }, [geometry]);
  const nodes = useMemo(
    () =>
      (laid?.nodes ?? []).map((n) => ({
        ...n,
        selected: n.id === selectedId,
        className: dimmed?.has(n.id) ? "opacity-30 transition-opacity" : "transition-opacity",
      })),
    [laid, selectedId, dimmed],
  );

  // Stepping through a run: bring the current box into view (keeping the zoom)
  const { setCenter, getZoom } = useReactFlow();
  useEffect(() => {
    const n = focusId ? (laid?.nodes ?? []).find((x) => x.id === focusId) : null;
    if (!n) return;
    const { width, height } = sizeOf(n);
    setCenter(n.position.x + width / 2, n.position.y + height / 2, { zoom: getZoom(), duration: document.hidden ? 0 : 300 });
  }, [focusId, laid, setCenter, getZoom]);

  // The quick view: after a short pause on a shape (or keyboard focus, or a long press on a touch screen)
  const [glance, setGlance] = useState<{ id: string; x: number; y: number; side: "below" | "above" } | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const glanceEl = useRef<HTMLDivElement>(null);
  const overCard = useRef(false); // is the pointer over the quick view?
  const showGlance = (id: string, el: Element, delay: number) => {
    window.clearTimeout(timer.current);
    if (id.includes(":") || id === INPUT_ID || id === OUTPUT_ID) return; // boundaries, start and result explain themselves
    timer.current = window.setTimeout(() => {
      const box = wrapper.current?.getBoundingClientRect();
      const r = el.getBoundingClientRect();
      if (!box) return;
      // below the shape (the map runs left to right, so that space is usually free), or above it when there's no room
      const CARD_W = 320;
      const CARD_H = 250;
      const x = Math.max(8, Math.min(r.left - box.left, box.width - CARD_W - 8));
      const below = r.bottom - box.top + 10;
      const side = below + CARD_H <= box.height || r.top - box.top < CARD_H ? "below" : "above";
      setGlance({ id, side, x, y: side === "below" ? below : r.top - box.top - 10 });
    }, delay);
  };
  const hideGlance = () => {
    window.clearTimeout(timer.current);
    overCard.current = false;
    setGlance(null);
  };
  // Leaving a shape hides the quick view after a moment, so the pointer can move onto it (it has buttons). While the
  // pointer is over the card it stays: browsers can report "entered the card" before "left the shape", so the hide
  // checks where the pointer is rather than relying on the order of events.
  const leaveSoon = () => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      if (!overCard.current) setGlance(null);
    }, 300);
  };
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const nodeEl = (target: EventTarget | null) => (target as HTMLElement | null)?.closest?.(".react-flow__node") as HTMLElement | null;
  const edges = useMemo(
    () => (laid?.edges ?? []).map((e) => (dimmed?.has(e.target) ? { ...e, style: { ...e.style, opacity: 0.3 } } : e)),
    [laid, dimmed],
  );

  if (!level) return <div className="p-8 text-muted-foreground">This part of the map no longer exists.</div>;

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const id = (document.activeElement as HTMLElement | null)?.closest(".react-flow__node")?.getAttribute("data-id");
    const node = nodes.find((n) => n.id === id);
    if (!node) return;
    e.preventDefault();
    if (node.type === "boundary") (node.data as { onOpen?: () => void }).onOpen?.();
    else if (node.type !== "flow") onSelect(node.id);
    else if (e.key === "Enter" && (node.data as FlowNodeData).childCount > 0 && selectedId === node.id) onOpen(node.id);
    else onSelect(node.id);
  };

  return (
    <div
      ref={wrapper}
      className="relative size-full"
      onKeyDown={onKeyDown}
      onFocusCapture={(e) => {
        const el = nodeEl(e.target);
        if (el?.dataset.id) showGlance(el.dataset.id, el, 0);
      }}
      onBlurCapture={(e) => {
        if (!glanceEl.current?.contains(e.relatedTarget as HTMLElement | null)) hideGlance();
      }}
      onPointerDown={(e) => {
        if (glanceEl.current?.contains(e.target as HTMLElement)) return;
        const el = nodeEl(e.target);
        if (e.pointerType === "touch" && el?.dataset.id) showGlance(el.dataset.id, el, 500); // long press
        else hideGlance();
      }}
      onPointerUp={(e) => e.pointerType === "touch" && window.clearTimeout(timer.current)}
    >
    <Canvas
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      nodesDraggable={false}
      nodesConnectable={false}
      deleteKeyCode={null}
      panOnDrag
      selectionOnDrag={false}
      fitView={false} // Flowhaus fits the map itself (fit below), keeping the text readable
      minZoom={0.2}
      proOptions={{ hideAttribution: true }}
      onNodeClick={(_, n) => {
        if (n.type === "goto") onSelect((n.data as { target: string }).target);
        else if (n.type !== "boundary") onSelect(n.id);
      }}
      onNodeDoubleClick={(_, n) => {
        if (n.type === "flow" && (n.data as FlowNodeData).childCount > 0) onOpen(n.id);
      }}
      onPaneClick={() => onSelect(null)}
      onNodeMouseEnter={(e, n) => n.type !== "boundary" && showGlance(n.id, e.currentTarget as Element, 450)}
      onNodeMouseLeave={leaveSoon}
      onMoveStart={hideGlance}
    >
    </Canvas>
    {cropped && (
      <p className="pointer-events-none absolute right-3 bottom-3 z-10 border border-border bg-background/90 px-2 py-1 text-xs text-muted-foreground">
        Scroll or drag to see the rest of the map
      </p>
    )}
    {glance && (
      <div
        ref={glanceEl}
        className="absolute z-20"
        style={{ left: glance.x, top: glance.y, transform: glance.side === "above" ? "translateY(-100%)" : undefined }}
        role="region"
        aria-label="Quick view"
        onPointerEnter={() => {
          overCard.current = true;
          window.clearTimeout(timer.current);
        }}
        onPointerLeave={() => {
          overCard.current = false;
          leaveSoon();
        }}
      >
        <Glance
          map={map}
          run={run}
          flowId={map.flow.id}
          nodeId={glance.id}
          onTry={onTry ? () => (hideGlance(), onTry(glance.id)) : undefined}
          onOpen={map.levels[glance.id]?.children.length ? () => (hideGlance(), onOpen(glance.id)) : undefined}
        />
      </div>
    )}
    </div>
  );
}

/** Where a line runs (from the layout), without its label or colour (those follow the run). */
function pick(d: RoutedEdgeData | undefined): Pick<RoutedEdgeData, "points" | "labelAt"> {
  return { points: d?.points, labelAt: d?.labelAt };
}

function edgeFor(source: string, target: string, map: FlowMap, run: Run | null, e?: MapEdge): Edge {
  const s = source.includes(":") ? "success" : nodeInfo(map, run, source).status;
  const t = target.includes(":") ? "not_run" : nodeInfo(map, run, target).status;
  // a line is dark when items went along it: its start ran and so did where it leads (a branch not taken stays grey)
  const flowed = s === "success" && (t !== "not_run" || target.includes(":") || target === OUTPUT_ID);
  const color = t === "failed" ? "var(--color-red-400)" : flowed ? "var(--muted-foreground)" : "var(--input)";
  // a choice's answers are numbered in the order they're checked; "Otherwise" catches the rest
  const label = e?.label && e.order && !e.otherwise ? `${e.order}. ${e.label}` : (e?.label ?? null);
  const data: RoutedEdgeData = { label, when: e?.when ?? null };
  return {
    id: `${source}->${target}${e?.label ? `:${e.label}` : ""}`,
    source,
    target,
    type: "routed",
    data,
    animated: t === "running",
    markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
    style: { stroke: color, strokeWidth: flowed ? 1.5 : 1.25 },
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
