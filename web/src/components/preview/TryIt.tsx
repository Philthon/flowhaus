import { FlaskConical, MessageSquare, Plus, RotateCcw, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { api, type Row, type WhatIf } from "@/lib/api";
import { fieldLabel, fromDrafts, isInternal, showValue, toDrafts, type DraftField } from "@/lib/fields";
import { useTerms } from "@/lib/terms";
import { cn } from "@/lib/utils";

const MAX_ITEMS = 5;

/**
 * "What if this step got these items?" Start from the items it really got in the run you're looking at, change any
 * field, and run the step (and, if you like, everything after it) in test mode. Nothing is published, saved to the
 * flow's output or added to its run history. Steps that run somewhere else (connected automations) can't run here:
 * the chat predicts the result from the code instead, and says it's a prediction.
 */
export function TryIt({
  flowId,
  stepId,
  label,
  start,
  connected,
  onAsk,
}: {
  flowId: string;
  stepId: string;
  label: string;
  start: Row[];
  connected: boolean;
  onAsk: (text: string) => void;
}) {
  const terms = useTerms();
  const blank = (): DraftField => ({ name: "", value: "", kind: "text", fromRun: false });
  const [drafts, setDrafts] = useState<DraftField[][]>(() => (start.length ? toDrafts(start, MAX_ITEMS) : [[blank()]]));
  const [downstream, setDownstream] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<WhatIf | null>(null);
  const [error, setError] = useState<string | null>(null);

  const edit = (i: number, f: number, patch: Partial<DraftField>) =>
    setDrafts((all) => all.map((d, j) => (j === i ? d.map((x, g) => (g === f ? { ...x, ...patch } : x)) : d)));
  const items = () => {
    const r = fromDrafts(drafts, terms.item);
    if ("error" in r) {
      setError(r.error);
      return null;
    }
    return r.items;
  };

  const predict = () => {
    const list = items();
    if (!list) return;
    setError(null);
    onAsk(
      `Predict what "${label}" would do with these ${terms.items}${downstream ? ", and what would come out at the end" : ""}. ` +
        `Work it out from the code; don't run anything. Say clearly that it's a prediction.\n\n` +
        "```json\n" + JSON.stringify(list, null, 2) + "\n```",
    );
  };

  const run = async () => {
    if (connected) return predict();
    const list = items();
    if (!list) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.whatIf(flowId, stepId, list, downstream));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4 text-sm">
      <p className="text-muted-foreground">
        {connected
          ? `This step runs where the automation lives, so Flowhaus can't run it here. Change the ${terms.items} below and the chat predicts what would happen, from the code.`
          : `Change the ${terms.items} below and run this step on them in test mode. Nothing is published, saved or added to the run history.`}
        {start.length > 0 && ` They start as the ${terms.items} this step got in this run.`}
      </p>

      <div className="space-y-3">
        {drafts.map((d, i) => (
          <fieldset key={i} className="border border-border p-3">
            <legend className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
              {terms.item} {i + 1}
              {drafts.length > 1 && (
                <button
                  type="button"
                  className="hover:text-foreground"
                  aria-label={`Remove ${terms.item} ${i + 1}`}
                  onClick={() => setDrafts((all) => all.filter((_, j) => j !== i))}
                >
                  <X className="size-3.5" />
                </button>
              )}
            </legend>
            <div className="grid grid-cols-[minmax(80px,max-content)_1fr] items-center gap-x-3 gap-y-1.5">
              {d.map((f, g) => (
                <FieldRow key={g} field={f} onName={(name) => edit(i, g, { name })} onValue={(value) => edit(i, g, { value })} />
              ))}
            </div>
            <button
              type="button"
              className="mt-2 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setDrafts((all) => all.map((x, j) => (j === i ? [...x, blank()] : x)))}
            >
              <Plus className="size-3" /> Add a field
            </button>
          </fieldset>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {drafts.length < MAX_ITEMS && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setDrafts((all) => [...all, (all[0] ?? [blank()]).map((f) => ({ ...f, value: "" }))])}
          >
            <Plus /> Another {terms.item}
          </Button>
        )}
        {start.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setDrafts(toDrafts(start, MAX_ITEMS));
              setResult(null);
              setError(null);
            }}
          >
            <RotateCcw /> Back to this run's {terms.items}
          </Button>
        )}
        <label className="flex items-center gap-2 text-xs">
          <input type="checkbox" checked={downstream} onChange={(e) => setDownstream(e.target.checked)} />
          Also run the steps after it
        </label>
        <Button size="sm" className="ml-auto" disabled={busy} onClick={run}>
          {connected ? <MessageSquare /> : <FlaskConical />}
          {busy ? "Running the test…" : connected ? "Ask the chat to predict" : "Run the test"}
        </Button>
      </div>

      {error && <p className="text-red-700 dark:text-red-400">{error}</p>}
      {result && <Outcome result={result} onPredict={predict} onAsk={onAsk} />}
    </div>
  );
}

