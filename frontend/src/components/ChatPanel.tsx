import { useEffect, useRef, useState } from "react";
import { CircleCheck, Send, Sparkles, TriangleAlert, X } from "lucide-react";
import {
  api,
  ApiError,
  type ChatMessageOut,
  type ChatOut,
  type ChatToolCallOut,
  type Uuid,
} from "@/api/client";
import { Button } from "@/components/ui/button";

// ---------------------------------------------------------------------------
// A reply is flagged as a partial-success/interruption (PRD §17-18 — a
// mutating tool call already persisted before a later step in the same
// turn failed, e.g. a provider rate limit) by this exact phrase, which
// app/ai/chat_service.py's _interrupted_result always includes. Matching on
// it avoids duplicating that classification logic on the frontend.
// ---------------------------------------------------------------------------

const INTERRUPTED_MARKER = "You may want to check the result.";

function isInterrupted(reply: string): boolean {
  return reply.includes(INTERRUPTED_MARKER);
}

// Mutating tools the chat agent exposes (app/ai/tools/chat_tools.py
// MUTATING_TOOLS) — mirrored here since persisted history rows only store
// the full tool_calls list, not a pre-filtered "changes" list like the live
// POST /api/chat response does.
const MUTATING_TOOLS = new Set(["add_validation", "remove_validation", "update_test_body"]);

function deriveChanges(toolCalls: ChatToolCallOut[] | null | undefined): ChatToolCallOut[] {
  if (!toolCalls) return [];
  return toolCalls.filter((tc) => MUTATING_TOOLS.has(tc.tool) && !tc.error);
}

function describeChange(tc: ChatToolCallOut, testNamesById: Record<Uuid, string>): string {
  const rawTestId = tc.arguments.test_id;
  const testId = typeof rawTestId === "string" ? rawTestId : undefined;
  const testName = testId ? (testNamesById[testId] ?? "a test") : "a test";
  switch (tc.tool) {
    case "add_validation":
      return `Added a validation to '${testName}'`;
    case "remove_validation":
      return `Removed a validation from '${testName}'`;
    case "update_test_body":
      return `Updated '${testName}' test body`;
    default:
      return `${tc.tool} on '${testName}'`;
  }
}

// ---------------------------------------------------------------------------
// ask_user (Phase C) — the assistant asking a clarifying question instead
// of guessing. Not a mutation, so it's derived separately from `changes`.
// ---------------------------------------------------------------------------

interface AskUserPrompt {
  question: string;
  options: string[];
}

function deriveAskUser(toolCalls: ChatToolCallOut[] | null | undefined): AskUserPrompt | null {
  if (!toolCalls) return null;
  const call = toolCalls.find((tc) => tc.tool === "ask_user" && !tc.error);
  if (!call) return null;
  const { question, options } = call.arguments as { question?: unknown; options?: unknown };
  if (typeof question !== "string" || !Array.isArray(options)) return null;
  const stringOptions = options.filter((o): o is string => typeof o === "string");
  if (stringOptions.length === 0) return null;
  return { question, options: stringOptions };
}

function messageFromChatError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 404) return "This suite couldn't be found.";
    // detail is the raw provider error text (app/ai/chat_service.py),
    // shown to the user as-is rather than paraphrased.
    return e.detail || "The assistant ran into a problem and couldn't reply. Try again.";
  }
  return "Couldn't reach the assistant. Check your connection and try again.";
}

// ---------------------------------------------------------------------------
// One row in the message list. `pending`/`failed` cover an in-flight or
// failed *user* message (optimistically rendered before the server
// responds); persisted rows (from history or a successful reply) are
// always `role: "user" | "assistant"` with no local-only state.
// ---------------------------------------------------------------------------

interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  changes?: ChatToolCallOut[];
  askUser?: AskUserPrompt | null;
  interrupted?: boolean;
  pending?: boolean;
  failed?: boolean;
}

