import { AlertTriangle, ClipboardCheck, Lightbulb, Loader2, RefreshCw, X } from "lucide-react";
import { useState } from "react";

import { Evidence } from "@/components/chat/NextStepCard";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, PRIORITY_LABEL, type Checkup, type HarnessQuestion, type ReviewItem } from "@/lib/api";
import { reviewSignal } from "@/lib/review";
import { cn } from "@/lib/utils";

type Key = keyof Pick<Checkup, "fix_now" | "silent" | "drift" | "ideas" | "setup">;
const ERRORS: { key: Key; title: string }[] = [
  { key: "fix_now", title: "Broken in this run" },
  { key: "silent", title: "Silent failures" },
  { key: "drift", title: "Changing over recent runs" },
];
const ERROR_TONE = { error: "text-red-600", warn: "text-amber-500", idea: "text-muted-foreground", none: "text-muted-foreground" };
const IMPROVEMENTS: { key: Key; title: string }[] = [{ key: "ideas", title: "Ideas from the numbers" }];

type Props = {
  flowId: string;
  /** The checkup, fetched once by the page and shared with the status strip, the buttons and the chat's opener. */
  review: Checkup | null;
  loading: boolean;
  onReload: () => Promise<unknown>;
  onClose: () => void;
  onShowStep: (id: string) => void;
  onAsk: (text: string) => void;
};

/**
 * The Review: everything the harness finds about this flow, judged against docs/practices.md, in two tabs. Errors:
 * what's broken in this run, what fails silently, what changes over the recent runs. Improvements: what the numbers
 * suggest, and what's left to finish setting up. Each item has its next step and a way to act on it (solve it with
 * the chat, show the step, or say it doesn't apply here).
 */
export function ReviewPanel({ flowId, review, loading, onReload, onClose, onShowStep, onAsk }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null); // null: errors when there are any
  const act = (p: Promise<unknown>) => p.then(onReload, (e: Error) => setError(e.message));
  const errors = review?.errors ?? 0;
  const improvements = review?.improvements ?? 0;
  const tab = picked ?? (errors || !improvements ? "errors" : "improvements");
  const runs = review?.runs_checked ?? 0;
  const dismiss = (i: ReviewItem) => (i.source === "finding" ? (reason: string) => act(api.dismissFinding(flowId, i.id, reason)) : undefined);
  const sections = (list: { key: Key; title: string }[]) =>
    review &&
    list
      .filter((s) => review[s.key].length)
      .map((s) => (
        <Section key={s.key} title={s.title} count={review[s.key].length}>
          {review[s.key].map((i) => (
            <Row key={`${s.key}:${i.id}`} item={i} onAsk={onAsk} onShowStep={onShowStep} onDismiss={dismiss(i)} />
          ))}
        </Section>
      ));

  return (
    <section className="flex h-full min-h-0 flex-col bg-background" aria-label="Review of this flow">
      <header className="flex items-start justify-between gap-3 px-4 pt-2.5">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 font-semibold">
            <ClipboardCheck className="size-4" /> Review
          </h2>
          <p className="text-sm text-muted-foreground">
            {review ? `Judged against docs/practices.md, from the last ${runs} run${runs === 1 ? "" : "s"}.` : "Looking at the runs and the map…"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button variant="ghost" size="sm" onClick={() => void onReload()} disabled={loading} aria-label="Review again">
            {loading ? <Loader2 className="animate-spin" /> : <RefreshCw />}
          </Button>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close review">
            <X />
          </Button>
        </div>
      </header>
      <Tabs value={tab} onValueChange={(v) => setPicked(String(v))} className="flex min-h-0 flex-1 flex-col gap-0">
        <TabsList variant="line" className="mx-3 mt-1 shrink-0">
          <TabsTrigger value="errors">
            <AlertTriangle className={ERROR_TONE[reviewSignal(review).tone]} />
            Errors <span className="tabular-nums text-muted-foreground">{errors}</span>
          </TabsTrigger>
          <TabsTrigger value="improvements">
            <Lightbulb className={cn(improvements ? "text-amber-500" : "text-muted-foreground")} />
            Improvements <span className="tabular-nums text-muted-foreground">{improvements}</span>
          </TabsTrigger>
        </TabsList>
        <div className="min-h-0 flex-1 overflow-auto border-t text-sm">
          {error && <p className="tone-error m-4 mb-0 px-2 py-1 text-xs">{error}</p>}
          <TabsContent value="errors" className="space-y-5 p-4">
            {review && !errors && (
              <p className="text-muted-foreground">
                {runs
                  ? `No errors. Steady over the last ${runs} run${runs === 1 ? "" : "s"}: nothing failed, lost silently or drifting.`
                  : "No errors, and no finished runs yet to learn from."}
              </p>
            )}
            {sections(ERRORS)}
          </TabsContent>
          <TabsContent value="improvements" className="space-y-5 p-4">
            {review && !improvements && <p className="text-muted-foreground">Nothing to improve right now.</p>}
            {sections(IMPROVEMENTS)}
            {review && review.setup.length + review.questions.length > 0 && (
              <Section title="Finish setting it up" count={review.setup.length + review.questions.length}>
                {review.questions.map((q) => (
                  <QuestionRow key={q.id} q={q} onShowStep={onShowStep} onAnswer={(a) => act(api.answerQuestion(flowId, q.id, a))} />
                ))}
                {review.setup.map((i) => (
                  <Row key={`setup:${i.id}`} item={i} onAsk={onAsk} onShowStep={onShowStep} onDismiss={dismiss(i)} />
                ))}
              </Section>
            )}
            {review && <Footer review={review} onRestore={(id) => act(api.restoreHarness(flowId, id))} />}
          </TabsContent>
        </div>
      </Tabs>
    </section>
  );
}

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-[11px] font-medium tracking-[0.12em] text-muted-foreground uppercase">
        {title} <span className="tabular-nums">· {count}</span>
      </h3>
      <ul className="space-y-3">{children}</ul>
    </section>
  );
}

