import { describe, expect, it } from "vitest";

import type { Checkup, ReviewItem } from "./api";
import { reviewSignal } from "./review";

const item = (priority: ReviewItem["priority"]): ReviewItem =>
  ({ id: priority, source: "insight", priority, level: "warn", title: priority, detail: "", evidence: [] }) as unknown as ReviewItem;
const checkup = (part: Partial<Checkup>): Checkup =>
  ({ fix_now: [], silent: [], drift: [], ideas: [], setup: [], questions: [], improvements: 0, ...part }) as unknown as Checkup;

describe("the Review button", () => {
  it("is red with a critical error, and names it for the Run button", () => {
    const s = reviewSignal(checkup({ fix_now: [item("P0")], drift: [item("P1")] }));
    expect(s.tone).toBe("error");
    expect(s.critical?.priority).toBe("P0");
    expect(s.count).toBe(2);
  });
  it("is yellow with other errors", () => {
    expect(reviewSignal(checkup({ silent: [item("P1")], ideas: [item("P2")], improvements: 1 })).tone).toBe("warn");
  });
  it("is a light bulb with only improvements, counting those", () => {
    const s = reviewSignal(checkup({ setup: [item("P0")], improvements: 3 }));
    expect([s.tone, s.count, s.critical]).toEqual(["idea", 3, undefined]);
  });
  it("is quiet with nothing open", () => {
    expect(reviewSignal(checkup({})).tone).toBe("none");
  });
});
