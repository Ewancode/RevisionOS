import * as Dialog from "@radix-ui/react-dialog";
import { useNavigate } from "@tanstack/react-router";
import { Command } from "cmdk";
import {
  BarChart3,
  BookText,
  CalendarDays,
  CalendarRange,
  ChartLine,
  Code2,
  Layers,
  LayoutDashboard,
  ListChecks,
  MessageSquare,
  Moon,
  Play,
  Search,
  Settings,
  Sun,
  Timer,
  Upload,
  XCircle,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import { useSession, useUpdateSettings } from "@/features/auth/session";
import { useStartDaily } from "@/features/learning/queries";
import { useModules } from "@/features/structure/queries";
import { useStartQuiz } from "@/features/study/queries";

import { useViewingYear } from "./viewingYear";

const item =
  "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm aria-selected:bg-surface data-[disabled=true]:opacity-50";
const group = "px-1 py-1 text-xs font-medium text-muted [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1";

function Item({
  onSelect,
  icon,
  children,
  keywords,
  shortcut,
}: {
  onSelect: () => void;
  icon: ReactNode;
  children: ReactNode;
  keywords?: string[];
  shortcut?: string;
}) {
  return (
    <Command.Item className={item} onSelect={onSelect} keywords={keywords}>
      <span aria-hidden className="text-muted">
        {icon}
      </span>
      <span className="flex-1 text-fg">{children}</span>
      {shortcut && <kbd className="text-xs text-muted">{shortcut}</kbd>}
    </Command.Item>
  );
}

/**
 * Ctrl+K: go anywhere, start anything, or search (SPEC 67). Actions on a
 * module list each of the current year's modules, so typing its code
 * narrows to them.
 */
export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate();
  const { year } = useViewingYear();
  const modules = useModules(year?.id);
  const session = useSession();
  const settings = useUpdateSettings();
  const daily = useStartDaily();
  const quiz = useStartQuiz();
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  const run = (action: () => unknown) => async () => {
    setError(null);
    try {
      await action();
      onOpenChange(false);
      setQuery("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "That did not work.");
    }
  };
  const dark = session.data?.settings.theme === "dark";

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) setError(null);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <Dialog.Content className="fixed left-1/2 top-[12vh] z-50 w-[min(36rem,calc(100vw-2rem))] -translate-x-1/2 overflow-hidden rounded-lg border border-border bg-bg shadow-xl">
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <Dialog.Description className="sr-only">
            Type to find a page, start practice, act on a module or search your materials.
          </Dialog.Description>
          <Command label="Command palette" loop>
            <div className="flex items-center gap-2 border-b border-border px-3">
              <Search size={16} className="text-muted" aria-hidden />
              <Command.Input
                value={query}
                onValueChange={setQuery}
                placeholder="Type a command, a module or something to search…"
                className="h-11 flex-1 bg-transparent text-sm outline-none"
              />
            </div>
            {error && (
              <p role="alert" className="flex items-center gap-1 px-3 py-2 text-sm text-danger">
                <XCircle size={14} /> {error}
              </p>
            )}
            <Command.List className="max-h-[60vh] overflow-y-auto p-1">
              <Command.Empty className="px-3 py-6 text-center text-sm text-muted">Nothing matches.</Command.Empty>
              {query.trim() && (
                <Command.Group heading="Search" className={group} forceMount>
                  <Command.Item
                    className={item}
                    value={`search ${query}`}
                    forceMount
                    onSelect={run(() => navigate({ to: "/search", search: { q: query.trim() } }))}
                  >
                    <Search size={16} className="text-muted" aria-hidden />
                    <span className="flex-1 text-fg">Search your materials for “{query.trim()}”</span>
                  </Command.Item>
                  <Command.Item
                    className={item}
                    value={`ask ${query}`}
                    forceMount
                    onSelect={run(() => navigate({ to: "/chat", search: {} }))}
                  >
                    <MessageSquare size={16} className="text-muted" aria-hidden />
                    <span className="flex-1 text-fg">Ask Claude</span>
                  </Command.Item>
                </Command.Group>
              )}
              <Command.Group heading="Practise" className={group}>
                <Item
                  icon={<Play size={16} />}
                  keywords={["daily", "quiz", "start"]}
                  onSelect={run(async () => {
                    const started = await daily.mutateAsync();
                    await navigate({ to: "/attempts/$attemptId", params: { attemptId: started.attempt_id } });
                  })}
                >
                  Start today's quiz
                </Item>
                <Item icon={<Layers size={16} />} keywords={["flashcards", "cards", "review"]} shortcut="g r" onSelect={run(() => navigate({ to: "/review", search: {} }))}>
                  Review flashcards
                </Item>
                <Item icon={<XCircle size={16} />} keywords={["mistakes", "errors"]} onSelect={run(() => navigate({ to: "/mistakes", search: {} }))}>
                  Mistake bank
                </Item>
              </Command.Group>
              <Command.Group heading="Go to" className={group}>
                <Item icon={<LayoutDashboard size={16} />} shortcut="g t" onSelect={run(() => navigate({ to: "/" }))}>
                  Today
                </Item>
                <Item icon={<MessageSquare size={16} />} keywords={["claude", "chat", "assistant"]} shortcut="Ctrl J" onSelect={run(() => navigate({ to: "/chat", search: {} }))}>
                  Ask Claude
                </Item>
                <Item icon={<CalendarRange size={16} />} keywords={["plan", "exams"]} shortcut="g p" onSelect={run(() => navigate({ to: "/planner" }))}>
                  Revision planner
                </Item>
                <Item icon={<CalendarDays size={16} />} shortcut="g c" onSelect={run(() => navigate({ to: "/calendar" }))}>
                  Calendar
                </Item>
                <Item icon={<ChartLine size={16} />} keywords={["weak topics", "readiness", "progress"]} shortcut="g a" onSelect={run(() => navigate({ to: "/analytics" }))}>
                  Analytics and weak topics
                </Item>
                <Item icon={<BarChart3 size={16} />} onSelect={run(() => navigate({ to: "/profile" }))}>
                  Learning profile
                </Item>
                <Item icon={<Settings size={16} />} shortcut="g s" onSelect={run(() => navigate({ to: "/settings" }))}>
                  Settings
                </Item>
                <Item icon={<BarChart3 size={16} />} keywords={["cost", "budget"]} onSelect={run(() => navigate({ to: "/usage" }))}>
                  AI usage
                </Item>
              </Command.Group>
              {(modules.data ?? []).length > 0 && year && (
                <Command.Group heading="Modules" className={group}>
                  {(modules.data ?? []).flatMap((m) => {
                    const name = `${m.code} ${m.title}`;
                    const words = [m.code, m.title];
                    return [
                      <Item key={`${m.id}-open`} icon={<BookText size={16} />} keywords={words}
                        onSelect={run(() => navigate({ to: "/y/$yearId/m/$moduleId", params: { yearId: year.id, moduleId: m.id } }))}>
                        Open {name}
                      </Item>,
                      <Item key={`${m.id}-quiz`} icon={<ListChecks size={16} />} keywords={[...words, "quiz", "questions", "generate"]}
                        onSelect={run(() => navigate({ to: "/modules/$moduleId/questions", params: { moduleId: m.id } }))}>
                        {m.code}: questions and quizzes
                      </Item>,
                      <Item key={`${m.id}-mock`} icon={<Timer size={16} />} keywords={[...words, "mock", "exam", "start"]}
                        onSelect={run(async () => {
                          const started = await quiz.mutateAsync({ module_id: m.id, kind: "mock" });
                          await navigate({ to: "/attempts/$attemptId", params: { attemptId: started.attempt_id } });
                        })}>
                        {m.code}: start a mock exam
                      </Item>,
                      <Item key={`${m.id}-guide`} icon={<BookText size={16} />} keywords={[...words, "revision guide", "create", "material"]}
                        onSelect={run(() => navigate({ to: "/modules/$moduleId/materials", params: { moduleId: m.id } }))}>
                        {m.code}: revision materials
                      </Item>,
                      <Item key={`${m.id}-upload`} icon={<Upload size={16} />} keywords={[...words, "upload", "lecture", "file"]}
                        onSelect={run(() => navigate({ to: "/y/$yearId/m/$moduleId", params: { yearId: year.id, moduleId: m.id } }))}>
                        {m.code}: upload material
                      </Item>,
                      <Item key={`${m.id}-cards`} icon={<Layers size={16} />} keywords={[...words, "flashcards"]}
                        onSelect={run(() => navigate({ to: "/review", search: { module_id: m.id } }))}>
                        {m.code}: review flashcards
                      </Item>,
                      <Item key={`${m.id}-code`} icon={<Code2 size={16} />} keywords={[...words, "coding", "python", "r"]}
                        onSelect={run(() => navigate({ to: "/modules/$moduleId/coding", params: { moduleId: m.id } }))}>
                        {m.code}: coding practice
                      </Item>,
                    ];
                  })}
                </Command.Group>
              )}
              <Command.Group heading="Appearance" className={group}>
                <Item
                  icon={dark ? <Sun size={16} /> : <Moon size={16} />}
                  keywords={["theme", "dark", "light", "mode"]}
                  onSelect={run(() => settings.mutateAsync({ theme: dark ? "light" : "dark" }))}
                >
                  Switch to {dark ? "light" : "dark"} theme
                </Item>
              </Command.Group>
            </Command.List>
          </Command>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
