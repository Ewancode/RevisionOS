import { Link, Navigate, Outlet, useNavigate } from "@tanstack/react-router";
import {
  BarChart3,
  Layers,
  LayoutDashboard,
  LogOut,
  MessageSquare,
  Plus,
  Search as SearchIcon,
  Settings,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui";
import { useLogout, useSession } from "@/features/auth/session";
import { NewModuleDialog, YearDialog } from "@/features/structure/forms";
import { useModules, type Module } from "@/features/structure/queries";

import { useViewingYear, ViewingYearProvider } from "./viewingYear";

function groupBySubject(modules: Module[]): [string | null, Module[]][] {
  const groups = new Map<string | null, Module[]>();
  for (const m of modules) {
    const key = m.subject_tag ?? null;
    groups.set(key, [...(groups.get(key) ?? []), m]);
  }
  // Untagged modules first, then subjects alphabetically.
  return [...groups.entries()].sort(([a], [b]) =>
    a === null ? -1 : b === null ? 1 : a.localeCompare(b),
  );
}

function ModuleLink({ module, yearId }: { module: Module; yearId: string }) {
  return (
    <Link
      to="/y/$yearId/m/$moduleId"
      params={{ yearId, moduleId: module.id }}
      className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface"
      activeProps={{ className: "bg-surface font-medium" }}
    >
      <span
        aria-hidden
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ background: module.colour ?? "var(--color-accent)" }}
      />
      <span className="truncate">
        <span className="text-muted">{module.code}</span> {module.title}
      </span>
    </Link>
  );
}

/** Search box; Ctrl+K (Cmd+K on a Mac) focuses it from anywhere. */
function SidebarSearch() {
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        input.current?.focus();
        input.current?.select();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <form
      role="search"
      className="relative"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) void navigate({ to: "/search", search: { q: text.trim() } });
      }}
    >
      <SearchIcon size={14} className="pointer-events-none absolute left-2.5 top-2.5 text-muted" aria-hidden />
      <input
        ref={input}
        type="search"
        aria-label="Search your materials"
        aria-keyshortcuts="Control+K"
        placeholder="Search  (Ctrl+K)"
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="h-9 w-full rounded-md border border-border bg-bg pl-8 pr-2 text-sm"
      />
    </form>
  );
}

function Sidebar() {
  const { years, year, setYearId } = useViewingYear();
  const [showArchived, setShowArchived] = useState(false);
  const modules = useModules(year?.id, showArchived ? "all" : "active");
  const [newModule, setNewModule] = useState(false);
  const [newYear, setNewYear] = useState(false);
  const logout = useLogout();
  const navigate = useNavigate();

  return (
    <nav
      aria-label="Main"
      className="flex w-full flex-col gap-4 border-b border-border bg-bg p-3 md:h-screen md:w-64 md:shrink-0 md:overflow-y-auto md:border-b-0 md:border-r"
    >
      <Link to="/" className="px-2 text-base font-semibold">
        Revision OS
      </Link>

      <SidebarSearch />

      <div className="flex flex-col gap-1">
        <Link
          to="/"
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface"
          activeOptions={{ exact: true }}
          activeProps={{ className: "bg-surface font-medium" }}
        >
          <LayoutDashboard size={16} /> Today
        </Link>
        <Link
          to="/chat"
          search={{}}
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface"
          activeProps={{ className: "bg-surface font-medium" }}
        >
          <MessageSquare size={16} /> Ask Claude
        </Link>
        <Link
          to="/review"
          search={{}}
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface"
          activeProps={{ className: "bg-surface font-medium" }}
        >
          <Layers size={16} /> Review flashcards
        </Link>
        <Link
          to="/profile"
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface"
          activeProps={{ className: "bg-surface font-medium" }}
        >
          <BarChart3 size={16} /> Learning profile
        </Link>
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="year-switcher" className="px-2 text-xs font-medium uppercase text-muted">
          Academic year
        </label>
        <div className="flex gap-1">
          <select
            id="year-switcher"
            className="h-8 flex-1 rounded-md border border-border bg-bg px-2 text-sm"
            value={year?.id ?? ""}
            onChange={(e) => {
              setYearId(e.target.value);
              void navigate({ to: "/" });
            }}
          >
            {years.map((y) => (
              <option key={y.id} value={y.id}>
                {y.label}
                {y.is_current ? " (current)" : ""}
              </option>
            ))}
          </select>
          <Button size="sm" variant="ghost" aria-label="New academic year" onClick={() => setNewYear(true)}>
            <Plus size={14} />
          </Button>
        </div>
      </div>

      {year && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between px-2">
            <h2 className="text-xs font-medium uppercase text-muted">Modules</h2>
            <Button size="sm" variant="ghost" aria-label="New module" onClick={() => setNewModule(true)}>
              <Plus size={14} />
            </Button>
          </div>
          {groupBySubject(modules.data ?? []).map(([subject, items]) => (
            <div key={subject ?? "_"} className="flex flex-col">
              {subject && <p className="px-2 pt-2 text-xs text-muted">{subject}</p>}
              {items.map((m) => (
                <ModuleLink key={m.id} module={m} yearId={year.id} />
              ))}
            </div>
          ))}
          <label className="flex items-center gap-2 px-2 pt-1 text-xs text-muted">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
            />
            Show archived
          </label>
        </div>
      )}

      <div className="mt-auto flex flex-col gap-1">
        <Link
          to="/settings"
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface"
          activeProps={{ className: "bg-surface font-medium" }}
        >
          <Settings size={16} /> Settings
        </Link>
        <button
          type="button"
          onClick={async () => {
            await logout.mutateAsync().catch(() => undefined);
            await navigate({ to: "/login" });
          }}
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-surface"
        >
          <LogOut size={16} /> Sign out
        </button>
      </div>

      <YearDialog open={newYear} onOpenChange={setNewYear} onCreated={(y) => setYearId(y.id)} />
      {year && (
        <NewModuleDialog
          open={newModule}
          onOpenChange={setNewModule}
          yearId={year.id}
          onCreated={(m) =>
            navigate({ to: "/y/$yearId/m/$moduleId", params: { yearId: year.id, moduleId: m.id } })
          }
        />
      )}
    </nav>
  );
}

/** Layout for every signed-in page; signed-out visitors go to /login. */
export function AppShell() {
  const session = useSession();
  if (session.isPending) return <p className="p-6 text-sm text-muted">Loading…</p>;
  if (!session.data) return <Navigate to="/login" />;
  return (
    <ViewingYearProvider>
      <div className="flex min-h-screen flex-col md:flex-row">
        <Sidebar />
        <main className="flex-1 px-4 py-6 md:px-10">
          <Outlet />
        </main>
      </div>
    </ViewingYearProvider>
  );
}
