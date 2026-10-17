import type { Edge, Node } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { NODE_HEIGHT, isChoice, layout, sizeOf } from "./layout";

const box = (id: string, label = id): Node => ({ id, type: "flow", position: { x: 0, y: 0 }, data: { label, description: "", status: "success" } });
const decision = (id: string, answers: number): Node => ({
  id,
  type: "decision",
  position: { x: 0, y: 0 },
  data: { label: "Which way?", description: "", status: "success", answers },
});
const line = (source: string, target: string, label?: string): Edge => ({ id: `${source}->${target}`, source, target, data: { label } });

describe("sizes", () => {
  it("grows a box to fit long text", () => {
    const short = sizeOf(box("a", "Find"));
    const long = sizeOf({ ...box("a"), data: { label: "Find", description: "word ".repeat(60), status: "success" } });
    expect(short.height).toBe(NODE_HEIGHT);
    expect(long.height).toBeGreaterThan(short.height);
  });

  it("makes a decision with three or more answers a choice, tall enough for one line per answer", () => {
    expect(isChoice(decision("d", 2))).toBe(false);
    expect(isChoice(decision("d", 3))).toBe(true);
    expect(sizeOf(decision("d", 6)).height).toBeGreaterThan(sizeOf(decision("d", 3)).height);
  });
});

describe("layout", () => {
  it("sends a choice's answers out of its flat right edge, top to bottom in the order they're checked", async () => {
    const nodes = [decision("d", 3), box("x"), box("y"), box("z")];
    const edges = [line("d", "x", "1. One"), line("d", "y", "2. Two"), line("d", "z", "Otherwise")];
    const out = await layout(nodes, edges);
    const d = out.nodes.find((n) => n.id === "d")!;
    const { width } = sizeOf(d);
    const starts = out.edges.map((e) => (e.data as { points: { x: number; y: number }[] }).points[0]);
    for (const p of starts) expect(p.x).toBeCloseTo(d.position.x + width, 0);
    expect(starts[0].y).toBeLessThan(starts[1].y);
    expect(starts[1].y).toBeLessThan(starts[2].y);
  });

  it("sends a yes/no decision's second answer out of the bottom tip", async () => {
    const out = await layout([decision("d", 2), box("yes"), box("no")], [line("d", "yes", "Yes"), line("d", "no", "No")]);
    const d = out.nodes.find((n) => n.id === "d")!;
    const { width, height } = sizeOf(d);
    const [yes, no] = out.edges.map((e) => (e.data as { points: { x: number; y: number }[] }).points[0]);
    expect(yes.x).toBeCloseTo(d.position.x + width, 0);
    expect(no.y).toBeCloseTo(d.position.y + height, 0);
  });
});
