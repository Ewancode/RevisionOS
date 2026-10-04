import { Link, useNavigate } from "@tanstack/react-router";
import { AlertTriangle, CalendarClock, Check, Clock, Compass, Play, SkipForward } from "lucide-react";
import { useState } from "react";

import { Button, ErrorText } from "@/components/ui";
import { useStartQuiz } from "@/features/study/queries";

import {
  formatMinutes,
  inDays,
  useBuiltSession,
  usePlan,
  useRecommendations,
  useSessionActions,
  type BuiltBlock,
  type StudySession,
} from "./queries";

const card = "flex flex-col gap-3 rounded-lg border border-border p-4";

/** Start what a planned session or a built block says to do. */
export function useStartStudy() {
  const start = useStartQuiz();
  const navigate = useNavigate();
  const run = async (target: {
    to: "practice" | "mock" | "review" | "mistakes";
    module_id?: string;
    topic_id?: string | null;
    questions?: number;
    title?: string;
  }) => {
    if (target.to === "review") return navigate({ to: "/review", search: {} });
    if (target.to === "mistakes") return navigate({ to: "/mistakes", search: { module_id: target.module_id } });
    if (!target.module_id) return;
    const started = await start.mutateAsync(
      target.to === "mock"
        ? { module_id: target.module_id, kind: "mock", title: target.title ?? null }
        : {
            module_id: target.module_id,
            topic_ids: target.topic_id ? [target.topic_id] : null,
            count: target.questions ?? 6,
            title: target.title ?? null,
          },
    );
    return navigate({ to: "/attempts/$attemptId", params: { attemptId: started.attempt_id } });
  };
  return { run, pending: start.isPending, error: start.error };
}

