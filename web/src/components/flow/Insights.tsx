import { ChevronDown, Lightbulb } from "lucide-react";
import { useEffect, useState } from "react";

import { api, type Harness, type HarnessFinding, type HarnessQuestion, type Insight } from "@/lib/api";
import { cn } from "@/lib/utils";

const TONE: Record<Insight["level"], string> = {
  error: "border-red-200 bg-red-50 text-red-900",
  warn: "border-amber-200 bg-amber-50 text-amber-950",
  info: "border-border bg-card text-foreground",
};
const RANK: Record<Insight["level"], number> = { error: 0, warn: 1, info: 2 };

type Props = {
  flowId: string;
  refreshKey: string;
  onShowStep: (id: string) => void;
  onAsk: (text: string) => void;
};

/** The harness speaking up: what the recent runs show, the big-picture gaps and blind spots, and questions only the
 *  user can answer. Every finding can be dismissed with a reason; it then stays quiet and the chat respects it. */
export function Insights({ flowId, refreshKey, onShowStep, onAsk }: Props) {
  const [items, setItems] = useState<Insight[]>([]);
  const [harness, setHarness] = useState<Harness | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api
      .insights(flowId)
      .then((r) => live && setItems(r.insights))
      .catch(() => live && setItems([]));
    api
      .harness(flowId)
      .then((h) => live && setHarness(h))
      .catch(() => live && setHarness(null));
    return () => {
      live = false;
    };
  }, [flowId, refreshKey]);

  const findings = harness?.findings ?? [];
  const questions = harness?.questions ?? [];
  const all: { level: Insight["level"]; title: string }[] = [...items, ...findings];
  if (!all.length && !questions.length && !harness?.dismissed.length && !harness?.answered.length) return null;

  const top = [...all].sort((a, b) => RANK[a.level] - RANK[b.level])[0];
  const act = (p: Promise<Harness>) =>
    p.then((h) => {
      setHarness(h);
      setError(null);
    }, (e: Error) => setError(e.message));
  const extra = [
    all.length > 1 && `${all.length - 1} more to look at`,
    questions.length > 0 && `${questions.length} question${questions.length > 1 ? "s" : ""} for you`,
  ].filter(Boolean);

  return (
    <div className={cn("border-b px-4 py-2 text-sm", TONE[top?.level ?? "info"])}>
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 text-left" aria-expanded={open}>
        <Lightbulb className="size-4 shrink-0" />
        <span className="min-w-0 flex-1 truncate">
          <b>{top ? top.title : questions[0] ? `A question: ${questions[0].title}` : "Nothing open"}</b>
          {extra.length > 0 && <span className="opacity-70"> · {extra.join(" · ")}</span>}
        </span>
        <ChevronDown className={cn("size-4 shrink-0 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="mt-2 max-h-[38vh] space-y-4 overflow-y-auto pr-3 pb-1 pl-6">
          {error && <p className="text-xs text-red-700">{error}</p>}
          {items.length > 0 && (
            <Section title="From the recent runs">
              {items.map((i, k) => (
                <li key={k}>
                  <p className="font-medium">{i.title}</p>
                  <p className="text-xs opacity-80">{i.detail}</p>
                  {i.node_id && <Link onClick={() => onShowStep(i.node_id!)}>Show this step</Link>}
                </li>
              ))}
            </Section>
          )}
          {questions.length > 0 && (
            <Section title="Questions only you can answer">
              {questions.map((q) => (
                <QuestionRow key={q.id} q={q} onShowStep={onShowStep} onAnswer={(a) => act(api.answerQuestion(flowId, q.id, a))} />
              ))}
            </Section>
          )}
          {(["gap", "blind_spot"] as const).map((kind) => {
            const list = findings.filter((f) => f.kind === kind);
            return (
              list.length > 0 && (
                <Section key={kind} title={kind === "gap" ? "Big picture" : "Blind spots: what Flowhaus can't see"}>
                  {list.map((f) => (
                    <FindingRow
                      key={f.id}
                      f={f}
                      onAsk={onAsk}
                      onShowStep={onShowStep}
                      onDismiss={(reason) => act(api.dismissFinding(flowId, f.id, reason))}
                    />
                  ))}
                </Section>
              )
            );
          })}
          {harness && <Footer harness={harness} onRestore={(id) => act(api.restoreHarness(flowId, id))} />}
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-1 text-[11px] font-semibold tracking-wide uppercase opacity-60">{title}</h3>
      <ul className="space-y-2">{children}</ul>
    </section>
  );
}

function Link({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button className="mr-3 text-xs underline underline-offset-2 hover:opacity-70" onClick={onClick}>
      {children}
    </button>
  );
}

function FindingRow({ f, onAsk, onShowStep, onDismiss }: {
  f: HarnessFinding;
  onAsk: (t: string) => void;
  onShowStep: (id: string) => void;
  onDismiss: (reason: string) => void;
}) {
  const [dismissing, setDismissing] = useState(false);
  const [reason, setReason] = useState("");
  return (
    <li className={cn("border-l-2 pl-2", f.level === "error" ? "border-red-400" : f.level === "warn" ? "border-amber-400" : "border-border")}>
      <p className="font-medium">{f.title}</p>
      <p className="text-xs opacity-80">{f.detail}</p>
      {f.practice && <p className="text-[11px] opacity-60">Practice: {f.practice}</p>}
      {dismissing ? (
        <form
          className="mt-1 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (reason.trim()) onDismiss(reason.trim());
          }}
        >
          <input
            autoFocus
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={500}
            placeholder="Why it doesn't apply here (the chat will respect it)"
            className="min-w-0 flex-1 border bg-background px-2 py-1 text-xs text-foreground"
          />
          <button type="submit" disabled={!reason.trim()} className="border bg-background px-2 text-xs text-foreground disabled:opacity-50">
            Save
          </button>
          <button type="button" onClick={() => setDismissing(false)} className="text-xs underline underline-offset-2">
            Cancel
          </button>
        </form>
      ) : (
        <div className="mt-0.5">
          {f.ask && <Link onClick={() => onAsk(f.ask!)}>Ask Claude about it</Link>}
          {f.node_id && <Link onClick={() => onShowStep(f.node_id!)}>Show this step</Link>}
          <Link onClick={() => setDismissing(true)}>Not relevant here…</Link>
        </div>
      )}
    </li>
  );
}

