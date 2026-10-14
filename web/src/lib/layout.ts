import dagre from "@dagrejs/dagre";
import type { Edge, Node } from "@xyflow/react";

export const NODE_WIDTH = 228;
export const NODE_HEIGHT = 156;
export const BOUNDARY_WIDTH = 132;
export const BOUNDARY_HEIGHT = 64;

/** Dagre layout for one level of the map: left-to-right, or top-to-bottom on narrow screens. */
export function layout(nodes: Node[], edges: Edge[], vertical = false): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: vertical ? "TB" : "LR", nodesep: 32, ranksep: vertical ? 28 : 36, marginx: 8, marginy: 8 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of nodes) g.setNode(n.id, sizeOf(n));
  for (const e of edges) g.setEdge(e.source, e.target);
  dagre.layout(g);
  return nodes.map((n) => {
    const p = g.node(n.id);
    const { width: w, height: h } = sizeOf(n);
    // initialWidth/Height: render and fit right away, before the browser has measured the box
    return { ...n, position: { x: p.x - w / 2, y: p.y - h / 2 }, initialWidth: w, initialHeight: h };
  });
}

export function sizeOf(n: Node) {
  if (n.type === "boundary") return { width: BOUNDARY_WIDTH, height: BOUNDARY_HEIGHT };
  if (n.type === "trigger" || n.type === "result") return { width: 160, height: 80 };
  // a failed box shows an extra "Failed in …" line
  const failed = (n.data as { status?: string } | undefined)?.status === "failed";
  return { width: NODE_WIDTH, height: NODE_HEIGHT + (failed ? 36 : 0) };
}
