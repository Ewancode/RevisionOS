import { useState } from "react";

import { ErrorText } from "@/components/ui";

import { useUsage, type Usage } from "./queries";

const RANGES = [7, 30, 90] as const;

function money(currency: string, n: number) {
  return new Intl.NumberFormat("en-GB", { style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(n);
}

const count = (n: number) => new Intl.NumberFormat("en-GB").format(n);

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-border p-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="text-xl font-semibold tabular-nums">{value}</dd>
      {note && <dd className="text-xs text-muted">{note}</dd>}
    </div>
  );
}

/** Estimated cost per day: one series, so the title names it (no legend). */
function DailyCost({ usage }: { usage: Usage }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...usage.by_day.map((d) => d.cost), 0);
  const day = (iso: string) =>
    new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  const shown = hover !== null ? usage.by_day[hover] : undefined;

  return (
    <section aria-labelledby="daily-cost" className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="daily-cost" className="text-base font-semibold">
          Estimated cost per day
        </h2>
        <p className="text-xs text-muted" aria-live="polite">
          {shown
            ? `${day(shown.day)}: ${money(usage.currency, shown.cost)} · ${shown.requests} requests`
            : `Peak ${money(usage.currency, max)}`}
        </p>
      </div>
      <div
        role="img"
        aria-label={`Bar chart of estimated AI cost per day over the last ${usage.days} days; the table below has the values.`}
        className="flex h-32 items-end gap-[2px] border-b border-border"
        onMouseLeave={() => setHover(null)}
      >
        {usage.by_day.map((d, i) => (
          <div
            key={d.day}
            className="flex h-full flex-1 items-end"
            onMouseEnter={() => setHover(i)}
            title={`${day(d.day)}: ${money(usage.currency, d.cost)}`}
          >
            <div
              className={`w-full rounded-t-[4px] ${hover === i ? "bg-fg" : "bg-accent"}`}
              style={{ height: max > 0 && d.cost > 0 ? `max(2px, ${(d.cost / max) * 100}%)` : 0 }}
            />
          </div>
        ))}
      </div>
      <div className="flex justify-between text-xs text-muted">
        <span>{day(usage.by_day[0]?.day ?? usage.since)}</span>
        <span>{day(usage.by_day.at(-1)?.day ?? usage.since)}</span>
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer text-xs text-muted">Show as a table</summary>
        <table className="mt-2 w-full max-w-sm text-xs">
          <thead>
            <tr className="text-left text-muted">
              <th className="py-1 font-medium">Day</th>
              <th className="py-1 text-right font-medium">Requests</th>
              <th className="py-1 text-right font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {usage.by_day
              .filter((d) => d.requests > 0)
              .map((d) => (
                <tr key={d.day} className="border-t border-border">
                  <td className="py-1">{day(d.day)}</td>
                  <td className="py-1 text-right tabular-nums">{d.requests}</td>
                  <td className="py-1 text-right tabular-nums">{money(usage.currency, d.cost)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}

function Breakdown({ title, rows, currency }: { title: string; rows: Usage["by_feature"]; currency: string }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-base font-semibold">{title}</h2>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">No usage in this period.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="py-1 font-medium">Name</th>
              <th className="py-1 text-right font-medium">Requests</th>
              <th className="py-1 text-right font-medium">Tokens</th>
              <th className="py-1 text-right font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className="border-t border-border">
                <td className="py-1.5">{r.label}</td>
                <td className="py-1.5 text-right tabular-nums">{count(r.requests)}</td>
                <td className="py-1.5 text-right tabular-nums">{count(r.tokens)}</td>
                <td className="py-1.5 text-right tabular-nums">{money(currency, r.cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function UsagePage() {
  const [days, setDays] = useState<number>(30);
  const usage = useUsage(days);
  const u = usage.data;

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">AI usage</h1>
        <div role="group" aria-label="Period" className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              aria-pressed={days === r}
              onClick={() => setDays(r)}
              className={`rounded-md border px-2 py-1 text-xs ${days === r ? "border-accent bg-surface font-medium" : "border-border hover:bg-surface"}`}
            >
              {r} days
            </button>
          ))}
        </div>
      </div>
      <ErrorText error={usage.error} />
      {u && (
        <>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Tile label="Estimated cost" value={money(u.currency, u.totals.cost)} />
            <Tile label="Requests" value={count(u.totals.requests)} />
            <Tile
              label="Tokens"
              value={count(u.totals.input_tokens + u.totals.output_tokens)}
              note={`${count(u.totals.cache_read_tokens)} read from cache`}
            />
            <Tile label="Blocked by budget" value={count(u.totals.blocked_requests)} />
          </dl>
          <DailyCost usage={u} />
          <Breakdown title="By feature" rows={u.by_feature} currency={u.currency} />
          <Breakdown title="By model" rows={u.by_model} currency={u.currency} />
          <Breakdown title="By module" rows={u.by_module} currency={u.currency} />
          <p className="text-xs text-muted">
            Costs are estimates from token counts and the prices in backend/config/ai.yaml, converted to {u.currency}.
            Caps are set there too.
          </p>
        </>
      )}
    </div>
  );
}
