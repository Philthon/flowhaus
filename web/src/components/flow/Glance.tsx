import { FlaskConical, Layers } from "lucide-react";
import { useEffect, useState } from "react";

import { api, type FlowMap, type Preview, type Row, type Run } from "@/lib/api";
import { fieldLabel, isInternal, showValue } from "@/lib/fields";
import { useTerms } from "@/lib/terms";

/**
 * The quick view when you rest on a shape: only what the shape doesn't already show. The logic in plain words (when
 * it says more than the box), a decision's rule, and one sample (a real item from the last run when there is one,
 * otherwise the step's written example). "Test with different input" opens the step's "Test" tab.
 */
const cache = new Map<string, Promise<Preview | null>>();

/** A finished run's sample never changes, so it's fetched once; a running run's is fetched fresh each time. */
function previewOf(flowId: string, nodeId: string, run: Run) {
  if (run.status === "running") return api.preview(flowId, nodeId, run.run_id).catch(() => null);
  const key = `${flowId}:${run.run_id}:${nodeId}`;
  if (!cache.has(key)) cache.set(key, api.preview(flowId, nodeId, run.run_id).catch(() => null));
  return cache.get(key)!;
}

const MAX_FIELDS = 4;

type Field = { name: string; value: string; before?: string };
type Sample =
  | { kind: "skipped"; reason: string; fields: Field[] }
  | { kind: "changed"; fields: Field[] }
  | { kind: "item"; fields: Field[] }
  | { kind: "example"; text: string };

const fieldsOf = (row: Row): Field[] =>
  Object.keys(row)
    .filter((k) => !isInternal(k) && row[k] != null && row[k] !== "")
    .slice(0, MAX_FIELDS)
    .map((k) => ({ name: k, value: showValue(row[k]) }));

function pickSample(p: Preview | null, example?: string | null): Sample | null {
  if (p) {
    const skipped = p.rejected_samples?.[0];
    if (skipped) return { kind: "skipped", reason: skipped.reason, fields: fieldsOf(skipped.before) };
    const outById = new Map((p.sample_out ?? []).map((r) => [r._row_id, r]));
    for (const before of p.sample_in ?? []) {
      const after = outById.get(before._row_id);
      if (!after) continue;
      const changed = Object.keys(after).filter((k) => !isInternal(k) && String(after[k] ?? "") !== String(before[k] ?? ""));
      if (changed.length)
        return {
          kind: "changed",
          fields: changed.slice(0, MAX_FIELDS).map((k) => ({
            name: k,
            value: showValue(after[k]),
            before: before[k] == null || before[k] === "" ? undefined : showValue(before[k]),
          })),
        };
    }
    const first = p.sample_out?.[0] ?? p.sample_in?.[0];
    if (first) return { kind: "item", fields: fieldsOf(first) };
  }
  return example ? { kind: "example", text: example } : null;
}

/** A small heading inside the card. */
function Caption({ children }: { children: React.ReactNode }) {
  return <p className="text-[10px] font-medium tracking-[0.12em] text-muted-foreground uppercase">{children}</p>;
}

