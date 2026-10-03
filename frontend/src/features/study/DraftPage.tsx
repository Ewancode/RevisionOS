import { Link, useNavigate } from "@tanstack/react-router";
import { AlertTriangle, Check, RefreshCw, Save, X } from "lucide-react";
import { useState } from "react";

import { CitedMarkdown, Sources, type Citation } from "@/components/CitedMarkdown";
import { MathMarkdown } from "@/components/MathMarkdown";
import { Button, ErrorText } from "@/components/ui";
import { useModule } from "@/features/structure/queries";

import {
  DIFFICULTIES,
  QUESTION_TYPES,
  label,
  useDraft,
  useDraftActions,
  type Draft,
  type DraftItem,
  type DraftPassage,
} from "./queries";

const FAILURES: Record<string, string> = {
  no_material: "None of your materials matched. Upload some files for this module, or choose files.",
  ai_budget_reached: "Your AI budget is used up; try again when it resets.",
  ai_not_configured: "Claude is not configured (no API key).",
  ai_unavailable: "Claude could not be reached. Try again shortly.",
  ai_refused: "Claude declined this request.",
  exam_in_progress: "AI help is off while a mock exam is open.",
};

function answerText(item: DraftItem): string | null {
  switch (item.type) {
    case "multiple_choice":
      return item.options && item.correct_option != null
        ? `${item.correct_option + 1}. ${item.options[item.correct_option] ?? ""}`
        : null;
    case "true_false":
      return item.true_or_false == null ? null : item.true_or_false ? "True" : "False";
    case "numerical":
      return item.value == null ? null : `${item.value}${item.unit ? ` ${item.unit}` : ""}`;
    case "expression":
      return item.expression ?? null;
    case "short_answer":
      return item.accepted_answers?.join(" / ") ?? null;
    default:
      return item.model_answer ?? null;
  }
}

function ItemSources({ item, passages }: { item: DraftItem; passages: DraftPassage[] }) {
  const cited = (item.sources ?? []).map((n) => passages.find((p) => p.n === n)).filter((p) => p !== undefined);
  if (!cited.length) return null;
  return (
    <p className="text-xs text-muted">
      From:{" "}
      {cited.map((p, i) => (
        <span key={p.n}>
          {i > 0 && ", "}
          <Link to="/doc/$documentId" params={{ documentId: p.document_id }} search={{ page: p.page_no }} className="hover:underline">
            {p.filename} p.{p.page_no}
          </Link>
        </span>
      ))}
    </p>
  );
}

function ItemPreview({
  item,
  index,
  passages,
  checked,
  onToggle,
}: {
  item: DraftItem;
  index: number;
  passages: DraftPassage[];
  checked: boolean;
  onToggle: (on: boolean) => void;
}) {
  const question = item.stem_md !== undefined;
  const answer = question ? answerText(item) : null;
  return (
    <li className={`flex gap-3 rounded-lg border p-3 ${item.valid ? "border-border" : "border-danger opacity-80"}`}>
      <input
        type="checkbox"
        className="mt-1"
        aria-label={`Keep item ${index + 1}`}
        checked={checked}
        disabled={!item.valid}
        onChange={(e) => onToggle(e.target.checked)}
      />
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        {question && item.type && item.difficulty && (
          <p className="text-xs text-muted">
            {label(QUESTION_TYPES, item.type)} · {label(DIFFICULTIES, item.difficulty)}
            {item.repaired && " · fixed after a failed check"}
          </p>
        )}
        <MathMarkdown className="text-sm">{(question ? item.stem_md : item.front_md) ?? ""}</MathMarkdown>
        {question && item.options && (
          <ol className="list-decimal pl-5 text-sm">
            {item.options.map((o, i) => (
              <li key={i} className={i === item.correct_option ? "font-medium" : ""}>
                <MathMarkdown>{o}</MathMarkdown>
              </li>
            ))}
          </ol>
        )}
        <details className="text-sm">
          <summary className="cursor-pointer text-xs text-muted">{question ? "Answer and solution" : "Back"}</summary>
          <div className="mt-2 flex flex-col gap-2 border-l-2 border-border pl-3">
            {question ? (
              <>
                {answer && (
                  <p className="text-xs">
                    <span className="text-muted">Answer:</span> <code>{answer}</code>
                  </p>
                )}
                {item.rubric && (
                  <ul className="list-disc pl-5 text-xs">
                    {item.rubric.map((r, i) => (
                      <li key={i}>
                        ({r.marks}) {r.point}
                      </li>
                    ))}
                  </ul>
                )}
                <MathMarkdown className="text-sm">{item.solution_md ?? ""}</MathMarkdown>
              </>
            ) : (
              <MathMarkdown className="text-sm">{item.back_md ?? ""}</MathMarkdown>
            )}
          </div>
        </details>
        <ItemSources item={item} passages={passages} />
        {!item.valid && (
          <p role="note" className="flex items-start gap-1 text-xs text-danger">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" /> Failed the checks: {item.problems.join("; ")}.
          </p>
        )}
      </div>
    </li>
  );
}

