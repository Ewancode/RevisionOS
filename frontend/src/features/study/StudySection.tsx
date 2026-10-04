import { Link } from "@tanstack/react-router";
import { BookText, Code2, Layers, ListChecks, RefreshCw } from "lucide-react";

import type { Module } from "@/features/structure/queries";

import { useDrafts } from "./queries";

/** Breadcrumb back to the module, and the page title. */
export function ModuleHeader({ module, title }: { module: Module | undefined; title: string }) {
  return (
    <header className="flex flex-col gap-1">
      {module && (
        <Link
          to="/y/$yearId/m/$moduleId"
          params={{ yearId: module.academic_year_id, moduleId: module.id }}
          className="text-sm text-muted hover:underline"
        >
          {module.code} {module.title}
        </Link>
      )}
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
    </header>
  );
}

const DRAFT_NAMES = {
  material: "Material",
  questions: "Questions",
  flashcards: "Flashcards",
  coding: "Coding exercises",
} as const;

/** On a module's page: where to revise, and drafts awaiting your decision. */
export function StudySection({ moduleId }: { moduleId: string }) {
  const drafts = useDrafts(moduleId);
  const link =
    "flex items-center gap-2 rounded-lg border border-border p-3 text-sm font-medium hover:bg-surface";
  return (
    <section aria-labelledby="study" className="flex flex-col gap-3">
      <h2 id="study" className="text-base font-semibold">
        Study
      </h2>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Link to="/modules/$moduleId/materials" params={{ moduleId }} className={link}>
          <BookText size={16} /> Revision materials
        </Link>
        <Link to="/modules/$moduleId/questions" params={{ moduleId }} className={link}>
          <ListChecks size={16} /> Questions and quizzes
        </Link>
        <Link to="/modules/$moduleId/flashcards" params={{ moduleId }} className={link}>
          <Layers size={16} /> Flashcards
        </Link>
        <Link to="/modules/$moduleId/coding" params={{ moduleId }} className={link}>
          <Code2 size={16} /> Coding practice
        </Link>
      </div>
      {(drafts.data?.length ?? 0) > 0 && (
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-medium">Drafts waiting for you</h3>
          <ul className="flex flex-col gap-1">
            {drafts.data?.map((d) => (
              <li key={d.id}>
                <Link
                  to="/drafts/$draftId"
                  params={{ draftId: d.id }}
                  className="flex items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-surface"
                >
                  {d.status === "generating" && <RefreshCw size={12} className="animate-spin" />}
                  {DRAFT_NAMES[d.kind]}
                  <span className="text-xs text-muted">
                    {d.status === "generating" ? "being written" : d.status === "failed" ? "failed" : "ready to review"}
                    {" · "}
                    {new Date(d.created_at).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" })}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
