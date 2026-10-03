import { useNavigate } from "@tanstack/react-router";
import { GitCompare, History, Pencil, RotateCcw, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";

import { CitedMarkdown, Sources } from "@/components/CitedMarkdown";
import { MathMarkdown } from "@/components/MathMarkdown";
import { Button, ConfirmDelete, ErrorText } from "@/components/ui";
import { useModule } from "@/features/structure/queries";

import { GenerateDialog } from "./GenerateDialog";
import {
  MATERIAL_KINDS,
  label,
  useDiff,
  useMaterial,
  useMaterialActions,
  useVersion,
  type Material,
} from "./queries";
import { ModuleHeader } from "./StudySection";

function DiffView({ materialId, from, to }: { materialId: string; from: string; to: string }) {
  const diff = useDiff(materialId, from, to);
  if (diff.isPending) return <p className="text-sm text-muted">Comparing…</p>;
  if (diff.isError) return <ErrorText error={diff.error} />;
  const changed = diff.data.lines.some((l) => l.op !== "equal");
  return (
    <section aria-label="Changes" className="flex flex-col gap-1">
      <h2 className="text-sm font-semibold">
        Version {diff.data.from_version} → version {diff.data.to_version}
      </h2>
      {!changed && <p className="text-sm text-muted">No differences.</p>}
      <pre className="overflow-x-auto rounded-md border border-border p-2 text-xs leading-5">
        {diff.data.lines.map((line, i) => (
          <div
            key={i}
            className={
              line.op === "insert"
                ? "bg-[color-mix(in_srgb,var(--color-success)_15%,transparent)]"
                : line.op === "delete"
                  ? "bg-[color-mix(in_srgb,var(--color-danger)_15%,transparent)] line-through"
                  : "text-muted"
            }
          >
            <span aria-hidden className="mr-2 select-none">
              {line.op === "insert" ? "+" : line.op === "delete" ? "−" : " "}
            </span>
            <span className="sr-only">{line.op === "insert" ? "Added: " : line.op === "delete" ? "Removed: " : ""}</span>
            {line.text || " "}
          </div>
        ))}
      </pre>
    </section>
  );
}

function Editor({ material, onDone }: { material: Material; onDone: () => void }) {
  const { addVersion } = useMaterialActions(material.id);
  const [content, setContent] = useState(material.current.content_md);
  const [note, setNote] = useState("");
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        await addVersion.mutateAsync({ content_md: content, change_note: note.trim() || null });
        onDone();
      }}
    >
      <p className="text-sm text-muted">Saving creates version {material.versions.length + 1}; earlier versions are kept.</p>
      <div className="grid gap-2 lg:grid-cols-2">
        <textarea
          aria-label="Material (Markdown)"
          className="min-h-96 rounded-md border border-border bg-bg p-2 font-mono text-sm"
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
        <MathMarkdown className="min-h-96 rounded-md border border-border p-2 text-sm">{content}</MathMarkdown>
      </div>
      <input
        aria-label="What changed (optional)"
        placeholder="What changed (optional)"
        maxLength={300}
        className="h-9 rounded-md border border-border bg-bg px-2 text-sm"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <ErrorText error={addVersion.error} />
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={addVersion.isPending || content === material.current.content_md}>
          Save new version
        </Button>
        <Button onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

