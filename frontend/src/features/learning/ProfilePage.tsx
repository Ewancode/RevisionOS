import { MathMarkdown } from "@/components/MathMarkdown";
import { ErrorText } from "@/components/ui";
import { QUESTION_TYPES, label, type QuestionType } from "@/features/study/queries";

import { useProfile } from "./queries";

interface Metrics {
  answered: number;
  accuracy: number | null;
  by_type: Record<string, { answered: number; accuracy: number }>;
  exam_conditions: { answered: number; accuracy: number } | null;
  untimed: { answered: number; accuracy: number } | null;
  recent_errors: { considered: number; by_category: Record<string, number> };
  hints_per_answer: number;
  flashcards: { reviews_30d: number; recall_rate: number | null };
  recall_minus_application: number | null;
  active_days_30d: number;
}

const pct = (n: number | null | undefined) => (n === null || n === undefined ? "—" : `${Math.round(n * 100)}%`);
const CATEGORY = (key: string) => key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/** Measured statistics only (SPEC 28), and Claude's weekly summary of them. */
export function ProfilePage() {
  const profile = useProfile();
  if (profile.isPending) return <p className="text-sm text-muted">Loading…</p>;
  if (profile.isError) return <ErrorText error={profile.error} />;
  const m = profile.data.current as unknown as Metrics;
  const snapshot = profile.data.snapshot;
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Learning profile</h1>
        <p className="text-sm text-muted">
          Built only from what you have done: answers, marks and flashcard reviews. No guesses about you.
        </p>
      </header>

      {snapshot?.summary_md ? (
        <section aria-labelledby="summary" className="rounded-lg border border-border p-4">
          <h2 id="summary" className="mb-2 text-sm font-semibold">
            This week (written by Claude from the numbers below)
          </h2>
          <MathMarkdown className="text-sm">{snapshot.summary_md}</MathMarkdown>
        </section>
      ) : (
        <p className="text-sm text-muted">
          {m.answered < 10
            ? "A weekly summary appears once you have answered at least 10 questions."
            : "This week's summary is being written."}
        </p>
      )}

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["Questions answered", String(m.answered)],
          ["Accuracy", pct(m.accuracy)],
          ["Flashcard recall (30 days)", pct(m.flashcards.recall_rate)],
          ["Active days (30 days)", String(m.active_days_30d)],
        ].map(([k, v]) => (
          <div key={k} className="rounded-lg border border-border p-3">
            <dt className="text-xs text-muted">{k}</dt>
            <dd className="text-lg font-semibold tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>

      <section className="grid gap-6 sm:grid-cols-2">
        <table className="text-sm">
          <caption className="text-left text-sm font-semibold">Accuracy by question type</caption>
          <tbody>
            {Object.entries(m.by_type).map(([type, s]) => (
              <tr key={type} className="border-t border-border">
                <td className="py-1">{label(QUESTION_TYPES, type as QuestionType)}</td>
                <td className="py-1 text-right tabular-nums text-muted">{s.answered}</td>
                <td className="py-1 text-right tabular-nums">{pct(s.accuracy)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <table className="text-sm">
          <caption className="text-left text-sm font-semibold">
            Recent mistakes (last {m.recent_errors.considered})
          </caption>
          <tbody>
            {Object.entries(m.recent_errors.by_category).map(([category, count]) => (
              <tr key={category} className="border-t border-border">
                <td className="py-1">{CATEGORY(category)}</td>
                <td className="py-1 text-right tabular-nums">{count}</td>
              </tr>
            ))}
            {!Object.keys(m.recent_errors.by_category).length && (
              <tr>
                <td className="py-1 text-muted">None recorded yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="flex flex-col gap-1 text-sm">
        <p>
          Under exam conditions: {m.exam_conditions ? `${pct(m.exam_conditions.accuracy)} of ${m.exam_conditions.answered}` : "no mock exams yet"}
          {" · "}untimed: {m.untimed ? `${pct(m.untimed.accuracy)} of ${m.untimed.answered}` : "—"}
        </p>
        {m.recall_minus_application !== null && (
          <p>
            Flashcard recall minus question accuracy: {Math.round(m.recall_minus_application * 100)} points
            {m.recall_minus_application > 0.15 && " — you know the facts better than you apply them."}
          </p>
        )}
      </section>
    </div>
  );
}