export function TextLink({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" className="mr-3 text-xs underline underline-offset-2 hover:opacity-70" onClick={onClick}>
      {children}
    </button>
  );
}

// how urgent, by colour and by text (P0..P3), so it doesn't rest on colour alone
const BAR: Record<ReviewItem["priority"], string> = { P0: "border-red-500", P1: "border-amber-500", P2: "border-border", P3: "border-border" };
const CHIP: Record<ReviewItem["priority"], string> = {
  P0: "border-red-500 text-red-700 dark:text-red-300",
  P1: "border-amber-500 text-amber-800 dark:text-amber-300",
  P2: "border-border text-muted-foreground",
  P3: "border-border text-muted-foreground",
};

function Row({ item, onAsk, onShowStep, onDismiss }: {
  item: ReviewItem;
  onAsk: (t: string) => void;
  onShowStep: (id: string) => void;
  onDismiss?: (reason: string) => void;
}) {
  const [dismissing, setDismissing] = useState(false);
  const [reason, setReason] = useState("");
  return (
    <li className={cn("space-y-1 border-l-2 pl-3", BAR[item.priority])}>
      <p className="flex items-start gap-2 font-medium">
        <span
          className={cn("mt-0.5 shrink-0 border px-1 font-mono text-[10px] leading-4", CHIP[item.priority])}
          title={`${item.priority}: ${PRIORITY_LABEL[item.priority]}`}
        >
          {item.priority}
          <span className="sr-only"> {PRIORITY_LABEL[item.priority]}</span>
        </span>
        <span>{item.title}</span>
      </p>
      {item.detail && <p className="text-xs text-muted-foreground">{item.detail}</p>}
      {item.next_step && (
        <p className="text-[13px]">
          <b className="font-medium">Next step: </b>
          {item.next_step}
        </p>
      )}
      {item.why && <p className="text-xs text-muted-foreground">{item.why}</p>}
      <Evidence lines={item.evidence} unseen={item.unseen} />
      {item.practice && <p className="text-[11px] text-muted-foreground">Practice: {item.practice}</p>}
      {dismissing && onDismiss ? (
        <form
          className="flex gap-2"
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
            aria-label="Why it doesn't apply here"
            className="min-w-0 flex-1 border bg-background px-2 py-1 text-xs"
          />
          <Button type="submit" size="sm" variant="outline" disabled={!reason.trim()}>
            Save
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setDismissing(false)}>
            Cancel
          </Button>
        </form>
      ) : (
        <div className="flex flex-wrap items-center gap-y-1 pt-0.5">
          {item.prompt && <TextLink onClick={() => onAsk(item.prompt!)}>Solve it with the chat</TextLink>}
          {item.node_id && <TextLink onClick={() => onShowStep(item.node_id!)}>Show the step</TextLink>}
          {onDismiss && <TextLink onClick={() => setDismissing(true)}>Not relevant here…</TextLink>}
        </div>
      )}
    </li>
  );
}

function QuestionRow({ q, onShowStep, onAnswer }: { q: HarnessQuestion; onShowStep: (id: string) => void; onAnswer: (a: string) => void }) {
  const [text, setText] = useState("");
  return (
    <li className="space-y-1 border-l-2 border-sky-500 pl-3">
      <p className="font-medium">{q.title}</p>
      <p className="text-xs text-muted-foreground">{q.detail}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        {q.options.map((o) => (
          <button key={o.value} type="button" onClick={() => onAnswer(o.value)} className="border bg-background px-2 py-0.5 text-xs hover:bg-muted">
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
              aria-label={q.title}
              className="w-40 border bg-background px-2 py-0.5 text-xs"
            />
            {text.trim() && <button className="border bg-background px-2 text-xs">OK</button>}
          </form>
        )}
        {q.node_id && <TextLink onClick={() => onShowStep(q.node_id!)}>Show the step</TextLink>}
      </div>
    </li>
  );
}

function Footer({ review, onRestore }: { review: Checkup; onRestore: (id: string) => void }) {
  const [show, setShow] = useState(false);
  const c = review.coverage;
  const kept = review.dismissed.length + review.answered.length;
  return (
    <div className="space-y-1 border-t pt-3 text-[11px] text-muted-foreground">
      {c && (
        <p>
          {c.with_numbers !== null && `Flowhaus sees numbers for ${c.with_numbers} of ${c.steps} steps · `}
          {c.linked_to_code} of {c.steps} linked to code
          {c.questions > 0 && ` · ${c.questions_answered} of ${c.questions} questions answered`}
        </p>
      )}
      {kept > 0 && (
        <button type="button" className="underline underline-offset-2" onClick={() => setShow((s) => !s)}>
          {show ? "Hide" : "Show"} what you told Flowhaus ({kept})
        </button>
      )}
      {show && (
        <ul className="space-y-1">
          {review.answered.map((a) => (
            <li key={a.id}>
              {a.title}: <b>{a.answer}</b> <TextLink onClick={() => onRestore(a.id)}>Change</TextLink>
            </li>
          ))}
          {review.dismissed.map((d) => (
            <li key={d.id}>
              Not relevant: {d.title}. <i>“{d.reason}”</i> <TextLink onClick={() => onRestore(d.id)}>Bring back</TextLink>
            </li>
          ))}
        </ul>
      )}
      {review.context_file && <p>Your answers live in {review.context_file}.</p>}
    </div>
  );
}
