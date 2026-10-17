import { ArrowUp, Check, ChevronDown, Loader2, PanelLeftClose, RotateCcw, Sparkles, Square, Target, Wrench, X } from "lucide-react";
import { useCallback, useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";

import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { Message, MessageContent, MessageResponse } from "@/components/ai-elements/message";
import { Button } from "@/components/ui/button";
import { api, type Change, type NextSteps, type Settings } from "@/lib/api";

import { type ApprovalRequest, ApprovalCard, ProposalCard } from "./ChangeCards";
import { NextStepCard } from "./NextStepCard";
import { useTerms } from "@/lib/terms";
import { cn } from "@/lib/utils";

type ToolStep = { label: string; done: boolean; narration?: boolean };
type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  text: string;
  scope?: string | null;
  tools: ToolStep[];
  notes: string[];
  error?: string;
  pending?: boolean;
  canUndo?: boolean;
  diff?: string;
  proposal?: Change;
  approvals?: ApprovalRequest[];
  /** Flowhaus's own check of a change the chat made (a replay of the last real run), not the chat's judgement. */
  check?: { same: boolean; summary: string; examples: string[] };
};

export type ChatHandle = { ask: (text: string) => void };

type Props = {
  ref?: Ref<ChatHandle>;
  flowId: string | null;
  isSample: boolean;
  isConnected?: boolean;
  onFlowCreated?: (flowId: string) => void;
  onBusyChange?: (busy: boolean) => void;
  onCollapse?: () => void;
  selected: { id: string; label: string } | null;
  runId: string | null;
  onClearSelection: () => void;
  onRun: (runId: string, flowId?: string) => void;
  onMapChanged: () => void;
  /** What to fix first in the run you're looking at (from the page's checkup): the chat's opener. */
  plan?: NextSteps | null;
};

const STARTERS_NONE = [
  "Explain this flow in plain English",
  "What happened in the last run?",
  "Which step skips the most items?",
];
const STARTERS_NODE = ["What does this do?", "Why were items skipped here?"];
const STARTERS_LIVE_NODE = [...STARTERS_NODE, "Allow plus signs in emails"];
const startersConnected = (items: string) => ["What happened in this run?", `Why were ${items} skipped?`, `How could it skip fewer ${items}?`];
const STARTERS_SAMPLE = ["Explain this flow in plain English", "What happened in the last run?", "What would you change to skip fewer items?"];

let nextId = 1;