function FieldRow({ field, onName, onValue }: { field: DraftField; onName: (v: string) => void; onValue: (v: string) => void }) {
  const input = "h-8 w-full border border-input bg-transparent px-2 text-[13px] focus-visible:outline-2 focus-visible:outline-sky-500";
  const label = fieldLabel(field.name) || "Value";
  return (
    <>
      {field.fromRun ? (
        <span className="truncate text-xs text-muted-foreground" title={field.name}>
          {fieldLabel(field.name)}
        </span>
      ) : (
        <input className={input} placeholder="Field name" value={field.name} onChange={(e) => onName(e.target.value)} aria-label="Field name" />
      )}
      <input
        className={input}
        value={field.value}
        inputMode={field.kind === "number" ? "decimal" : undefined}
        placeholder={field.kind === "yesno" ? "yes or no" : undefined}
        onChange={(e) => onValue(e.target.value)}
        aria-label={label}
      />
    </>
  );
}

function Outcome({ result, onPredict, onAsk }: { result: WhatIf; onPredict: () => void; onAsk: (t: string) => void }) {
  const terms = useTerms();
  if (result.mode === "predict")
    return (
      <div className="border-l-2 border-[var(--bauhaus-blue)] pl-3">
        <p>{result.note}</p>
        <Button variant="outline" size="sm" className="mt-2" onClick={onPredict}>
          <MessageSquare /> Ask the chat to predict
        </Button>
      </div>
    );
  const out = result.out ?? [];
  const fields = [...new Set(out.flatMap((r) => Object.keys(r)))].filter((k) => !isInternal(k));
  return (
    <div className="space-y-3 border-t pt-3">
      <p className="text-xs text-muted-foreground">{result.note}</p>
      <ol className="space-y-2">
        {(result.steps ?? []).map((s) => (
          <li key={s.id}>
            <p className="font-medium">
              <span className={cn("mr-2 inline-block size-2 rounded-full", s.status === "failed" ? "bg-red-500" : "bg-emerald-600")} />
              {s.label}
            </p>
            {s.error && (
              <p className="ml-4 text-red-700 dark:text-red-400">
                {s.error}{" "}
                <button
                  type="button"
                  className="text-xs text-foreground underline underline-offset-2"
                  onClick={() => onAsk(`Testing “${s.label}” with different input failed: ${s.error}\nWhy, and what's the shortest fix? Don't change anything yet.`)}
                >
                  Solve it with the chat
                </button>
              </p>
            )}
            <ul className="ml-4 space-y-0.5 text-[13px]">
              {s.items.map((f) => (
                <li key={f.n}>
                  <span className="text-muted-foreground">
                    {terms.item} {f.n}:{" "}
                  </span>
                  {f.outcome === "skipped" ? (
                    <span className="text-amber-700 dark:text-amber-400">skipped, {f.reason}</span>
                  ) : f.outcome === "failed" ? (
                    <span className="text-red-700 dark:text-red-400">failed</span>
                  ) : f.path ? (
                    <>
                      went on as <b className="border border-foreground/20 px-1 text-xs font-medium">{f.path}</b>
                    </>
                  ) : f.outcome === "kept" ? (
                    "kept as it was"
                  ) : (
                    Object.entries(f.changes ?? {}).map(([k, [a, b]], j) => (
                      <span key={k}>
                        {j > 0 && " · "}
                        {fieldLabel(k)}:{" "}
                        {a == null || a === "" ? (
                          <>
                            {showValue(b)} <span className="text-muted-foreground">(new)</span>
                          </>
                        ) : (
                          <>
                            <s className="text-muted-foreground">{showValue(a)}</s> → {showValue(b)}
                          </>
                        )}
                      </span>
                    ))
                  )}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
      <div>
        <p className="mb-1 font-medium">
          What comes out: {out.length} {out.length === 1 ? terms.item : terms.items}
        </p>
        {out.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  {fields.map((k) => (
                    <th key={k} className="px-2 py-1 font-normal">
                      {fieldLabel(k)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {out.map((r, i) => (
                  <tr key={i} className="border-b border-border/60">
                    {fields.map((k) => (
                      <td key={k} className="px-2 py-1">
                        {showValue(r[k])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
