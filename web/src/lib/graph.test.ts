import { describe, expect, it } from "vitest";

import { loopEdges } from "./graph";

describe("lines that loop back", () => {
  it("finds the line back to an earlier step, and only that one", () => {
    const edges = [
      { source: "find", target: "check" },
      { source: "check", target: "copy" },
      { source: "check", target: "wait" },
      { source: "wait", target: "check" }, // try again
    ];
    expect([...loopEdges(["find", "check", "wait", "copy"], edges)]).toEqual(["wait->check"]);
  });

  it("finds none in a map without loops, however it branches", () => {
    const edges = [
      { source: "a", target: "b" },
      { source: "a", target: "c" },
      { source: "b", target: "d" },
      { source: "c", target: "d" },
    ];
    expect(loopEdges(["a", "b", "c", "d"], edges).size).toBe(0);
  });

  it("handles a map that is one big loop", () => {
    const edges = [
      { source: "a", target: "b" },
      { source: "b", target: "a" },
    ];
    expect(loopEdges(["a", "b"], edges).size).toBe(1);
  });
});
