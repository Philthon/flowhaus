import { describe, expect, it } from "vitest";

import { downstreamOf, loopEdges } from "./graph";

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

describe("what comes after a step", () => {
  it("follows every line onwards, in the steps' order, without the step itself or looping forever", () => {
    const edges = [
      { source: "a", target: "b" },
      { source: "b", target: "c" },
      { source: "b", target: "d" },
      { source: "d", target: "b" },
    ];
    expect(downstreamOf(["a", "b", "c", "d", "e"], edges, ["b"])).toEqual(["c", "d"]);
    expect(downstreamOf(["a", "b", "c", "d", "e"], edges, ["e"])).toEqual([]);
  });
});

