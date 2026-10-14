import { AlertTriangle, ExternalLink, GitPullRequest, Loader2, ShieldQuestion, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { api, type Change } from "@/lib/api";

import { DiffView } from "./ChatPanel";

/** A change the chat prepared. The pull request opens only when the user clicks the button. */
export function ProposalCard({ change: initial }: { change: Change }) {
  const [change, setChange] = useState(initial);
  const [busy, setBusy] = useState<"pr" | "discard" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const act = async (kind: "pr" | "discard") => {
    setBusy(kind);
    setError(null);
    try {
      setChange(kind === "pr" ? await api.openPullRequest(change.id) : await api.discardChange(change.id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="space-y-2 border border-border bg-card p-3 text-sm">
      <div className="flex items-start gap-2">
        <GitPullRequest className="mt-0.5 size-4 shrink-0 text-[var(--bauhaus-blue)]" />
        <div className="min-w-0">
          <p className="font-medium">{change.title}</p>
          <p className="text-xs text-muted-foreground">
            Proposed change to {change.repo} · {change.files.length} {change.files.length === 1 ? "file" : "files"} · into {change.base}
          </p>
        </div>
      </div>
      {change.summary && <p className="text-[13px] whitespace-pre-wrap text-muted-foreground">{change.summary}</p>}
      <ReviewNotes change={change} />
      {change.warnings.map((w) => (
        <p key={w} className="flex items-start gap-1.5 bg-amber-50 px-2 py-1 text-xs text-amber-900">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {w}
        </p>
      ))}
      {change.diff && <DiffView diff={change.diff} label="Review the change" />}
      {error && <p className="bg-red-50 px-2 py-1 text-xs text-red-800">{error}</p>}
      {change.status === "proposed" && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button size="sm" onClick={() => act("pr")} disabled={!!busy}>
            {busy === "pr" ? <Loader2 className="animate-spin" /> : <GitPullRequest />} Open pull request
          </Button>
          <Button size="sm" variant="ghost" onClick={() => act("discard")} disabled={!!busy}>
            <Trash2 /> Discard
          </Button>
          <span className="text-xs text-muted-foreground">Nothing is sent to GitHub until you open it.</span>
        </div>
      )}
      {change.status === "opened" && change.pr_url && (
        <a href={change.pr_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs underline">
          Pull request opened <ExternalLink className="size-3" />
        </a>
      )}
      {change.status === "discarded" && <p className="text-xs text-muted-foreground">Discarded.</p>}
    </div>
  );
}

/** The harness's review: a change to one step reaches every step after it. */
function ReviewNotes({ change }: { change: Change }) {
  const r = change.review ?? {};
  const touched = r.touched ?? [];
  const after = r.downstream ?? [];
  if (!touched.length && !after.length && !change.impact && !r.repeats?.length && !r.log_lines?.length && !r.unmapped_files?.length)
    return null;
  return (
    <div className="space-y-1.5 border-l-2 border-[var(--bauhaus-blue)] pl-2.5 text-xs">
      {touched.length > 0 && (
        <p>
          <span className="text-muted-foreground">Changes </span>
          {touched.map((t) => t.label).join(", ")}
          {after.length > 0 && (
            <>
              <span className="text-muted-foreground">, and can affect everything after it: </span>
              {after.map((t) => t.label).join(" → ")}
            </>
          )}
        </p>
      )}
      {r.unmapped_files && r.unmapped_files.length > 0 && (
        <p className="text-muted-foreground">
          Not linked to a step in the map: {r.unmapped_files.join(", ")} (shared code can affect several steps).
        </p>
      )}
      {change.impact && (
        <p>
          <span className="text-muted-foreground">Expected effect: </span>
          {change.impact}
        </p>
      )}
      {r.repeats?.map((x) => (
        <p key={x.file + x.same_as} className="text-amber-900">
          Repeats code that already exists in {x.same_as}: consider reusing it (one source of truth).
        </p>
      ))}
      {r.log_lines?.map((x) => (
        <p key={x.line} className="text-amber-900">
          Changes a log line the map counts for “{x.label}”: update the counting rule too, or that step will look empty.
        </p>
      ))}
    </div>
  );
}

export type ApprovalRequest = { id: string; server: string; tool: string; input: string; answered?: boolean | "expired" };

/** Claude wants to call a tool from one of your MCP servers: it waits for this answer. */
export function ApprovalCard({ request, onAnswered }: { request: ApprovalRequest; onAnswered: (allow: boolean | "expired") => void }) {
  const [error, setError] = useState<string | null>(null);
  const answer = async (allow: boolean) => {
    try {
      await api.answerApproval(request.id, allow);
      onAnswered(allow);
    } catch (e) {
      setError((e as Error).message);
      onAnswered("expired");
    }
  };
  return (
    <div className="space-y-2 border border-amber-300 bg-amber-50/60 p-3 text-sm dark:bg-amber-950/30">
      <p className="flex items-center gap-1.5 font-medium">
        <ShieldQuestion className="size-4 text-amber-700" /> Allow Claude to use <code className="font-mono">{request.tool}</code> on{" "}
        <b>{request.server}</b>?
      </p>
      <pre className="max-h-40 overflow-auto bg-background/70 p-2 font-mono text-[11px]">{request.input}</pre>
      {request.answered === undefined ? (
        <div className="flex gap-2">
          <Button size="sm" onClick={() => answer(true)}>
            Allow once
          </Button>
          <Button size="sm" variant="outline" onClick={() => answer(false)}>
            Deny
          </Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          {request.answered === true ? "Allowed." : request.answered === false ? "Denied." : "No longer waiting."}
        </p>
      )}
      {error && <p className="text-xs text-red-800">{error}</p>}
    </div>
  );
}
