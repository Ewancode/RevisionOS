import { Link, useNavigate } from "@tanstack/react-router";
import { Archive, ArchiveRestore, MessageSquare, Pencil, Search, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button, ConfirmDelete, ErrorText } from "@/components/ui";
import { Materials } from "@/features/documents/Materials";
import { ProgressSection } from "@/features/learning/ProgressSection";
import { StudySection } from "@/features/study/StudySection";

import { EditModuleDialog } from "./forms";
import { useDeleteModule, useModule, useUpdateModule } from "./queries";
import { TopicTree } from "./TopicTree";

export function ModulePage({ moduleId }: { moduleId: string }) {
  const module = useModule(moduleId);
  const update = useUpdateModule(moduleId);
  const remove = useDeleteModule();
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);

  if (module.isPending) return <p className="text-sm text-muted">Loading…</p>;
  if (module.isError) return <ErrorText error={module.error} />;
  const m = module.data;
  const archived = m.status === "archived";

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-muted">
            <span
              aria-hidden
              className="mr-2 inline-block h-2.5 w-2.5 rounded-full"
              style={{ background: m.colour ?? "var(--color-accent)" }}
            />
            {m.code}
            {m.subject_tag && ` · ${m.subject_tag}`}
            {m.credits !== null && ` · ${m.credits} credits`}
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">{m.title}</h1>
          {archived && (
            <p className="mt-1 inline-block rounded bg-surface px-2 py-0.5 text-xs text-muted">
              Archived
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <Link
            to="/search"
            search={{ q: "", module_id: m.id }}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border px-2 text-xs font-medium hover:bg-surface"
          >
            <Search size={14} /> Search this module
          </Link>
          <Link
            to="/chat"
            search={{ module_id: m.id }}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border px-2 text-xs font-medium hover:bg-surface"
          >
            <MessageSquare size={14} /> Ask about this module
          </Link>
          <Button size="sm" onClick={() => setEditing(true)}>
            <Pencil size={14} /> Edit
          </Button>
          <Button
            size="sm"
            disabled={update.isPending}
            onClick={() => update.mutate({ status: archived ? "active" : "archived" })}
          >
            {archived ? <ArchiveRestore size={14} /> : <Archive size={14} />}
            {archived ? "Unarchive" : "Archive"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setDeleting(true)}>
            <Trash2 size={14} /> Delete
          </Button>
        </div>
      </header>
      <ErrorText error={update.error} />

      <StudySection moduleId={moduleId} />
      <ProgressSection moduleId={moduleId} />

      <div className="grid gap-8 xl:grid-cols-2">
        <TopicTree moduleId={moduleId} />
        <Materials moduleId={moduleId} />
      </div>

      {editing && <EditModuleDialog open={editing} onOpenChange={setEditing} module={m} />}
      <ConfirmDelete
        open={deleting}
        onOpenChange={setDeleting}
        thing={`${m.code} ${m.title}`}
        detail="The module and all its topics move to the trash. You can restore them from Settings for 30 days."
        onConfirm={async () => {
          await remove.mutateAsync(m.id);
          await navigate({ to: "/" });
        }}
      />
    </div>
  );
}
