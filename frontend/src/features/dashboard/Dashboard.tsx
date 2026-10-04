import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { useViewingYear } from "@/app/viewingYear";
import { Button } from "@/components/ui";
import { useSession } from "@/features/auth/session";
import { TodayPanels } from "@/features/learning/TodayPanels";
import { NewModuleDialog, YearDialog } from "@/features/structure/forms";
import { useModules } from "@/features/structure/queries";
import { greeting } from "@/lib/greeting";

/** Today: what to practise now (daily quiz, due flashcards, weak topics,
 *  recurring mistakes) and your modules. Exams and the plan join in Phase 8. */
export function Dashboard() {
  const session = useSession();
  const { year, isPending } = useViewingYear();
  const modules = useModules(year?.id);
  const [newYear, setNewYear] = useState(false);
  const [newModule, setNewModule] = useState(false);

  const name = session.data?.user.display_name ?? "";

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">
          {greeting()}, {name}
        </h1>
        {year && <p className="text-sm text-muted">Viewing {year.label}</p>}
      </header>

      {!isPending && !year && (
        <section className="rounded-lg border border-border bg-surface p-5">
          <h2 className="font-semibold">Start with your academic year</h2>
          <p className="mt-1 text-sm text-muted">
            Years hold your modules. Earlier years stay available when you move on.
          </p>
          <Button className="mt-3" variant="primary" onClick={() => setNewYear(true)}>
            Create academic year
          </Button>
        </section>
      )}

      {year && modules.data?.length === 0 && (
        <section className="rounded-lg border border-border bg-surface p-5">
          <h2 className="font-semibold">Add your first module</h2>
          <p className="mt-1 text-sm text-muted">
            For example MATH103 Linear Algebra. You can add its topics next.
          </p>
          <Button className="mt-3" variant="primary" onClick={() => setNewModule(true)}>
            Add module
          </Button>
        </section>
      )}

      {year && !!modules.data?.length && <TodayPanels />}

      {year && !!modules.data?.length && (
        <section aria-labelledby="modules-heading">
          <h2 id="modules-heading" className="mb-3 text-base font-semibold">
            Modules
          </h2>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {modules.data.map((m) => (
              <li key={m.id}>
                <Link
                  to="/y/$yearId/m/$moduleId"
                  params={{ yearId: year.id, moduleId: m.id }}
                  className="block rounded-lg border border-border p-4 hover:bg-surface"
                  style={{ borderTop: `3px solid ${m.colour ?? "var(--color-accent)"}` }}
                >
                  <p className="text-xs font-medium text-muted">{m.code}</p>
                  <p className="font-medium">{m.title}</p>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <YearDialog open={newYear} onOpenChange={setNewYear} />
      {year && <NewModuleDialog open={newModule} onOpenChange={setNewModule} yearId={year.id} />}
    </div>
  );
}
