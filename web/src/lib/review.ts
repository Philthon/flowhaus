import type { Checkup, ReviewItem } from "./api";

/** The Review's two tabs: what's wrong, and how to make it better. */
export const errorsOf = (r: Checkup): ReviewItem[] => [...r.fix_now, ...r.silent, ...r.drift];
export const improvementsOf = (r: Checkup): ReviewItem[] => [...r.ideas, ...r.setup];

/**
 * What the Review button shows: the worst open error (red for P0, yellow for anything else), or a light bulb when
 * there are only improvements. `critical` is the first P0, which also turns Run red.
 */
export function reviewSignal(r: Checkup | null) {
  if (!r) return { tone: "none" as const, count: 0, critical: undefined };
  const errors = errorsOf(r);
  const critical = errors.find((i) => i.priority === "P0");
  const tone = critical ? ("error" as const) : errors.length ? ("warn" as const) : r.improvements ? ("idea" as const) : ("none" as const);
  return { tone, count: errors.length || r.improvements, critical };
}
