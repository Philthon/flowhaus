import type { Edge, Node } from "@xyflow/react";
import type { ElkExtendedEdge, ElkNode } from "elkjs/lib/elk-api";

export const NODE_WIDTH = 228;
export const NODE_HEIGHT = 156;
export const BOUNDARY_WIDTH = 132;
export const BOUNDARY_HEIGHT = 64;

/** Where a routed line goes (from ELK), and where its label sits. */
export type RoutedEdgeData = {
  points?: { x: number; y: number }[];
  label?: string | null;
  when?: string | null;
  labelAt?: { x: number; y: number } | null;
};

// ---------------------------------------------------------------------------- text-fitted sizes
//
// Every shape is sized so all of its text fits, measured with the real font. The same sizes are used to draw the
// shapes and to lay out the map, so lines meet each shape exactly. Boxes and pills share one width and a minimum
// height, so a map of short labels still lines up evenly.

let ctx: CanvasRenderingContext2D | null | undefined;
const FONT = '"Jost Variable", "Futura", "Century Gothic", sans-serif';

function textWidth(text: string, px: number, weight: number): number {
  if (ctx === undefined) ctx = typeof document === "undefined" ? null : document.createElement("canvas").getContext("2d");
  if (!ctx) return text.length * px * 0.55;
  ctx.font = `${weight} ${px}px ${FONT}`;
  return ctx.measureText(text).width;
}

/** How many lines `text` wraps to in `width` pixels (word by word, like the browser). */
export function linesFor(text: string | null | undefined, px: number, width: number, weight = 400): number {
  const words = (text ?? "").split(/\s+/).filter(Boolean);
  if (!words.length) return 0;
  const space = textWidth(" ", px, weight);
  let lines = 1;
  let used = 0;
  for (const w of words) {
    const ww = textWidth(w, px, weight);
    if (used && used + space + ww > width) {
      lines += 1;
      used = 0;
    }
    if (ww > width) {
      lines += Math.floor(ww / width); // a very long word breaks across lines
      used = ww % width;
    } else used = used ? used + space + ww : ww;
  }
  return lines;
}

type Text = { label?: string; description?: string; status?: string; childCount?: number; trigger?: { label?: string };
              failedChildLabel?: string | null; errorMessage?: string | null; answers?: number };

/** A decision with three or more answers is a choice: pointed on the left, a flat right edge with one exit per answer. */
export const isChoice = (n: Pick<Node, "type" | "data">) => n.type === "decision" && ((n.data as Text | undefined)?.answers ?? 0) > 2;
export const CHOICE_POINT = 26;

const PILL_MIN = 132;

export function sizeOf(n: Pick<Node, "type" | "data">) {
  const d = (n.data ?? {}) as Text;
  switch (n.type) {
    case "boundary":
      return { width: BOUNDARY_WIDTH, height: BOUNDARY_HEIGHT };
    case "trigger":
    case "result":
    case "end": {
      // caption + label (+ a count line), inside a pill with 40px sides
      const label = n.type === "trigger" ? d.trigger?.label : d.label;
      const lines = linesFor(label, 15, NODE_WIDTH - 84, 500);
      return { width: NODE_WIDTH, height: Math.max(PILL_MIN, 36 + 18 + lines * 19 + (n.type === "end" ? 0 : 20)) };
    }
    case "decision": {
      if (isChoice(n)) {
        // room for the question beside the point, and for each answer's line down the flat right edge
        const lines = linesFor(d.label, 13, 220 - CHOICE_POINT - 34, 500);
        return { width: 220, height: Math.max(124, (d.answers ?? 3) * 34 + 20, 36 + lines * 17 + 24) };
      }
      // the question must fit inside the diamond (its inner rectangle is half as wide and half as high)
      let width = 200;
      let height = 124;
      for (let i = 0; i < 12; i++) {
        const lines = linesFor(d.label, 12.5, width / 2 - 6, 500);
        if (14 + lines * 16 <= height / 2) break;
        width += 24;
        height += 18;
      }
      return { width, height };
    }
    case "goto":
      // a small marker: "Go to" + the box it goes back to
      return { width: 168, height: Math.max(48, 26 + linesFor(d.label, 12.5, 168 - 44, 500) * 16) };
    case "wait": {
      const label = linesFor(d.label, 14, NODE_WIDTH - 60, 500);
      const desc = linesFor(d.description, 12, NODE_WIDTH - 60);
      return { width: NODE_WIDTH, height: Math.max(NODE_HEIGHT, 24 + 16 + label * 18 + desc * 17 + 20 + 12) };
    }
  }
  // a step box: header (title), content (description, and "Failed in …" when it failed), footer (counts)
  const title = linesFor(d.label, 15, NODE_WIDTH - 24 - 18 - (d.childCount ? 24 : 0), 500);
  const desc = linesFor(d.description, 13, NODE_WIDTH - 24);
  const failed = d.status === "failed" && (d.failedChildLabel || d.errorMessage);
  const failure = failed ? 10 + 16 * Math.min(4, linesFor(d.failedChildLabel ? `Failed in ${d.failedChildLabel}` : d.errorMessage, 12, NODE_WIDTH - 60)) + 8 : 0;
  return { width: NODE_WIDTH, height: Math.max(NODE_HEIGHT, 84 + title * 19 + desc * 18 + failure) };
}

