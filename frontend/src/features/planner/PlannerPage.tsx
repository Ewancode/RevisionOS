import { Link } from "@tanstack/react-router";
import { AlertTriangle, CalendarPlus, Sparkles, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { useViewingYear } from "@/app/viewingYear";
import { Button, ErrorText } from "@/components/ui";
import { useModules } from "@/features/structure/queries";

import { ExamDialog, ExamList } from "./Exams";
import {
  formatMinutes,
  parseDay,
  useAvailability,
  useDeleteOverride,
  useExams,
  useParseAvailability,
  usePlan,
  usePreferences,
  useSetAvailability,
  useSetPreferences,
  WEEKDAYS,
  type Availability,
  type Proposal,
} from "./queries";

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  const id = `planner-${title.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 rounded-lg border border-border p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 id={id} className="font-semibold">
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function dayLabel(day: string): string {
  return parseDay(day).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

function ProposalCard({ proposal, onDone }: { proposal: Proposal; onDone: () => void }) {
  const save = useSetAvailability();
  return (
    <div role="region" aria-label="Proposed availability" className="flex flex-col gap-2 rounded-md bg-surface p-3 text-sm">
      <p>{proposal.note}</p>
      <ul className="flex flex-col gap-0.5 text-xs">
        {proposal.weekdays.map((m, i) =>
          m === null ? null : (
            <li key={WEEKDAYS[i]}>
              Every {WEEKDAYS[i]}: {formatMinutes(m)}
            </li>
          ),
        )}
        {proposal.dates.map((d) => (
          <li key={String(d.day)}>
            {dayLabel(String(d.day))}: {formatMinutes(Number(d.minutes))}
          </li>
        ))}
      </ul>
      <ErrorText error={save.error} />
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="primary"
          disabled={save.isPending}
          onClick={async () => {
            await save.mutateAsync({
              weekdays: proposal.weekdays,
              overrides: proposal.dates.map((d) => ({ day: String(d.day), minutes: Number(d.minutes) })),
            });
            onDone();
          }}
        >
          Use this
        </Button>
        <Button size="sm" onClick={onDone}>
          Discard
        </Button>
      </div>
    </div>
  );
}

function WeeklyHours({ availability }: { availability: Availability }) {
  const save = useSetAvailability();
  const removeOverride = useDeleteOverride();
  const [hours, setHours] = useState(availability.weekdays.map((m) => String(m / 60)));
  const [overrideDay, setOverrideDay] = useState("");
  const [overrideHours, setOverrideHours] = useState("0");
  const changed = hours.some((h, i) => Math.round(Number(h) * 60) !== availability.weekdays[i]);
  return (
    <>
      <form
        className="flex flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({ weekdays: hours.map((h) => Math.round(Number(h) * 60)), overrides: [] });
        }}
      >
        <div className="grid grid-cols-7 gap-2">
          {WEEKDAYS.map((name, i) => (
            <label key={name} className="flex flex-col gap-1 text-xs">
              <span className={availability.custom[i] ? "font-medium" : "text-muted"}>{name.slice(0, 3)}</span>
              <input
                type="number"
                min={0}
                max={16}
                step={0.25}
                aria-label={`${name} hours`}
                value={hours[i]}
                onChange={(e) => setHours(hours.map((h, j) => (j === i ? e.target.value : h)))}
                className="h-8 w-full rounded-md border border-border bg-bg px-1.5 text-sm"
              />
            </label>
          ))}
        </div>
        <p className="text-xs text-muted">Hours you can revise on a usual week. Faded days are still the defaults.</p>
        <div>
          <Button type="submit" size="sm" variant="primary" disabled={!changed || save.isPending}>
            Save weekly hours
          </Button>
        </div>
      </form>

      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-medium">Exceptions</h3>
        {availability.overrides.length > 0 && (
          <ul className="flex flex-col gap-1 text-sm">
            {availability.overrides.map((o) => (
              <li key={String(o.day)} className="flex items-center gap-2">
                {dayLabel(String(o.day))}: {Number(o.minutes) === 0 ? "busy" : formatMinutes(Number(o.minutes))}
                {o.note ? <span className="text-xs text-muted">{String(o.note)}</span> : null}
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Remove exception on ${dayLabel(String(o.day))}`}
                  onClick={() => removeOverride.mutate(String(o.day))}
                >
                  <X size={12} />
                </Button>
              </li>
            ))}
          </ul>
        )}
        <form
          className="flex flex-wrap items-end gap-2 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            if (!overrideDay) return;
            save.mutate({
              weekdays: [null, null, null, null, null, null, null],
              overrides: [{ day: overrideDay, minutes: Math.round(Number(overrideHours) * 60) }],
            });
            setOverrideDay("");
          }}
        >
          <label className="flex flex-col gap-1 text-xs">
            Day
            <input
              type="date"
              value={overrideDay}
              onChange={(e) => setOverrideDay(e.target.value)}
              className="h-8 rounded-md border border-border bg-bg px-2 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            Hours
            <input
              type="number"
              min={0}
              max={16}
              step={0.25}
              value={overrideHours}
              onChange={(e) => setOverrideHours(e.target.value)}
              className="h-8 w-20 rounded-md border border-border bg-bg px-2 text-sm"
            />
          </label>
          <Button type="submit" size="sm" disabled={!overrideDay}>
            Add exception
          </Button>
        </form>
      </div>
      <ErrorText error={save.error ?? removeOverride.error} />
    </>
  );
}

