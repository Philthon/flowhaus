import { ChevronDown, Network } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { FlowMap, Run } from "@/lib/api";
import { STATUS_STYLE } from "@/lib/status";
import { cn } from "@/lib/utils";
import { nodeInfo } from "./FlowCanvas";

type Props = {
  map: FlowMap;
  run: Run | null;
  levelPath: string[];
  selectedId: string | null;
  onOpen: (groupId: string) => void;
  onReveal: (nodeId: string) => void;
  onRoot: () => void;
  onHeight?: (px: number) => void;
};

/**
 * "You are here" as a small org chart. Shown whenever you are below the top level:
 * the flow and each box you went into as a single line down (siblings left out), then the
 * boxes on your current level side by side. If you select a box on that level that has
 * steps inside, its steps appear side by side one row further down.
 */
export function LevelMiniMap({ map, run, levelPath, selectedId, onOpen, onReveal, onRoot, onHeight }: Props) {
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
  const row = map.levels[current]?.children ?? [];
  const peek = selectedId && row.includes(selectedId) ? (map.levels[selectedId]?.children ?? []) : [];

  const Box = ({ id, active, dim, onClick }: { id: string; active?: boolean; dim?: boolean; onClick: () => void }) => {
    const info = nodeInfo(map, run, id);
    const inside = map.levels[id]?.children.length ?? 0;
    return (
      <button
        onClick={onClick}
        title={`${info.label}${inside ? ` · ${inside} inside` : ""}`}
        className={cn(
          "flex max-w-full min-w-0 items-center gap-1 rounded border bg-background px-1.5 py-0.5 text-left text-[10px] leading-4 hover:border-foreground/50",
          active && "border-foreground/60 bg-muted font-medium",
          id === selectedId && !active && "ring-2 ring-sky-500",
          dim && "opacity-70",
          info.status === "failed" && "border-red-400",
        )}
      >
        <span className={cn("size-1.5 shrink-0 rounded-full", STATUS_STYLE[info.status].dot)} />
        <span className="truncate">{info.label}</span>
        {inside > 0 && !active && <span className="shrink-0 text-muted-foreground">›</span>}
      </button>
    );
  };

  /** Boxes next to each other, joined to the box above by an org-chart connector. */
  const Row = ({ ids, dim }: { ids: string[]; dim?: boolean }) => (
    <ul className="flex gap-1.5">
      {ids.map((id, i) => (
        <li
          key={id}
          className={cn(
            "relative flex min-w-[4.5rem] flex-1 justify-center pt-2",
            "before:absolute before:top-0 before:left-1/2 before:h-2 before:w-px before:bg-border",
            "after:absolute after:top-0 after:h-px after:bg-border",
            ids.length === 1 ? "after:hidden" : i === 0 ? "after:right-[-3px] after:left-1/2" : i === ids.length - 1 ? "after:right-1/2 after:left-[-3px]" : "after:right-[-3px] after:left-[-3px]",
          )}
        >
          <Box id={id} dim={dim} onClick={() => (map.levels[id]?.children.length ? onOpen(id) : onReveal(id))} />
        </li>
      ))}
    </ul>
  );

  const Line = () => <div className="mx-auto h-2 w-px bg-border" aria-hidden />;

  return (
    <div ref={box} className="absolute top-3 right-3 z-10 w-[min(30rem,48%)] border border-border bg-card text-xs">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 font-medium text-muted-foreground hover:text-foreground"
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
          {/* What's inside the box you're in, side by side */}
          {row.length > 0 && (
            <>
              <Line />
              <Row ids={row} />
            </>
          )}
          {/* Peek one level further under the selected box */}
          {peek.length > 0 && (
            <>
              <Line />
              <Row ids={peek} dim />
            </>
          )}
        </div>
      )}
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
