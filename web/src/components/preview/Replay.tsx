import { MessageSquare, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { api, type WhatIf } from "@/lib/api";
import { fieldLabel } from "@/lib/fields";
import { useTerms } from "@/lib/terms";
import { cn } from "@/lib/utils";

const show = (v: unknown) => (v == null || v === "" ? "–" : String(v));

/**
 * A past run replayed in test mode: its items go through the flow as it is now, and what comes out is compared with
 * what the run gave. After a change, this shows which items would come out differently, before it runs for real.
 */
export function ReplayPanel({ flowId, runId, onClose, onAsk }: { flowId: string; runId: string; onClose: () => void; onAsk: (t: string) => void }) {
  const terms = useTerms();
  const [result, setResult] = useState<WhatIf | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .replay(flowId, runId)
      .then((r) => live && setResult(r))
      .catch((e) => live && setError(String(e.message ?? e)));
    return () => {
      live = false;
    };
  }, [flowId, runId]);

  const c = result?.compare;
  const same = c && c.changed === 0 && c.now_skipped === 0 && c.now_kept === 0;
  const word = (n: number) => (n === 1 ? terms.item : terms.items);

  return (
    <section className="flex h-full min-h-0 flex-col border-t bg-background" aria-label="Replay">
      <header className="flex items-start justify-between gap-4 border-b px-4 py-2.5">
        <div className="min-w-0">
          <h2 className="font-semibold">Replay this run in test mode</h2>
          <p className="text-sm text-muted-foreground">
            The same {terms.items}, through the flow as it is now. Nothing is published, saved or added to the run history.
          </p>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close replay">
          <X />
        </Button>
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4 text-sm">
        {error ? (
          <p className="text-red-700 dark:text-red-400">{error}</p>
        ) : !result ? (
          <p className="text-muted-foreground">Replaying…</p>
        ) : result.mode === "predict" ? (
          <div className="border-l-2 border-[var(--bauhaus-blue)] pl-3">
            <p>{result.note}</p>
            <Button variant="outline" size="sm" className="mt-2" onClick={() => onAsk("What would this run give if it ran again now? Work it out from the code; don't run anything.")}>
              <MessageSquare /> Ask the chat
            </Button>
          </div>
        ) : (
          <>
            {c ? (
              <div className={cn("border-l-2 pl-3", same ? "border-emerald-600" : "border-amber-500")}>
                <p className="text-base font-medium">
                  {same
                    ? `Same result as the run: ${c.after} ${word(c.after)} come out, nothing different.`
                    : `${c.before} ${word(c.before)} came out then, ${c.after} would now.`}
                </p>
                {!same && (
                  <p className="text-muted-foreground tabular-nums">
                    {[
                      c.changed && `${c.changed} would come out different`,
                      c.now_skipped && `${c.now_skipped} would be skipped now`,
                      c.now_kept && `${c.now_kept} would come out that didn't before`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                )}
                {!same && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-2"
                    onClick={() =>
                      onAsk(
                        `Replaying a past run with the flow as it is now: ${c.before} came out then, ${c.after} now (${c.changed} different, ${c.now_skipped} now skipped). ` +
                          `Examples: ${c.examples.map((x) => `${x.item}: ${x.now ?? Object.keys(x.changes ?? {}).join(", ")}`).join("; ")}.\nWhich change causes this, and is it what we want?`,
                      )
                    }
                  >
                    Ask the chat why
                  </Button>
                )}
                {c.examples.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {c.examples.map((x, i) => (
                      <li key={i}>
                        <b className="font-medium">{x.item}</b>:{" "}
                        {x.now ??
                          Object.entries(x.changes ?? {}).map(([k, [a, b]], j) => (
                            <span key={k}>
                              {j > 0 && " · "}
                              {fieldLabel(k)}: <s className="text-muted-foreground">{show(a)}</s> → {show(b)}
                            </span>
                          ))}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <p className="text-muted-foreground">
                This run didn't finish, so there's nothing to compare with. Below is how far the {terms.items} get now.
              </p>
            )}
            <div>
              <p className="mb-1 font-medium">Step by step</p>
              <ol className="space-y-1">
                {(result.steps ?? []).map((s) => {
                  const n = (o: string) => s.items.filter((f) => f.outcome === o && !f.path).length;
                  const paths = Object.entries(
                    s.items.reduce<Record<string, number>>((acc, f) => (f.path ? { ...acc, [f.path]: (acc[f.path] ?? 0) + 1 } : acc), {}),
                  ).map(([label, count]) => `${count} ${label}`);
                  return (
                    <li key={s.id} className="flex flex-wrap items-baseline gap-x-2">
                      <span className={cn("inline-block size-2 shrink-0 rounded-full", s.status === "failed" ? "bg-red-500" : "bg-emerald-600")} />
                      <span className="font-medium">{s.label}</span>
                      <span className="text-muted-foreground tabular-nums">
                        {s.error ??
                          [
                            ...paths,
                            n("changed") && `${n("changed")} changed`,
                            n("kept") && `${n("kept")} as they were`,
                            n("skipped") && `${n("skipped")} skipped`,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                      </span>
                    </li>
                  );
                })}
              </ol>
            </div>
            <p className="text-xs text-muted-foreground">{result.note}</p>
          </>
        )}
      </div>
    </section>
  );
}
