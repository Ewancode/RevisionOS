import { Check, ChevronLeft, ChevronRight, Lock, RotateCcw, SkipForward } from "lucide-react";
import { useState } from "react";

import { Button, ErrorText } from "@/components/ui";

import {
  addDays,
  formatMinutes,
  isoDay,
  parseDay,
  useCalendar,
  useSessionActions,
  weekStart,
  type CalendarDay,
  type StudySession,
} from "./queries";

export type CalendarView = "day" | "week" | "month";

const STATUS_STYLE: Record<StudySession["status"], string> = {
  planned: "border-accent",
  done: "border-success opacity-70",
  missed: "border-danger opacity-70",
  skipped: "border-border opacity-50",
};

function range(view: CalendarView, focus: string): [string, string] {
  if (view === "day") return [focus, focus];
  if (view === "week") {
    const start = weekStart(focus);
    return [start, addDays(start, 6)];
  }
  const d = parseDay(focus);
  const first = isoDay(new Date(d.getFullYear(), d.getMonth(), 1));
  const last = isoDay(new Date(d.getFullYear(), d.getMonth() + 1, 0));
  return [weekStart(first), addDays(weekStart(last), 6)];
}

function shift(view: CalendarView, focus: string, by: number): string {
  if (view === "day") return addDays(focus, by);
  if (view === "week") return addDays(focus, 7 * by);
  const d = parseDay(focus);
  return isoDay(new Date(d.getFullYear(), d.getMonth() + by, 1));
}

function heading(view: CalendarView, focus: string, start: string, end: string): string {
  const d = parseDay(focus);
  if (view === "day") return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  if (view === "month") return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const opts = { day: "numeric", month: "short" } as const;
  return `${parseDay(start).toLocaleDateString(undefined, opts)} – ${parseDay(end).toLocaleDateString(undefined, opts)}`;
}

function SessionChip({ session, detailed, today }: { session: StudySession; detailed: boolean; today: string }) {
  const actions = useSessionActions();
  const [moveTo, setMoveTo] = useState(session.day);
  const movable = session.status === "planned";
  const label = session.kind === "mock_exam" ? `Mock exam ${session.module_code}` : session.title;
  return (
    <li
      draggable={movable}
      onDragStart={(e) => e.dataTransfer.setData("text/session", session.id)}
      className={`flex flex-col gap-1 rounded border-l-4 bg-surface px-2 py-1 text-xs ${STATUS_STYLE[session.status]} ${movable ? "cursor-grab" : ""}`}
      title={session.reason}
    >
      <p className="flex items-center gap-1">
        {session.locked && <Lock size={10} aria-label="Fixed" />}
        <span className="truncate font-medium">{label}</span>
        <span className="shrink-0 text-muted">{formatMinutes(session.minutes)}</span>
      </p>
      {detailed && (
        <>
          <p className="text-muted">
            {session.module_code} · {session.status}
            {session.actual_minutes ? ` · ${formatMinutes(session.actual_minutes)} spent` : ""}
          </p>
          <p className="text-muted">{session.reason}</p>
          <div className="flex flex-wrap items-center gap-1">
            {session.status === "planned" ? (
              <>
                <Button size="sm" onClick={() => actions.status.mutate({ id: session.id, status: "done" })}>
                  <Check size={12} /> Done
                </Button>
                <Button size="sm" variant="ghost" onClick={() => actions.status.mutate({ id: session.id, status: "skipped" })}>
                  <SkipForward size={12} /> Skip
                </Button>
                <label className="flex items-center gap-1">
                  <span className="sr-only">Move {label} to</span>
                  <input
                    type="date"
                    min={today}
                    value={moveTo}
                    onChange={(e) => setMoveTo(e.target.value)}
                    className="h-7 rounded border border-border bg-bg px-1"
                  />
                </label>
                <Button
                  size="sm"
                  disabled={moveTo === session.day || moveTo < today}
                  onClick={() => actions.move.mutate({ id: session.id, day: moveTo })}
                >
                  Move
                </Button>
              </>
            ) : (
              <Button size="sm" variant="ghost" onClick={() => actions.status.mutate({ id: session.id, status: "planned" })}>
                <RotateCcw size={12} /> Undo
              </Button>
            )}
          </div>
          <ErrorText error={actions.status.error ?? actions.move.error} />
        </>
      )}
    </li>
  );
}

