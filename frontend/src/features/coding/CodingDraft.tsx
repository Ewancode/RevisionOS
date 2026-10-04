import { useNavigate } from "@tanstack/react-router";
import { AlertTriangle, CheckCircle2, FlaskConical, Save, XCircle } from "lucide-react";
import { useState } from "react";

import { Button, ErrorText } from "@/components/ui";
import { MathMarkdown } from "@/components/MathMarkdown";
import { useDraftActions, type Draft } from "@/features/study/queries";

import { useRunner } from "./useRunner";
import type { TestResult } from "./runtime/types";

export interface CodingItem {
  title: string;
  language: "python" | "r";
  difficulty: string;
  prompt_md: string;
  starter_code: string;
  solution_code: string;
  tests: { name: string; code: string; hidden: boolean }[];
  packages: string[];
  problems: string[];
  valid: boolean;
}

type Check = { state: "passed" } | { state: "failed"; tests: TestResult[]; error: string | null };

function ItemCard({
  item,
  index,
  check,
  checked,
  onToggle,
}: {
  item: CodingItem;
  index: number;
  check: Check | undefined;
  checked: boolean;
  onToggle: (on: boolean) => void;
}) {
  const savable = item.valid && check?.state === "passed";
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <label className="flex items-start gap-2">
        <input
          type="checkbox"
          className="mt-1"
          checked={checked}
          disabled={!savable}
          onChange={(e) => onToggle(e.target.checked)}
          aria-label={`Keep exercise ${index + 1}`}
        />
        <span className="flex flex-col">
          <span className="font-medium">{item.title}</span>
          <span className="text-xs text-muted">
            {item.language === "python" ? "Python" : "R"} · {item.difficulty} · {item.tests.length} tests (
            {item.tests.filter((t) => t.hidden).length} hidden)
            {item.packages.length ? ` · ${item.packages.join(", ")}` : ""}
          </span>
        </span>
      </label>
      <MathMarkdown className="text-sm">{item.prompt_md}</MathMarkdown>
      <details className="text-xs">
        <summary className="cursor-pointer text-muted">Starter code, reference solution and tests</summary>
        <p className="mt-2 font-medium">Starter</p>
        <pre className="overflow-x-auto rounded-md bg-surface p-2">{item.starter_code}</pre>
        <p className="mt-2 font-medium">Reference solution</p>
        <pre className="overflow-x-auto rounded-md bg-surface p-2">{item.solution_code}</pre>
        {item.tests.map((t) => (
          <div key={t.name}>
            <p className="mt-2 font-medium">
              {t.name}
              {t.hidden ? " (hidden)" : ""}
            </p>
            <pre className="overflow-x-auto rounded-md bg-surface p-2">{t.code}</pre>
          </div>
        ))}
      </details>
      {item.problems.map((p) => (
        <p key={p} role="note" className="flex items-start gap-1 text-xs text-danger">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {p}
        </p>
      ))}
      {check?.state === "passed" && (
        <p className="flex items-center gap-1 text-xs text-success">
          <CheckCircle2 size={12} /> The reference solution passes all {item.tests.length} tests in your browser.
        </p>
      )}
      {check?.state === "failed" && (
        <div role="note" className="flex flex-col gap-0.5 text-xs text-danger">
          <p className="flex items-center gap-1">
            <XCircle size={12} /> The reference solution fails its own tests, so it cannot be saved.
          </p>
          {check.error && <p className="font-mono">{check.error}</p>}
          {check.tests
            .filter((t) => !t.passed)
            .map((t) => (
              <p key={t.name} className="font-mono">
                {t.name}: {t.message}
              </p>
            ))}
        </div>
      )}
    </li>
  );
}

/**
 * Claude's coding exercises, previewed. The server checks what it can
 * without running code; here, in your browser, each reference solution is
 * run against its own tests. Only exercises that pass both can be saved.
 */
export function CodingDraft({ draft }: { draft: Draft }) {
  const items = (draft.payload?.items ?? []) as CodingItem[];
  const language = items[0]?.language ?? "python";
  const runner = useRunner(language);
  const { save } = useDraftActions(draft);
  const navigate = useNavigate();
  const [checks, setChecks] = useState<Record<number, Check>>({});
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [checking, setChecking] = useState(false);
  const valid = items.filter((i) => i.valid).length;

  const checkAll = async () => {
    setChecking(true);
    const next: Record<number, Check> = {};
    const keep = new Set<number>();
    for (const [i, item] of items.entries()) {
      if (!item.valid) continue;
      const result = await runner.run({
        code: item.solution_code,
        tests: item.tests.map((t) => ({ name: t.name, code: t.code })),
        mode: "test",
        packages: item.packages,
      });
      if (!result) continue;
      const passed = !result.error && result.tests.length === item.tests.length && result.tests.every((t) => t.passed);
      next[i] = passed ? { state: "passed" } : { state: "failed", tests: result.tests, error: result.error };
      if (passed) keep.add(i);
      setChecks({ ...next });
    }
    setSelected(keep);
    setChecking(false);
  };

  const checkedAny = Object.keys(checks).length > 0;
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">
        {valid} of {items.length} exercises passed the app's checks. Next, run each reference solution against its
        own tests in your browser; only exercises whose solutions pass can be saved.
      </p>
      <div>
        <Button onClick={() => void checkAll()} disabled={checking || !runner.ready || valid === 0}>
          <FlaskConical size={14} /> {checkedAny ? "Check again" : "Check the solutions in your browser"}
        </Button>
      </div>
      {runner.status && checking && (
        <p role="status" className="text-sm text-muted">
          {runner.status}
        </p>
      )}
      <ol className="flex flex-col gap-2">
        {items.map((item, i) => (
          <ItemCard
            key={i}
            item={item}
            index={i}
            check={checks[i]}
            checked={selected.has(i)}
            onToggle={(on) =>
              setSelected((s) => {
                const n = new Set(s);
                if (on) n.add(i);
                else n.delete(i);
                return n;
              })
            }
          />
        ))}
      </ol>
      <ErrorText error={save.error ?? runner.configError} />
      <div>
        <Button
          variant="primary"
          disabled={save.isPending || selected.size === 0}
          onClick={async () => {
            await save.mutateAsync({ selected: [...selected] });
            await navigate({ to: "/modules/$moduleId/coding", params: { moduleId: draft.module_id } });
          }}
        >
          <Save size={14} /> Save {selected.size} exercise{selected.size === 1 ? "" : "s"}
        </Button>
      </div>
    </div>
  );
}
