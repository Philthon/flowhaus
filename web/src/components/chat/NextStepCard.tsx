import { ArrowRight, Wrench } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { NextSteps } from "@/lib/api";

/** What a next step is based on: the log lines (or numbers), and what Flowhaus couldn't see. */
export function Evidence({ lines, unseen }: { lines?: string[]; unseen?: string | null }) {
  if (!lines?.length && !unseen) return null;
  return (
    <div className="space-y-0.5 text-[11px] text-muted-foreground">
      {lines?.length ? <p>Based on:</p> : null}
      {lines?.map((l) => (
        <p key={l} className="font-mono break-words whitespace-pre-wrap">
          {l}
        </p>
      ))}
      {unseen && <p>{unseen}</p>}
    </div>
  );
}

/**
 * The chat's opener when something is wrong: which problem to solve first and why, its next step, and a button that
 * hands it to the chat. Other problems are listed below, each one click away. Worked out by Flowhaus from the run
 * and the review (no model call), so it's there the moment the chat opens.
 */
export function NextStepCard({ plan, onSolve }: { plan: NextSteps; onSolve: (prompt: string) => void }) {
  const first = plan.first;
  if (!first) return null;
  return (
    <section className="space-y-2 border-l-2 border-red-500 pl-3 text-sm" aria-label="What to fix first">
      <p className="text-[10px] font-medium tracking-[0.12em] text-muted-foreground uppercase">
        {plan.others.length ? "Solve this first" : "What went wrong"}
      </p>
      <p className="font-medium">{first.title}</p>
      {first.detail && <p className="text-muted-foreground">{first.detail}</p>}
      <p>
        <b className="font-medium">Next step: </b>
        {first.next_step}
      </p>
      {first.why && <p className="text-xs text-muted-foreground">{first.why}</p>}
      <Evidence lines={first.evidence} unseen={first.unseen} />
      <Button size="sm" variant="outline" onClick={() => onSolve(first.prompt)}>
        <Wrench /> Solve it with the chat
      </Button>
      {plan.others.length > 0 && (
        <div className="pt-1">
          <p className="text-xs text-muted-foreground">Also:</p>
          <ul className="space-y-0.5">
            {plan.others.map((o) => (
              <li key={o.id}>
                <button
                  type="button"
                  onClick={() => onSolve(o.prompt)}
                  className="flex items-start gap-1 text-left text-xs hover:underline"
                  title={o.next_step}
                >
                  <ArrowRight className="mt-0.5 size-3 shrink-0" />
                  {o.title}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
