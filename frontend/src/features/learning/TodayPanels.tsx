import { Link, useNavigate } from "@tanstack/react-router";
import { AlertTriangle, Layers, Play } from "lucide-react";

import { Button, ErrorText } from "@/components/ui";

import { evidence, useDailyPlan, useDueCards, useMistakes, useStartDaily, useWeakest } from "./queries";
import { StrengthBar } from "./StrengthBar";

const card = "flex flex-col gap-3 rounded-lg border border-border p-4";

export function DailyQuiz() {
  const plan = useDailyPlan();
  const start = useStartDaily();
  const navigate = useNavigate();
  const p = plan.data;
  const chosen = (p?.buckets ?? []).filter((b) => b.allocated > 0);
  return (
    <section aria-labelledby="daily" className={card}>
      <h2 id="daily" className="font-semibold">
        Daily quiz
      </h2>
      {p && p.questions === 0 ? (
        <p className="text-sm text-muted">
          No questions to practise yet. Generate some on a module's Questions page.
        </p>
      ) : (
        p && (
          <>
            <p className="text-sm">
              {p.questions} questions, about {p.minutes} minutes, chosen where practice helps most:
            </p>
            <ul className="flex flex-col gap-1 text-sm">
              {chosen.slice(0, 5).map((b) => (
                <li key={`${b.module_id}-${b.topic_id ?? "none"}`}>
                  <span className="font-medium">{b.title}</span>{" "}
                  <span className="text-xs text-muted">
                    {b.module_code} · {b.allocated} · {b.reasons.join(", ")}
                  </span>
                </li>
              ))}
            </ul>
            <div>
              <Button
                variant="primary"
                disabled={start.isPending}
                onClick={async () => {
                  const started = await start.mutateAsync();
                  await navigate({ to: "/attempts/$attemptId", params: { attemptId: started.attempt_id } });
                }}
              >
                <Play size={14} /> Start
              </Button>
            </div>
          </>
        )
      )}
      <ErrorText error={plan.error ?? start.error} />
    </section>
  );
}

export function DueCards() {
  const due = useDueCards();
  const counts = due.data?.counts;
  return (
    <section aria-labelledby="due" className={card}>
      <h2 id="due" className="flex items-center gap-2 font-semibold">
        <Layers size={16} /> Flashcards
      </h2>
      {counts && (counts.due ?? 0) > 0 ? (
        <>
          <p className="text-sm">
            {counts.due} due: {counts.review} to review, {counts.learning} learning, {counts.new} new.
          </p>
          <Link to="/review" className="self-start rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-on-accent">
            Review now
          </Link>
        </>
      ) : (
        <p className="text-sm text-muted">Nothing due. Cards come back just before you would forget them.</p>
      )}
    </section>
  );
}

export function WeakTopics() {
  const weakest = useWeakest();
  if (!weakest.data?.length) return null;
  return (
    <section aria-labelledby="weak" className={card}>
      <h2 id="weak" className="font-semibold">
        Weakest topics
      </h2>
      <ul className="flex flex-col gap-2">
        {weakest.data.map((t) => (
          <li key={`${t.module_id}-${t.topic_id ?? "none"}`} className="flex flex-col gap-1">
            <p className="text-sm">
              <span className="font-medium">{t.title}</span>{" "}
              <span className="text-xs text-muted">
                {t.module_code} · {evidence(t)}
              </span>
            </p>
            <StrengthBar value={t.strength} lowData={t.low_data} />
          </li>
        ))}
      </ul>
    </section>
  );
}

export function RecurringMistakes() {
  const mistakes = useMistakes();
  const recurring = (mistakes.data ?? []).filter((g) => g.recurring);
  if (!recurring.length) return null;
  return (
    <section aria-labelledby="recurring" className={card}>
      <h2 id="recurring" className="flex items-center gap-2 font-semibold">
        <AlertTriangle size={16} /> Recurring mistakes
      </h2>
      <ul className="flex flex-col gap-1 text-sm">
        {recurring.slice(0, 4).map((g) => (
          <li key={`${g.topic_id ?? g.module_id}-${g.category}`}>
            <Link
              to="/mistakes"
              search={{ module_id: g.module_id }}
              className="hover:underline"
            >
              {g.label}
            </Link>{" "}
            <span className="text-xs text-muted">
              in {g.topic_title} · {g.recent} times in the last 30 days
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
