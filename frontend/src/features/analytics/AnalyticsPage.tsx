import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { useViewingYear } from "@/app/viewingYear";
import { ErrorText } from "@/components/ui";

import { ActivityGrid, BarChart, LineChart } from "./charts";
import { formatValue, shortDate, useOverview, useReadiness, useTrends, type Trends } from "./queries";
import { ReadinessCard } from "./ReadinessCard";
import { Stat } from "./Stat";

function percent(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export function TrendCharts({ trends }: { trends: Trends }) {
  const weeks = trends.weeks;
  const totals = new Map<string, number>();
  for (const w of weeks) for (const [k, n] of Object.entries(w.mistakes)) totals.set(k, (totals.get(k) ?? 0) + n);
  const mistakes = [...totals.entries()].sort((a, b) => b[1] - a[1]);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <LineChart
        title="Accuracy by week"
        basis={trends.basis.accuracy ?? ""}
        points={weeks.map((w) => ({ label: shortDate(w.start), value: w.accuracy ?? null }))}
        format={percent}
      />
      <BarChart
        title="Study time by week"
        basis={trends.basis.study_time ?? ""}
        points={weeks.map((w) => ({ label: shortDate(w.start), value: w.study_minutes }))}
        format={(v) => formatValue(v, "minutes")}
      />
      <BarChart
        title="Questions answered by week"
        basis="Answers marked each week"
        points={weeks.map((w) => ({ label: shortDate(w.start), value: w.answered }))}
      />
      <figure className="flex flex-col gap-2 rounded-lg border border-border p-4">
        <figcaption>
          <h3 className="font-semibold">Mistake trends</h3>
          <p className="text-xs text-muted">{trends.basis.mistakes}</p>
        </figcaption>
        {mistakes.length === 0 ? (
          <p className="text-sm text-muted">No classified mistakes in these weeks.</p>
        ) : (
          <ul aria-label="Mistakes by kind" className="flex flex-col gap-1.5 text-sm">
            {mistakes.slice(0, 6).map(([kind, n]) => (
              <li key={kind} className="flex items-center gap-2">
                <span className="w-44 shrink-0 truncate">{trends.mistake_labels[kind] ?? kind}</span>
                <span className="h-2 rounded-full bg-accent" style={{ width: `${(n / mistakes[0]![1]) * 60}%` }} aria-hidden />
                <span className="text-xs text-muted">{n}</span>
              </li>
            ))}
          </ul>
        )}
      </figure>
      <ActivityGrid title="Revision consistency" basis={trends.basis.consistency ?? ""} days={trends.days} />
      <BarChart
        title="Planned sessions done by week"
        basis="Past planned sessions marked done, as a share of those planned (done, missed or skipped)"
        points={weeks.map((w) => ({
          label: shortDate(w.start),
          value: w.sessions_planned ? w.sessions_done / w.sessions_planned : null,
        }))}
        format={percent}
        max={1}
      />
    </div>
  );
}

export function AnalyticsPage() {
  const overview = useOverview();
  const readiness = useReadiness();
  const { year } = useViewingYear();
  const [moduleId, setModuleId] = useState("");
  const trends = useTrends(moduleId || undefined);
  const o = overview.data;

  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Analytics</h1>
        <p className="text-sm text-muted">
          Computed from your answers, flashcard reviews and planned sessions. Select the{" "}
          <span aria-hidden>ⓘ</span> beside a figure to see what it was worked out from.
        </p>
      </header>
      <ErrorText error={overview.error ?? readiness.error ?? trends.error} />

      {o && (
        <section aria-labelledby="module-performance" className="flex flex-col gap-3">
          <h2 id="module-performance" className="text-base font-semibold">
            Module performance
          </h2>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {o.modules.map((m) => (
              <li
                key={m.module_id}
                className="flex flex-col gap-3 rounded-lg border border-border p-4"
                style={{ borderTop: `3px solid ${m.colour ?? "var(--color-accent)"}` }}
              >
                {year ? (
                  <Link
                    to="/y/$yearId/m/$moduleId"
                    params={{ yearId: year.id, moduleId: m.module_id }}
                    className="font-medium hover:underline"
                  >
                    {m.code} {m.title}
                  </Link>
                ) : (
                  <p className="font-medium">
                    {m.code} {m.title}
                  </p>
                )}
                <div className="grid grid-cols-2 gap-3">
                  <Stat label="Estimated strength" metric={m.progress} format="percent" size="sm" />
                  <Stat label="Coverage" metric={m.coverage} format="percent" size="sm" />
                  <Stat label={`Answered (${o.recent.days} days)`} metric={m.answered} size="sm" />
                  <Stat label={`Accuracy (${o.recent.days} days)`} metric={m.accuracy} format="percent" size="sm" />
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {!!readiness.data?.length && (
        <section aria-labelledby="readiness-heading" className="flex flex-col gap-3">
          <h2 id="readiness-heading" className="text-base font-semibold">
            Exam readiness
          </h2>
          {readiness.data.map((r) => (
            <ReadinessCard key={r.exam_id} readiness={r} />
          ))}
        </section>
      )}

      {o && (o.strong.length > 0 || o.weak.length > 0) && (
        <section aria-labelledby="topic-strengths" className="grid gap-4 md:grid-cols-2">
          <h2 id="topic-strengths" className="sr-only">
            Topic strengths
          </h2>
          {(
            [
              ["Strongest topics", o.strong],
              ["Weakest topics", o.weak],
            ] as const
          ).map(([title, topics]) => (
            <div key={title} className="flex flex-col gap-2 rounded-lg border border-border p-4">
              <h3 className="font-semibold">{title}</h3>
              <p className="text-xs text-muted">Estimated strength, topics with enough data only</p>
              {topics.length === 0 ? (
                <p className="text-sm text-muted">None yet.</p>
              ) : (
                <ul className="flex flex-col gap-1 text-sm">
                  {topics.map((t) => (
                    <li key={`${t.module_id}-${t.topic_id ?? "none"}`} className="flex justify-between gap-2">
                      <span>
                        {t.title} <span className="text-xs text-muted">{t.module_code}</span>
                      </span>
                      <span>
                        {Math.round(t.strength * 100)}%{" "}
                        <span className="text-xs text-muted">{t.attempts} answers</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </section>
      )}

      <section aria-labelledby="trends-heading" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="trends-heading" className="text-base font-semibold">
            Trends
          </h2>
          {o && (
            <select
              aria-label="Show trends for"
              value={moduleId}
              onChange={(e) => setModuleId(e.target.value)}
              className="h-8 rounded-md border border-border bg-bg px-2 text-sm"
            >
              <option value="">All modules</option>
              {o.modules.map((m) => (
                <option key={m.module_id} value={m.module_id}>
                  {m.code}
                </option>
              ))}
            </select>
          )}
        </div>
        {trends.data && <TrendCharts trends={trends.data} />}
      </section>
    </div>
  );
}