export function ChatPanel({ ref, flowId, isSample, isConnected, selected, runId, onClearSelection, onRun, onMapChanged, onFlowCreated, onBusyChange, onCollapse, plan }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [canUndo, setCanUndo] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    onBusyChange?.(busy);
  }, [busy, onBusyChange]);

  useEffect(() => {
    fetch("/api/chat/status")
      .then((r) => r.json())
      .then((s) => setCanUndo(!!s.can_undo))
      .catch(() => {});
  }, []);

  const update = (id: number, fn: (m: ChatMessage) => ChatMessage) =>
    setMessages((ms) => ms.map((m) => (m.id === id ? fn(m) : m)));

  const stream = useCallback(
    async (url: string, body: unknown, userText: string | null) => {
      if (busy) return;
      setBusy(true);
      const assistantId = nextId++;
      setMessages((ms) => [
        ...ms,
        ...(userText != null
          ? [{ id: nextId++, role: "user" as const, text: userText, scope: selected?.label ?? null, tools: [], notes: [] }]
          : []),
        { id: assistantId, role: "assistant", text: "", tools: [], notes: [], pending: true },
      ]);
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
          signal: controller.signal,
        });
        if (!res.ok || !res.body) {
          const detail = await res.json().then((b) => b.detail).catch(() => null);
          throw new Error(typeof detail === "string" ? detail : `the server answered ${res.status}`);
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.trim()) continue;
            const ev = JSON.parse(line);
            if (ev.type === "text") update(assistantId, (m) => ({ ...m, text: m.text + ev.text }));
            else if (ev.type === "tool")
              // Text written before a tool call is the agent thinking out loud: tuck it into the step list
              // so the visible answer is only what it says after its last action.
              update(assistantId, (m) => ({
                ...m,
                text: "",
                tools: [
                  ...m.tools.map((t) => ({ ...t, done: true })),
                  ...(m.text.trim() ? [{ label: m.text.trim(), done: true, narration: true }] : []),
                  { label: ev.label, done: false },
                ],
              }));
            else if (ev.type === "flow_created") {
              onFlowCreated?.(ev.flow_id);
              update(assistantId, (m) => ({ ...m, notes: [...m.notes, `Created the flow “${ev.name}”`] }));
            } else if (ev.type === "run") {
              onRun(ev.run_id, ev.flow_id);
              update(assistantId, (m) => ({
                ...m,
                notes: [...m.notes, ev.status === "success" ? "Ran the flow again" : "Ran the flow again — it failed"],
              }));
            } else if (ev.type === "map_changed") {
              onMapChanged();
              if (ev.files?.length)
                update(assistantId, (m) => ({ ...m, notes: [...m.notes, "Updated the flow and its map"], diff: ev.diff || undefined }));
            } else if (ev.type === "problems")
              update(assistantId, (m) => ({ ...m, notes: [...m.notes, `Map problems: ${ev.problems.join("; ")}`] }));
            else if (ev.type === "proposal") update(assistantId, (m) => ({ ...m, proposal: ev.change }));
            else if (ev.type === "check")
              update(assistantId, (m) => ({ ...m, check: { same: ev.same, summary: ev.summary, examples: ev.examples ?? [] } }));
            else if (ev.type === "approval")
              update(assistantId, (m) => ({
                ...m,
                approvals: [...(m.approvals ?? []), { id: ev.id, server: ev.server, tool: ev.tool, input: ev.input }],
              }));
            else if (ev.type === "approval_done")
              update(assistantId, (m) => ({
                ...m,
                approvals: (m.approvals ?? []).map((a) => (a.id === ev.id && a.answered === undefined ? { ...a, answered: "expired" } : a)),
              }));
            else if (ev.type === "error") update(assistantId, (m) => ({ ...m, error: ev.message }));
            else if (ev.type === "done") {
              setCanUndo(!!ev.can_undo);
              update(assistantId, (m) => ({ ...m, canUndo: !!ev.changed && !!ev.can_undo }));
            }
          }
        }
      } catch (e) {
        if ((e as Error).name !== "AbortError")
          update(assistantId, (m) => ({ ...m, error: `Could not reach the chat: ${(e as Error).message}` }));
      } finally {
        update(assistantId, (m) => ({ ...m, pending: false, tools: m.tools.map((t) => ({ ...t, done: true })) }));
        setBusy(false);
        abortRef.current = null;
      }
    },
    [busy, selected, onRun, onMapChanged, onFlowCreated],
  );

  const send = useCallback(
    (text: string) => {
      const message = text.trim();
      if (!message) return;
      setInput("");
      stream("/api/chat", { message, selected_node_id: selected?.id ?? null, run_id: runId, flow_id: flowId }, message);
    },
    [stream, selected, runId, flowId],
  );

  useImperativeHandle(ref, () => ({ ask: send }), [send]);


  const undo = () => stream("/api/chat/undo", { run_id: runId }, "Undo the last change");
  const newChat = async () => {
    await fetch("/api/chat/reset", { method: "POST" }).then((r) => r.text());
    setMessages([]);
    setCanUndo(false);
  };

  const terms = useTerms();
  const starters = !flowId
    ? []
    : selected
      ? flowId === "contact-cleaning"
        ? STARTERS_LIVE_NODE
        : STARTERS_NODE
      : isConnected
        ? startersConnected(terms.items)
        : isSample
        ? STARTERS_SAMPLE
        : STARTERS_NONE;

  return (
    <aside className="flex h-full min-h-0 flex-col border-r bg-background" aria-label="Chat">
      <header className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4" />
          <h2 className="font-semibold">Chat</h2>
          <EnginePicker disabled={busy} />
        </div>
        <div className="flex gap-1">
          {canUndo && !isSample && (
            <Button variant="ghost" size="sm" onClick={undo} disabled={busy} title="Undo the last change the chat made">
              <RotateCcw /> Undo change
            </Button>
          )}
          {messages.length > 0 && (
            <Button variant="ghost" size="sm" onClick={newChat} disabled={busy}>
              New chat
            </Button>
          )}
          {onCollapse && (
            <Button variant="ghost" size="icon" onClick={onCollapse} title="Fold the chat away" aria-label="Fold the chat away">
              <PanelLeftClose />
            </Button>
          )}
        </div>
      </header>

      <Conversation className="min-h-0">
        <ConversationContent className="gap-5">
          {flowId && plan?.first && <div className="pt-4"><NextStepCard plan={plan} onSolve={send} /></div>}
          {messages.length === 0 && !plan?.first && (
            <div className="space-y-4 pt-6 text-sm">
              <p className="text-muted-foreground">
                Ask about the flow, or ask for a change in plain English. Select a box on the map first to talk about
                just that step.
                {isSample && " This is a sample flow: the chat explains it and proposes changes, but can't apply them yet."}
                {isConnected && " This is your real automation, shown read-only: the chat can read its code and runs, explain them and propose changes."}
              </p>
            </div>
          )}
          {messages.map((m) => (
            <Message key={m.id} from={m.role}>
              {m.role === "user" && m.scope && (
                <span className="ml-auto flex items-center gap-1 text-[11px] text-muted-foreground">
                  <Target className="size-3" /> {m.scope}
                </span>
              )}
              <MessageContent>
                {m.role === "assistant" && m.tools.length > 0 && (
                  <ul className="space-y-1 text-xs text-muted-foreground">
                    {collapseTools(m.tools).map((t, i) =>
                      t.narration ? (
                        <li key={i} className="line-clamp-2 pl-5 italic">
                          {t.label}
                        </li>
                      ) : (
                        <li key={i} className="flex items-center gap-1.5">
                          {t.done ? <Check className="size-3.5 shrink-0 text-emerald-600" /> : <Loader2 className="size-3.5 shrink-0 animate-spin" />}
                          {t.label}
                        </li>
                      ),
                    )}
                  </ul>
                )}
                {m.role === "assistant" ? (
                  m.text ? (
                    <MessageResponse>{m.text}</MessageResponse>
                  ) : m.pending && !m.tools.length ? (
                    <span className="flex items-center gap-2 text-muted-foreground">
                      <Loader2 className="size-4 animate-spin" /> Thinking…
                    </span>
                  ) : null
                ) : (
                  <p className="whitespace-pre-wrap">{m.text}</p>
                )}
                {m.notes.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {m.notes.map((n, i) => (
                      <span key={i} className="flex items-center gap-1 px-0 py-0.5 text-[11px] text-emerald-700 dark:text-emerald-400">
                        <Wrench className="size-3" /> {n}
                      </span>
                    ))}
                  </div>
                )}
                {m.diff && <DiffView diff={m.diff} />}
                {m.approvals?.map((a) => (
                  <ApprovalCard
                    key={a.id}
                    request={a}
                    onAnswered={(allow) =>
                      update(m.id, (x) => ({ ...x, approvals: x.approvals?.map((y) => (y.id === a.id ? { ...y, answered: allow } : y)) }))
                    }
                  />
                ))}
                {m.check && (
                  <div className={cn("space-y-1 border-l-2 pl-2.5 text-xs", m.check.same ? "border-emerald-600" : "border-amber-500")}>
                    <p className="text-[10px] font-medium tracking-[0.12em] text-muted-foreground uppercase">Checked by Flowhaus</p>
                    <p>{m.check.summary}</p>
                    {m.check.examples.map((x) => (
                      <p key={x} className="text-muted-foreground">
                        {x}
                      </p>
                    ))}
                  </div>
                )}
                {m.proposal && <ProposalCard change={m.proposal} />}
                {m.error && <p className="rounded bg-red-50 px-2 py-1 text-xs text-red-800 dark:bg-red-950 dark:text-red-200">{m.error}</p>}
              </MessageContent>
            </Message>
          ))}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      <div className="space-y-2 border-t p-3">
        {!busy && (
          <div className="flex flex-wrap gap-1.5">
            {starters.map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                className="border border-border bg-card px-2.5 py-1 text-left text-xs text-muted-foreground hover:border-input hover:text-foreground"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        {selected && (
          <div className="flex w-fit max-w-full items-center gap-1.5 rounded-md border border-sky-200 bg-sky-50 py-0.5 pr-0.5 pl-2 text-xs text-sky-900 dark:border-sky-800 dark:bg-sky-950 dark:text-sky-100">
            <Target className="size-3.5 shrink-0" />
            <span className="truncate">
              Talking about: <b>{selected.label}</b>
            </span>
            <button
              onClick={onClearSelection}
              className="rounded p-0.5 hover:bg-sky-100 dark:hover:bg-sky-900"
              aria-label="Stop talking about this step"
            >
              <X className="size-3.5" />
            </button>
          </div>
        )}
        <form
          className="flex items-end gap-2 border border-input bg-card p-1.5 focus-within:border-sky-500"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                send(input);
              }
            }}
            rows={2}
            placeholder={!flowId ? "Describe the flow you want…" : selected ? `Ask about "${selected.label}"…` : "Ask about the flow or request a change…"}
            className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-1.5 py-1 text-sm outline-none"
            disabled={busy}
          />
          {busy ? (
            <Button
              type="button"
              size="icon"
              variant="secondary"
              onClick={() => {
                fetch("/api/chat/stop", { method: "POST" }).catch(() => {});
                abortRef.current?.abort();
              }}
              aria-label="Stop"
              title="Stop the chat"
            >
              <Square />
            </Button>
          ) : (
            <Button type="submit" size="icon" disabled={!input.trim()} aria-label="Send">
              <ArrowUp />
            </Button>
          )}
        </form>
      </div>
    </aside>
  );
}

