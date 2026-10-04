import { CalendarPlus, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button, ConfirmDelete, ErrorText, Field, Modal } from "@/components/ui";
import { useTopicTree, type TopicNode } from "@/features/structure/queries";

import { inDays, useExamMutations, useExams, type Exam } from "./queries";

function flatten(nodes: TopicNode[], depth = 0): { id: string; title: string; depth: number }[] {
  return nodes.flatMap((n) => [{ id: n.id, title: n.title, depth }, ...flatten(n.children ?? [], depth + 1)]);
}

/** <input type="datetime-local"> value for a timestamp, in local time. */
function localInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function ExamDialog({
  open,
  onOpenChange,
  moduleId,
  exam,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  moduleId: string;
  exam?: Exam;
}) {
  const { create, update } = useExamMutations();
  const topics = flatten(useTopicTree(moduleId).data ?? []);
  const [title, setTitle] = useState(exam?.title ?? "Final exam");
  const [startsAt, setStartsAt] = useState(exam ? localInput(exam.starts_at) : "");
  const [duration, setDuration] = useState(String(exam?.duration_minutes ?? 120));
  const [location, setLocation] = useState(exam?.location ?? "");
  const [weighting, setWeighting] = useState(exam?.weighting ? String(exam.weighting) : "");
  const [confidence, setConfidence] = useState(exam?.confidence ? String(exam.confidence) : "");
  const [chosen, setChosen] = useState<string[]>(exam?.topic_ids ?? []);
  const mutation = exam ? update : create;

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={exam ? "Edit exam" : "Add exam"}
      description="The planner spreads your revision before it, weakest topics first."
    >
      <form
        className="flex flex-col gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          const body = {
            title,
            starts_at: new Date(startsAt).toISOString(),
            duration_minutes: Number(duration),
            location: location || null,
            weighting: weighting ? Number(weighting) : null,
            confidence: confidence ? Number(confidence) : null,
            topic_ids: chosen,
          };
          if (exam) await update.mutateAsync({ id: exam.id, body });
          else await create.mutateAsync({ module_id: moduleId, ...body });
          onOpenChange(false);
        }}
      >
        <Field label="Title" required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
        <Field
          label="Date and time"
          type="datetime-local"
          required
          value={startsAt}
          onChange={(e) => setStartsAt(e.target.value)}
        />
        <div className="grid grid-cols-2 gap-3">
          <Field
            label="Length (minutes)"
            type="number"
            min={1}
            max={600}
            required
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
          />
          <Field label="Location" maxLength={200} value={location} onChange={(e) => setLocation(e.target.value)} />
          <Field
            label="Weighting (%)"
            type="number"
            min={1}
            max={100}
            hint="Share of the module mark"
            value={weighting}
            onChange={(e) => setWeighting(e.target.value)}
          />
          <div className="flex flex-col gap-1">
            <label htmlFor="exam-confidence" className="text-sm font-medium">
              Confidence
            </label>
            <select
              id="exam-confidence"
              className="h-9 rounded-md border border-border bg-bg px-2 text-sm"
              value={confidence}
              onChange={(e) => setConfidence(e.target.value)}
            >
              <option value="">Not sure</option>
              <option value="1">1 · worried</option>
              <option value="2">2</option>
              <option value="3">3</option>
              <option value="4">4</option>
              <option value="5">5 · confident</option>
            </select>
          </div>
        </div>
        {topics.length > 0 && (
          <fieldset className="flex flex-col gap-1">
            <legend className="text-sm font-medium">Topics examined</legend>
            <p className="text-xs text-muted">Leave all unticked if the exam covers the whole module.</p>
            <div className="max-h-40 overflow-y-auto rounded-md border border-border p-2">
              {topics.map((t) => (
                <label key={t.id} className="flex items-center gap-2 text-sm" style={{ paddingLeft: t.depth * 12 }}>
                  <input
                    type="checkbox"
                    checked={chosen.includes(t.id)}
                    onChange={(e) =>
                      setChosen(e.target.checked ? [...chosen, t.id] : chosen.filter((id) => id !== t.id))
                    }
                  />
                  {t.title}
                </label>
              ))}
            </div>
          </fieldset>
        )}
        <ErrorText error={mutation.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={mutation.isPending}>
            Save
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function ExamList({ exams, moduleId }: { exams: Exam[]; moduleId?: string }) {
  const { remove } = useExamMutations();
  const [editing, setEditing] = useState<Exam | null>(null);
  const [deleting, setDeleting] = useState<Exam | null>(null);
  return (
    <>
      <ul className="flex flex-col gap-2">
        {exams.map((e) => (
          <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <p>
              {!moduleId && <span className="font-medium">{e.module_code} </span>}
              {e.title}{" "}
              <span className="text-xs text-muted">
                {new Date(e.starts_at).toLocaleString(undefined, {
                  weekday: "short",
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}{" "}
                · {inDays(e.days_until)}
                {e.weighting ? ` · ${e.weighting}%` : ""}
                {e.topic_ids.length ? ` · ${e.topic_ids.length} topics` : " · whole module"}
                {e.location ? ` · ${e.location}` : ""}
              </span>
            </p>
            <div className="flex gap-1">
              <Button size="sm" variant="ghost" aria-label={`Edit ${e.title}`} onClick={() => setEditing(e)}>
                <Pencil size={14} />
              </Button>
              <Button size="sm" variant="ghost" aria-label={`Delete ${e.title}`} onClick={() => setDeleting(e)}>
                <Trash2 size={14} />
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {editing && (
        <ExamDialog
          open
          onOpenChange={(o) => !o && setEditing(null)}
          moduleId={editing.module_id}
          exam={editing}
        />
      )}
      <ConfirmDelete
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        thing={deleting?.title ?? "exam"}
        detail="Its planned revision sessions are removed too."
        onConfirm={() => remove.mutateAsync(deleting!.id)}
      />
    </>
  );
}

/** A module's exams, on the module page. */
export function ExamsSection({ moduleId }: { moduleId: string }) {
  const exams = useExams(moduleId);
  const [adding, setAdding] = useState(false);
  return (
    <section aria-labelledby="exams-heading" className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 id="exams-heading" className="text-base font-semibold">
          Exams
        </h2>
        <Button size="sm" onClick={() => setAdding(true)}>
          <CalendarPlus size={14} /> Add exam
        </Button>
      </div>
      {exams.data?.length === 0 && (
        <p className="text-sm text-muted">No exams yet. Add one and the planner schedules your revision.</p>
      )}
      {!!exams.data?.length && <ExamList exams={exams.data} moduleId={moduleId} />}
      <ErrorText error={exams.error} />
      {adding && <ExamDialog open onOpenChange={setAdding} moduleId={moduleId} />}
    </section>
  );
}
