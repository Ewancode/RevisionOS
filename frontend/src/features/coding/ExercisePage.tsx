import { useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Play, RotateCcw, Send } from "lucide-react";
import { useMemo, useState } from "react";

import { Button, ErrorText } from "@/components/ui";
import { MathMarkdown } from "@/components/MathMarkdown";
import { useModule } from "@/features/structure/queries";
import { ModuleHeader } from "@/features/study/StudySection";

import { CodeEditor } from "./CodeEditor";
import { HintLadder } from "./HintLadder";
import { codingKeys, useExercise, useExerciseHints, useSubmissions, useSubmit, type Exercise } from "./queries";
import { ResultsPanel, resultsText } from "./ResultsPanel";
import { useRunner } from "./useRunner";

function Workspace({ exercise }: { exercise: Exercise }) {
  const qc = useQueryClient();
  const [code, setCode] = useState(exercise.latest_code ?? exercise.starter_code);
  const runner = useRunner(exercise.language);
  const submit = useSubmit(exercise.id);
  const submissions = useSubmissions(exercise.id);
  const { query: hints, next } = useExerciseHints(exercise.id);
  const hidden = useMemo(() => new Set(exercise.tests.filter((t) => t.hidden).map((t) => t.name)), [exercise.tests]);
  const tests = exercise.tests.map((t) => ({ name: t.name, code: t.code }));
  const busy = runner.running || submit.isPending;

  const run = (mode: "run" | "test") => runner.run({ code, tests, mode, packages: exercise.packages });

  const submitCode = async () => {
    const result = await run("test");
    if (!result) return;
    await submit.mutateAsync({
      code,
      results: result.tests.map((t) => ({ name: t.name, passed: t.passed, message: t.message.slice(0, 2000) })),
      error: result.error?.slice(0, 4000) ?? null,
      runtime_ms: result.runtimeMs,
    });
    // A submission may unlock the full solution.
    await qc.invalidateQueries({ queryKey: codingKeys.hints(exercise.id) });
  };

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="flex flex-col gap-4">
        <MathMarkdown className="text-sm">{exercise.prompt_md}</MathMarkdown>
        <section aria-label="Visible tests" className="flex flex-col gap-1">
          <h2 className="text-sm font-semibold">Tests</h2>
          {exercise.tests.map((t, i) =>
            t.hidden ? (
              <p key={t.name} className="text-xs text-muted">
                Hidden test {exercise.tests.slice(0, i + 1).filter((x) => x.hidden).length}: checked when you run the
                tests, not shown.
              </p>
            ) : (
              <div key={t.name}>
                <p className="text-xs font-medium">{t.name}</p>
                <pre className="overflow-x-auto rounded-md bg-surface p-2 text-xs">{t.code}</pre>
              </div>
            ),
          )}
        </section>
        <HintLadder
          hints={hints.data}
          pending={next.isPending}
          error={next.error ?? hints.error}
          onNext={() =>
            next.mutate({ work: code, results: runner.result ? resultsText(runner.result, hidden).slice(0, 4000) : null })
          }
        />
      </div>

      <div className="flex flex-col gap-3">
        <CodeEditor
          value={code}
          onChange={setCode}
          language={exercise.language}
          label={`Your ${exercise.language === "python" ? "Python" : "R"} code`}
          onRun={() => void run("test")}
        />
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => void run("run")} disabled={busy || !runner.ready}>
            <Play size={14} /> Run
          </Button>
          <Button onClick={() => void run("test")} disabled={busy || !runner.ready}>
            <FlaskConical size={14} /> Run tests
          </Button>
          <Button variant="primary" onClick={() => void submitCode()} disabled={busy || !runner.ready}>
            <Send size={14} /> Submit
          </Button>
          <Button variant="ghost" onClick={() => setCode(exercise.starter_code)} disabled={busy}>
            <RotateCcw size={14} /> Reset
          </Button>
        </div>
        <p className="text-xs text-muted">
          Your code runs in your browser, never on the server. Ctrl+Enter runs the tests.
        </p>
        {runner.status && (
          <p role="status" className="text-sm text-muted">
            {runner.status}
          </p>
        )}
        <ErrorText error={runner.configError ?? submit.error} />
        {submit.data && (
          <p role="status" className="text-sm font-medium">
            Submitted: {submit.data.passed} of {submit.data.total} tests passed
            {submit.data.passed === submit.data.total ? ". Well done." : "."}
          </p>
        )}
        {runner.result && <ResultsPanel result={runner.result} hidden={hidden} />}
        {!!submissions.data?.length && (
          <section aria-label="Your submissions" className="flex flex-col gap-1">
            <h2 className="text-sm font-semibold">Your submissions</h2>
            <ul className="flex flex-col gap-0.5 text-xs">
              {submissions.data.map((s) => (
                <li key={s.id} className="flex items-center justify-between gap-2">
                  <span>
                    {new Date(s.created_at).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" })} ·{" "}
                    {s.passed}/{s.total} passed
                  </span>
                  <Button size="sm" variant="ghost" onClick={() => setCode(s.code)}>
                    Load
                  </Button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}

export function ExercisePage({ exerciseId }: { exerciseId: string }) {
  const exercise = useExercise(exerciseId);
  const module = useModule(exercise.data?.module_id ?? "", Boolean(exercise.data));
  if (exercise.isPending) return <p className="text-sm text-muted">Loading…</p>;
  if (exercise.isError) return <ErrorText error={exercise.error} />;
  const e = exercise.data;
  return (
    <div className="flex flex-col gap-4">
      <ModuleHeader module={module.data} title={e.title} />
      <p className="text-xs text-muted">
        {e.language === "python" ? "Python" : "R"} · {e.difficulty}
        {e.origin === "claude" ? " · written by Claude" : ""}
        {e.assessed ? " · assessed work: hints only, never the solution" : ""}
        {e.packages.length ? ` · uses ${e.packages.join(", ")}` : ""}
      </p>
      <Workspace key={e.id} exercise={e} />
    </div>
  );
}
