import { describe, expect, it } from "vitest";

import type { FlowMap, Run } from "./api";
import { laterThan, playOrder } from "./playback";

const counts = (status: string) => ({ status, rows_in: 1, rows_out: 1, rows_rejected: 0, rows_changed: 0 });

// listed out of order on purpose: the order comes from the lines, not the list
const map = {
  groups: [
    { id: "g", label: "G", description: "", parent: null },
    { id: "g2", label: "G2", description: "", parent: "g" },
  ],
  steps: [
    { id: "c", group: null },
    { id: "a", group: null },
    { id: "skipped_path", group: null },
    { id: "s1", group: "g2" },
  ],
  levels: {
    root: {
      children: ["c", "g", "a", "skipped_path"],
      edges: [
        { source: "a", target: "g" },
        { source: "g", target: "c" },
        { source: "a", target: "skipped_path" },
      ],
      inbound: [],
      outbound: [],
    },
  },
} as unknown as FlowMap;

const run = {
  nodes: { a: counts("success"), c: counts("success"), skipped_path: counts("not_run"), s1: counts("success") },
  groups: { g: counts("success"), g2: counts("success") },
} as unknown as Run;

describe("stepping through a run", () => {
  it("goes through the boxes in the order items went, leaving out the path not taken", () => {
    expect(playOrder(map, run, "root")).toEqual(["a", "g", "c"]);
  });

  it("has nothing to step through without a run", () => {
    expect(playOrder(map, null, "root")).toEqual([]);
  });

  it("dims what is still to come, including everything inside a box", () => {
    const order = playOrder(map, run, "root");
    expect([...laterThan(map, order, 0)].sort()).toEqual(["c", "g", "g2", "s1"]);
    expect(laterThan(map, order, order.length - 1).size).toBe(0);
  });
});
