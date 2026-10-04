import { Link, useNavigate } from "@tanstack/react-router";
import { CheckCircle2, Plus, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button, ConfirmDelete, ErrorText, Field, Modal } from "@/components/ui";
import { useModule } from "@/features/structure/queries";
import { GenerateDialog } from "@/features/study/GenerateDialog";
import { ModuleHeader } from "@/features/study/StudySection";

import { LANGUAGES, useExerciseMutations, useExercises, type ExerciseIn, type ExerciseSummary } from "./queries";

const textarea = "min-h-24 rounded-md border border-border bg-bg p-2 font-mono text-xs";
const control = "h-9 rounded-md border border-border bg-bg px-2 text-sm";

interface TestDraft {
  name: string;
  code: string;
  hidden: boolean;
}

/** Write an exercise yourself: the task, starter and reference code, tests. */
function NewExerciseDialog({ open, onOpenChange, moduleId }: { open: boolean; onOpenChange: (o: boolean) => void; moduleId: string }) {
  const { create } = useExerciseMutations();
  const navigate = useNavigate();
  const [language, setLanguage] = useState<ExerciseIn["language"]>("python");
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [starter, setStarter] = useState("");
  const [solution, setSolution] = useState("");
  const [packages, setPackages] = useState("");
  const [assessed, setAssessed] = useState(false);
  const [tests, setTests] = useState<TestDraft[]>([{ name: "", code: "", hidden: false }]);
  const assertion = language === "python" ? "assert f(2) == 4, 'f(2) should be 4'" : 'stopifnot(f(2) == 4)';

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="New coding exercise"
      description="Tests are code run after yours; each passes unless it raises (an assert in Python, stop() in R)."
    >
      <form
        className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto"
        onSubmit={async (e) => {
          e.preventDefault();
          const made = await create.mutateAsync({
            module_id: moduleId,
            language,
            title,
            prompt_md: prompt,
            starter_code: starter,
            solution_code: solution,
            tests: tests.filter((t) => t.name.trim() && t.code.trim()),
            packages: packages.split(",").map((p) => p.trim()).filter(Boolean),
            assessed,
          });
          onOpenChange(false);
          await navigate({ to: "/coding/$exerciseId", params: { exerciseId: made.id } });
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          Language
          <select className={control} value={language} onChange={(e) => setLanguage(e.target.value as ExerciseIn["language"])}>
            {LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
        <Field label="Title" required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
        <label className="flex flex-col gap-1 text-sm">
          Task (Markdown)
          <textarea className={textarea} required value={prompt} onChange={(e) => setPrompt(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Starter code
          <textarea className={textarea} value={starter} onChange={(e) => setStarter(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Reference solution (shown only after you submit an attempt, and never for assessed work)
          <textarea className={textarea} required value={solution} onChange={(e) => setSolution(e.target.value)} />
        </label>
        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm">Tests</legend>
          {tests.map((t, i) => (
            <div key={i} className="flex flex-col gap-1 rounded-md border border-border p-2">
              <input
                aria-label={`Test ${i + 1} name`}
                placeholder="What it checks, e.g. handles an empty list"
                className={control}
                value={t.name}
                onChange={(e) => setTests(tests.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))}
              />
              <textarea
                aria-label={`Test ${i + 1} code`}
                placeholder={assertion}
                className={textarea}
                value={t.code}
                onChange={(e) => setTests(tests.map((x, j) => (j === i ? { ...x, code: e.target.value } : x)))}
              />
              <label className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={t.hidden}
                  onChange={(e) => setTests(tests.map((x, j) => (j === i ? { ...x, hidden: e.target.checked } : x)))}
                />
                Hidden (checked, but its code is not shown)
              </label>
            </div>
          ))}
          <Button size="sm" onClick={() => setTests([...tests, { name: "", code: "", hidden: false }])}>
            <Plus size={14} /> Add a test
          </Button>
        </fieldset>
        <Field
          label="Packages (optional, comma-separated)"
          hint={language === "python" ? "e.g. pandas; imports are usually found automatically" : "e.g. dplyr"}
          value={packages}
          onChange={(e) => setPackages(e.target.value)}
        />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={assessed} onChange={(e) => setAssessed(e.target.checked)} />
          Assessed coursework (the tutor gives hints only, never the solution)
        </label>
        <ErrorText error={create.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={create.isPending}>
            Save
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function progressText(e: ExerciseSummary): string {
  const p = e.progress;
  if (!p.submissions) return "not tried yet";
  return `best ${p.best_passed ?? 0}/${p.total} · ${p.submissions} submission${p.submissions === 1 ? "" : "s"}`;
}

export function CodingPage({ moduleId }: { moduleId: string }) {
  const module = useModule(moduleId);
  const exercises = useExercises(moduleId);
  const { remove } = useExerciseMutations();
  const [creating, setCreating] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [deleting, setDeleting] = useState<ExerciseSummary | null>(null);

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <ModuleHeader module={module.data} title="Coding practice" />
      <p className="text-sm text-muted">
        Python and R exercises that run and mark in your browser. Stuck? The tutor gives hints one step at a time.
      </p>
      <div className="flex gap-2">
        <Button variant="primary" onClick={() => setGenerating(true)}>
          <Sparkles size={14} /> Generate with Claude
        </Button>
        <Button onClick={() => setCreating(true)}>
          <Plus size={14} /> Write your own
        </Button>
      </div>
      <ErrorText error={exercises.error} />
      {exercises.data?.length === 0 && <p className="text-sm text-muted">No exercises yet.</p>}
      <ul className="flex flex-col gap-2">
        {exercises.data?.map((e) => (
          <li key={e.id} className="flex items-center justify-between gap-2 rounded-lg border border-border p-3">
            <div>
              <Link to="/coding/$exerciseId" params={{ exerciseId: e.id }} className="font-medium hover:underline">
                {e.title}
              </Link>
              <p className="flex items-center gap-1 text-xs text-muted">
                {e.progress.solved && <CheckCircle2 size={12} className="text-success" aria-label="Solved" />}
                {e.language === "python" ? "Python" : "R"} · {e.difficulty} · {progressText(e)}
                {e.assessed ? " · assessed" : ""}
              </p>
            </div>
            <Button size="sm" variant="ghost" aria-label={`Delete ${e.title}`} onClick={() => setDeleting(e)}>
              <Trash2 size={14} />
            </Button>
          </li>
        ))}
      </ul>
      {creating && <NewExerciseDialog open onOpenChange={setCreating} moduleId={moduleId} />}
      {generating && <GenerateDialog open onOpenChange={setGenerating} moduleId={moduleId} kind="coding" />}
      <ConfirmDelete
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        thing={deleting?.title ?? "exercise"}
        detail="It moves to the trash (Settings), where you can restore it with your submissions."
        onConfirm={() => remove.mutateAsync(deleting!.id)}
      />
    </div>
  );
}
