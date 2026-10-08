import * as Dialog from "@radix-ui/react-dialog";
import { Link, Navigate, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  BarChart3,
  ChartLine,
  CalendarDays,
  CalendarRange,
  Command,
  Layers,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  Plus,
  Search as SearchIcon,
  Settings,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui";
import { useLogout, useSession } from "@/features/auth/session";
import { NotificationBell } from "@/features/planner/NotificationBell";
import { NewModuleDialog, YearDialog } from "@/features/structure/forms";
import { ExamControlProvider, ExamTimer } from "@/features/study/ExamTimer";
import { useModules, type Module } from "@/features/structure/queries";

import { CommandPalette } from "./CommandPalette";
import { ShortcutsHelp, useShortcuts } from "./shortcuts";
import { SidebarResizer, useSidebarWidth } from "./SidebarResizer";
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

/** Search box; "/" focuses it from anywhere (Ctrl+K opens the palette). */
function SidebarSearch() {
  const navigate = useNavigate();
  const [text, setText] = useState("");

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
        id="sidebar-search"
        type="search"
        aria-label="Search your materials"
        aria-keyshortcuts="/"
        placeholder="Search  ( / )"
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="h-9 w-full rounded-md border border-border bg-bg pl-8 pr-2 text-sm"
      />
    </form>
  );
}

function Sidebar({ onOpenPalette, inDrawer = false }: { onOpenPalette: () => void; inDrawer?: boolean }) {
  const { years, year, setYearId } = useViewingYear();
  const [showArchived, setShowArchived] = useState(false);
  const modules = useModules(year?.id, showArchived ? "all" : "active");
  const [newModule, setNewModule] = useState(false);
  const [newYear, setNewYear] = useState(false);
  const logout = useLogout();
  const navigate = useNavigate();

  return (
    <nav aria-label="Main" className="flex h-full w-full flex-col gap-4 overflow-y-auto bg-bg p-3">
      <div className="flex items-center justify-between">
        <Link to="/" className="px-2 text-base font-semibold">
          Revision OS
        </Link>
        {/* In the phone drawer the top bar has the bell. */}
        {!inDrawer && <NotificationBell />}
      </div>

      <SidebarSearch />
      <button
        type="button"
        onClick={onOpenPalette}
        aria-keyshortcuts="Control+K"
        className="flex items-center justify-between rounded-md px-2 py-1 text-xs text-muted hover:bg-surface"
      >
        <span className="flex items-center gap-1.5">
          <Command size={12} aria-hidden /> Commands
        </span>
        <kbd className="font-mono">Ctrl K</kbd>
      </button>

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
          to="/planner"
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface"
          activeProps={{ className: "bg-surface font-medium" }}
        >
          <CalendarRange size={16} /> Planner
        </Link>
        <Link
          to="/calendar"
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface"
          activeProps={{ className: "bg-surface font-medium" }}
        >
          <CalendarDays size={16} /> Calendar
        </Link>
        <Link
          to="/analytics"
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface"
          activeProps={{ className: "bg-surface font-medium" }}
        >
          <ChartLine size={16} /> Analytics
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

/** True on screens at least `md` wide (tests have no matchMedia: desktop). */
function useIsDesktop(): boolean {
  const query = "(min-width: 768px)";
  const [desktop, setDesktop] = useState(() =>
    typeof window.matchMedia === "function" ? window.matchMedia(query).matches : true,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const update = () => setDesktop(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return desktop;
}

/** On a phone: a top bar, with the sidebar in a drawer. */
function MobileBar({ onOpenPalette }: { onOpenPalette: () => void }) {
  const [open, setOpen] = useState(false);
  const location = useRouterState({ select: (s) => s.location.pathname });
  // Close the drawer once a link in it has been followed.
  useEffect(() => setOpen(false), [location]);
  return (
    <header className="sticky top-0 z-30 flex items-center justify-between gap-2 border-b border-border bg-bg px-2 py-2">
      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Trigger asChild>
          <Button variant="ghost" size="sm" aria-label="Open menu">
            <Menu size={20} />
          </Button>
        </Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
          <Dialog.Content className="fixed inset-y-0 left-0 z-50 w-[min(18rem,85vw)] border-r border-border bg-bg shadow-xl">
            <Dialog.Title className="sr-only">Menu</Dialog.Title>
            <Dialog.Description className="sr-only">Pages, modules and settings.</Dialog.Description>
            <Dialog.Close asChild>
              <Button variant="ghost" size="sm" aria-label="Close menu" className="absolute right-2 top-2 z-10">
                <X size={18} />
              </Button>
            </Dialog.Close>
            <Sidebar
              inDrawer
              onOpenPalette={() => {
                setOpen(false);
                onOpenPalette();
              }}
            />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
      <Link to="/" className="text-base font-semibold">
        Revision OS
      </Link>
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="sm" aria-label="Search and commands" onClick={onOpenPalette}>
          <SearchIcon size={18} />
        </Button>
        <NotificationBell />
      </div>
    </header>
  );
}

/** Layout for every signed-in page; signed-out visitors go to /login. */
export function AppShell() {
  const session = useSession();
  const desktop = useIsDesktop();
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useSidebarWidth();
  useShortcuts({ openPalette: () => setPalette(true), openHelp: () => setHelp(true) });
  if (session.isPending) return <p className="p-6 text-sm text-muted">Loading…</p>;
  if (!session.data) return <Navigate to="/login" />;
  return (
    <ViewingYearProvider>
      <ExamControlProvider>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-bg focus:px-3 focus:py-2 focus:shadow"
      >
        Skip to content
      </a>
      <div className="flex min-h-screen flex-col md:flex-row">
        {desktop ? (
          <aside
            className="relative h-screen shrink-0 border-r border-border md:sticky md:top-0"
            style={{ width: sidebarWidth }}
          >
            <Sidebar onOpenPalette={() => setPalette(true)} />
            <SidebarResizer width={sidebarWidth} onResize={setSidebarWidth} />
          </aside>
        ) : (
          <MobileBar onOpenPalette={() => setPalette(true)} />
        )}
        <main id="main" tabIndex={-1} className="min-w-0 flex-1 px-4 py-6 outline-none md:px-10">
          <Outlet />
        </main>
        <ExamTimer />
      </div>
      <CommandPalette open={palette} onOpenChange={setPalette} />
      <ShortcutsHelp open={help} onOpenChange={setHelp} />
      </ExamControlProvider>
    </ViewingYearProvider>
  );
}
