import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";

/**
 * The controls for stepping through a recorded run: back, forward, which step you're on. Arrow keys work too.
 * Nothing runs; the map and the panel show what the run recorded at each step.
 */
export function StepThrough({
  labels,
  index,
  onIndex,
  onStop,
}: {
  labels: string[];
  index: number | null;
  onIndex: (i: number) => void;
  onStop: () => void;
}) {
  const playing = index != null;
  useEffect(() => {
    if (!playing) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target instanceof Element ? e.target : null;
      if (t?.closest("input, textarea, select, [contenteditable=true], [role=menu]")) return;
      if (e.key === "ArrowRight" && index < labels.length - 1) onIndex(index + 1);
      else if (e.key === "ArrowLeft" && index > 0) onIndex(index - 1);
      else if (e.key === "Escape") onStop();
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [playing, index, labels.length, onIndex, onStop]);

  if (!playing) return null;
  return (
    <div className="flex items-center gap-1 border border-foreground/25 bg-background p-1 text-sm" role="group" aria-label="Step through this run">
      <Button variant="ghost" size="icon" disabled={index === 0} onClick={() => onIndex(index - 1)} aria-label="Previous step">
        <ChevronLeft />
      </Button>
      <span className="max-w-[min(420px,50vw)] min-w-0 truncate px-1 whitespace-nowrap" aria-live="polite">
        <span className="tabular-nums text-muted-foreground">
          {index + 1} of {labels.length}
        </span>{" "}
        <span className="font-medium">{labels[index]}</span>
      </span>
      <Button variant="ghost" size="icon" disabled={index === labels.length - 1} onClick={() => onIndex(index + 1)} aria-label="Next step">
        <ChevronRight />
      </Button>
      <Button variant="ghost" size="icon" onClick={onStop} aria-label="Stop stepping through">
        <X />
      </Button>
    </div>
  );
}
