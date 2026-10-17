import { AlertTriangle, ChevronRight, Lightbulb } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { Checkup } from "@/lib/api";
import { PRIORITY_BANNER, reviewSignal } from "@/lib/review";
import { cn } from "@/lib/utils";


type Props = {
  review: Checkup | null;
  /** The failed run, in words: where (a path of box names) and why. */
  failure: { where: string; message: string } | null;
  mapProblems: string[];
  onShowFailure?: () => void;
  onOpenReview: () => void;
};

/**
 * One line above the map with the most important thing right now, and what to do about it:
 *   the run failed (where, why, the next step)  >  the map is out of date with the code  >  the top idea.
 * Everything else is one click away in the Review. Replaces separate failure, map and findings banners.
 */
export function StatusStrip({ review, failure, mapProblems, onShowFailure, onOpenReview }: Props) {
  const items = review ? [...review.silent, ...review.drift, ...review.ideas] : [];
  const count = reviewSignal(review).count; // the same number as the Review button: errors, or else improvements
  const top = [...items].sort((a, b) => a.priority.localeCompare(b.priority))[0];
  const next = failure ? review?.plan?.first?.next_step : top?.next_step;
  if (!failure && !mapProblems.length && !top) return null;

  const tone = PRIORITY_BANNER[failure ? "P0" : mapProblems.length ? "P1" : (top?.priority ?? "P2")];
  const Icon = failure || mapProblems.length || top?.priority === "P0" ? AlertTriangle : Lightbulb;
  return (
    <div className={cn("flex items-center gap-3 border-b px-4 py-2 text-sm", tone)} role={failure ? "alert" : undefined}>
      <Icon className="size-4 shrink-0" />
      <p className="line-clamp-2 min-w-0 flex-1">
        {failure ? (
          <>
            <b className="font-medium">
              This run failed in {failure.where}
              {/[.?!]$/.test(failure.where) ? "" : "."}
            </b>{" "}
            {failure.message}
          </>
        ) : mapProblems.length ? (
          <>
            <b className="font-medium">The map is out of date with the code:</b> {mapProblems.join(" · ")}
          </>
        ) : (
          <b className="font-medium">{top!.title}</b>
        )}
        {next && <span className="opacity-80"> · Next step: {next}</span>}
      </p>
      {failure && onShowFailure && (
        <Button size="sm" variant="outline" className="shrink-0 bg-card" onClick={onShowFailure}>
          Show me
        </Button>
      )}
      <button type="button" onClick={onOpenReview} className="flex shrink-0 items-center gap-0.5 text-xs font-medium hover:underline">
        Review{count ? ` · ${count}` : ""} <ChevronRight className="size-3.5" />
      </button>
    </div>
  );
}
