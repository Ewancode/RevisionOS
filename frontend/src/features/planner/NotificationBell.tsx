import { useNavigate } from "@tanstack/react-router";
import { Bell } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui";

import { useNotificationActions, useNotifications } from "./queries";

/** The sidebar bell: reminders made when you open the app (no push until Phase 11). */
export function NotificationBell() {
  const notifications = useNotifications();
  const { read, readAll } = useNotificationActions();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const unread = notifications.data?.unread ?? 0;
  const items = notifications.data?.items ?? [];

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  return (
    <div ref={box} className="relative">
      <Button
        size="sm"
        variant="ghost"
        className="relative"
        aria-expanded={open}
        aria-controls="notifications-panel"
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        onClick={() => setOpen(!open)}
      >
        <Bell size={16} />
        {unread > 0 && (
          <span
            aria-hidden
            className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-danger px-1 text-[10px] leading-4 text-on-danger"
          >
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </Button>
      {open && (
        <div
          id="notifications-panel"
          role="region"
          aria-label="Notifications"
          className="absolute left-0 top-9 z-50 flex w-80 flex-col gap-2 rounded-lg border border-border bg-bg p-3 shadow-xl"
        >
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">Notifications</h2>
            {unread > 0 && (
              <Button size="sm" variant="ghost" onClick={() => readAll.mutate()}>
                Mark all read
              </Button>
            )}
          </div>
          {items.length === 0 ? (
            <p className="text-sm text-muted">Nothing new.</p>
          ) : (
            <ul className="flex max-h-96 flex-col gap-1 overflow-y-auto">
              {items.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={async () => {
                      if (!n.read_at) read.mutate(n.id);
                      if (n.link) {
                        setOpen(false);
                        await navigate({ to: n.link as "/" });
                      }
                    }}
                    className={`w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-surface ${n.read_at ? "text-muted" : "font-medium"}`}
                  >
                    {n.title}
                    {n.body && <span className="block text-xs font-normal text-muted">{n.body}</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
