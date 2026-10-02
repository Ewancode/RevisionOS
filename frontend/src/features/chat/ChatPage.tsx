import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { BookOpen, GraduationCap, Lightbulb, MessageSquarePlus, NotebookPen, Send, Square, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { MathMarkdown } from "@/components/MathMarkdown";
import { Button, ConfirmDelete, ErrorText } from "@/components/ui";
import { useBudget } from "@/features/documents/queries";
import { useModule } from "@/features/structure/queries";

import {
  ask,
  dismissLiveError,
  stopAnswer,
  useConversation,
  useConversations,
  useCreateConversation,
  useDeleteConversation,
  useLiveAnswer,
  usePendingActionMutations,
  type ChatMessage,
  type Citation,
  type LiveAnswer,
  type PendingAction,
} from "./queries";

const CITE_HREF = /^#(?:user-content-)?cite-(\d+)$/;

const PROVENANCE: Record<string, { label: string; icon: ReactNode; className: string }> = {
  university: {
    label: "From your university material",
    icon: <GraduationCap size={12} />,
    className: "border-accent text-accent",
  },
  own: { label: "From your notes", icon: <NotebookPen size={12} />, className: "border-border" },
  general: {
    label: "General knowledge — not from your materials",
    icon: <Lightbulb size={12} />,
    className: "border-border text-muted",
  },
};

function ProvenanceBadges({ provenance }: { provenance: string[] }) {
  return (
    <ul aria-label="Where this answer comes from" className="flex flex-wrap gap-1.5">
      {provenance.map((p) => {
        const badge = PROVENANCE[p];
        if (!badge) return null;
        return (
          <li key={p} className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${badge.className}`}>
            {badge.icon}
            {badge.label}
          </li>
        );
      })}
    </ul>
  );
}

function citationTitle(c: Citation) {
  return `${c.filename} — page ${c.page_no}`;
}

/** Answer text, with `[[n]](#cite-n)` markers drawn as links to the cited page. */
function AnswerText({ content, citations }: { content: string; citations: Citation[] }) {
  return (
    <MathMarkdown
      className="text-sm"
      components={{
        a({ href, children }) {
          const match = href ? CITE_HREF.exec(href) : null;
          if (match) {
            const citation = citations[Number(match[1]) - 1];
            if (!citation) return null;
            return (
              <Link
                to="/doc/$documentId"
                params={{ documentId: citation.document_id }}
                search={{ page: citation.page_no }}
                title={citationTitle(citation)}
                aria-label={`Source ${citation.n}: ${citationTitle(citation)}`}
                className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-surface px-1 align-super text-[10px] font-semibold text-accent no-underline hover:underline"
              >
                {citation.n}
              </Link>
            );
          }
          return (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          );
        },
      }}
    >
      {content}
    </MathMarkdown>
  );
}

function Sources({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null;
  return (
    <section aria-label="Sources" className="flex flex-col gap-1 border-t border-border pt-2">
      <h3 className="text-xs font-medium text-muted">Sources</h3>
      <ol className="flex flex-col gap-1 text-xs">
        {citations.map((c) => (
          <li key={c.n} className="flex gap-2">
            <span className="w-4 shrink-0 text-right font-semibold text-accent">{c.n}</span>
            <span className="min-w-0">
              <Link
                to="/doc/$documentId"
                params={{ documentId: c.document_id }}
                search={{ page: c.page_no }}
                className="font-medium hover:underline"
              >
                {citationTitle(c)}
              </Link>
              <span className="text-muted">
                {" "}
                · {c.module_code} · {c.source_tier === "university" ? "University material" : "My notes"}
                {c.heading_path && ` · ${c.heading_path}`}
              </span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function ActionCard({ action, conversationId }: { action: PendingAction; conversationId: string }) {
  const { confirm, cancel } = usePendingActionMutations(conversationId);
  const busy = confirm.isPending || cancel.isPending;
  const done: Record<string, string> = {
    confirmed: "Deleted. You can restore it from Settings › Trash.",
    cancelled: "Cancelled. Nothing was deleted.",
    expired: "This request expired. Nothing was deleted; ask again if you still want it.",
  };
  return (
    <div role="group" aria-label="Deletion request" className="flex flex-col gap-2 rounded-md border border-danger p-3 text-sm">
      <p>{action.preview}</p>
      {action.status === "pending" ? (
        <div className="flex gap-2">
          <Button size="sm" variant="danger" disabled={busy} onClick={() => confirm.mutate(action.id)}>
            <Trash2 size={14} /> Delete
          </Button>
          <Button size="sm" disabled={busy} onClick={() => cancel.mutate(action.id)}>
            Keep it
          </Button>
        </div>
      ) : (
        <p className="text-xs text-muted">{done[action.status]}</p>
      )}
      <ErrorText error={confirm.error ?? cancel.error} />
    </div>
  );
}

function Steps({ steps }: { steps: string[] }) {
  if (!steps.length) return null;
  return (
    <details className="text-xs text-muted">
      <summary className="cursor-pointer select-none">
        {steps.length === 1 ? steps[0] : `${steps.length} steps`}
      </summary>
      <ul className="mt-1 list-disc pl-5">
        {steps.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ul>
    </details>
  );
}

function UserBubble({ children }: { children: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] whitespace-pre-wrap rounded-lg bg-surface px-3 py-2 text-sm">{children}</p>
    </div>
  );
}

function AssistantMessage({ message, conversationId }: { message: ChatMessage; conversationId: string }) {
  return (
    <article aria-label="Claude's answer" className="flex flex-col gap-2">
      <Steps steps={message.steps} />
      {message.content && <AnswerText content={message.content} citations={message.citations} />}
      {message.status === "stopped" && <p className="text-xs text-muted">Stopped.</p>}
      {message.status === "error" && (
        <p role="alert" className="text-sm text-danger">
          {message.error_code === "ai_refused"
            ? "Claude declined to answer this."
            : message.error_code === "ai_budget_reached"
              ? "Your AI budget is used up; the assistant resumes when it resets."
              : "The answer failed. Try again."}
        </p>
      )}
      {(message.actions ?? []).map((a) => (
        <ActionCard key={a.id} action={a} conversationId={conversationId} />
      ))}
      <Sources citations={message.citations} />
      {message.status !== "error" && message.provenance.length > 0 && (
        <ProvenanceBadges provenance={message.provenance} />
      )}
    </article>
  );
}

function LiveMessage({ answer, conversationId }: { answer: LiveAnswer; conversationId: string }) {
  const working = !answer.error && !answer.stopped;
  return (
    <>
      <UserBubble>{answer.question}</UserBubble>
      <article aria-label="Claude's answer" aria-busy={working} className="flex flex-col gap-2">
        {answer.statuses.length > 0 && (
          <p role="status" className="text-xs text-muted">
            {answer.statuses.at(-1)}…
          </p>
        )}
        {answer.text && <MathMarkdown className="text-sm">{answer.text}</MathMarkdown>}
        {answer.actions.map((a) => (
          <ActionCard key={a.id} action={a} conversationId={conversationId} />
        ))}
        {answer.error && (
          <div className="flex items-center gap-3">
            <p role="alert" className="text-sm text-danger">
              {answer.error.message}
            </p>
            {answer.error.status !== 200 && (
              <Button size="sm" variant="ghost" onClick={() => dismissLiveError(conversationId)}>
                Dismiss
              </Button>
            )}
          </div>
        )}
      </article>
    </>
  );
}

function BudgetLine() {
  const budget = useBudget();
  const b = budget.data;
  if (!b) return null;
  if (!b.configured) {
    return <p className="text-xs text-danger">Claude is not configured: add ANTHROPIC_API_KEY to .env and restart.</p>;
  }
  const money = (n: number) => new Intl.NumberFormat("en-GB", { style: "currency", currency: b.currency }).format(n);
  return (
    <p className={`text-xs ${b.warning ? "text-danger" : "text-muted"}`}>
      AI spend today {money(b.spent_today)} of {money(b.daily_cap)} ·{" "}
      <Link to="/usage" className="hover:underline">
        usage
      </Link>
    </p>
  );
}

function Composer({
  onSend,
  busy,
  onStop,
  autoFocus,
}: {
  onSend: (text: string) => Promise<unknown> | void;
  busy: boolean;
  onStop?: () => void;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState("");
  const send = () => {
    const question = text.trim();
    if (!question || busy) return;
    setText("");
    void onSend(question);
  };
  return (
    <form
      className="flex flex-col gap-1.5"
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      <div className="flex items-end gap-2">
        <textarea
          aria-label="Ask about your materials"
          placeholder="Ask about your lectures… (Enter to send, Shift+Enter for a new line)"
          rows={2}
          autoFocus={autoFocus}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
          className="max-h-48 min-h-11 flex-1 resize-y rounded-lg border border-border bg-bg px-3 py-2 text-sm"
        />
        {busy && onStop ? (
          <Button onClick={onStop} aria-label="Stop the answer">
            <Square size={14} /> Stop
          </Button>
        ) : (
          <Button type="submit" variant="primary" disabled={busy || !text.trim()} aria-label="Send">
            <Send size={14} />
          </Button>
        )}
      </div>
      <BudgetLine />
    </form>
  );
}

function ConversationList({ activeId }: { activeId?: string }) {
  const conversations = useConversations();
  const remove = useDeleteConversation();
  const navigate = useNavigate();
  const [deleting, setDeleting] = useState<{ id: string; title: string } | null>(null);
  return (
    <nav aria-label="Conversations" className="flex flex-col gap-1 md:w-60 md:shrink-0">
      <Link
        to="/chat"
        search={{}}
        className="mb-1 inline-flex items-center gap-2 rounded-md border border-border px-2 py-1.5 text-sm font-medium hover:bg-surface"
      >
        <MessageSquarePlus size={16} /> New conversation
      </Link>
      <ul className="flex max-h-48 flex-col gap-0.5 overflow-y-auto md:max-h-none">
        {conversations.data?.map((c) => (
          <li key={c.id} className="group flex items-center">
            <Link
              to="/chat/$conversationId"
              params={{ conversationId: c.id }}
              className={`min-w-0 flex-1 truncate rounded-md px-2 py-1.5 text-sm hover:bg-surface ${
                c.id === activeId ? "bg-surface font-medium" : ""
              }`}
            >
              {c.title}
            </Link>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Delete conversation ${c.title}`}
              className="opacity-0 focus:opacity-100 group-hover:opacity-100"
              onClick={() => setDeleting({ id: c.id, title: c.title })}
            >
              <Trash2 size={14} />
            </Button>
          </li>
        ))}
      </ul>
      <ConfirmDelete
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        thing={`the conversation “${deleting?.title ?? ""}”`}
        detail="Conversations are deleted permanently. Your files and notes are not affected."
        onConfirm={async () => {
          if (!deleting) return;
          await remove.mutateAsync(deleting.id);
          if (deleting.id === activeId) await navigate({ to: "/chat", search: {} });
        }}
      />
    </nav>
  );
}

const SUGGESTIONS = [
  "Where did my lecturer explain this week's main theorem?",
  "Summarise the key definitions from my latest lecture",
  "What files do I have for each module?",
];

function NewConversation({ moduleId }: { moduleId?: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const create = useCreateConversation();
  const module = useModule(moduleId ?? "", moduleId !== undefined);

  const start = async (question: string) => {
    const conversation = await create.mutateAsync(moduleId ? { module_id: moduleId } : {});
    void ask(qc, conversation.id, question);
    await navigate({ to: "/chat/$conversationId", params: { conversationId: conversation.id } });
  };

  return (
    <div className="flex flex-1 flex-col gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">Ask Claude</h1>
      <p className="text-sm text-muted">
        Answers come from your uploaded materials first, with links to the exact pages. When your materials
        don't cover something, Claude says so.
      </p>
      {moduleId && (
        <p className="flex items-center gap-2 text-sm">
          <BookOpen size={14} /> Asking about{" "}
          {module.data ? `${module.data.code} ${module.data.title}` : "one module"}
          <Link to="/chat" search={{}} className="text-xs text-muted hover:underline">
            (ask about everything)
          </Link>
        </p>
      )}
      <ul className="flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <li key={s}>
            <button
              type="button"
              disabled={create.isPending}
              onClick={() => void start(s)}
              className="rounded-full border border-border px-3 py-1 text-xs hover:bg-surface"
            >
              {s}
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-auto">
        <Composer onSend={start} busy={create.isPending} autoFocus />
        <ErrorText error={create.error} />
      </div>
    </div>
  );
}

function Thread({ conversationId }: { conversationId: string }) {
  const qc = useQueryClient();
  const conversation = useConversation(conversationId);
  const liveAnswer = useLiveAnswer(conversationId);
  const end = useRef<HTMLDivElement>(null);
  const all = conversation.data?.messages ?? [];
  // While an answer streams, its saved copy (once refetched) is not shown twice.
  const messages = liveAnswer ? all.slice(0, liveAnswer.baseline) : all;
  const streaming = liveAnswer !== undefined && !liveAnswer.error && !liveAnswer.stopped;

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length, liveAnswer?.text, liveAnswer?.statuses.length]);

  if (conversation.isPending) return <p className="text-sm text-muted">Loading…</p>;
  if (conversation.isError) return <ErrorText error={conversation.error} />;

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-4">
      <h1 className="truncate text-lg font-semibold">{conversation.data.title}</h1>
      <div className="flex flex-col gap-5">
        {messages.map((m) =>
          m.role === "user" ? (
            <UserBubble key={m.id}>{m.content}</UserBubble>
          ) : (
            <AssistantMessage key={m.id} message={m} conversationId={conversationId} />
          ),
        )}
        {liveAnswer && <LiveMessage answer={liveAnswer} conversationId={conversationId} />}
        <div ref={end} />
      </div>
      <div className="sticky bottom-0 mt-auto bg-bg pb-2 pt-2">
        <Composer
          busy={streaming}
          onStop={() => stopAnswer(conversationId)}
          onSend={(question) => ask(qc, conversationId, question)}
        />
      </div>
    </div>
  );
}

export function ChatPage({ conversationId, moduleId }: { conversationId?: string; moduleId?: string }) {
  return (
    <div className="flex min-h-[calc(100vh-3rem)] max-w-5xl flex-col gap-6 md:flex-row">
      <ConversationList activeId={conversationId} />
      {conversationId ? (
        <Thread key={conversationId} conversationId={conversationId} />
      ) : (
        <NewConversation key={moduleId ?? "all"} moduleId={moduleId} />
      )}
    </div>
  );
}