function ItemsDraft({ draft }: { draft: Draft }) {
  const items = (draft.payload?.items ?? []) as DraftItem[];
  const passages = (draft.payload?.passages ?? []) as DraftPassage[];
  const [selected, setSelected] = useState<Set<number>>(
    () => new Set(items.flatMap((item, i) => (item.valid ? [i] : []))),
  );
  const { save } = useDraftActions(draft);
  const navigate = useNavigate();
  const valid = items.filter((i) => i.valid).length;
  const noun = draft.kind === "questions" ? "question" : "card";
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">
        {valid} of {items.length} {noun}s passed the app's checks. Untick any you don't want; ones that failed
        cannot be saved.
      </p>
      <ol className="flex flex-col gap-2">
        {items.map((item, i) => (
          <ItemPreview
            key={i}
            item={item}
            index={i}
            passages={passages}
            checked={selected.has(i)}
            onToggle={(on) =>
              setSelected((s) => {
                const next = new Set(s);
                if (on) next.add(i);
                else next.delete(i);
                return next;
              })
            }
          />
        ))}
      </ol>
      <ErrorText error={save.error} />
      <div>
        <Button
          variant="primary"
          disabled={save.isPending || selected.size === 0}
          onClick={async () => {
            await save.mutateAsync({ selected: [...selected] });
            await navigate({
              to: draft.kind === "questions" ? "/modules/$moduleId/questions" : "/modules/$moduleId/flashcards",
              params: { moduleId: draft.module_id },
            });
          }}
        >
          <Save size={14} /> Save {selected.size} {noun}
          {selected.size === 1 ? "" : "s"}
        </Button>
      </div>
    </div>
  );
}

function MaterialDraft({ draft }: { draft: Draft }) {
  const payload = draft.payload as { title: string; content_md: string; citations: Citation[] };
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(payload.content_md);
  const [title, setTitle] = useState(payload.title);
  const { save } = useDraftActions(draft);
  const navigate = useNavigate();
  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1 text-sm">
        Title
        <input className="h-9 rounded-md border border-border bg-bg px-2" value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <div className="flex gap-2">
        <Button size="sm" variant={editing ? "secondary" : "ghost"} aria-pressed={editing} onClick={() => setEditing((e) => !e)}>
          {editing ? "Preview" : "Edit"}
        </Button>
      </div>
      {editing ? (
        <textarea
          aria-label="Material (Markdown)"
          className="min-h-96 rounded-md border border-border bg-bg p-2 font-mono text-sm"
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
      ) : (
        <article className="rounded-lg border border-border p-4">
          <CitedMarkdown content={content} citations={payload.citations} />
          <Sources citations={payload.citations} />
        </article>
      )}
      <ErrorText error={save.error} />
      <div>
        <Button
          variant="primary"
          disabled={save.isPending}
          onClick={async () => {
            const saved = await save.mutateAsync({
              title: title.trim() || null,
              content_md: content === payload.content_md ? null : content,
            });
            if (saved.material_id) {
              await navigate({ to: "/materials/$materialId", params: { materialId: saved.material_id } });
            }
          }}
        >
          <Save size={14} /> Save
        </Button>
      </div>
    </div>
  );
}

