import { ArrowLeft, ChevronDown, Network } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import type { FlowMap, Run } from "@/lib/api";
import { STATUS_STYLE } from "@/lib/status";
import { cn } from "@/lib/utils";
import { nodeInfo } from "@/lib/mapinfo";

type Props = {
  map: FlowMap;
  run: Run | null;
  levelPath: string[];
  onOpen: (groupId: string) => void;
  onRoot: () => void;
  /** Up one level (also Esc). */
  onBack: () => void;
  onHeight?: (px: number) => void;
};

/**
 * "You are here" as a small org chart. Shown whenever you are below the top level: the flow and each box you went
 * into, as a single line down (siblings left out). What's inside the current box isn't repeated: the big map shows it.
 */
export function LevelMiniMap({ map, run, levelPath, onOpen, onRoot, onBack, onHeight }: Props) {
  const [open, setOpen] = useState(true);
  const box = useRef<HTMLDivElement>(null);

  // Tell the canvas how much room to leave at the top, so boxes are never hidden behind the map.
  useEffect(() => {
    const el = box.current;
    if (!el || !onHeight) return;
    const ro = new ResizeObserver(() => onHeight(el.offsetHeight));
    ro.observe(el);
    onHeight(el.offsetHeight);
    return () => {
      ro.disconnect();
      onHeight(0);
    };
  }, [onHeight]);
  const current = levelPath.at(-1) ?? "root";

  const Box = ({ id, active, onClick }: { id: string; active?: boolean; onClick: () => void }) => {
    const info = nodeInfo(map, run, id);
    const inside = map.levels[id]?.children.length ?? 0;
    return (
      <button
        onClick={onClick}
        title={`${info.label}${inside ? ` · ${inside} inside` : ""}`}
        className={cn(
          "flex max-w-full min-w-0 items-center gap-1 rounded border bg-background px-1.5 py-0.5 text-left text-[10px] leading-4 hover:border-foreground/50",
          active && "border-foreground/60 bg-muted font-medium",
          info.status === "failed" && "border-red-400",
        )}
      >
        <span className={cn("size-1.5 shrink-0 rounded-full", STATUS_STYLE[info.status].dot)} />
        <span className="truncate">{info.label}</span>
        {inside > 0 && !active && <span className="shrink-0 text-muted-foreground">›</span>}
      </button>
    );
  };

  const Line = () => <div className="mx-auto h-2 w-px bg-border" aria-hidden />;

  return (
    <div className="absolute top-3 right-3 z-10 flex max-w-[70%] items-start gap-2">
      <Button variant="outline" size="sm" className="shrink-0 bg-card" onClick={onBack} title="Back up one level (Esc)">
        <ArrowLeft /> Back
      </Button>
      <div ref={box} className="w-[30rem] min-w-0 border border-border bg-card text-xs">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center gap-1.5 px-2.5 py-1.5 font-medium whitespace-nowrap text-muted-foreground hover:text-foreground"
          aria-expanded={open}
        >
          <Network className="size-3.5" /> Where you are
          <span className="ml-auto text-[10px]">
            Layer {levelPath.length + 1} of {depthOf(map)}
          </span>
          <ChevronDown className={cn("size-3.5 transition-transform", !open && "-rotate-90")} />
        </button>
        {open && (
          <div className="max-h-[45vh] overflow-auto border-t p-2">
            {/* Your path: the flow, then each box you went into (no siblings) */}
            <div className="flex flex-col items-center">
              <button
                onClick={onRoot}
                title="Back to the top level"
                className="max-w-[70%] truncate rounded-md border bg-background px-2 py-0.5 text-[11px] font-semibold hover:border-foreground/50"
              >
                {map.title}
              </button>
              {levelPath.map((id) => (
                <div key={id} className="flex w-full flex-col items-center">
                  <Line />
                  <div className="max-w-[70%]">
                    <Box id={id} active={id === current} onClick={() => onOpen(id)} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function depthOf(map: FlowMap): number {
  let max = 1;
  const parent = new Map(map.groups.map((g) => [g.id, g.parent]));
  for (const s of map.steps) {
    let d = 1;
    for (let cur = s.group; cur && d < 10; cur = parent.get(cur) ?? null) d++;
    max = Math.max(max, d);
  }
  return max;
}
