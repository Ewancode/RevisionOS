import { Link } from "@tanstack/react-router";
import { Camera, CheckCircle2, CircleDashed, Clock, Gavel, Lightbulb, RefreshCw, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { MathMarkdown } from "@/components/MathMarkdown";
import { Button, ErrorText, Modal } from "@/components/ui";
import { HintLadder } from "@/features/coding/HintLadder";
import { useQuestionHints } from "@/features/coding/queries";
import type { ApiError } from "@/lib/api/client";

import {
  DIFFICULTIES,
  QUESTION_TYPES,
  label,
  uploadPhoto,
  useAttempt,
  useAttemptActions,
  type Attempt,
  type AttemptItem,
} from "./queries";

type Response = Record<string, unknown> | null;
const WRITTEN = new Set(["explanation", "derivation"]);
const SAVE_DELAY_MS = 600;
const input = "h-9 rounded-md border border-border bg-bg px-2 text-sm";

function pct(score: number | null | undefined) {
  return score === null || score === undefined ? "—" : `${Math.round(score * 100)}%`;
}

// --- answering --------------------------------------------------------------------------------

/** Your answer so far, as text, so the tutor's hint can respond to it. */
function workText(item: AttemptItem, response: Response): string {
  if (!response) return "";
  const view = item.view as { options?: string[] };
  if (typeof response.choice === "number") return `Chose: ${view.options?.[response.choice] ?? response.choice}`;
  if (typeof response.answer === "boolean") return `Answered: ${response.answer ? "true" : "false"}`;
  return Object.values(response)
    .filter((v) => typeof v === "string" || typeof v === "number")
    .join("\n");
}

/** The tutor's hint ladder for one question (practice quizzes, not exams). */
function QuestionHints({ attemptId, item, response }: { attemptId: string; item: AttemptItem; response: Response }) {
  const [open, setOpen] = useState(false);
  const { query, next } = useQuestionHints(attemptId, item.question_id, open);
  if (!open) {
    return (
      <div>
        <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
          <Lightbulb size={14} /> Stuck? Get a hint
        </Button>
      </div>
    );
  }
  return (
    <HintLadder
      hints={query.data}
      pending={next.isPending}
      error={next.error ?? query.error}
      onNext={() => next.mutate({ work: workText(item, response).slice(0, 20_000) })}
    />
  );
}

function AnswerInput({
  item,
  value,
  onChange,
  attemptId,
}: {
  item: AttemptItem;
  value: Response;
  onChange: (response: Response) => void;
  attemptId: string;
}) {
  const view = item.view as { options?: string[]; unit?: string | null; variables?: string[]; marks?: number };
  const name = `q-${item.question_id}`;
  switch (item.type) {
    case "multiple_choice":
      return (
        <fieldset className="flex flex-col gap-1">
          <legend className="sr-only">Choose one</legend>
          {(view.options ?? []).map((option, i) => (
            <label key={i} className="flex items-start gap-2 rounded-md px-2 py-1 hover:bg-surface">
              <input
                type="radio"
                name={name}
                className="mt-1"
                checked={value?.choice === i}
                onChange={() => onChange({ choice: i })}
              />
              <MathMarkdown className="text-sm">{option}</MathMarkdown>
            </label>
          ))}
        </fieldset>
      );
    case "true_false":
      return (
        <fieldset className="flex gap-4">
          <legend className="sr-only">True or false</legend>
          {[true, false].map((v) => (
            <label key={String(v)} className="flex items-center gap-2 text-sm">
              <input type="radio" name={name} checked={value?.answer === v} onChange={() => onChange({ answer: v })} />
              {v ? "True" : "False"}
            </label>
          ))}
        </fieldset>
      );
    case "numerical":
      return (
        <div className="flex flex-wrap items-center gap-2">
          <input
            aria-label="Your answer"
            className={input}
            placeholder="e.g. 0.117 or 15/128"
            value={String(value?.value ?? "")}
            onChange={(e) => onChange(e.target.value ? { ...value, value: e.target.value } : null)}
          />
          {view.unit && (
            <input
              aria-label="Unit"
              className={`${input} w-28`}
              placeholder={`unit (${view.unit})`}
              value={String(value?.unit ?? "")}
              onChange={(e) => onChange({ value: String(value?.value ?? ""), unit: e.target.value || null })}
            />
          )}
        </div>
      );
    case "expression":
      return (
        <div className="flex flex-col gap-1">
          <input
            aria-label="Your answer"
            className={`${input} font-mono`}
            placeholder="e.g. x^2 e^x"
            value={String(value?.expression ?? "")}
            onChange={(e) => onChange(e.target.value ? { expression: e.target.value } : null)}
          />
          <p className="text-xs text-muted">
            In terms of {(view.variables ?? []).join(", ")}. Use ^ for powers; sqrt, exp, ln, sin… work.
          </p>
        </div>
      );
    case "short_answer":
      return (
        <input
          aria-label="Your answer"
          className={input}
          value={String(value?.text ?? "")}
          onChange={(e) => onChange(e.target.value ? { text: e.target.value } : null)}
        />
      );
    default:
      return (
        <WrittenAnswer
          item={item}
          attemptId={attemptId}
          text={String(value?.text ?? "")}
          onText={(text) => onChange(text ? { text } : null)}
          marks={view.marks}
        />
      );
  }
}

function WrittenAnswer({
  item,
  attemptId,
  text,
  onText,
  marks,
}: {
  item: AttemptItem;
  attemptId: string;
  text: string;
  onText: (text: string) => void;
  marks?: number;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [transcribed, setTranscribed] = useState<{ markdown: string; notes: string } | null>(null);
  return (
    <div className="flex flex-col gap-2">
      <textarea
        aria-label="Your answer"
        className="min-h-32 rounded-md border border-border bg-bg p-2 font-mono text-sm"
        placeholder="Markdown with LaTeX ($...$) — or upload a photo of your working"
        value={text}
        onChange={(e) => onText(e.target.value)}
      />
      {text.includes("$") && <MathMarkdown className="rounded-md bg-surface p-2 text-sm">{text}</MathMarkdown>}
      <div className="flex items-center gap-2 text-xs text-muted">
        {marks !== undefined && <span>{marks} marks</span>}
        <label className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-border px-2 py-1 hover:bg-surface">
          <Camera size={12} /> {busy ? "Reading your working…" : item.has_photo ? "Replace photo" : "Photo of your working"}
          <input
            type="file"
            accept="image/*"
            className="sr-only"
            disabled={busy}
            onChange={async (e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (!file) return;
              setBusy(true);
              setError(null);
              try {
                const result = await uploadPhoto(attemptId, item.question_id, file);
                setTranscribed({ markdown: result.markdown, notes: result.notes });
              } catch (err) {
                setError(err);
              } finally {
                setBusy(false);
              }
            }}
          />
        </label>
      </div>
      <ErrorText error={error} />
      {transcribed && (
        <div className="flex flex-col gap-2 rounded-md border border-border p-2">
          <p className="text-xs font-medium">Claude read your photo as — check it before using it:</p>
          <MathMarkdown className="text-sm">{transcribed.markdown}</MathMarkdown>
          {transcribed.notes && <p className="text-xs text-danger">{transcribed.notes}</p>}
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="primary"
              onClick={() => {
                onText(text ? `${text}\n\n${transcribed.markdown}` : transcribed.markdown);
                setTranscribed(null);
              }}
            >
              Use this
            </Button>
            <Button size="sm" onClick={() => setTranscribed(null)}>
              Discard
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function Countdown({ deadline, onTimeUp }: { deadline: string; onTimeUp: () => void }) {
  const [left, setLeft] = useState(() => new Date(deadline).getTime() - Date.now());
  const fired = useRef(false);
  useEffect(() => {
    const timer = setInterval(() => {
      const ms = new Date(deadline).getTime() - Date.now();
      setLeft(ms);
      if (ms <= 0 && !fired.current) {
        fired.current = true;
        onTimeUp();
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [deadline, onTimeUp]);
  const seconds = Math.max(0, Math.floor(left / 1000));
  const text = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  return (
    <p
      role="timer"
      aria-label={`Time left: ${text}`}
      className={`flex items-center gap-1 font-mono text-sm ${seconds < 300 ? "text-danger" : ""}`}
    >
      <Clock size={14} /> {text}
    </p>
  );
}

function Answering({ attempt }: { attempt: Attempt }) {
  const { save, submit } = useAttemptActions(attempt.id);
  const [responses, setResponses] = useState<Record<string, Response>>(() =>
    Object.fromEntries(attempt.items.map((i) => [i.question_id, (i.response ?? null) as Response])),
  );
  const [confirming, setConfirming] = useState(false);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const spent = useRef<Record<string, number>>(Object.fromEntries(attempt.items.map((i) => [i.question_id, i.time_ms ?? 0])));
  const focusedAt = useRef<{ id: string; at: number } | null>(null);

  const persist = (questionId: string, response: Response) => {
    clearTimeout(timers.current[questionId]);
    timers.current[questionId] = setTimeout(() => {
      save.mutate({ questionId, body: { response, time_ms: Math.round(spent.current[questionId] ?? 0) } });
    }, SAVE_DELAY_MS);
  };
  const track = (id: string | null) => {
    const now = Date.now();
    if (focusedAt.current) spent.current[focusedAt.current.id] = (spent.current[focusedAt.current.id] ?? 0) + now - focusedAt.current.at;
    focusedAt.current = id ? { id, at: now } : null;
  };
  const unanswered = attempt.items.filter((i) => responses[i.question_id] === null).length;

  return (
    <div className="flex flex-col gap-4">
      {attempt.mode === "exam" && (
        <p className="rounded-md bg-surface px-3 py-2 text-sm">
          Exam conditions: AI help is off until you submit, and the exam submits itself when time runs out.
        </p>
      )}
      <ol className="flex flex-col gap-4">
        {attempt.items.map((item) => (
          <li
            key={item.question_id}
            className="flex flex-col gap-3 rounded-lg border border-border p-4"
            onFocusCapture={() => track(item.question_id)}
            onBlurCapture={() => track(null)}
          >
            <p className="text-xs text-muted">
              Question {item.position + 1} · {label(QUESTION_TYPES, item.type)} · {label(DIFFICULTIES, item.difficulty)}
            </p>
            <MathMarkdown className="text-sm">{item.stem_md}</MathMarkdown>
            <AnswerInput
              item={item}
              attemptId={attempt.id}
              value={responses[item.question_id] ?? null}
              onChange={(response) => {
                setResponses((r) => ({ ...r, [item.question_id]: response }));
                persist(item.question_id, response);
              }}
            />
            {attempt.mode === "normal" && (
              <QuestionHints attemptId={attempt.id} item={item} response={responses[item.question_id] ?? null} />
            )}
          </li>
        ))}
      </ol>
      <ErrorText error={save.error} />
      <div>
        <Button variant="primary" onClick={() => setConfirming(true)}>
          Submit quiz
        </Button>
      </div>
      <Modal
        open={confirming}
        onOpenChange={setConfirming}
        title="Submit the quiz?"
        description={
          unanswered
            ? `${unanswered} question${unanswered === 1 ? " is" : "s are"} unanswered. You can't change answers after submitting.`
            : "You can't change answers after submitting."
        }
      >
        <ErrorText error={submit.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={() => setConfirming(false)}>Keep going</Button>
          <Button
            variant="primary"
            disabled={submit.isPending}
            onClick={async () => {
              Object.values(timers.current).forEach(clearTimeout);
              await Promise.all(
                attempt.items.map((i) =>
                  save.mutateAsync({
                    questionId: i.question_id,
                    body: { response: responses[i.question_id] ?? null, time_ms: Math.round(spent.current[i.question_id] ?? 0) },
                  }),
                ),
              );
              await submit.mutateAsync();
              setConfirming(false);
            }}
          >
            Submit
          </Button>
        </div>
      </Modal>
    </div>
  );
}

// --- results --------------------------------------------------------------------------------------

function yourAnswer(item: AttemptItem): string {
  const r = item.response as Record<string, unknown> | null;
  if (!r) return "(no answer)";
  const view = item.view as { options?: string[] };
  if (item.type === "multiple_choice") return view.options?.[Number(r.choice)] ?? "?";
  if (item.type === "true_false") return r.answer ? "True" : "False";
  if (item.type === "numerical") return `${String(r.value)}${r.unit ? ` ${String(r.unit)}` : ""}`;
  if (item.type === "expression") return String(r.expression);
  return String(r.text ?? "");
}

const MARKED_BY: Record<string, string> = {
  rule: "Marked exactly",
  sympy: "Checked with SymPy",
  ai: "Marked by Claude",
  override: "Your mark",
};

function ResultItem({ item, attemptId }: { item: AttemptItem; attemptId: string }) {
  const { dispute, override } = useAttemptActions(attemptId);
  const [mark, setMark] = useState("");
  const feedback = (item.feedback ?? {}) as {
    summary?: string;
    unmarked?: string;
    points?: { point: string; marks: number; awarded: number; comment: string }[];
    explanation?: Record<"why_wrong" | "correct_answer" | "reasoning" | "mistake" | "how_to_avoid", string>;
  };
  const score = item.score;
  const icon =
    score === null || score === undefined ? (
      <CircleDashed size={16} className="text-muted" />
    ) : score >= 0.999 ? (
      <CheckCircle2 size={16} className="text-success" />
    ) : (
      <XCircle size={16} className="text-danger" />
    );
  const canDispute = item.marked_by === "ai" || (score === null && WRITTEN.has(item.type));
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border p-4">
      <p className="flex items-center gap-2 text-sm font-medium">
        {icon} Question {item.position + 1} · {pct(score)}
        <span className="text-xs font-normal text-muted">
          {item.marked_by ? MARKED_BY[item.marked_by] : "Not marked"}
          {item.marking_confidence && ` (${item.marking_confidence} confidence)`}
        </span>
      </p>
      <MathMarkdown className="text-sm">{item.stem_md}</MathMarkdown>
      <div className="rounded-md bg-surface p-2 text-sm">
        <p className="text-xs text-muted">Your answer</p>
        <MathMarkdown>{yourAnswer(item)}</MathMarkdown>
      </div>
      {feedback.unmarked && <p className="text-sm text-danger">{feedback.unmarked}</p>}
      {feedback.summary && <p className="text-sm">{feedback.summary}</p>}
      {feedback.points && (
        <ul className="flex flex-col gap-1 text-xs">
          {feedback.points.map((p, i) => (
            <li key={i}>
              <span className="font-medium">
                {p.awarded}/{p.marks}
              </span>{" "}
              {p.point}
              {p.comment && <span className="text-muted"> — {p.comment}</span>}
            </li>
          ))}
        </ul>
      )}
      {feedback.explanation && (
        <dl className="grid gap-1 border-l-2 border-danger pl-3 text-sm">
          <dt className="text-xs text-muted">Why it was wrong</dt>
          <dd><MathMarkdown>{feedback.explanation.why_wrong}</MathMarkdown></dd>
          <dt className="text-xs text-muted">The correct answer</dt>
          <dd><MathMarkdown>{feedback.explanation.correct_answer}</MathMarkdown></dd>
          <dt className="text-xs text-muted">The reasoning</dt>
          <dd><MathMarkdown>{feedback.explanation.reasoning}</MathMarkdown></dd>
          {feedback.explanation.mistake && (
            <>
              <dt className="text-xs text-muted">The mistake</dt>
              <dd><MathMarkdown>{feedback.explanation.mistake}</MathMarkdown></dd>
            </>
          )}
          <dt className="text-xs text-muted">How to avoid it</dt>
          <dd><MathMarkdown>{feedback.explanation.how_to_avoid}</MathMarkdown></dd>
        </dl>
      )}
      <details className="text-sm">
        <summary className="cursor-pointer text-xs text-muted">Correct answer and worked solution</summary>
        <div className="mt-2 flex flex-col gap-2">
          {item.correct_answer && (
            <p className="text-sm">
              <span className="text-muted">Answer: </span>
              <MathMarkdown>{item.correct_answer}</MathMarkdown>
            </p>
          )}
          <MathMarkdown className="text-sm">{item.solution_md ?? ""}</MathMarkdown>
          {(item.sources ?? []).map((s, i) => (
            <Link
              key={i}
              to="/doc/$documentId"
              params={{ documentId: String(s.document_id) }}
              search={{ page: Number(s.page_no) }}
              className="text-xs text-muted hover:underline"
            >
              From {String(s.filename)} p.{String(s.page_no)}
            </Link>
          ))}
        </div>
      </details>
      {item.question_attempt_id && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {canDispute && (
            <Button
              size="sm"
              variant="ghost"
              disabled={dispute.isPending}
              onClick={() => dispute.mutate(item.question_attempt_id ?? "")}
              title="Re-mark with Claude's stronger model"
            >
              <Gavel size={12} /> {dispute.isPending ? "Re-marking…" : "Dispute mark"}
            </Button>
          )}
          <form
            className="flex items-center gap-1"
            onSubmit={(e) => {
              e.preventDefault();
              const value = Number(mark);
              if (Number.isFinite(value) && value >= 0 && value <= 100) {
                override.mutate({ answerId: item.question_attempt_id ?? "", score: value / 100 });
                setMark("");
              }
            }}
          >
            <input
              aria-label="Your mark, in percent"
              placeholder="%"
              inputMode="numeric"
              className="h-7 w-14 rounded-md border border-border bg-bg px-1"
              value={mark}
              onChange={(e) => setMark(e.target.value)}
            />
            <Button size="sm" type="submit" variant="ghost">
              Set mark
            </Button>
          </form>
        </div>
      )}
      <ErrorText error={(dispute.error ?? override.error) as ApiError | null} />
    </li>
  );
}

function Results({ attempt }: { attempt: Attempt }) {
  const s = attempt.summary;
  return (
    <div className="flex flex-col gap-5">
      {attempt.status === "marking" && (
        <p role="status" className="flex items-center gap-2 text-sm">
          <RefreshCw size={14} className="animate-spin" /> Claude is marking your written answers and explaining
          mistakes…
        </p>
      )}
      {s && (
        <section aria-label="Summary" className="flex flex-col gap-3">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {[
              ["Score", pct(s.score)],
              ["Correct", String(s.correct)],
              ["Partly right", String(s.partial)],
              ["Wrong", String(s.incorrect)],
              ["Time", s.time_taken_seconds !== null && s.time_taken_seconds !== undefined ? `${Math.round(s.time_taken_seconds / 60)} min` : "—"],
            ].map(([k, v]) => (
              <div key={k} className="rounded-lg border border-border p-3">
                <dt className="text-xs text-muted">{k}</dt>
                <dd className="text-lg font-semibold tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
          {s.unmarked > 0 && <p className="text-sm text-muted">{s.unmarked} answer(s) not marked yet.</p>}
          <div className="grid gap-4 sm:grid-cols-2">
            {[
              ["By difficulty", s.by_difficulty],
              ["By topic", s.by_topic],
            ].map(([title, rows]) => (
              <table key={String(title)} className="text-sm">
                <caption className="text-left text-xs font-medium text-muted">{String(title)}</caption>
                <tbody>
                  {(rows as typeof s.by_topic).map((b) => (
                    <tr key={b.key} className="border-t border-border">
                      <td className="py-1">{b.label}</td>
                      <td className="py-1 text-right tabular-nums text-muted">{b.questions}</td>
                      <td className="py-1 text-right tabular-nums">{pct(b.score)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ))}
          </div>
          {s.weak_areas.length > 0 && <p className="text-sm">Weak areas: {s.weak_areas.join(", ")}.</p>}
          {s.next_steps.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold">Next steps</h2>
              <ul className="list-disc pl-5 text-sm">
                {s.next_steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}
      <ol className="flex flex-col gap-3">
        {attempt.items.map((item) => (
          <ResultItem key={item.question_id} item={item} attemptId={attempt.id} />
        ))}
      </ol>
    </div>
  );
}

export function AttemptPage({ attemptId }: { attemptId: string }) {
  const attempt = useAttempt(attemptId);
  const { submit } = useAttemptActions(attemptId);
  if (attempt.isPending) return <p className="text-sm text-muted">Loading…</p>;
  if (attempt.isError) return <ErrorText error={attempt.error} />;
  const a = attempt.data;
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          {a.quiz.module_id ? (
            <Link
              to="/modules/$moduleId/questions"
              params={{ moduleId: a.quiz.module_id }}
              className="text-sm text-muted hover:underline"
            >
              Questions and quizzes
            </Link>
          ) : (
            <Link to="/" className="text-sm text-muted hover:underline">
              Today
            </Link>
          )}
          <h1 className="text-2xl font-semibold tracking-tight">{a.quiz.title}</h1>
        </div>
        {a.status === "in_progress" && a.deadline && (
          <Countdown
            deadline={a.deadline}
            onTimeUp={() => submit.mutate(undefined, { onSettled: () => void attempt.refetch() })}
          />
        )}
      </header>
      {a.status === "in_progress" ? <Answering attempt={a} /> : <Results attempt={a} />}
    </div>
  );
}
