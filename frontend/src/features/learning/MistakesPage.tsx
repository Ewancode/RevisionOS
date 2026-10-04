import { Link, useNavigate } from "@tanstack/react-router";
import { AlertTriangle, Play, Sparkles } from "lucide-react";

import { MathMarkdown } from "@/components/MathMarkdown";
import { Button, ErrorText } from "@/components/ui";
import { useModule } from "@/features/structure/queries";
import { useGenerate, useStartQuiz } from "@/features/study/queries";

import { useMistakes, type MistakeGroup } from "./queries";

function Group({ group }: { group: MistakeGroup }) {
  const start = useStartQuiz();
  const generate = useGenerate();
  const navigate = useNavigate();
  const questionIds = [...new Set(group.examples.map((e) => e.question_id))];
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border p-4">
      <p className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{group.label}</span>
        <span className="text-sm text-muted">in {group.topic_title}</span>
        {group.recurring && (
          <span className="inline-flex items-center gap-1 rounded-full border border-danger px-2 py-0.5 text-xs text-danger">
            <AlertTriangle size={12} /> Recurring
          </span>
        )}
      </p>
      <p className="text-xs text-muted">
        {group.count} in total · {group.recent} in the last 30 days
        {group.last_at && ` · last ${new Date(group.last_at).toLocaleDateString("en-GB")}`}
      </p>
      {group.patterns.length > 0 && (
        <ul className="list-disc pl-5 text-sm">
          {group.patterns.map((p) => (
            <li key={p.description}>
              <MathMarkdown>{p.description}</MathMarkdown>
              {p.count > 1 && <span className="text-xs text-muted"> ×{p.count}</span>}
            </li>
          ))}
        </ul>
      )}
      <details className="text-sm">
        <summary className="cursor-pointer text-xs text-muted">Where it happened</summary>
        <ul className="mt-2 flex flex-col gap-2">
          {group.examples.map((e) => (
            <li key={e.answer_id} className="border-l-2 border-border pl-2">
              <div className="max-h-16 overflow-hidden text-xs">
                <MathMarkdown>{e.stem_md}</MathMarkdown>
              </div>
              <Link
                to="/attempts/$attemptId"
                params={{ attemptId: e.attempt_id }}
                className="text-xs text-muted hover:underline"
              >
                See the answer and explanation ({new Date(e.at).toLocaleDateString("en-GB")})
              </Link>
            </li>
          ))}
        </ul>
      </details>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          disabled={start.isPending}
          onClick={async () => {
            const started = await start.mutateAsync({
              module_id: group.module_id,
              question_ids: questionIds,
              title: `Retry: ${group.label.toLowerCase()} in ${group.topic_title}`,
            });
            await navigate({ to: "/attempts/$attemptId", params: { attemptId: started.attempt_id } });
          }}
        >
          <Play size={14} /> Retry these
        </Button>
        <Button
          size="sm"
          disabled={generate.isPending}
          title="Claude writes new questions that test this mistake; you preview them first"
          onClick={async () => {
            const draft = await generate.mutateAsync({
              module_id: group.module_id,
              topic_id: group.topic_id,
              kind: "questions",
              count: 5,
              instructions: `Deliberately test this recurring mistake: ${group.label}. ${group.patterns
                .slice(0, 3)
                .map((p) => p.description)
                .join(" ")}`.slice(0, 2000),
              document_ids: [],
            });
            await navigate({ to: "/drafts/$draftId", params: { draftId: draft.id } });
          }}
        >
          <Sparkles size={14} /> New questions on it
        </Button>
      </div>
      <ErrorText error={start.error ?? generate.error} />
    </li>
  );
}

export function MistakesPage({ moduleId }: { moduleId?: string }) {
  const mistakes = useMistakes(moduleId);
  const module = useModule(moduleId ?? "", moduleId !== undefined);
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <header>
        {module.data && (
          <Link
            to="/y/$yearId/m/$moduleId"
            params={{ yearId: module.data.academic_year_id, moduleId: module.data.id }}
            className="text-sm text-muted hover:underline"
          >
            {module.data.code} {module.data.title}
          </Link>
        )}
        <h1 className="text-2xl font-semibold tracking-tight">Mistake bank</h1>
        <p className="text-sm text-muted">
          Your mistakes, grouped by topic and kind. Three of the same kind in a topic within 30 days make it
          recurring, and the daily quiz then targets it.
        </p>
      </header>
      <ErrorText error={mistakes.error} />
      {mistakes.isSuccess && mistakes.data.length === 0 && (
        <p className="text-sm text-muted">No mistakes recorded yet. They appear here after quizzes are marked.</p>
      )}
      <ul className="flex flex-col gap-3">
        {mistakes.data?.map((g) => (
          <Group key={`${g.module_id}-${g.topic_id ?? "none"}-${g.category}`} group={g} />
        ))}
      </ul>
    </div>
  );
}
