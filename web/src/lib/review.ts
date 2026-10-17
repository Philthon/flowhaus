import type { Checkup, ReviewItem } from "./api";

/** The Review's Errors tab: what's wrong. (The server counts both tabs: `errors`, `improvements`.) */
const errorsOf = (r: Checkup): ReviewItem[] => [...r.fix_now, ...r.silent, ...r.drift];

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

type Priority = ReviewItem["priority"];

/** The colours of urgency, in one place so the button, the bar above the map and the Review always agree. */
export const SIGNAL_COLOR: Record<ReturnType<typeof reviewSignal>["tone"], string> = {
  error: "text-red-600",
  warn: "text-amber-500",
  idea: "text-amber-500",
  none: "",
};
/** The bar above the map, by the priority of what it shows. */
export const PRIORITY_BANNER: Record<Priority, string> = {
  P0: "tone-error",
  P1: "tone-warn",
  P2: "border-border bg-card text-foreground",
  P3: "border-border bg-card text-foreground",
};
/** An item in the Review: the line on its left, and its P0..P3 chip (the text says it too, not only the colour). */
export const PRIORITY_BAR: Record<Priority, string> = { P0: "border-red-500", P1: "border-amber-500", P2: "border-border", P3: "border-border" };
export const PRIORITY_CHIP: Record<Priority, string> = {
  P0: "border-red-500 text-red-700 dark:text-red-300",
  P1: "border-amber-500 text-amber-800 dark:text-amber-300",
  P2: "border-border text-muted-foreground",
  P3: "border-border text-muted-foreground",
};