function SessionRow({ session }: { session: StudySession }) {
  const actions = useSessionActions();
  const study = useStartStudy();
  const done = session.status === "done";
  return (
    <li className="flex flex-col gap-1 border-t border-border pt-2 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={`text-sm ${done ? "text-muted line-through" : ""}`}>
          <span className="font-medium">
            {session.kind === "mock_exam" ? "Mock exam" : session.title}
          </span>{" "}
          <span className="text-xs text-muted">
            {session.module_code} · {formatMinutes(session.minutes)}
          </span>
        </p>
        {session.status === "planned" && (
          <div className="flex gap-1">
            <Button
              size="sm"
              variant="primary"
              disabled={study.pending}
              onClick={() =>
                study.run({
                  to: session.kind === "mock_exam" ? "mock" : "practice",
                  module_id: session.module_id,
                  topic_id: session.topic_id,
                  questions: Math.max(3, Math.round(session.minutes / 1.5)),
                  title: session.kind === "mock_exam" ? `${session.module_code} mock exam` : undefined,
                })
              }
            >
              <Play size={12} /> Start
            </Button>
            <Button
              size="sm"
              aria-label={`Mark ${session.title} done`}
              onClick={() => actions.status.mutate({ id: session.id, status: "done" })}
            >
              <Check size={12} />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Skip ${session.title}`}
              onClick={() => actions.status.mutate({ id: session.id, status: "skipped" })}
            >
              <SkipForward size={12} />
            </Button>
          </div>
        )}
      </div>
      <p className="text-xs text-muted">{session.reason}</p>
      <ErrorText error={actions.status.error ?? study.error} />
    </li>
  );
}

/** Today's planned revision, with the reasons behind each session. */
function TodaysRevision() {
  const plan = usePlan();
  const today = plan.data?.today ?? [];
  const shortfalls = plan.data?.shortfalls ?? [];
  return (
    <section aria-labelledby="todays-revision" className={card}>
      <h2 id="todays-revision" className="flex items-center gap-2 font-semibold">
        <CalendarClock size={16} /> Today's revision
      </h2>
      {plan.data && today.length === 0 && (
        <p className="text-sm text-muted">
          {plan.data.exams.length
            ? "Nothing planned today."
            : "Add your exams and the planner spreads your revision before them."}{" "}
          <Link to="/planner" className="underline">
            Planner
          </Link>
        </p>
      )}
      {today.length > 0 && (
        <ul className="flex flex-col gap-2">
          {today.map((s) => (
            <SessionRow key={s.id} session={s} />
          ))}
        </ul>
      )}
      {shortfalls.map((s) => (
        <p key={s.exam_id} role="status" className="flex items-start gap-1.5 text-xs text-danger">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          {s.title}: {s.reason === "time" ? "not enough time" : "too few days left"} for everything —
          {" "}planned {formatMinutes(s.planned_minutes)} of {formatMinutes(s.needed_minutes)}.
        </p>
      ))}
      <ErrorText error={plan.error} />
    </section>
  );
}

function UpcomingExams() {
  const plan = usePlan();
  const exams = plan.data?.exams ?? [];
  if (!exams.length) return null;
  return (
    <section aria-labelledby="upcoming-exams" className={card}>
      <h2 id="upcoming-exams" className="font-semibold">
        Upcoming exams
      </h2>
      <ul className="flex flex-col gap-1 text-sm">
        {exams.slice(0, 5).map((e) => (
          <li key={e.id}>
            <span className="font-medium">{e.module_code}</span> {e.title}{" "}
            <span className="text-xs text-muted">
              {inDays(e.days_until)} ·{" "}
              {new Date(e.starts_at).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function BlockRow({ block }: { block: BuiltBlock }) {
  const study = useStartStudy();
  const action = block.action as {
    to: "practice" | "review" | "mistakes";
    module_id?: string;
    topic_id?: string | null;
    questions?: number;
  };
  return (
    <li className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm">
          <span className="font-medium">{block.title}</span>{" "}
          <span className="text-xs text-muted">{formatMinutes(block.minutes)}</span>
        </p>
        <Button size="sm" disabled={study.pending} onClick={() => study.run(action)}>
          <Play size={12} /> Go
        </Button>
      </div>
      <p className="text-xs text-muted">{block.reason}</p>
      <ErrorText error={study.error} />
    </li>
  );
}

/** "I have 45 minutes": what to do with the time, and why. */
export function SessionBuilder() {
  const [text, setText] = useState("45");
  const [minutes, setMinutes] = useState<number | null>(null);
  const built = useBuiltSession(minutes);
  return (
    <section aria-labelledby="builder" className={card}>
      <h2 id="builder" className="flex items-center gap-2 font-semibold">
        <Clock size={16} /> Got some time?
      </h2>
      <form
        className="flex items-center gap-2 text-sm"
        onSubmit={(e) => {
          e.preventDefault();
          const n = Number(text);
          if (Number.isInteger(n) && n >= 10 && n <= 240) setMinutes(n);
        }}
      >
        <label htmlFor="builder-minutes">I have</label>
        <input
          id="builder-minutes"
          type="number"
          min={10}
          max={240}
          step={5}
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="h-8 w-20 rounded-md border border-border bg-bg px-2"
        />
        <span>minutes</span>
        <Button type="submit" size="sm" variant="primary">
          Plan it
        </Button>
      </form>
      {built.data && (
        <>
          {built.data.blocks.length === 0 ? (
            <p className="text-sm text-muted">Nothing to practise yet: add questions or flashcards to a module.</p>
          ) : (
            <ol aria-label="Your session" className="flex flex-col gap-2">
              {built.data.blocks.map((b, i) => (
                <BlockRow key={`${b.kind}-${i}`} block={b} />
              ))}
            </ol>
          )}
        </>
      )}
      <ErrorText error={built.error} />
    </section>
  );
}

function RecommendedNext() {
  const recommendations = useRecommendations();
  const items = recommendations.data ?? [];
  if (!items.length) return null;
  return (
    <section aria-labelledby="recommended" className={card}>
      <h2 id="recommended" className="flex items-center gap-2 font-semibold">
        <Compass size={16} /> Recommended next
      </h2>
      <ol className="flex flex-col gap-2">
        {items.map((b, i) => (
          <BlockRow key={`${b.kind}-${i}`} block={b} />
        ))}
      </ol>
      <ErrorText error={recommendations.error} />
    </section>
  );
}

export function TodayPlan() {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <RecommendedNext />
      <TodaysRevision />
      <SessionBuilder />
      <UpcomingExams />
    </div>
  );
}
