import { Link, useNavigate } from "@tanstack/react-router";
import { Archive, ArchiveRestore, Play, Sparkles, Timer } from "lucide-react";
import { useState } from "react";

import { MathMarkdown } from "@/components/MathMarkdown";
import { Button, ErrorText } from "@/components/ui";
import { useModule, useTopicTree } from "@/features/structure/queries";

import { flattenTopics, GenerateDialog } from "./GenerateDialog";
import {
  DIFFICULTIES,
  QUESTION_TYPES,
  label,
  useAttempts,
  useQuestions,
  useStartQuiz,
  useUpdateQuestion,
  type BankFilters,
  type Difficulty,
  type Question,
  type QuestionType,
  type QuizCreate,
} from "./queries";
import { ModuleHeader } from "./StudySection";

const select = "h-8 rounded-md border border-border bg-bg px-2 text-sm";

function result(q: Question) {
  if (q.last_score === null || q.last_score === undefined) return { text: "Not tried", className: "text-muted" };
  const pct = Math.round(q.last_score * 100);
  return {
    text: `Last: ${pct}% (${q.attempts} attempt${q.attempts === 1 ? "" : "s"})`,
    className: q.last_score >= 0.999 ? "text-success" : "text-danger",
  };
}

function QuestionRow({
  question,
  checked,
  onToggle,
}: {
  question: Question;
  checked: boolean;
  onToggle: (on: boolean) => void;
}) {
  const update = useUpdateQuestion();
  const r = result(question);
  const retired = question.status === "retired";
  return (
    <li className="flex gap-3 rounded-lg border border-border p-3">
      <input
        type="checkbox"
        className="mt-1"
        aria-label="Select question"
        checked={checked}
        disabled={retired}
        onChange={(e) => onToggle(e.target.checked)}
      />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="flex flex-wrap gap-x-2 text-xs text-muted">
          <span>{label(QUESTION_TYPES, question.type)}</span>·<span>{label(DIFFICULTIES, question.difficulty)}</span>·
          <span className={r.className}>{r.text}</span>
          {question.origin === "claude" && <span>· Claude generated</span>}
        </p>
        <div className="max-h-32 overflow-hidden">
          <MathMarkdown className="text-sm">{question.stem_md}</MathMarkdown>
        </div>
        {question.sources.length > 0 && (
          <p className="text-xs text-muted">
            From{" "}
            {question.sources.map((s, i) => (
              <span key={i}>
                {i > 0 && ", "}
                <Link
                  to="/doc/$documentId"
                  params={{ documentId: String(s.document_id) }}
                  search={{ page: Number(s.page_no) }}
                  className="hover:underline"
                >
                  {String(s.filename)} p.{String(s.page_no)}
                </Link>
              </span>
            ))}
          </p>
        )}
      </div>
      <Button
        size="sm"
        variant="ghost"
        aria-label={retired ? "Bring back" : "Retire"}
        title={retired ? "Bring back into practice" : "Retire (keeps your attempts)"}
        onClick={() => update.mutate({ id: question.id, body: { status: retired ? "active" : "retired" } })}
      >
        {retired ? <ArchiveRestore size={14} /> : <Archive size={14} />}
      </Button>
    </li>
  );
}