function AvailabilitySection() {
  const availability = useAvailability();
  const parse = useParseAvailability();
  const [text, setText] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  return (
    <Section title="When you can revise">
      <form
        className="flex flex-col gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          if (text.trim()) setProposal(await parse.mutateAsync(text.trim()));
        }}
      >
        <label htmlFor="availability-text" className="text-sm">
          Describe it in your own words
        </label>
        <div className="flex gap-2">
          <input
            id="availability-text"
            maxLength={1000}
            placeholder="e.g. 3 hours on weekdays, 1 on Sundays, nothing next Saturday"
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="h-9 flex-1 rounded-md border border-border bg-bg px-2 text-sm"
          />
          <Button type="submit" disabled={parse.isPending || !text.trim()}>
            <Sparkles size={14} /> {parse.isPending ? "Reading…" : "Suggest"}
          </Button>
        </div>
        <ErrorText error={parse.error} />
      </form>
      {proposal && (
        <ProposalCard
          proposal={proposal}
          onDone={() => {
            setProposal(null);
            setText("");
          }}
        />
      )}
      {availability.data && (
        // Keyed so the inputs reset after a save or an accepted proposal.
        <WeeklyHours key={JSON.stringify(availability.data)} availability={availability.data} />
      )}
      <ErrorText error={availability.error} />
    </Section>
  );
}

