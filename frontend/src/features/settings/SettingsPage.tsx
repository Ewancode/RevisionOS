import { Link } from "@tanstack/react-router";
import { useState, type FormEvent, type ReactNode } from "react";

import { Button, ErrorText, Field } from "@/components/ui";
import { useChangePassword, useSession, useUpdateSettings } from "@/features/auth/session";
import { useMakeYearCurrent, useRestore, useTrash, useYears } from "@/features/structure/queries";
import { useBudget } from "@/features/documents/queries";
import { SystemStatus } from "@/features/system/SystemStatus";
import type { Theme } from "@/lib/theme";

function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = `settings-${title.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 border-b border-border pb-6">
      <h2 id={id} className="text-base font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Profile() {
  const session = useSession();
  const update = useUpdateSettings();
  const [name, setName] = useState(session.data?.user.display_name ?? "");
  return (
    <Section title="Profile">
      <form
        className="flex max-w-sm items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          update.mutate({ display_name: name });
        }}
      >
        <div className="flex-1">
          <Field label="Display name" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <Button type="submit" disabled={update.isPending}>
          Save
        </Button>
      </form>
      <p className="text-sm text-muted">Signed in as {session.data?.user.email}</p>
      <ErrorText error={update.error} />
    </Section>
  );
}

const THEMES: { value: Theme; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

function Appearance() {
  const session = useSession();
  const update = useUpdateSettings();
  const settings = session.data?.settings;
  if (!settings) return null;
  return (
    <Section title="Appearance">
      <fieldset className="flex gap-4">
        <legend className="mb-2 text-sm font-medium">Theme</legend>
        {THEMES.map(({ value, label }) => (
          <label key={value} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="theme"
              value={value}
              checked={settings.theme === value}
              onChange={() => update.mutate({ theme: value })}
            />
            {label}
          </label>
        ))}
      </fieldset>
      <label className="flex items-center gap-3 text-sm font-medium">
        Accent colour
        <input
          type="color"
          value={settings.accent_colour}
          onChange={(e) => update.mutate({ accent_colour: e.target.value })}
          className="h-8 w-12 rounded border border-border bg-bg p-1"
        />
      </label>
      <ErrorText error={update.error} />
    </Section>
  );
}

function AcademicYears() {
  const years = useYears();
  const makeCurrent = useMakeYearCurrent();
  return (
    <Section title="Academic years">
      <p className="text-sm text-muted">
        The current year is shown by default. Earlier years keep all their data.
      </p>
      <ul className="flex max-w-md flex-col gap-1">
        {years.data?.map((y) => (
          <li key={y.id} className="flex items-center justify-between rounded-md px-2 py-1 hover:bg-surface">
            <span className="text-sm">
              {y.label} <span className="text-muted">({y.start_date} – {y.end_date})</span>
            </span>
            {y.is_current ? (
              <span className="text-xs font-medium text-success">Current</span>
            ) : (
              <Button size="sm" onClick={() => makeCurrent.mutate(y.id)}>
                Make current
              </Button>
            )}
          </li>
        ))}
      </ul>
      <ErrorText error={makeCurrent.error} />
    </Section>
  );
}

function AiBudget() {
  const budget = useBudget();
  const b = budget.data;
  if (!b) return null;
  const money = (n: number) =>
    new Intl.NumberFormat("en-GB", { style: "currency", currency: b.currency }).format(n);
  return (
    <Section title="AI usage">
      {!b.configured && (
        <p className="text-sm text-danger">
          Claude is not configured. Add ANTHROPIC_API_KEY to .env and restart to enable the assistant and
          maths transcription.
        </p>
      )}
      <dl className="grid max-w-sm grid-cols-2 gap-y-1 text-sm">
        <dt className="text-muted">Today</dt>
        <dd>
          {money(b.spent_today)} of {money(b.daily_cap)}
        </dd>
        <dt className="text-muted">This month</dt>
        <dd>
          {money(b.spent_this_month)} of {money(b.monthly_cap)}
        </dd>
      </dl>
      {b.exhausted && <p className="text-sm text-danger">The budget is reached; AI features are paused until it resets.</p>}
      <p className="text-xs text-muted">
        Caps are set in backend/config/ai.yaml. Costs are estimates from token counts.{" "}
        <Link to="/usage" className="hover:underline">
          See usage by feature, model, module and day
        </Link>
        .
      </p>
    </Section>
  );
}

function Security() {
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const mismatch = repeat !== "" && next !== repeat;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (mismatch) return;
    await change.mutateAsync({ current_password: current, new_password: next }).catch(() => undefined);
    setCurrent("");
    setNext("");
    setRepeat("");
  }

  return (
    <Section title="Security">
      <form onSubmit={submit} className="flex max-w-sm flex-col gap-3">
        <Field label="Current password" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
        <Field label="New password" type="password" autoComplete="new-password" required minLength={12} hint="At least 12 characters. A passphrase works well." value={next} onChange={(e) => setNext(e.target.value)} />
        <Field label="Repeat new password" type="password" autoComplete="new-password" required value={repeat} error={mismatch ? "Passwords do not match." : undefined} onChange={(e) => setRepeat(e.target.value)} />
        <ErrorText error={change.error} />
        {change.isSuccess && (
          <p role="status" className="text-sm text-success">
            Password changed. Other devices have been signed out.
          </p>
        )}
        <Button type="submit" disabled={change.isPending || mismatch} className="self-start">
          Change password
        </Button>
      </form>
    </Section>
  );
}

function TrashSection() {
  const trash = useTrash();
  const restore = useRestore();
  const items = [
    ...(trash.data?.modules.map((m) => ({ kind: "module" as const, id: m.id, label: `${m.code} ${m.title}`, deleted: m.deleted_at })) ?? []),
    ...(trash.data?.topics.map((t) => ({ kind: "topic" as const, id: t.id, label: t.title, deleted: t.deleted_at })) ?? []),
    ...(trash.data?.documents.map((d) => ({ kind: "document" as const, id: d.id, label: d.original_filename, deleted: d.deleted_at })) ?? []),
    ...(trash.data?.materials.map((m) => ({ kind: "material" as const, id: m.id, label: m.title, deleted: m.deleted_at })) ?? []),
    ...(trash.data?.flashcards.map((c) => ({ kind: "flashcard" as const, id: c.id, label: c.front_md.slice(0, 80), deleted: c.deleted_at })) ?? []),
  ].sort((a, b) => b.deleted.localeCompare(a.deleted));
  const KIND_LABEL = {
    module: "Module",
    topic: "Topic",
    document: "File",
    material: "Material",
    flashcard: "Flashcard",
  } as const;

  return (
    <Section title="Trash">
      <p className="text-sm text-muted">
        Deleted modules, topics, files, materials and flashcards are kept for{" "}
        {trash.data?.retention_days ?? 30} days.
      </p>
      {items.length === 0 && <p className="text-sm">The trash is empty.</p>}
      <ul className="flex max-w-md flex-col gap-1">
        {items.map((item) => (
          <li key={item.id} className="flex items-center justify-between rounded-md px-2 py-1 hover:bg-surface">
            <span className="text-sm">
              <span className="text-muted">{KIND_LABEL[item.kind]}:</span> {item.label}
            </span>
            <Button size="sm" disabled={restore.isPending} onClick={() => restore.mutate({ kind: item.kind, id: item.id })}>
              Restore
            </Button>
          </li>
        ))}
      </ul>
      <ErrorText error={restore.error} />
    </Section>
  );
}

export function SettingsPage() {
  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <Profile />
      <Appearance />
      <AcademicYears />
      <AiBudget />
      <Security />
      <TrashSection />
      <SystemStatus />
    </div>
  );
}