function MessageBubble({
  message,
  testNamesById,
  onOptionSelect,
  optionsDisabled,
}: {
  message: DisplayMessage;
  testNamesById: Record<Uuid, string>;
  /** Sends *text* as the next user message, exactly as if typed. */
  onOptionSelect: (text: string) => void;
  optionsDisabled: boolean;
}) {
  const isUser = message.role === "user";

  return (
    <div className={`flex animate-fade-in-up ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[85%] space-y-1.5 ${isUser ? "items-end" : "items-start"} flex flex-col`}>
        <div className={`flex items-end gap-2 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
          {!isUser && (
            <span className="mb-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ai-gradient text-white shadow-sm">
              <Sparkles className="h-3 w-3" strokeWidth={2.5} />
            </span>
          )}
          <div
            className={[
              "rounded-2xl px-3.5 py-2.5 text-sm whitespace-pre-wrap break-words shadow-sm",
              isUser
                ? "bg-primary text-primary-foreground rounded-br-sm"
                : message.interrupted
                  ? "bg-warning-bg border border-warning-border text-foreground rounded-bl-sm"
                  : "bg-muted text-foreground rounded-bl-sm",
              message.pending ? "opacity-60" : "",
            ].join(" ")}
          >
            {message.content}
          </div>
        </div>

        {message.failed && (
          <p className="text-xs text-destructive px-1">Failed to send.</p>
        )}

        {message.interrupted && (
          <p className="text-xs text-warning px-1 flex items-center gap-1">
            <TriangleAlert className="h-3 w-3" /> Interrupted before finishing — double-check the result below.
          </p>
        )}

        {message.changes && message.changes.length > 0 && (
          <div className="space-y-1 pl-1">
            {message.changes.map((tc, i) => (
              <p key={i} className="text-xs text-success px-2 py-1 rounded-md bg-success-bg/60 flex items-center gap-1.5 w-fit">
                <CircleCheck className="h-3 w-3 shrink-0" /> {describeChange(tc, testNamesById)}
              </p>
            ))}
          </div>
        )}

        {message.askUser && (
          <div className="flex flex-wrap gap-1.5 pl-1">
            {message.askUser.options.map((opt) => (
              <button
                key={opt}
                type="button"
                disabled={optionsDisabled}
                onClick={() => onOptionSelect(opt)}
                className="rounded-full border border-primary/30 bg-accent/60 px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-accent disabled:opacity-50"
              >
                {opt}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ChatWaitingIndicator() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="flex items-center gap-2.5 rounded-2xl rounded-bl-sm border border-primary/15 bg-accent/60 px-3.5 py-2.5 text-xs animate-fade-in-up ml-8">
      <span className="flex gap-1" aria-hidden="true">
        <span className="h-1.5 w-1.5 rounded-full bg-primary animate-bounce [animation-delay:-0.3s]" />
        <span className="h-1.5 w-1.5 rounded-full bg-primary animate-bounce [animation-delay:-0.15s]" />
        <span className="h-1.5 w-1.5 rounded-full bg-primary animate-bounce" />
      </span>
      <div className="min-w-0">
        <div className="text-foreground font-medium">Thinking…</div>
        <div className="text-muted-foreground">Can take 10-30+ seconds.</div>
      </div>
      <span className="text-muted-foreground ml-auto shrink-0 font-mono tabular-nums">{elapsed}s</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel — a floating dock in the bottom-right corner (PRD §25.3 "AI
// Assistant Panel"), toggled open/closed rather than a permanent column,
// since the rest of the page is a fixed max-w-5xl single-column layout with
// no existing side-panel slot to fit into. Styled as the product's flagship
// AI surface — gradient header, glowing launcher, polished bubbles.
// ---------------------------------------------------------------------------

export function ChatPanel({
  suiteId,
  testNamesById,
  onChangesApplied,
}: {
  suiteId: Uuid;
  /** test_id -> name, so a change summary can name the test rather than
   *  showing a raw id (SuiteDetailPage already maintains this map). */
  testNamesById: Record<Uuid, string>;
  /** Called once per reply that included at least one successful change,
   *  so the suite page can refetch test data without a manual reload. */
  onChangesApplied: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);

  // History loads on page open (independent of the panel being expanded)
  // so it's ready the moment the user opens the panel.
  useEffect(() => {
    let cancelled = false;
    api
      .getChatHistory(suiteId)
      .then((rows: ChatMessageOut[]) => {
        if (cancelled) return;
        setMessages(
          rows.map((row) => ({
            id: row.id,
            role: row.role,
            content: row.content,
            changes: deriveChanges(row.tool_calls),
            askUser: deriveAskUser(row.tool_calls),
            interrupted: row.role === "assistant" && isInterrupted(row.content),
          }))
        );
      })
      .catch(() => {
        // Silent — worst case, the panel opens empty and the conversation
        // continues from there; nothing else on the page depends on this.
      })
      .finally(() => {
        if (!cancelled) setHistoryLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [suiteId]);

  useEffect(() => {
    if (open) listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, open, sending]);

  function sendMessage(overrideText?: string) {
    const text = (overrideText ?? input).trim();
    if (!text || sending) return;

    const localId = `local-${Date.now()}`;
    setMessages((prev) => [...prev, { id: localId, role: "user", content: text, pending: true }]);
    if (overrideText === undefined) setInput("");
    setSending(true);

    api
      .sendChatMessage(suiteId, text)
      .then((result: ChatOut) => {
        setMessages((prev) => [
          ...prev.map((m) => (m.id === localId ? { ...m, pending: false } : m)),
          {
            id: `assistant-${Date.now()}`,
            role: "assistant",
            content: result.reply,
            changes: result.changes,
            askUser: deriveAskUser(result.tool_calls),
            interrupted: isInterrupted(result.reply),
          },
        ]);
        if (result.changes.length > 0) onChangesApplied();
      })
      .catch((e: unknown) => {
        setMessages((prev) => [
          ...prev.map((m) => (m.id === localId ? { ...m, pending: false, failed: true } : m)),
          {
            id: `assistant-error-${Date.now()}`,
            role: "assistant",
            content: messageFromChatError(e),
          },
        ]);
      })
      .finally(() => setSending(false));
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full ai-gradient bg-[length:160%_160%] px-5 py-3.5 text-sm font-semibold text-white shadow-[var(--shadow-glow)] transition-all duration-200 hover:scale-105 hover:bg-[position:100%_0] active:scale-100"
      >
        <Sparkles className="h-4 w-4" strokeWidth={2.5} />
        AI Assistant
      </button>
    );
  }

  return (
    <div className="fixed bottom-5 right-5 z-40 flex h-[34rem] w-96 max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-2xl border border-primary/15 bg-card shadow-[var(--shadow-panel)] animate-scale-in origin-bottom-right">
      {/* Header */}
      <div className="ai-gradient flex items-center justify-between px-4 py-3.5 shrink-0">
        <span className="flex items-center gap-2 text-sm font-semibold text-white">
          <Sparkles className="h-4 w-4" strokeWidth={2.5} />
          AI Assistant
        </span>
        <button
          onClick={() => setOpen(false)}
          className="flex h-7 w-7 items-center justify-center rounded-full text-white/90 transition-colors hover:bg-white/15 hover:text-white"
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Message list */}
      <div ref={listRef} className="flex-1 overflow-y-auto px-3.5 py-3.5 space-y-3.5 bg-gradient-to-b from-accent/20 to-transparent">
        {!historyLoaded ? (
          <div className="space-y-2 animate-pulse">
            <div className="h-8 bg-muted rounded-2xl w-2/3" />
            <div className="h-8 bg-muted rounded-2xl w-1/2 ml-auto" />
          </div>
        ) : messages.length === 0 ? (
          <div className="text-center py-8 px-2">
            <span className="mx-auto flex h-10 w-10 items-center justify-center rounded-full ai-gradient text-white shadow-md shadow-primary/30 mb-3">
              <Sparkles className="h-5 w-5" />
            </span>
            <p className="text-xs text-muted-foreground">
              Ask about this suite's endpoints and tests, or ask the assistant to
              add/remove a validation or fix a failing test's request body.
            </p>
          </div>
        ) : (
          messages.map((m) => (
            <MessageBubble
              key={m.id}
              message={m}
              testNamesById={testNamesById}
              onOptionSelect={sendMessage}
              optionsDisabled={sending}
            />
          ))
        )}
        {sending && <ChatWaitingIndicator />}
      </div>

      {/* Input */}
      <div className="border-t border-border p-2.5 shrink-0 space-y-1.5 bg-card">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={sending}
            rows={2}
            placeholder="Ask the assistant…"
            className="flex-1 resize-none rounded-xl border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring/50 focus:border-primary disabled:opacity-60 transition-all"
          />
          <Button
            size="icon"
            variant="brand"
            onClick={sendMessage}
            disabled={sending || !input.trim()}
            aria-label="Send message"
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