export function MaterialPage({ materialId }: { materialId: string }) {
  const material = useMaterial(materialId);
  const module = useModule(material.data?.module_id ?? "", material.data !== undefined);
  const actions = useMaterialActions(materialId);
  const navigate = useNavigate();
  const [viewing, setViewing] = useState<string | null>(null);
  const [comparing, setComparing] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [improving, setImproving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deletingVersion, setDeletingVersion] = useState<{ id: string; no: number } | null>(null);
  const old = useVersion(materialId, viewing);

  if (material.isPending) return <p className="text-sm text-muted">Loading…</p>;
  if (material.isError) return <ErrorText error={material.error} />;
  const m = material.data;
  const shown = viewing && old.data ? old.data : m.current;

  return (
    <div className="flex max-w-6xl flex-col gap-4">
      <ModuleHeader module={module.data} title={m.title} />
      <p className="text-sm text-muted">
        {label(MATERIAL_KINDS, m.kind)} · {m.origin === "claude" ? "Claude generated" : "My material"} · version{" "}
        {m.current.version_no}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => setEditing(true)} disabled={editing}>
          <Pencil size={14} /> Edit
        </Button>
        <Button size="sm" onClick={() => setImproving(true)}>
          <Sparkles size={14} /> Improve with Claude
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setDeleting(true)}>
          <Trash2 size={14} /> Delete
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_16rem]">
        <div className="flex min-w-0 flex-col gap-4">
          {editing ? (
            <Editor material={m} onDone={() => setEditing(false)} />
          ) : (
            <>
              {viewing && (
                <p role="status" className="flex items-center gap-2 rounded-md bg-surface px-2 py-1 text-sm">
                  Viewing version {shown.version_no}.
                  <Button size="sm" variant="ghost" onClick={() => setViewing(null)}>
                    Back to current
                  </Button>
                </p>
              )}
              {comparing && <DiffView materialId={m.id} from={comparing} to={m.current.id} />}
              <article className="rounded-lg border border-border p-4">
                <CitedMarkdown content={shown.content_md} citations={shown.citations} />
                <Sources citations={shown.citations} />
              </article>
            </>
          )}
        </div>
        <aside aria-label="Version history" className="flex flex-col gap-2">
          <h2 className="flex items-center gap-1 text-sm font-semibold">
            <History size={14} /> Versions
          </h2>
          <ol className="flex flex-col gap-2">
            {m.versions.map((v) => {
              const current = v.id === m.current.id;
              return (
                <li key={v.id} className="flex flex-col gap-1 rounded-md border border-border p-2 text-xs">
                  <p>
                    <span className="font-medium">v{v.version_no}</span>
                    {current && " (current)"} · {v.created_by === "claude" ? "Claude" : "You"} ·{" "}
                    {new Date(v.created_at).toLocaleDateString("en-GB")}
                  </p>
                  {v.change_note && <p className="text-muted">{v.change_note}</p>}
                  {!current && (
                    <div className="flex flex-wrap gap-1">
                      <Button size="sm" variant="ghost" onClick={() => setViewing(v.id)}>
                        View
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setComparing(comparing === v.id ? null : v.id)}>
                        <GitCompare size={12} /> {comparing === v.id ? "Hide changes" : "Compare"}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => actions.restoreVersion.mutate(v.id)}>
                        <RotateCcw size={12} /> Restore
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`Delete version ${v.version_no}`}
                        onClick={() => setDeletingVersion({ id: v.id, no: v.version_no })}
                      >
                        <Trash2 size={12} />
                      </Button>
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
          <ErrorText error={actions.restoreVersion.error} />
        </aside>
      </div>

      <GenerateDialog
        open={improving}
        onOpenChange={setImproving}
        moduleId={m.module_id}
        kind="material"
        improveMaterialId={m.id}
      />
      <ConfirmDelete
        open={deleting}
        onOpenChange={setDeleting}
        thing={`“${m.title}”`}
        detail="It moves to the trash with all its versions; restore it from Settings for 30 days."
        onConfirm={async () => {
          await actions.remove.mutateAsync();
          await navigate({ to: "/modules/$moduleId/materials", params: { moduleId: m.module_id } });
        }}
      />
      <ConfirmDelete
        open={deletingVersion !== null}
        onOpenChange={(open) => !open && setDeletingVersion(null)}
        thing={`version ${deletingVersion?.no ?? ""}`}
        detail="Deleting a version is permanent. The other versions are not affected."
        onConfirm={async () => {
          if (!deletingVersion) return;
          await actions.deleteVersion.mutateAsync(deletingVersion.id);
          if (viewing === deletingVersion.id) setViewing(null);
          if (comparing === deletingVersion.id) setComparing(null);
        }}
      />
    </div>
  );
}