function PreferencesSection() {
  const prefs = usePreferences();
  const save = useSetPreferences();
  const p = prefs.data;
  if (!p) return <ErrorText error={prefs.error} />;
  return (
    <Section title="Sessions">
      <div className="flex flex-wrap gap-4 text-sm">
        <label className="flex items-center gap-2">
          Session length
          <select
            value={p.session_minutes}
            onChange={(e) => save.mutate({ session_minutes: Number(e.target.value) })}
            className="h-8 rounded-md border border-border bg-bg px-2"
          >
            {[25, 30, 45, 60, 90, 120].map((m) => (
              <option key={m} value={m}>
                {formatMinutes(m)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          At most
          <select
            value={p.max_sessions_per_day}
            onChange={(e) => save.mutate({ max_sessions_per_day: Number(e.target.value) })}
            className="h-8 rounded-md border border-border bg-bg px-2"
          >
            {[1, 2, 3, 4, 5, 6].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          sessions a day
        </label>
      </div>
      <fieldset className="flex flex-wrap items-center gap-3 text-sm">
        <legend className="mb-1 text-sm">Rest days (nothing planned)</legend>
        {WEEKDAYS.map((name, i) => (
          <label key={name} className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={p.rest_weekdays.includes(i)}
              onChange={(e) =>
                save.mutate({
                  rest_weekdays: e.target.checked
                    ? [...p.rest_weekdays, i].sort()
                    : p.rest_weekdays.filter((d) => d !== i),
                })
              }
            />
            {name.slice(0, 3)}
          </label>
        ))}
      </fieldset>
      <ErrorText error={save.error} />
    </Section>
  );
}

function ExamsSection() {
  const exams = useExams();
  const { year } = useViewingYear();
  const modules = useModules(year?.id);
  const [moduleId, setModuleId] = useState("");
  const [adding, setAdding] = useState(false);
  return (
    <Section
      title="Exams"
      action={
        !!modules.data?.length && (
          <div className="flex gap-1">
            <select
              aria-label="Module for the new exam"
              value={moduleId}
              onChange={(e) => setModuleId(e.target.value)}
              className="h-7 rounded-md border border-border bg-bg px-2 text-xs"
            >
              <option value="">Module…</option>
              {modules.data.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.code}
                </option>
              ))}
            </select>
            <Button size="sm" disabled={!moduleId} onClick={() => setAdding(true)}>
              <CalendarPlus size={14} /> Add exam
            </Button>
          </div>
        )
      }
    >
      {exams.data?.length === 0 && <p className="text-sm text-muted">No upcoming exams.</p>}
      {!!exams.data?.length && <ExamList exams={exams.data} />}
      <ErrorText error={exams.error} />
      {adding && moduleId && <ExamDialog open onOpenChange={setAdding} moduleId={moduleId} />}
    </Section>
  );
}

function PlanSection() {
  const plan = usePlan();
  const p = plan.data;
  if (!p) return <ErrorText error={plan.error} />;
  const sessions = [...p.today, ...p.upcoming].slice(0, 30);
  return (
    <Section
      title="Your plan"
      action={
        <Link to="/calendar" className="text-sm underline">
          Open calendar
        </Link>
      }
    >
      {p.shortfalls.map((s) => (
        <div key={s.exam_id} role="alert" className="flex gap-2 rounded-md border border-danger p-3 text-sm">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-danger" />
          <div>
            <p className="font-medium">{s.title}: the plan can't cover everything.</p>
            <p className="text-muted">
              {s.reason === "time"
                ? `It needs about ${formatMinutes(s.needed_minutes)} but you have ${formatMinutes(s.available_minutes)} before the exam. `
                : `There are too few days left to space out ${formatMinutes(s.needed_minutes)} of revision. `}
              Planned {formatMinutes(s.planned_minutes)}.
              {s.left_out.length > 0 && ` Less time for: ${s.left_out.join(", ")}.`} Add hours below to fit more in.
            </p>
          </div>
        </div>
      ))}
      {sessions.length === 0 ? (
        <p className="text-sm text-muted">Nothing planned yet. Add an exam to get a plan.</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="sr-only">
            <tr>
              <th>Day</th>
              <th>Session</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.id} className="border-t border-border align-top">
                <td className="whitespace-nowrap py-1.5 pr-3 text-xs text-muted">{dayLabel(s.day)}</td>
                <td className="py-1.5 pr-3">
                  <span className="font-medium">{s.kind === "mock_exam" ? "Mock exam" : s.title}</span>{" "}
                  <span className="text-xs text-muted">
                    {s.module_code} · {formatMinutes(s.minutes)}
                    {s.locked ? " · fixed" : ""}
                  </span>
                </td>
                <td className="py-1.5 text-xs text-muted">{s.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="text-xs text-muted">
        Replanned {new Date(p.generated_at).toLocaleString()} · runs again when your progress or plans change.
      </p>
    </Section>
  );
}

export function PlannerPage() {
  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">Revision planner</h1>
      <PlanSection />
      <ExamsSection />
      <AvailabilitySection />
      <PreferencesSection />
    </div>
  );
}
