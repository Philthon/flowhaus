import { Check, Copy } from "lucide-react";
import { useState } from "react";

import type { Settings } from "@/lib/api";
import { cn } from "@/lib/utils";

export const AGENT_PROMPT = "Set up Flowhaus for my automations. Follow AGENTS.md.";

function CopyLine({ text, label, mono = true }: { text: string; label: string; mono?: boolean }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the text is selectable */
    }
  };
  return (
    <div className="flex items-stretch border border-border bg-background">
      <code className={cn("min-w-0 flex-1 select-all overflow-x-auto px-3 py-2 text-[13px] whitespace-nowrap", !mono && "font-sans")}>
        {text}
      </code>
      <button
        onClick={copy}
        className="flex shrink-0 items-center gap-1 border-l border-border px-2.5 text-xs text-muted-foreground hover:text-foreground"
        aria-label={`Copy ${label}`}
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

const MARKS = [
  <circle key="c" cx="6" cy="6" r="5" fill="var(--bauhaus-blue)" />,
  <rect key="s" x="1" y="1" width="10" height="10" fill="var(--bauhaus-red)" />,
  <path key="t" d="M6 1 L11 11 L1 11 Z" fill="var(--bauhaus-yellow)" />,
];

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="grid grid-cols-[20px_minmax(0,1fr)] gap-x-3 gap-y-1.5">
      <svg viewBox="0 0 12 12" className="mt-1 size-3" aria-hidden>
        {MARKS[n % 3]}
      </svg>
      <p className="font-medium">
        <span className="mr-1.5 text-muted-foreground tabular-nums">{n + 1}.</span>
        {title}
      </p>
      <div className="col-start-2 space-y-2 text-sm text-muted-foreground">{children}</div>
    </li>
  );
}

/** How to connect the first (or next) automation. Written for handing the work to a coding agent. */
export function OnboardingGuide({
  settings,
  waiting,
  onExploreDemo,
}: {
  settings: Settings | null;
  waiting: boolean;
  onExploreDemo?: () => void;
}) {
  const errors = Object.entries(settings?.automation_errors ?? {});
  return (
    <div className="space-y-6">
      <div className="space-y-1.5">
        <h2 className="text-xl font-medium tracking-tight">{waiting ? "Onboard your first automation" : "Connect another automation"}</h2>
        <p className="max-w-prose text-sm text-muted-foreground">
          Flowhaus draws the automations you already run as a plain-English map: what came in, what came out, what was skipped and why.
          It works with GitHub Actions workflows, scripts that save a folder per run, and anything else through a small adapter. It only
          reads them; it never runs or changes them.
        </p>
      </div>

      <ol className="space-y-5">
        <Step n={0} title="Open this folder in your coding agent">
          <p>Claude Code, Codex, Cursor or any agent that can run commands.</p>
          {settings && <CopyLine text={settings.project_dir} label="folder path" />}
        </Step>
        <Step n={1} title="Ask it to set things up">
          <CopyLine text={AGENT_PROMPT} label="prompt" mono={false} />
          <p>
            It finds what you already run, asks which ones to connect, writes the map in plain words and checks it against your real
            runs. It asks before anything sensitive, and your settings stay on this computer.
          </p>
        </Step>
        <Step n={2} title="Watch it appear here">
          {waiting ? (
            <p className="flex items-center gap-2">
              <span className="relative flex size-2">
                <span className="absolute inline-flex size-full animate-ping bg-[var(--bauhaus-blue)] opacity-60" />
                <span className="relative inline-flex size-2 bg-[var(--bauhaus-blue)]" />
              </span>
              Waiting for your first automation. This page updates by itself.
            </p>
          ) : (
            <p>New automations show up on the Flows page by themselves.</p>
          )}
        </Step>
      </ol>

      {errors.length > 0 && (
        <div className="space-y-1 border border-red-200 bg-red-50 p-3 text-sm text-red-900">
          <p className="font-medium">Some automation settings couldn't be read:</p>
          {errors.map(([folder, msg]) => (
            <p key={folder} className="font-mono text-xs break-all">
              {msg}
            </p>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border pt-4 text-xs text-muted-foreground">
        <span>
          Prefer the terminal? <code className="font-mono">uv run flowhaus scan</code>, then <code className="font-mono">flowhaus add</code>.
          See <span className="font-mono">docs/automations.md</span>.
        </span>
        {onExploreDemo && (
          <button className="ml-auto underline underline-offset-2 hover:text-foreground" onClick={onExploreDemo}>
            Explore demo flows first
          </button>
        )}
      </div>
    </div>
  );
}
