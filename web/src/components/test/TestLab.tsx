import { CheckCircle2, FlaskConical, Loader2, Play, Plus, Shuffle, Trash2, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { api, type TestCase, type TestLabState, type TestRun } from "@/lib/api";
import { useTerms } from "@/lib/terms";
import { cn } from "@/lib/utils";

const HEAT = [
  { at: 0, label: "Calm", hint: "typical items, like your sample data" },
  { at: 0.35, label: "Tricky", hint: "spaces, capitals, accents, missing values" },
  { at: 0.65, label: "Edge cases", hint: "broken formats, odd dates, duplicates, very long text" },
  { at: 0.85, label: "Wild", hint: "several problems at once, injection text, 'null', only spaces" },
];

/**
 * Pressure-test a flow, Postman-style: items you write or generate, a run through the whole flow in test mode,
 * and checks on what happened. Test runs never count toward the flow's numbers.
 */
export function TestLab({ flowId, onOpenRun }: { flowId: string; onOpenRun: (runId: string) => void }) {
  const terms = useTerms();
  const [state, setState] = useState<TestLabState | null>(null);
  const [cases, setCases] = useState<TestCase[]>([]);
  const [count, setCount] = useState(10);
  const [temperature, setTemperature] = useState(0.5);
  const [busy, setBusy] = useState<null | "generate" | "run">(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TestRun | null>(null);
  const [confirming, setConfirming] = useState(false);

  const load = useCallback(() => {
    api
      .tests(flowId)
      .then((s) => {
        setState(s);
        setCases(s.suite.cases);
      })
      .catch((e) => setError(e.message));
  }, [flowId]);
  useEffect(load, [load]);

  // a GitHub test run finishes later: check back until it's done
  useEffect(() => {
    if (!result || result.status !== "running") return;
    const t = window.setTimeout(() => api.testRun(flowId, result.id).then(setResult).catch(() => {}), 10000);
    return () => window.clearTimeout(t);
  }, [flowId, result]);

  const fields = useMemo(() => {
    const names = state?.fields.map((f) => f.name) ?? [];
    for (const c of cases) for (const k of Object.keys(c.item)) if (!names.includes(k)) names.push(k);
    return names;
  }, [state, cases]);

  const save = async (next: TestCase[]) => {
    setCases(next);
    try {
      await api.saveSuite(flowId, { cases: next, checks: state?.suite.checks ?? [] });
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const generate = async () => {
    setBusy("generate");
    setError(null);
    try {
      const r = await api.generateTests(flowId, count, temperature);
      await save([...cases, ...r.cases]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const run = async () => {
    setConfirming(false);
    setBusy("run");
    setError(null);
    try {
      setResult(await api.runTests(flowId, state?.mode.kind !== "local"));
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (!state) return <p className="flex items-center gap-2 p-6 text-sm text-muted-foreground">{error ?? <Loader2 className="size-4 animate-spin" />}</p>;
  const mode = state.mode;
  const heat = [...HEAT].reverse().find((h) => temperature >= h.at) ?? HEAT[0];
  const byCase = new Map((result?.results ?? []).map((r) => [r.case_id, r]));

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <div className="mx-auto max-w-5xl space-y-5 px-5 py-5">
        <header className="space-y-1">
          <h2 className="flex items-center gap-2 text-lg font-medium">
            <FlaskConical className="size-5 text-[var(--bauhaus-blue)]" /> Test lab
          </h2>
          <p className="text-sm text-muted-foreground">
            Run the whole flow on test {terms.items} (yours or generated) and check what happens to each one. Test runs never
            count toward this flow's numbers.
          </p>
          <p className={cn("text-xs", mode.ready ? "text-muted-foreground" : "text-amber-900")}>
            <b>{mode.label}.</b> {mode.ready ? mode.non_production : mode.setup}
          </p>
        </header>

        {/* generator */}
        <section className="flex flex-wrap items-end gap-4 border border-border bg-card p-4">
          <label className="space-y-1 text-xs">
            <span className="block text-muted-foreground">How many</span>
            <select value={count} onChange={(e) => setCount(Number(e.target.value))} className="h-8 border bg-background px-2 text-sm">
              {[5, 10, 20, 50].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <label className="min-w-56 flex-1 space-y-1 text-xs">
            <span className="flex justify-between text-muted-foreground">
              <span>
                Temperature: <b className="text-foreground">{heat.label}</b>
              </span>
              <span>{heat.hint}</span>
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={temperature}
              onChange={(e) => setTemperature(Number(e.target.value))}
              className="w-full accent-[var(--bauhaus-red)]"
              aria-label="Temperature: how tricky the generated items are"
            />
          </label>
          <Button variant="outline" onClick={generate} disabled={!!busy || fields.length === 0}>
            {busy === "generate" ? <Loader2 className="animate-spin" /> : <Shuffle />} Generate {terms.items}
          </Button>
          {fields.length === 0 && (
            <p className="w-full text-xs text-muted-foreground">
              Flowhaus doesn't know what one item looks like yet: add sample data, or `test.examples` in automation.yaml.
            </p>
          )}
        </section>

        {/* the items */}
        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium">
              Test {terms.items} <span className="font-normal text-muted-foreground">({cases.length})</span>
            </h3>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => save([...cases, { id: Math.random().toString(16).slice(2, 10), item: Object.fromEntries(fields.map((f) => [f, ""])), note: "written by hand", expect: "any" }])}
              >
                <Plus /> Add one
              </Button>
              {cases.length > 0 && (
                <Button size="sm" variant="ghost" onClick={() => save([])}>
                  <Trash2 /> Clear
                </Button>
              )}
            </div>
          </div>
          {cases.length === 0 ? (
            <p className="border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
              No test {terms.items} yet. Generate some above, or add one by hand.
            </p>
          ) : (
            <div className="overflow-x-auto border border-border bg-card">
              <table className="w-full text-sm">
                <thead className="border-b text-left text-xs text-muted-foreground">
                  <tr>
                    {fields.map((f) => (
                      <th key={f} className="px-2 py-1.5 font-medium">
                        {f}
                      </th>
                    ))}
                    <th className="px-2 py-1.5 font-medium">What it tests</th>
                    <th className="px-2 py-1.5 font-medium">Expect</th>
                    {result && <th className="px-2 py-1.5 font-medium">What happened</th>}
                    <th />
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {cases.map((c, i) => {
                    const r = byCase.get(c.id);
                    return (
                      <tr key={c.id} className="align-top">
                        {fields.map((f) => (
                          <td key={f} className="px-1 py-1">
                            <input
                              value={String(c.item[f] ?? "")}
                              onChange={(e) => setCases(cases.map((x, j) => (j === i ? { ...x, item: { ...x.item, [f]: e.target.value } } : x)))}
                              onBlur={() => save(cases)}
                              className="w-full min-w-28 bg-transparent px-1 py-0.5 font-mono text-xs outline-none focus:bg-muted"
                              aria-label={`${f} of test item ${i + 1}`}
                            />
                          </td>
                        ))}
                        <td className="max-w-56 px-2 py-1 text-xs text-muted-foreground">{c.note}</td>
                        <td className="px-2 py-1">
                          <select
                            value={c.expect}
                            onChange={(e) => save(cases.map((x, j) => (j === i ? { ...x, expect: e.target.value as TestCase["expect"] } : x)))}
                            className="border bg-background px-1 text-xs"
                            aria-label={`Expected outcome for test item ${i + 1}`}
                          >
                            <option value="any">anything</option>
                            <option value="kept">kept</option>
                            <option value="skipped">skipped</option>
                          </select>
                        </td>
                        {result && (
                          <td className="px-2 py-1 text-xs">
                            {r ? (
                              <span className={cn(r.ok ? "" : "font-medium text-red-700")}>
                                {r.got}
                                {r.step && <span className="text-muted-foreground"> at {r.step}</span>}
                                {r.reason && <span className="text-muted-foreground">: {r.reason}</span>}
                              </span>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </td>
                        )}
                        <td className="px-1 py-1">
                          <button onClick={() => save(cases.filter((_, j) => j !== i))} aria-label={`Remove test item ${i + 1}`} className="p-1 text-muted-foreground hover:text-foreground">
                            <Trash2 className="size-3.5" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => (mode.kind === "local" ? run() : setConfirming(true))} disabled={!!busy || !mode.ready || cases.length === 0}>
            {busy === "run" ? <Loader2 className="animate-spin" /> : <Play />} Run test
          </Button>
          {error && <p className="text-sm text-red-700">{error}</p>}
        </div>

        {result && <Checks result={result} onOpenRun={onOpenRun} />}

        {state.runs.length > 0 && (
          <section className="space-y-1 text-xs text-muted-foreground">
            <h3 className="font-medium text-foreground">Earlier test runs</h3>
            {state.runs.slice(0, 6).map((r) => {
              const failed = r.checks.filter((c) => !c.ok).length;
              return (
                <p key={r.id}>
                  {new Date(r.started_at).toLocaleString()} · {r.status === "running" ? "running" : failed ? `${failed} check${failed > 1 ? "s" : ""} failed` : "all checks passed"}
                  {r.run_id && (
                    <>
                      {" · "}
                      <button className="underline" onClick={() => onOpenRun(r.run_id!)}>
                        open on the map
                      </button>
                    </>
                  )}
                </p>
              );
            })}
          </section>
        )}
      </div>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent className="p-5 sm:max-w-md">
          <DialogTitle>Run your real automation in test mode?</DialogTitle>
          <p className="text-sm text-muted-foreground">{mode.label}, with your own setup and keys. What keeps it out of production, in your words:</p>
          <p className="border-l-2 border-[var(--bauhaus-yellow)] pl-3 text-sm">{mode.non_production}</p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button onClick={run}>Run test</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Checks({ result, onOpenRun }: { result: TestRun; onOpenRun: (runId: string) => void }) {
  if (result.status === "running")
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> {result.output ?? "Running…"}
      </p>
    );
  const passed = result.checks.filter((c) => c.ok).length;
  return (
    <section className="space-y-2 border border-border bg-card p-4">
      <h3 className="flex items-center justify-between text-sm font-medium">
        <span>
          {passed} of {result.checks.length} checks passed
        </span>
        {result.run_id && (
          <button className="text-xs font-normal underline" onClick={() => onOpenRun(result.run_id!)}>
            Open this test run on the map
          </button>
        )}
      </h3>
      <ul className="space-y-1 text-sm">
        {result.checks.map((c) => (
          <li key={c.name} className="flex items-start gap-2">
            {c.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-700" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-red-700" />}
            <span>
              {c.name}
              {!c.ok && c.detail && <span className="block text-xs text-muted-foreground">{c.detail}</span>}
            </span>
          </li>
        ))}
      </ul>
      {result.output && result.mode !== "local" && (
        <pre className="max-h-48 overflow-auto bg-muted/50 p-2 font-mono text-[11px]">{result.output}</pre>
      )}
    </section>
  );
}
