import { Link } from "@tanstack/react-router";
import { FileText, Flame, Sparkles } from "lucide-react";

import { ErrorText } from "@/components/ui";

import { useOverview } from "./queries";
import { Stat } from "./Stat";

const card = "flex flex-col gap-3 rounded-lg border border-border p-4";

/** Today's figures at a glance, each with what it was worked out from. */
export function TodayGlance() {
  const overview = useOverview();
  const o = overview.data;
  if (!o) return <ErrorText error={overview.error} />;
  const r = o.recent;
  const streak = o.streak.current.value ?? 0;
  return (
    <>
      <section aria-labelledby="glance" className={card}>
        <div className="flex items-center justify-between gap-2">
          <h2 id="glance" className="font-semibold">
            At a glance
          </h2>
          <p className="flex items-center gap-1 text-sm" title={o.streak.current.basis}>
            <Flame size={16} className={streak ? "text-danger" : "text-muted"} aria-hidden />
            {streak}-day streak
          </p>
        </div>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Today's progress" metric={o.today.progress} format="percent" />
          <Stat label="Streak" metric={o.streak.current} format="days" />
          <Stat label={`Questions (${r.days} days)`} metric={r.answered} />
          <Stat label={`Accuracy (${r.days} days)`} metric={r.accuracy} format="percent" />
          <Stat label={`Study time (${r.days} days)`} metric={r.study_minutes} format="minutes" />
          <Stat label={`Flashcard reviews (${r.days} days)`} metric={r.reviews} />
          <Stat label="Topics mastered" metric={o.mastered} />
          <Stat label="Mistake-bank items" metric={o.mistake_groups} />
        </div>
        <Link to="/analytics" className="self-start text-sm underline">
          All analytics
        </Link>
      </section>

      {(o.uploads.length > 0 || o.materials.length > 0) && (
        <section aria-labelledby="recent-items" className={card}>
          <h2 id="recent-items" className="font-semibold">
            Recently added
          </h2>
          <ul className="flex flex-col gap-1 text-sm">
            {o.uploads.slice(0, 3).map((u) => (
              <li key={u.id} className="flex items-center gap-2">
                <FileText size={14} className="shrink-0 text-muted" aria-hidden />
                <Link to="/doc/$documentId" params={{ documentId: u.id }} search={{}} className="truncate hover:underline">
                  {u.filename}
                </Link>
                <span className="text-xs text-muted">
                  {u.module_code}
                  {u.status !== "ready" ? ` · ${u.status}` : ""}
                </span>
              </li>
            ))}
            {o.materials.slice(0, 3).map((m) => (
              <li key={m.id} className="flex items-center gap-2">
                <Sparkles size={14} className="shrink-0 text-muted" aria-hidden />
                <Link to="/materials/$materialId" params={{ materialId: m.id }} className="truncate hover:underline">
                  {m.title}
                </Link>
                <span className="text-xs text-muted">
                  {m.module_code} · {m.origin === "claude" ? "generated" : "yours"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
