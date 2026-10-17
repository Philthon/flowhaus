import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  flowId: string;
  enabled: boolean;
  onChange?: (enabled: boolean) => void;
  size?: "sm" | "md";
  /** For real automations: ask before changing, and say what will happen there. */
  confirm?: { where: string; offHint?: string; onHint?: string };
  /** Show "On"/"Off" next to the switch (where there's no other label). */
  showLabel?: boolean;
};

/** On/Paused switch for a flow. With `confirm`, it asks first because it changes a real system. */
export function EnabledToggle({ flowId, enabled, onChange, size = "md", confirm, showLabel }: Props) {
  const [value, setValue] = useState(enabled);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLSpanElement>(null);
  if (value !== enabled && !busy) setValue(enabled);

  useEffect(() => {
    if (!asking) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setAsking(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [asking]);

  const apply = async (next: boolean) => {
    setBusy(true);
    setError(null);
    setValue(next);
    try {
      await api.setEnabled(flowId, next);
      setAsking(false);
      onChange?.(next);
    } catch (e) {
      setValue(!next);
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const click = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (busy) return;
    if (confirm) {
      setError(null);
      setAsking((a) => !a);
    } else apply(!value);
  };

  const next = !value;
  return (
    <span ref={box} className="relative inline-flex items-center" onClick={(e) => e.stopPropagation()}>
      {showLabel && <span className="mr-1.5 hidden text-xs text-muted-foreground @md:inline">{value ? "On" : "Off"}</span>}
      <button
        role="switch"
        aria-checked={value}
        aria-label={confirm ? `Switched on in ${confirm.where}` : "Runs when triggered"} // on or off is aria-checked
        title={confirm ? `${value ? "On" : "Off"} in ${confirm.where}. Click to change` : value ? "On: runs when triggered. Click to pause" : "Paused: will not run. Click to turn on"}
        onClick={click}
        disabled={busy}
        className={cn(
          "relative shrink-0 border border-foreground/30 transition-colors disabled:opacity-60",
          size === "sm" ? "h-4 w-7" : "h-5 w-9",
          value ? "border-emerald-500 bg-emerald-500" : "bg-muted",
        )}
      >
        <span
          className={cn(
            "absolute top-px left-px transition-transform",
            size === "sm" ? "size-3" : "size-4",
            value ? (size === "sm" ? "translate-x-3 bg-white" : "translate-x-4 bg-white") : "translate-x-0 bg-foreground/50",
          )}
        />
      </button>
      {confirm && asking && (
        <span
          role="dialog"
          aria-label={next ? "Turn on" : "Turn off"}
          className="absolute top-full right-0 z-50 mt-2 block w-72 border border-border bg-card p-3 text-left text-sm text-foreground"
        >
          <span className="block font-medium">
            {next ? "Turn it on" : "Turn it off"} in {confirm.where}?
          </span>
          <span className="mt-1 block text-xs text-muted-foreground">{next ? confirm.onHint : confirm.offHint}</span>
          {error && <span className="mt-2 block text-xs text-red-700 dark:text-red-400">{error}</span>}
          <span className="mt-3 flex gap-2">
            <Button size="sm" onClick={() => apply(next)} disabled={busy}>
              {busy ? "Changing…" : next ? "Turn on" : "Turn off"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setAsking(false)} disabled={busy}>
              Cancel
            </Button>
          </span>
        </span>
      )}
      {!confirm && error && <span className="absolute top-full right-0 mt-1 w-56 text-xs text-red-700 dark:text-red-400">{error}</span>}
    </span>
  );
}
