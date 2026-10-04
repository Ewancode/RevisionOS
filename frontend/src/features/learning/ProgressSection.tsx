import { Link } from "@tanstack/react-router";

import { evidence, useProgress, type TopicProgress } from "./queries";
import { StrengthBar } from "./StrengthBar";

function depthOf(topic: TopicProgress, byId: Map<string, TopicProgress>): number {
  let depth = 0;
  let parent = topic.parent_id ? byId.get(topic.parent_id) : undefined;
  while (parent) {
    depth += 1;
    parent = parent.parent_id ? byId.get(parent.parent_id) : undefined;
  }
  return depth;
}

/** A module's topics with estimated strength and the evidence behind it. */
export function ProgressSection({ moduleId }: { moduleId: string }) {
  const progress = useProgress(moduleId);
  const rows = progress.data ?? [];
  if (!rows.length) return null;
  const byId = new Map(rows.filter((r) => r.topic_id).map((r) => [r.topic_id as string, r]));
  return (
    <section aria-labelledby="progress" className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="progress" className="text-base font-semibold">
          Topic strength
        </h2>
        <Link to="/mistakes" search={{ module_id: moduleId }} className="text-sm text-muted hover:underline">
          Mistake bank
        </Link>
      </div>
      <p className="text-xs text-muted">
        Estimates from your marked answers (recent and harder ones count more) and flashcard recall.
      </p>
      <ul className="flex flex-col gap-2">
        {rows.map((t) => {
          const parent = rows.some((r) => r.parent_id === t.topic_id);
          const shown = parent
            ? { ...t, strength: t.subtree_strength, attempts: t.subtree_attempts }
            : t;
          return (
            <li
              key={t.topic_id ?? "none"}
              className="flex flex-col gap-1"
              style={{ paddingLeft: `${depthOf(t, byId) * 1}rem` }}
            >
              <p className="text-sm">
                <span className="font-medium">{t.title}</span>{" "}
                <span className="text-xs text-muted">
                  {evidence(shown)}
                  {parent && " · with subtopics"}
                </span>
              </p>
              <StrengthBar value={shown.strength} lowData={t.low_data && shown.attempts === t.attempts} />
            </li>
          );
        })}
      </ul>
    </section>
  );
}
