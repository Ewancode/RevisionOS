import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { MathMarkdown } from "@/components/MathMarkdown";
import { Button, ErrorText } from "@/components/ui";

import { formatInterval, useDueCards, useReview, type DueCard } from "./queries";

const RATINGS = [
  { value: 1, label: "Again", key: "1" },
  { value: 2, label: "Hard", key: "2" },
  { value: 3, label: "Good", key: "3" },
  { value: 4, label: "Easy", key: "4" },
] as const;

/**
 * Review the cards that are due: reveal, then say how well you knew it.
 * Keyboard: Space reveals, 1-4 rate. Scheduling is FSRS (on the server).
 */
export function ReviewSession({ moduleId }: { moduleId?: string }) {
  const due = useDueCards(moduleId);
  const review = useReview();
  // The session works through the cards that were due when it started.
  const [queue, setQueue] = useState<DueCard[] | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [done, setDone] = useState(0);
  const shownAt = useRef(Date.now());

  useEffect(() => {
    if (queue === null && due.data) setQueue(due.data.cards);
  }, [due.data, queue]);

  const card = queue?.[0];

  const rate = async (rating: number) => {
    if (!card || review.isPending) return;
    await review.mutateAsync({ cardId: card.id, rating, durationMs: Date.now() - shownAt.current });
    setDone((d) => d + 1);
    setRevealed(false);
    shownAt.current = Date.now();
    // "Again" brings the card back later in this session.
    setQueue((q) => (q ? [...q.slice(1), ...(rating === 1 ? [card] : [])] : q));
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      if (event.key === " " && !revealed) {
        event.preventDefault();
        setRevealed(true);
      } else if (revealed && ["1", "2", "3", "4"].includes(event.key)) {
        void rate(Number(event.key));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (due.isPending || queue === null) return <p className="text-sm text-muted">Loading…</p>;
  if (due.isError) return <ErrorText error={due.error} />;
  if (!card) {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-sm">
          {done ? `Done: ${done} review${done === 1 ? "" : "s"}. ` : ""}No more cards due right now.
        </p>
        <Link to="/" className="text-sm text-muted hover:underline">
          Back to Today
        </Link>
      </div>
    );
  }
  return (
    <section aria-label="Flashcard review" className="flex flex-col gap-3">
      <p className="text-xs text-muted">
        {queue.length} to go · {done} reviewed
      </p>
      <div className="flex min-h-48 flex-col gap-3 rounded-lg border border-border p-6">
        <MathMarkdown className="text-base">{card.front_md}</MathMarkdown>
        {revealed ? (
          <div className="border-t border-border pt-3">
            <MathMarkdown className="text-sm">{card.back_md}</MathMarkdown>
          </div>
        ) : (
          <Button className="self-start" variant="primary" onClick={() => setRevealed(true)}>
            Reveal answer <kbd className="ml-1 text-xs opacity-75">Space</kbd>
          </Button>
        )}
      </div>
      {revealed && (
        <div role="group" aria-label="How well did you know it?" className="grid grid-cols-4 gap-2">
          {RATINGS.map((r) => (
            <Button
              key={r.value}
              disabled={review.isPending}
              variant={r.value === 3 ? "primary" : "secondary"}
              onClick={() => void rate(r.value)}
              className="flex h-auto flex-col py-2"
              aria-keyshortcuts={r.key}
            >
              <span>{r.label}</span>
              <span className="text-xs font-normal opacity-80">{formatInterval(card.intervals[r.value] ?? 0)}</span>
            </Button>
          ))}
        </div>
      )}
      <ErrorText error={review.error} />
    </section>
  );
}
