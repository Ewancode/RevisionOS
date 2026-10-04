import { Lightbulb, Lock } from "lucide-react";

import { Button, ErrorText } from "@/components/ui";
import { MathMarkdown } from "@/components/MathMarkdown";

import type { Hints } from "./queries";

/**
 * The tutor's hint ladder (SPEC 38): a guiding question, a hint, a stronger
 * hint, the next step, and (for coding, after an attempt) the solution. The
 * server decides which rung comes next; this only asks for it.
 */
export function HintLadder({
  hints,
  onNext,
  pending,
  error,
}: {
  hints: Hints | undefined;
  onNext: () => void;
  pending: boolean;
  error: unknown;
}) {
  if (!hints) return null;
  return (
    <section aria-label="Hints" className="flex flex-col gap-2 rounded-md bg-surface p-3">
      {hints.hints.length > 0 && (
        <ol className="flex flex-col gap-2">
          {hints.hints.map((h) => (
            <li key={h.level} className="flex flex-col gap-1">
              <p className="text-xs font-medium text-muted">
                {h.level}. {h.label}
              </p>
              <MathMarkdown className="text-sm">{h.content_md}</MathMarkdown>
            </li>
          ))}
        </ol>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {hints.next_level !== null && hints.next_label ? (
          <Button size="sm" onClick={onNext} disabled={pending}>
            <Lightbulb size={14} /> {pending ? "Thinking…" : hints.hints.length ? `Next: ${hints.next_label}` : `Stuck? ${hints.next_label}`}
          </Button>
        ) : null}
        {hints.locked_reason && hints.next_level === null && (
          <p className="flex items-center gap-1 text-xs text-muted">
            <Lock size={12} /> {hints.locked_reason}
          </p>
        )}
        {hints.locked_reason && hints.next_level !== null && hints.hints.length > 0 && (
          <p className="text-xs text-muted">{hints.locked_reason}</p>
        )}
      </div>
      <ErrorText error={error} />
    </section>
  );
}