export function DiffView({ diff, label = "what changed in the code" }: { diff: string; label?: string }) {
  const [open, setOpen] = useState(false);
  const files = diff.split("\n").filter((l) => l.startsWith("+++ b/")).map((l) => l.slice(6));
  return (
    <div className="text-xs">
      <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1 text-muted-foreground hover:text-foreground">
        <ChevronDown className={open ? "size-3.5 rotate-180 transition-transform" : "size-3.5 transition-transform"} />
        {open ? "Hide" : "Show"} {label} ({files.join(", ")})
      </button>
      {open && (
        <pre className="mt-1 max-h-72 overflow-auto rounded-md border bg-muted/40 p-2 font-mono text-[11px] leading-snug">
          {diff.split("\n").map((line, i) => (
            <div
              key={i}
              className={
                line.startsWith("+") && !line.startsWith("+++")
                  ? "bg-emerald-100 text-emerald-950 dark:bg-emerald-950 dark:text-emerald-100"
                  : line.startsWith("-") && !line.startsWith("---")
                    ? "bg-red-100 text-red-950 dark:bg-red-950 dark:text-red-100"
                    : line.startsWith("@@")
                      ? "text-sky-700 dark:text-sky-300"
                      : ""
              }
            >
              {line || " "}
            </div>
          ))}
        </pre>
      )}
    </div>
  );
}

