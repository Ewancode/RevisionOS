import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import { Modal } from "@/components/ui";

/** "g" then a letter: go somewhere. */
const GO: Record<string, { to: string; label: string }> = {
  t: { to: "/", label: "Today" },
  p: { to: "/planner", label: "Revision planner" },
  c: { to: "/calendar", label: "Calendar" },
  a: { to: "/analytics", label: "Analytics" },
  r: { to: "/review", label: "Review flashcards" },
  s: { to: "/settings", label: "Settings" },
};

export const SHORTCUTS: [string, string][] = [
  ["Ctrl K", "Command palette: go anywhere, start practice, search"],
  ["Ctrl J", "Ask Claude (about the module you are in)"],
  ["/", "Focus the search box"],
  ...Object.entries(GO).map(([key, { label }]): [string, string] => [`g ${key}`, label]),
  ["Ctrl Enter", "Run the tests (in a coding exercise)"],
  ["?", "Show these shortcuts"],
];

/** Typing in a field (or a code editor) never triggers a shortcut. */
function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || Boolean(el.closest?.(".cm-editor"));
}

/** The app's keyboard shortcuts (SPEC 64). */
export function useShortcuts({ openPalette, openHelp }: { openPalette: () => void; openHelp: () => void }) {
  const navigate = useNavigate();
  const moduleId = useRouterState({
    select: (s) => s.matches.map((m) => (m.params as { moduleId?: string }).moduleId).find(Boolean),
  });
  const pendingG = useRef(0);
  const latest = useRef({ openPalette, openHelp, moduleId });
  latest.current = { openPalette, openHelp, moduleId };

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const mod = event.ctrlKey || event.metaKey;
      const key = event.key.toLowerCase();
      if (mod && key === "k") {
        event.preventDefault();
        latest.current.openPalette();
        return;
      }
      if (mod && key === "j") {
        event.preventDefault();
        const id = latest.current.moduleId;
        void navigate({ to: "/chat", search: id ? { module_id: id } : {} });
        return;
      }
      if (mod || event.altKey || typing(event.target)) return;
      if (event.key === "?") {
        event.preventDefault();
        latest.current.openHelp();
      } else if (event.key === "/") {
        const search = document.getElementById("sidebar-search");
        if (search) {
          event.preventDefault();
          search.focus();
        }
      } else if (key === "g") {
        pendingG.current = Date.now();
      } else if (Date.now() - pendingG.current < 1500 && GO[key]) {
        pendingG.current = 0;
        void navigate({ to: GO[key]!.to });
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);
}

export function ShortcutsHelp({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Keyboard shortcuts" description="On a Mac, Cmd works where Ctrl is shown.">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
        {SHORTCUTS.map(([keys, what]) => (
          <div key={keys} className="contents">
            <dt>
              {keys.split(" ").map((k) => (
                <kbd key={k} className="mr-1 rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-xs">
                  {k}
                </kbd>
              ))}
            </dt>
            <dd>{what}</dd>
          </div>
        ))}
      </dl>
    </Modal>
  );
}
