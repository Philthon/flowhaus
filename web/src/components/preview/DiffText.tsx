import { diffChars } from "diff";
import { Fragment } from "react";

import { cn } from "@/lib/utils";

const INVISIBLE: Record<string, string> = {
  "​": "zero-width space",
  "‌": "zero-width non-joiner",
  "‍": "zero-width joiner",
  "⁠": "word joiner",
  "﻿": "byte order mark",
};

/** Render text so that invisible characters and edge spaces can be seen. */
function Visible({ text, highlight }: { text: string; highlight: boolean }) {
  const parts: React.ReactNode[] = [];
  let buf = "";
  const flush = () => {
    if (buf) parts.push(buf);
    buf = "";
  };
  for (const ch of text) {
    if (INVISIBLE[ch]) {
      flush();
      parts.push(
        <span
          key={parts.length}
          title={INVISIBLE[ch]}
          className="mx-px rounded-sm bg-fuchsia-200 px-0.5 font-mono text-[9px] text-fuchsia-900 align-middle dark:bg-fuchsia-900 dark:text-fuchsia-100"
        >
          ZW
        </span>,
      );
    } else if (ch === " " && highlight) {
      flush();
      parts.push(
        <span key={parts.length} title="space" className="text-current opacity-70">
          ·
        </span>,
      );
    } else buf += ch;
  }
  flush();
  return <>{parts}</>;
}

/** One side of a before/after pair, with the characters that differ highlighted. */
export function DiffText({ before, after, side }: { before: string; after: string; side: "before" | "after" }) {
  if (before === after) return <Visible text={side === "before" ? before : after} highlight={false} />;
  const parts = diffChars(before, after);
  return (
    <>
      {parts.map((p, i) => {
        if (side === "before" && p.added) return null;
        if (side === "after" && p.removed) return null;
        const changed = p.added || p.removed;
        return (
          <Fragment key={i}>
            {changed ? (
              <mark
                className={cn(
                  "rounded-sm px-px",
                  p.removed
                    ? "bg-red-200/80 text-red-950 line-through decoration-red-500/60 dark:bg-red-900/70 dark:text-red-50"
                    : "bg-emerald-200/80 text-emerald-950 dark:bg-emerald-900/70 dark:text-emerald-50",
                )}
              >
                <Visible text={p.value} highlight />
              </mark>
            ) : (
              <Visible text={p.value} highlight={false} />
            )}
          </Fragment>
        );
      })}
    </>
  );
}