function History({ moduleId }: { moduleId: string }) {
  const attempts = useAttempts(moduleId);
  if (!attempts.data?.length) return null;
  return (
    <section aria-labelledby="history" className="flex flex-col gap-2">
      <h2 id="history" className="text-base font-semibold">
        Your quizzes
      </h2>
      <ul className="flex flex-col gap-1">
        {attempts.data.map((a) => (
          <li key={a.id}>
            <Link
              to="/attempts/$attemptId"
              params={{ attemptId: a.id }}
              className="flex items-baseline justify-between gap-2 rounded-md px-2 py-1 text-sm hover:bg-surface"
            >
              <span>
                {a.title}
                {a.mode === "exam" && <span className="text-xs text-muted"> · exam conditions</span>}
              </span>
              <span className="text-xs text-muted">
                {a.status === "in_progress"
                  ? "in progress"
                  : a.status === "marking"
                    ? "being marked"
                    : a.score !== null && a.score !== undefined
                      ? `${Math.round(a.score * 100)}%`
                      : "marked"}
                {" · "}
                {a.questions} questions · {new Date(a.started_at).toLocaleDateString("en-GB")}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function QuestionBankPage({ moduleId }: { moduleId: string }) {
  const module = useModule(moduleId);
  const topics = useTopicTree(moduleId);
  const [filters, setFilters] = useState<BankFilters>({ result: "any", status: "active" });
  const questions = useQuestions(moduleId, filters);
  const start = useStartQuiz();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [count, setCount] = useState(10);
  const [minutes, setMinutes] = useState(60);
  const [generating, setGenerating] = useState(false);
  const list = questions.data ?? [];

  const begin = async (body: Omit<QuizCreate, "module_id">) => {
    const started = await start.mutateAsync({ module_id: moduleId, ...body });
    await navigate({ to: "/attempts/$attemptId", params: { attemptId: started.attempt_id } });
  };
  const filterBody = {
    topic_ids: filters.topic_id ? [filters.topic_id] : null,
    difficulties: filters.difficulty ? [filters.difficulty] : null,
    types: filters.type ? [filters.type] : null,
    result: filters.result === "right" ? "any" : filters.result,
  } as const;

  return (
    <div className="flex max-w-4xl flex-col gap-5">
      <ModuleHeader module={module.data} title="Questions and quizzes" />

      <div className="flex flex-wrap items-end gap-2">
        <Button variant="primary" onClick={() => setGenerating(true)}>
          <Sparkles size={14} /> Generate questions
        </Button>
        <label className="flex items-center gap-1 text-sm">
          <input
            type="number"
            min={1}
            max={60}
            aria-label="Number of questions"
            className={`${select} w-16`}
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
          />
          questions
        </label>
        <Button disabled={start.isPending || !list.length} onClick={() => begin({ kind: "practice", count, ...filterBody })}>
          <Play size={14} /> Practise
        </Button>
        <Button
          disabled={start.isPending || selected.size === 0}
          onClick={() => begin({ kind: "practice", question_ids: [...selected] })}
        >
          Practise {selected.size} selected
        </Button>
        <Button disabled={start.isPending} onClick={() => begin({ kind: "practice", count, result: "wrong" })}>
          Retry wrong ones
        </Button>
        <label className="flex items-center gap-1 text-sm">
          <input
            type="number"
            min={5}
            max={240}
            aria-label="Exam minutes"
            className={`${select} w-16`}
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value))}
          />
          min
        </label>
        <Button
          disabled={start.isPending || !list.length}
          onClick={() => begin({ kind: "mock", count, time_limit_minutes: minutes, ...filterBody })}
          title="Timed, with AI help off until you submit"
        >
          <Timer size={14} /> Mock exam
        </Button>
      </div>
      <ErrorText error={start.error} />

      <div role="group" aria-label="Filters" className="flex flex-wrap gap-2">
        <select
          aria-label="Topic"
          className={select}
          value={filters.topic_id ?? ""}
          onChange={(e) => setFilters((f) => ({ ...f, topic_id: e.target.value || undefined }))}
        >
          <option value="">All topics</option>
          {flattenTopics(topics.data ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              {t.title}
            </option>
          ))}
        </select>
        <select
          aria-label="Difficulty"
          className={select}
          value={filters.difficulty ?? ""}
          onChange={(e) => setFilters((f) => ({ ...f, difficulty: (e.target.value || undefined) as Difficulty | undefined }))}
        >
          <option value="">Any difficulty</option>
          {DIFFICULTIES.map((d) => (
            <option key={d.value} value={d.value}>
              {d.label}
            </option>
          ))}
        </select>
        <select
          aria-label="Type"
          className={select}
          value={filters.type ?? ""}
          onChange={(e) => setFilters((f) => ({ ...f, type: (e.target.value || undefined) as QuestionType | undefined }))}
        >
          <option value="">Any type</option>
          {QUESTION_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <select
          aria-label="Result"
          className={select}
          value={filters.result}
          onChange={(e) => setFilters((f) => ({ ...f, result: e.target.value as BankFilters["result"] }))}
        >
          <option value="any">Any result</option>
          <option value="unattempted">Not tried</option>
          <option value="wrong">Got wrong last time</option>
          <option value="right">Got right last time</option>
        </select>
        <select
          aria-label="Status"
          className={select}
          value={filters.status}
          onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value as BankFilters["status"] }))}
        >
          <option value="active">In practice</option>
          <option value="retired">Retired</option>
        </select>
      </div>

      <ErrorText error={questions.error} />
      {questions.isSuccess && list.length === 0 && (
        <p className="text-sm text-muted">No questions match. Generate some from your materials.</p>
      )}
      <p className="text-xs text-muted">{list.length} questions</p>
      <ul className="flex flex-col gap-2">
        {list.map((q) => (
          <QuestionRow
            key={q.id}
            question={q}
            checked={selected.has(q.id)}
            onToggle={(on) =>
              setSelected((s) => {
                const next = new Set(s);
                if (on) next.add(q.id);
                else next.delete(q.id);
                return next;
              })
            }
          />
        ))}
      </ul>
      <History moduleId={moduleId} />
      <GenerateDialog open={generating} onOpenChange={setGenerating} moduleId={moduleId} kind="questions" />
    </div>
  );
}