/** "Trying Firecrawl: reading a", "Trying Firecrawl: reading b", … → one line with a count. */
function collapseTools(tools: ToolStep[]): ToolStep[] {
  const out: (ToolStep & { n?: number })[] = [];
  for (const t of tools) {
    const key = t.narration ? null : t.label.split(":")[0];
    const prev = out.at(-1);
    if (key && prev && !prev.narration && prev.label.split(":")[0] === key && key !== t.label) {
      const n = (prev.n ?? 1) + 1;
      out[out.length - 1] = { ...t, n, label: `${key} (${n}×): ${t.label.split(":").slice(1).join(":").trim()}` };
    } else out.push({ ...t });
  }
  return out;
}


/** Which agent answers: Claude or Codex. Same tools, same rules; Codex needs its CLI and a sign-in. */
function EnginePicker({ disabled }: { disabled: boolean }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.settings().then(setSettings).catch(() => {});
  }, []);
  if (!settings) return null;
  const codexReady = settings.codex.available && settings.codex.signed_in;
  const pick = async (engine: "claude" | "codex") => {
    try {
      setSettings(await api.updateSettings({ chat_engine: engine }));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <span className="relative flex items-center gap-1 text-xs text-muted-foreground">
      with
      <select
        value={settings.chat_engine}
        disabled={disabled}
        onChange={(e) => pick(e.target.value as "claude" | "codex")}
        className="border border-border bg-background px-1 py-0.5 text-xs text-foreground"
        aria-label="Which agent runs the chat"
        title={codexReady ? "Claude and Codex use the same tools and rules" : `Codex: ${settings.codex.why}`}
      >
        <option value="claude">Claude</option>
        <option value="codex" disabled={!codexReady && settings.chat_engine !== "codex"}>
          Codex{codexReady ? "" : " (not set up)"}
        </option>
      </select>
      {error && <span className="text-red-700 dark:text-red-400">{error}</span>}
    </span>
  );
}