/** One item, field by field: name on the left, value on the right; a changed value shows what it was. */
function Fields({ fields }: { fields: Field[] }) {
  return (
    <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-1 text-[13px]">
      {fields.map((f) => (
        <div key={f.name} className="contents">
          <dt className="truncate text-muted-foreground">{fieldLabel(f.name)}</dt>
          <dd className="min-w-0 break-words">
            {f.before !== undefined && (
              <>
                <s className="text-muted-foreground">{f.before}</s>
                {" → "}
              </>
            )}
            {f.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function Glance({
  map,
  run,
  flowId,
  nodeId,
  onTry,
  onOpen,
}: {
  map: FlowMap;
  run: Run | null;
  flowId: string;
  nodeId: string;
  onTry?: () => void;
  /** For a box with steps inside: open it. */
  onOpen?: () => void;
}) {
  const terms = useTerms();
  const step = map.steps.find((s) => s.id === nodeId);
  const group = map.groups.find((g) => g.id === nodeId);
  // decisions, ends and steps without a run show the written example; others fetch a real item (keyed, so a sample
  // never shows on the wrong shape while the next one loads)
  const fetches = !!run && step?.kind !== "decision" && step?.kind !== "end";
  const key = `${flowId}:${nodeId}:${run?.run_id}:${run?.status}`;
  const [loaded, setLoaded] = useState<{ key: string; sample: Sample | null } | null>(null);
  const sample: Sample | null | undefined = !fetches
    ? pickSample(null, step?.example)
    : loaded?.key === key
      ? loaded.sample
      : undefined;

  useEffect(() => {
    if (!fetches || !run) return;
    let live = true;
    previewOf(flowId, nodeId, run).then((p) => live && setLoaded({ key, sample: pickSample(p, step?.example) }));
    return () => {
      live = false;
    };
  }, [fetches, key, flowId, nodeId, run, step?.example]);

  // Only what the shape itself doesn't show. Boxes and waits show their title, description and counts; diamonds and
  // ends show just their title, and the answers sit on the lines.
  const titleOnly = step?.kind === "decision" || step?.kind === "end";
  const shown = titleOnly ? null : (step?.description ?? group?.description ?? null);
  const what = step?.explain && step.explain !== shown ? step.explain : titleOnly ? step?.description : null;
  const conditions = (step?.branches ?? []).filter((b) => b.when);
  const tryable = onTry && (group || (step && !titleOnly));

  return (
    <div className="w-[320px] divide-y divide-border border border-foreground/20 bg-card text-left text-[13px] leading-snug">
      {what && (
        <section className="space-y-1 p-3">
          <Caption>How it works</Caption>
          <p>{what}</p>
        </section>
      )}
      {step?.kind === "decision" && (step.rule || conditions.length > 0) && (
        <section className="space-y-1.5 p-3">
          {step.rule && (
            <>
              <Caption>Rule</Caption>
              <p>{step.rule}</p>
            </>
          )}
          {conditions.length > 0 && (
            <ul className="space-y-1 pt-0.5">
              {conditions.map((b) => (
                <li key={`${b.label}${b.to}`} className="flex gap-2">
                  <b className="shrink-0 border border-foreground/20 px-1 text-xs font-medium">{b.label}</b>
                  <span>{b.when}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {sample === undefined ? (
        <p className="p-3 text-xs text-muted-foreground">Loading an example…</p>
      ) : sample ? (
        <section className="space-y-1.5 p-3">
          {sample.kind === "skipped" ? (
            <>
              <Caption>Skipped in the last run</Caption>
              <p className="flex gap-2 font-medium">
                <span className="mt-1.5 size-2 shrink-0 rounded-full bg-amber-500" aria-hidden />
                {sample.reason}
              </p>
              <Fields fields={sample.fields} />
            </>
          ) : sample.kind === "changed" ? (
            <>
              <Caption>What it changed in one {terms.item}</Caption>
              <Fields fields={sample.fields} />
            </>
          ) : sample.kind === "item" ? (
            <>
              <Caption>One {terms.item} from the last run</Caption>
              <Fields fields={sample.fields} />
            </>
          ) : (
            <>
              <Caption>Example</Caption>
              <p>{sample.text}</p>
            </>
          )}
        </section>
      ) : null}
      <footer className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
        {onOpen ? (
          <button
            type="button"
            onClick={onOpen}
            className="flex items-center gap-1.5 border border-foreground/25 px-2 py-1 text-xs font-medium hover:border-foreground/60"
          >
            <Layers className="size-3.5" />
            Open · {map.levels[nodeId]?.children.length ?? 0} steps
          </button>
        ) : null}
        {tryable ? (
          <button
            type="button"
            onClick={onTry}
            className="flex items-center gap-1.5 border border-foreground/25 px-2 py-1 text-xs font-medium hover:border-foreground/60"
          >
            <FlaskConical className="size-3.5" />
            {map.flow.kind === "connected" ? "Predict with different input" : "Test with different input"}
          </button>
        ) : onOpen ? null : (
          <span />
        )}
        <span className="text-[11px] text-muted-foreground">Click for details</span>
      </footer>
    </div>
  );
}
