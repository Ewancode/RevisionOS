import { Link } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight, Plus, Shuffle, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";

import { MathMarkdown } from "@/components/MathMarkdown";
import { Button, ConfirmDelete, ErrorText } from "@/components/ui";
import { useModule } from "@/features/structure/queries";

import { GenerateDialog } from "./GenerateDialog";
import { useFlashcardActions, useFlashcards, type Flashcard } from "./queries";
import { ModuleHeader } from "./StudySection";

/** Flip through every card, outside the schedule (reviews are under "Review due"). */
function Study({ cards, onClose }: { cards: Flashcard[]; onClose: () => void }) {
  const [order, setOrder] = useState(() => cards.map((_, i) => i));
  const [index, setIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const card = cards[order[index] ?? 0];
  if (!card) return null;
  const go = (step: number) => {
    setIndex((i) => (i + step + order.length) % order.length);
    setRevealed(false);
  };
  return (
    <section aria-label="Study flashcards" className="flex flex-col gap-3">
      <p className="text-xs text-muted">
        Card {index + 1} of {order.length}
      </p>
      <div className="flex min-h-48 flex-col gap-3 rounded-lg border border-border p-6">
        <MathMarkdown className="text-base">{card.front_md}</MathMarkdown>
        {revealed ? (
          <div className="border-t border-border pt-3">
            <MathMarkdown className="text-sm">{card.back_md}</MathMarkdown>
          </div>
        ) : (
          <Button className="self-start" variant="primary" onClick={() => setRevealed(true)} autoFocus>
            Reveal answer
          </Button>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => go(-1)} aria-label="Previous card">
          <ChevronLeft size={14} />
        </Button>
        <Button onClick={() => go(1)} aria-label="Next card">
          <ChevronRight size={14} />
        </Button>
        <Button
          onClick={() => {
            setOrder((o) => [...o].sort(() => Math.random() - 0.5));
            setIndex(0);
            setRevealed(false);
          }}
        >
          <Shuffle size={14} /> Shuffle
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Done
        </Button>
      </div>
    </section>
  );
}

function NewCard({ moduleId, onDone }: { moduleId: string; onDone: () => void }) {
  const { create } = useFlashcardActions();
  const [front, setFront] = useState("");
  const [back, setBack] = useState("");
  return (
    <form
      className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-2"
      onSubmit={async (e) => {
        e.preventDefault();
        await create.mutateAsync({ module_id: moduleId, front_md: front, back_md: back });
        setFront("");
        setBack("");
        onDone();
      }}
    >
      <textarea
        aria-label="Front"
        placeholder="Front: the question"
        required
        className="min-h-20 rounded-md border border-border bg-bg p-2 text-sm"
        value={front}
        onChange={(e) => setFront(e.target.value)}
      />
      <textarea
        aria-label="Back"
        placeholder="Back: the answer ($...$ for maths)"
        required
        className="min-h-20 rounded-md border border-border bg-bg p-2 text-sm"
        value={back}
        onChange={(e) => setBack(e.target.value)}
      />
      <ErrorText error={create.error} />
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" variant="primary" disabled={create.isPending}>
          Add card
        </Button>
        <Button onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

export function FlashcardsPage({ moduleId }: { moduleId: string }) {
  const module = useModule(moduleId);
  const cards = useFlashcards(moduleId);
  const { remove } = useFlashcardActions();
  const [studying, setStudying] = useState(false);
  const [adding, setAdding] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [deleting, setDeleting] = useState<Flashcard | null>(null);
  const list = cards.data ?? [];
  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <ModuleHeader module={module.data} title="Flashcards" />
      {studying && list.length > 0 ? (
        <Study cards={list} onClose={() => setStudying(false)} />
      ) : (
        <div className="flex flex-wrap gap-2">
          <Link
            to="/review"
            search={{ module_id: moduleId }}
            className="inline-flex h-9 items-center rounded-md bg-accent px-3 text-sm font-medium text-on-accent"
          >
            Review due
          </Link>
          <Button disabled={!list.length} onClick={() => setStudying(true)}>
            Browse {list.length} cards
          </Button>
          <Button onClick={() => setGenerating(true)}>
            <Sparkles size={14} /> Generate with Claude
          </Button>
          <Button onClick={() => setAdding(true)}>
            <Plus size={14} /> Add a card
          </Button>
        </div>
      )}
      {adding && <NewCard moduleId={moduleId} onDone={() => setAdding(false)} />}
      <ErrorText error={cards.error} />
      {cards.isSuccess && !list.length && <p className="text-sm text-muted">No cards yet.</p>}
      <ul className="flex flex-col gap-2">
        {list.map((card) => (
          <li key={card.id} className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-[1fr_1fr_auto]">
            <MathMarkdown className="text-sm font-medium">{card.front_md}</MathMarkdown>
            <MathMarkdown className="text-sm text-muted">{card.back_md}</MathMarkdown>
            <Button size="sm" variant="ghost" aria-label="Delete card" onClick={() => setDeleting(card)}>
              <Trash2 size={14} />
            </Button>
          </li>
        ))}
      </ul>
      <GenerateDialog open={generating} onOpenChange={setGenerating} moduleId={moduleId} kind="flashcards" />
      <ConfirmDelete
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        thing="this flashcard"
        detail="It moves to the trash; restore it from Settings for 30 days."
        onConfirm={async () => {
          if (deleting) await remove.mutateAsync(deleting.id);
        }}
      />
    </div>
  );
}