function QuestionRow({ q, onShowStep, onAnswer }: { q: HarnessQuestion; onShowStep: (id: string) => void; onAnswer: (a: string) => void }) {
  const [text, setText] = useState("");
  return (
    <li className="border-l-2 border-sky-400 pl-2">
      <p className="font-medium">{q.title}</p>
      <p className="text-xs opacity-80">{q.detail}</p>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        {q.options.map((o) => (
          <button
            key={o.value}
            onClick={() => onAnswer(o.value)}
            className="border bg-background px-2 py-0.5 text-xs text-foreground hover:bg-muted"
          >
            {o.label}
          </button>
        ))}
        {q.free_text && (
          <form
            className="flex gap-1"
            onSubmit={(e) => {
              e.preventDefault();
              if (text.trim()) onAnswer(text.trim());
            }}
          >
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={100}
              placeholder={q.free_text}
              className="w-40 border bg-background px-2 py-0.5 text-xs text-foreground"
            />
            {text.trim() && <button className="border bg-background px-2 text-xs text-foreground">OK</button>}
          </form>
        )}
        {q.node_id && <Link onClick={() => onShowStep(q.node_id!)}>Show this step</Link>}
      </div>
    </li>
  );
}

function Footer({ harness, onRestore }: { harness: Harness; onRestore: (id: string) => void }) {
  const [show, setShow] = useState(false);
  const c = harness.coverage;
  const kept = harness.dismissed.length + harness.answered.length;
  return (
    <div className="space-y-1 border-t pt-2 text-[11px] opacity-70">
      {c && (
        <p>
          {c.with_numbers !== null && `Flowhaus sees numbers for ${c.with_numbers} of ${c.steps} steps · `}
          {c.linked_to_code} of {c.steps} linked to code
          {c.questions > 0 && ` · ${c.questions_answered} of ${c.questions} questions answered`}
        </p>
      )}
      {kept > 0 && (
        <button className="underline underline-offset-2" onClick={() => setShow((s) => !s)}>
          {show ? "Hide" : "Show"} what you told Flowhaus ({kept})
        </button>
      )}
      {show && (
        <ul className="space-y-1">
          {harness.answered.map((a) => (
            <li key={a.id}>
              {a.title}: <b>{a.answer}</b> <Link onClick={() => onRestore(a.id)}>Change</Link>
            </li>
          ))}
          {harness.dismissed.map((d) => (
            <li key={d.id}>
              Not relevant: {d.title}. <i>“{d.reason}”</i> <Link onClick={() => onRestore(d.id)}>Bring back</Link>
            </li>
          ))}
        </ul>
      )}
      <p>
        Judged against docs/practices.md. {harness.context_file && <>Your answers live in {harness.context_file}.</>}
      </p>
    </div>
  );
}