function DayCell({
  day,
  today,
  detailed,
  faded,
  compact,
  onOpen,
}: {
  day: CalendarDay;
  today: string;
  detailed: boolean;
  faded?: boolean;
  /** Month view on a phone: a count instead of each session. */
  compact?: boolean;
  onOpen?: () => void;
}) {
  const { move } = useSessionActions();
  const [over, setOver] = useState(false);
  const past = day.day < today;
  const date = parseDay(day.day);
  return (
    <li
      aria-label={date.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}
      onDragOver={(e) => {
        if (!past) {
          e.preventDefault();
          setOver(true);
        }
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        setOver(false);
        const id = e.dataTransfer.getData("text/session");
        if (id && !past) move.mutate({ id, day: day.day });
      }}
      className={`flex flex-col gap-1 rounded-md border p-1.5 ${compact ? "min-h-12 md:min-h-24" : "min-h-24"} ${
        day.day === today ? "border-accent" : "border-border"
      } ${over ? "bg-surface" : ""} ${faded ? "opacity-50" : ""}`}
    >
      <div className="flex items-baseline justify-between text-xs">
        {onOpen ? (
          <button
            type="button"
            onClick={onOpen}
            aria-label={`Open ${date.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}`}
            className="font-medium hover:underline"
          >
            {!compact && (
              <span className="md:hidden">{date.toLocaleDateString(undefined, { weekday: "short" })} </span>
            )}
            {date.getDate()}
          </button>
        ) : (
          <span className="font-medium">{date.getDate()}</span>
        )}
        {day.available_minutes > 0 && !past && (
          <span className={`text-muted ${compact ? "hidden md:inline" : ""}`}>{formatMinutes(day.available_minutes)}</span>
        )}
      </div>
      {compact && (day.sessions.length > 0 || day.exams.length > 0) && (
        <p className="flex flex-wrap gap-1 text-[11px] leading-tight md:hidden">
          {day.exams.length > 0 && <span className="rounded bg-danger px-1 font-medium text-on-danger">Exam</span>}
          {day.sessions.length > 0 && (
            <span className="text-muted">
              {day.sessions.length}
              <span className="sr-only"> planned session{day.sessions.length === 1 ? "" : "s"}</span>
              <span aria-hidden>×</span>
            </span>
          )}
        </p>
      )}
      {day.exams.map((e) => (
        <p
          key={e.id}
          className={`rounded bg-danger px-1.5 py-0.5 text-xs font-medium text-on-danger ${compact ? "hidden md:block" : ""}`}
        >
          {e.module_code} {e.title}{" "}
          {new Date(e.starts_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
        </p>
      ))}
      <ul className={`flex flex-col gap-1 ${compact ? "hidden md:flex" : ""}`}>
        {day.sessions.map((s) => (
          <SessionChip key={s.id} session={s} detailed={detailed} today={today} />
        ))}
      </ul>
      {(day.quizzes.length > 0 || day.reviews > 0 || (day.due_cards > 0 && !past)) && (
        <p className={`mt-auto text-[11px] text-muted ${compact ? "hidden md:block" : ""}`}>
          {[
            day.quizzes.length ? `${day.quizzes.length} quiz${day.quizzes.length > 1 ? "zes" : ""}` : "",
            day.reviews ? `${day.reviews} cards reviewed` : "",
            day.due_cards && !past ? `${day.due_cards} cards due` : "",
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
      <ErrorText error={move.error} />
    </li>
  );
}

export function CalendarPage({ initialView = "week" }: { initialView?: CalendarView }) {
  const today = isoDay(new Date());
  const [view, setView] = useState<CalendarView>(initialView);
  const [focus, setFocus] = useState(today);
  const [start, end] = range(view, focus);
  const calendar = useCalendar(start, end);
  const days = calendar.data?.days ?? [];
  const month = parseDay(focus).getMonth();

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Calendar</h1>
        <div role="group" aria-label="View" className="flex gap-1">
          {(["day", "week", "month"] as const).map((v) => (
            <Button key={v} size="sm" variant={view === v ? "primary" : "secondary"} aria-pressed={view === v} onClick={() => setView(v)}>
              {v.charAt(0).toUpperCase() + v.slice(1)}
            </Button>
          ))}
        </div>
      </header>
      <div className="flex items-center gap-2">
        <Button size="sm" aria-label="Previous" onClick={() => setFocus(shift(view, focus, -1))}>
          <ChevronLeft size={14} />
        </Button>
        <Button size="sm" onClick={() => setFocus(today)}>
          Today
        </Button>
        <Button size="sm" aria-label="Next" onClick={() => setFocus(shift(view, focus, 1))}>
          <ChevronRight size={14} />
        </Button>
        <h2 className="font-medium">{heading(view, focus, start, end)}</h2>
      </div>
      <p className="text-xs text-muted">
        Drag a session to another day (or use Move in day view) to fix it there; the rest of the plan rebalances
        around it.
      </p>
      <ErrorText error={calendar.error} />
      {view === "day" ? (
        days[0] && (
          <ul aria-label={heading(view, focus, start, end)}>
            <DayCell day={days[0]} today={today} detailed />
          </ul>
        )
      ) : (
        <div className="flex flex-col gap-1.5">
          {/* Weekday headings; each day also carries its full date for screen readers. */}
          <div aria-hidden className={`grid-cols-7 gap-1.5 ${view === "week" ? "hidden md:grid" : "grid"}`}>
            {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
              <div key={d} className="text-center text-xs font-medium text-muted">
                {d}
              </div>
            ))}
          </div>
          <ol
            aria-label={heading(view, focus, start, end)}
            className={view === "week" ? "grid grid-cols-1 gap-1.5 md:grid-cols-7" : "grid grid-cols-7 gap-1 md:gap-1.5"}
          >
            {days.map((d) => (
              <DayCell
                key={d.day}
                day={d}
                today={today}
                detailed={false}
                compact={view === "month"}
                faded={view === "month" && parseDay(d.day).getMonth() !== month}
                onOpen={() => {
                  setFocus(d.day);
                  setView("day");
                }}
              />
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
