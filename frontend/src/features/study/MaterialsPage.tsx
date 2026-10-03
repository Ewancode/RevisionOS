import { Link, useNavigate } from "@tanstack/react-router";
import { Plus, Sparkles } from "lucide-react";
import { useState } from "react";

import { MathMarkdown } from "@/components/MathMarkdown";
import { Button, ErrorText } from "@/components/ui";
import { useModule } from "@/features/structure/queries";

import { GenerateDialog } from "./GenerateDialog";
import { MATERIAL_KINDS, label, useCreateMaterial, useMaterials, type MaterialKind, type MaterialSummary } from "./queries";
import { ModuleHeader } from "./StudySection";

function MaterialList({ title, items, empty }: { title: string; items: MaterialSummary[]; empty: string }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-base font-semibold">{title}</h2>
      {items.length === 0 ? (
        <p className="text-sm text-muted">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {items.map((m) => (
            <li key={m.id}>
              <Link
                to="/materials/$materialId"
                params={{ materialId: m.id }}
                className="flex items-baseline justify-between gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface"
              >
                <span className="truncate font-medium">{m.title}</span>
                <span className="shrink-0 text-xs text-muted">
                  {label(MATERIAL_KINDS, m.kind)} · {new Date(m.updated_at).toLocaleDateString("en-GB")}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function NewMaterial({ moduleId, onDone }: { moduleId: string; onDone: () => void }) {
  const create = useCreateMaterial();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<MaterialKind>("notes");
  const [content, setContent] = useState("");
  return (
    <form
      className="flex flex-col gap-2 rounded-lg border border-border p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        const material = await create.mutateAsync({ module_id: moduleId, title, kind, content_md: content });
        onDone();
        await navigate({ to: "/materials/$materialId", params: { materialId: material.id } });
      }}
    >
      <div className="flex flex-wrap gap-2">
        <input
          aria-label="Title"
          placeholder="Title"
          required
          maxLength={200}
          className="h-9 flex-1 rounded-md border border-border bg-bg px-2 text-sm"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <select
          aria-label="Kind"
          className="h-9 rounded-md border border-border bg-bg px-2 text-sm"
          value={kind}
          onChange={(e) => setKind(e.target.value as MaterialKind)}
        >
          {MATERIAL_KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
      </div>
      <div className="grid gap-2 lg:grid-cols-2">
        <textarea
          aria-label="Content (Markdown with LaTeX)"
          placeholder="Markdown with LaTeX: $...$ inline, $$...$$ display"
          required
          className="min-h-64 rounded-md border border-border bg-bg p-2 font-mono text-sm"
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
        <MathMarkdown className="min-h-64 rounded-md border border-border p-2 text-sm">{content || "*Preview*"}</MathMarkdown>
      </div>
      <ErrorText error={create.error} />
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={create.isPending}>
          Save
        </Button>
        <Button onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

export function MaterialsPage({ moduleId }: { moduleId: string }) {
  const module = useModule(moduleId);
  const materials = useMaterials(moduleId);
  const [creating, setCreating] = useState(false);
  const [generating, setGenerating] = useState(false);
  const all = materials.data ?? [];
  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <ModuleHeader module={module.data} title="Revision materials" />
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => setGenerating(true)}>
          <Sparkles size={14} /> Generate with Claude
        </Button>
        <Button onClick={() => setCreating(true)}>
          <Plus size={14} /> Write your own
        </Button>
      </div>
      {creating && <NewMaterial moduleId={moduleId} onDone={() => setCreating(false)} />}
      <ErrorText error={materials.error} />
      <MaterialList
        title="My materials"
        items={all.filter((m) => m.origin === "user")}
        empty="Nothing yet. Write your own notes, guides or formula sheets here."
      />
      <MaterialList
        title="Claude generated"
        items={all.filter((m) => m.origin === "claude")}
        empty="Nothing yet. Ask Claude for a guide, summary or formula sheet."
      />
      <GenerateDialog open={generating} onOpenChange={setGenerating} moduleId={moduleId} kind="material" />
    </div>
  );
}
