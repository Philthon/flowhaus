import type { Status } from "./api";

export const STATUS_LABEL: Record<Status, string> = {
  not_run: "Not run",
  running: "Running",
  success: "Succeeded",
  failed: "Failed",
};

/**
 * Quiet flat status styling: a hairline frame with a thin color band on top.
 * card = frame, header = top band, dot = small circle marker, text = label color.
 */
export const STATUS_STYLE: Record<Status, { card: string; header: string; dot: string; text: string }> = {
  not_run: {
    card: "border-border",
    header: "border-t-[3px] border-t-border bg-card",
    dot: "bg-muted-foreground/40",
    text: "text-muted-foreground",
  },
  running: {
    card: "border-border",
    header: "border-t-[3px] border-t-sky-500 bg-card",
    dot: "bg-sky-500 animate-pulse",
    text: "text-sky-600",
  },
  success: {
    card: "border-border",
    header: "border-t-[3px] border-t-emerald-500 bg-card",
    dot: "bg-emerald-500",
    text: "text-emerald-600",
  },
  failed: {
    card: "border-red-200",
    header: "border-t-[3px] border-t-red-500 bg-card",
    dot: "bg-red-500",
    text: "text-red-600",
  },
};

export function plural(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}
