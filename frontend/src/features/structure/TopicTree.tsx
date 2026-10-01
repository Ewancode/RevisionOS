import {
  ArrowDown,
  ArrowUp,
  IndentDecrease,
  IndentIncrease,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button, ConfirmDelete, ErrorText } from "@/components/ui";

import { useTopicMutations, useTopicTree, type TopicNode } from "./queries";
import { indent, moveDown, moveUp, outdent, type Move } from "./treeOps";

function countDescendants(node: TopicNode): number {
  return (node.children ?? []).reduce((n, child) => n + 1 + countDescendants(child), 0);
}

function TitleForm({
  initial,
  label,
  onSubmit,
  onCancel,
}: {
  initial: string;
  label: string;
  onSubmit: (title: string) => Promise<unknown>;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(initial);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (title.trim()) await onSubmit(title.trim());
  }
  return (
    <form onSubmit={submit} className="flex items-center gap-2">
      <input
        aria-label={label}
        autoFocus
        maxLength={200}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && onCancel()}
        className="h-8 flex-1 rounded-md border border-border bg-bg px-2 text-sm"
      />
      <Button type="submit" size="sm" variant="primary">
        Save
      </Button>
      <Button size="sm" onClick={onCancel}>
        Cancel
      </Button>
    </form>
  );
}

function TopicItem({
  node,
  tree,
  moduleId,
}: {
  node: TopicNode;
  tree: TopicNode[];
  moduleId: string;
}) {
  const { create, update, move, remove } = useTopicMutations(moduleId);
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const descendants = countDescendants(node);

  const moves: { label: string; icon: typeof ArrowUp; target: Move | undefined }[] = [
    { label: "Move up", icon: ArrowUp, target: moveUp(tree, node.id) },
    { label: "Move down", icon: ArrowDown, target: moveDown(tree, node.id) },
    { label: "Make subtopic of the one above", icon: IndentIncrease, target: indent(tree, node.id) },
    { label: "Move out a level", icon: IndentDecrease, target: outdent(tree, node.id) },
  ];

  return (
    <li>
      <div className="group flex items-center gap-2 rounded-md px-2 py-1 hover:bg-surface">
        {editing ? (
          <div className="flex-1">
            <TitleForm
              initial={node.title}
              label={`Rename ${node.title}`}
              onCancel={() => setEditing(false)}
              onSubmit={async (title) => {
                await update.mutateAsync({ id: node.id, body: { title } });
                setEditing(false);
              }}
            />
          </div>
        ) : (
          <>
            <span className="flex-1 text-sm">{node.title}</span>
            <div className="flex gap-0.5 opacity-60 group-focus-within:opacity-100 group-hover:opacity-100">
              {moves.map(({ label, icon: Icon, target }) => (
                <Button
                  key={label}
                  size="sm"
                  variant="ghost"
                  aria-label={`${label}: ${node.title}`}
                  title={label}
                  disabled={!target || move.isPending}
                  onClick={() => target && move.mutate({ id: node.id, body: target })}
                >
                  <Icon size={14} />
                </Button>
              ))}
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Add subtopic to ${node.title}`}
                title="Add subtopic"
                onClick={() => setAdding(true)}
              >
                <Plus size={14} />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Rename ${node.title}`}
                title="Rename"
                onClick={() => setEditing(true)}
              >
                <Pencil size={14} />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Delete ${node.title}`}
                title="Delete"
                onClick={() => setDeleting(true)}
              >
                <Trash2 size={14} />
              </Button>
            </div>
          </>
        )}
      </div>
      {(node.children?.length || adding) && (
        <ul className="ml-5 border-l border-border pl-2">
          {node.children?.map((child) => (
            <TopicItem key={child.id} node={child} tree={tree} moduleId={moduleId} />
          ))}
          {adding && (
            <li className="px-2 py-1">
              <TitleForm
                initial=""
                label={`New subtopic of ${node.title}`}
                onCancel={() => setAdding(false)}
                onSubmit={async (title) => {
                  await create.mutateAsync({ title, parent_id: node.id });
                  setAdding(false);
                }}
              />
            </li>
          )}
        </ul>
      )}
      <ConfirmDelete
        open={deleting}
        onOpenChange={setDeleting}
        thing={`"${node.title}"`}
        detail={
          descendants
            ? `This also moves its ${descendants} subtopic${descendants === 1 ? "" : "s"} to the trash. You can restore them for 30 days.`
            : undefined
        }
        onConfirm={() => remove.mutateAsync(node.id)}
      />
    </li>
  );
}

export function TopicTree({ moduleId }: { moduleId: string }) {
  const tree = useTopicTree(moduleId);
  const { create, move } = useTopicMutations(moduleId);
  const [adding, setAdding] = useState(false);

  if (tree.isPending) return <p className="text-sm text-muted">Loading topics…</p>;
  if (tree.isError) return <ErrorText error={tree.error} />;

  return (
    <section aria-labelledby="topics-heading" className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 id="topics-heading" className="text-base font-semibold">
          Topics
        </h2>
        <Button size="sm" onClick={() => setAdding(true)}>
          <Plus size={14} /> Add topic
        </Button>
      </div>
      <ErrorText error={move.error} />
      {tree.data.length === 0 && !adding && (
        <p className="text-sm text-muted">
          No topics yet. Add the module&apos;s main topics, then subtopics under them.
        </p>
      )}
      <ul aria-label="Topic tree">
        {tree.data.map((node) => (
          <TopicItem key={node.id} node={node} tree={tree.data} moduleId={moduleId} />
        ))}
      </ul>
      {adding && (
        <TitleForm
          initial=""
          label="New topic"
          onCancel={() => setAdding(false)}
          onSubmit={async (title) => {
            await create.mutateAsync({ title });
            setAdding(false);
          }}
        />
      )}
      <ErrorText error={create.error} />
    </section>
  );
}
