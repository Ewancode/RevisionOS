import { Button, ErrorText } from "@/components/ui";
import { useStartStudy } from "@/features/planner/TodayPlan";

import { LineChart } from "./charts";
import { shortDate, useModuleAnalytics, useTrends } from "./queries";
import { ReadinessCard } from "./ReadinessCard";
import { Stat } from "./Stat";

/** The module dashboard's overview (SPEC 7): progress, recent activity,
 *  exam readiness and what to do next, each figure traceable. */
export function ModuleOverview({ moduleId }: { moduleId: string }) {
  const analytics = useModuleAnalytics(moduleId);
  const trends = useTrends(moduleId);
  const study = useStartStudy();
  const a = analytics.data;
  if (!a) return <ErrorText error={analytics.error} />;
  const r = a.recent;
  const rec = a.recommendation;
  return (
    <section aria-labelledby="overview-heading" className="flex flex-col gap-4">
      <h2 id="overview-heading" className="text-base font-semibold">
        Overview
      </h2>
      <div className="grid grid-cols-2 gap-4 rounded-lg border border-border p-4 sm:grid-cols-4">
        <Stat label="Estimated strength" metric={a.progress} format="percent" />
        <Stat label="Coverage" metric={a.coverage} format="percent" />
        <Stat label="Topics mastered" metric={a.mastered} />
        <Stat label={`Study time (${r.days} days)`} metric={r.study_minutes} format="minutes" />
        <Stat label={`Questions (${r.days} days)`} metric={r.answered} />
        <Stat label={`Correct (${r.days} days)`} metric={r.correct} />
        <Stat label={`Accuracy (${r.days} days)`} metric={r.accuracy} format="percent" />
        <Stat label={`Flashcard reviews (${r.days} days)`} metric={r.reviews} />
      </div>
      {rec && (
        <div role="region" aria-label="Recommendation" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border p-4">
          <div>
            <p className="text-sm">
              Focus on <span className="font-medium">{rec.title}</span> next.
            </p>
            <p className="text-xs text-muted">{rec.reason}</p>
          </div>
          <Button
            size="sm"
            variant="primary"
            disabled={study.pending}
            onClick={() => study.run(rec.action as Parameters<typeof study.run>[0])}
          >
            Practise
          </Button>
          <ErrorText error={study.error} />
        </div>
      )}
      {a.readiness && <ReadinessCard readiness={a.readiness} />}
      {trends.data && trends.data.weeks.some((w) => w.answered > 0) && (
        <LineChart
          title="Accuracy by week"
          basis={trends.data.basis.accuracy ?? ""}
          points={trends.data.weeks.map((w) => ({ label: shortDate(w.start), value: w.accuracy ?? null }))}
          format={(v) => `${Math.round(v * 100)}%`}
        />
      )}
    </section>
  );
}