export function DraftPage({ draftId }: { draftId: string }) {
  const draft = useDraft(draftId);
  const module = useModule(draft.data?.module_id ?? "", draft.data !== undefined);
  const navigate = useNavigate();
  const [instructions, setInstructions] = useState<string | null>(null);
  if (draft.isPending) return <p className="text-sm text-muted">Loading…</p>;
  if (draft.isError) return <ErrorText error={draft.error} />;
  const d = draft.data;
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <header className="flex flex-col gap-1">
        {module.data && (
          <Link
            to="/y/$yearId/m/$moduleId"
            params={{ yearId: module.data.academic_year_id, moduleId: module.data.id }}
            className="text-sm text-muted hover:underline"
          >
            {module.data.code} {module.data.title}
          </Link>
        )}
        <h1 className="text-2xl font-semibold tracking-tight">
          Draft {d.kind === "material" ? "material" : d.kind}
        </h1>
        {typeof d.request.instructions === "string" && d.request.instructions && (
          <p className="text-sm text-muted">You asked: {d.request.instructions}</p>
        )}
      </header>

      {d.status === "generating" && (
        <p role="status" className="flex items-center gap-2 text-sm">
          <RefreshCw size={14} className="animate-spin" /> Claude is writing this from your materials…
        </p>
      )}
      {d.status === "failed" && (
        <p role="alert" className="text-sm text-danger">
          {FAILURES[d.error_code ?? ""] ?? "Generation failed. Try regenerating."}
        </p>
      )}
      {d.status === "saved" && (
        <p className="flex items-center gap-1 text-sm">
          <Check size={14} /> Saved.
        </p>
      )}
      {d.status === "discarded" && <p className="text-sm text-muted">Discarded.</p>}

      {d.status === "ready" && (d.kind === "material" ? <MaterialDraft draft={d} /> : <ItemsDraft draft={d} />)}

      {(d.status === "ready" || d.status === "failed") && <DraftControls draft={d} instructions={instructions} setInstructions={setInstructions} onDiscarded={() => navigate({ to: "/" })} />}
    </div>
  );
}

function DraftControls({
  draft,
  instructions,
  setInstructions,
  onDiscarded,
}: {
  draft: Draft;
  instructions: string | null;
  setInstructions: (value: string | null) => void;
  onDiscarded: () => Promise<unknown>;
}) {
  const { regenerate, discard } = useDraftActions(draft);
  return (
    <section aria-label="Draft options" className="flex flex-col gap-2 border-t border-border pt-3">
      {instructions !== null && (
        <label className="flex flex-col gap-1 text-sm">
          What should be different?
          <textarea
            className="min-h-16 rounded-md border border-border bg-bg p-2 text-sm"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
          />
        </label>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={regenerate.isPending}
          onClick={() => {
            if (instructions === null) setInstructions(String(draft.request.instructions ?? ""));
            else regenerate.mutate(instructions.trim() || null, { onSuccess: () => setInstructions(null) });
          }}
        >
          <RefreshCw size={14} /> {instructions === null ? "Regenerate…" : "Regenerate now"}
        </Button>
        <Button
          variant="ghost"
          disabled={discard.isPending}
          onClick={async () => {
            await discard.mutateAsync();
            await onDiscarded();
          }}
        >
          <X size={14} /> Discard
        </Button>
      </div>
      <ErrorText error={regenerate.error ?? discard.error} />
    </section>
  );
}
