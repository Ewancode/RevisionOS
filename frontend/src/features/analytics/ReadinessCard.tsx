import type { Readiness } from "./queries";
import { Stat } from "./Stat";

const COMPONENTS: [string, string][] = [
  ["coverage", "Coverage"],
  ["strength", "Topic strength"],
  ["recent", "Recent marks"],
  ["mock", "Mock exams"],
  ["recency", "Practised lately"],
];

/** Exam readiness: the measured components and their weighted summary,
 *  never a predicted mark (SPEC 43). */
export function ReadinessCard({ readiness }: { readiness: Readiness }) {
  return (
    <section
      aria-label={`Readiness for ${readiness.module_code} ${readiness.title}`}
      className="flex flex-col gap-3 rounded-lg border border-border p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold">
          {readiness.module_code} {readiness.title}
        </h3>
        <span className="text-xs text-muted">
          in {readiness.days_until} day{readiness.days_until === 1 ? "" : "s"}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <p className="text-2xl font-semibold">{Math.round(readiness.index * 100)}</p>
        <div className="flex-1">
          <p className="text-sm font-medium">{readiness.band}</p>
          <div
            role="meter"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(readiness.index * 100)}
            aria-label={`Readiness ${Math.round(readiness.index * 100)} of 100`}
            className="h-1.5 w-full overflow-hidden rounded-full bg-surface"
          >
            <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round(readiness.index * 100)}%` }} />
          </div>
        </div>
      </div>
      <p className="text-xs text-muted">{readiness.note}</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {COMPONENTS.map(([key, label]) => {
          const metric = readiness.components[key];
          return metric ? <Stat key={key} label={label} metric={metric} format="percent" size="sm" /> : null;
        })}
      </div>
      {readiness.weak_topics.length > 0 && (
        <p className="text-sm">
          <span className="text-muted">Weakest exam topics: </span>
          {readiness.weak_topics.map((t) => `${t.title} (est. ${Math.round(t.strength * 100)}%)`).join(", ")}
        </p>
      )}
    </section>
  );
}