let elk: Promise<{ layout: (g: ElkNode) => Promise<ElkNode> }> | null = null;

/** ELK is big: load it the first time a map is drawn, not with the app. */
function engine() {
  elk ??= import("elkjs/lib/elk.bundled.js").then((m) => new m.default());
  return elk;
}

const LABEL_HEIGHT = 18;
// a line's label: 11px medium text, 6px padding each side and a hairline border (see RoutedEdge)
const labelWidth = (text: string) => Math.ceil(textWidth(text, 11, 500)) + 14;

/**
 * Lay out one level of the map as a flowchart, left to right:
 * - every box has one way in (left, middle) and one way out (right, middle), so lines meet shapes cleanly;
 * - lines are routed at right angles around the boxes (no curves, no lines through boxes);
 * - the order in the config is kept where possible, so the main path stays a straight line and branches sit beside it;
 * - branch labels ("Yes", "No") get their own space next to where the line leaves the decision.
 */
export async function layout(nodes: Node[], edges: Edge[]): Promise<{ nodes: Node[]; edges: Edge[] }> {
  const ELK = await engine();
  if (typeof document !== "undefined") await document.fonts?.ready; // measure text with the real font, not the fallback
  // the nth answer of a decision, in config order: picks which tip of the diamond its line leaves from
  const decisions = new Set(nodes.filter((n) => n.type === "decision").map((n) => n.id));
  const choices = new Set(nodes.filter(isChoice).map((n) => n.id));
  const exitIndex = new Map<string, number>();
  const answers = new Map<string, number>();
  for (const e of edges)
    if (decisions.has(e.source)) {
      const k = answers.get(e.source) ?? 0;
      exitIndex.set(e.id, k);
      answers.set(e.source, k + 1);
    }
  const graph: ElkNode = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
      "elk.layered.nodePlacement.favorStraightEdges": "true",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
      "elk.layered.crossingMinimization.semiInteractive": "true",
      "elk.layered.spacing.nodeNodeBetweenLayers": "64",
      "elk.spacing.nodeNode": "40",
      "elk.spacing.edgeNode": "24",
      "elk.spacing.edgeEdge": "16",
      "elk.layered.spacing.edgeNodeBetweenLayers": "24",
      "elk.spacing.edgeLabel": "4",
      "elk.edgeLabels.inline": "false",
      "elk.padding": "[top=8,left=8,bottom=8,right=8]",
    },
    children: nodes.map((n) => {
      const { width, height } = sizeOf(n);
      const port = (id: string, x: number, y: number, side: string) => ({ id, x, y, width: 0, height: 0, layoutOptions: { "elk.port.side": side } });
      const ports = [port(`${n.id}::in`, 0, height / 2, "WEST"), port(`${n.id}::out0`, width, height / 2, "EAST")];
      if (isChoice(n)) {
        // a choice: every answer leaves from the flat right edge, top to bottom in the order they're checked
        const k = (n.data as Text).answers ?? 3;
        ports.splice(1, 1, ...Array.from({ length: k }, (_, i) => port(`${n.id}::out${i}`, width, (height * (i + 1)) / (k + 1), "EAST")));
      } else if (n.type === "decision")
        // a decision's answers leave from different tips: the first straight on, the second down, a third up
        ports.push(port(`${n.id}::out1`, width / 2, height, "SOUTH"), port(`${n.id}::out2`, width / 2, 0, "NORTH"));
      return { id: n.id, width, height, layoutOptions: { "elk.portConstraints": "FIXED_POS" }, ports };
    }),
    edges: edges.map((e) => {
      const label = (e.data as RoutedEdgeData | undefined)?.label;
      return {
        id: e.id,
        sources: [`${e.source}::out${choices.has(e.source) ? (exitIndex.get(e.id) ?? 0) : Math.min(exitIndex.get(e.id) ?? 0, 2)}`],
        targets: [`${e.target}::in`],
        labels: label
          ? [{ id: `${e.id}::label`, text: label, width: labelWidth(label), height: LABEL_HEIGHT,
               layoutOptions: { "elk.edgeLabels.placement": "TAIL" } }]
          : [],
      };
    }),
  };
  const out = await ELK.layout(graph);
  const placed = new Map((out.children ?? []).map((c) => [c.id, c]));
  const routes = new Map((out.edges ?? []).map((e) => [e.id, e]));
  return {
    nodes: nodes.map((n) => {
      const p = placed.get(n.id);
      const { width, height } = sizeOf(n);
      // initialWidth/Height: render and fit right away, before the browser has measured the box
      return { ...n, position: { x: p?.x ?? 0, y: p?.y ?? 0 }, initialWidth: width, initialHeight: height };
    }),
    edges: edges.map((e) => {
      const r = routes.get(e.id) as ElkExtendedEdge | undefined;
      const s = r?.sections?.[0];
      const lab = r?.labels?.[0];
      const data: RoutedEdgeData = {
        ...(e.data as RoutedEdgeData | undefined),
        points: s ? [s.startPoint, ...(s.bendPoints ?? []), s.endPoint] : undefined,
        labelAt: lab && lab.x != null && lab.y != null ? { x: lab.x + (lab.width ?? 0) / 2, y: lab.y + (lab.height ?? 0) / 2 } : null,
      };
      return { ...e, type: "routed", data };
    }),
  };
}
