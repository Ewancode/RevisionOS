/**
 * Small SVG charts (ADR 15). Each has an accessible name, a caption saying
 * what it is computed from, and the same numbers as a table for screen
 * readers, so nothing is shown only as a shape.
 */
import type { ReactNode } from "react";

export interface Point {
  label: string;
  value: number | null;
}

function Frame({ title, basis, children, table }: { title: string; basis: string; children: ReactNode; table: ReactNode }) {
  return (
    <figure className="flex flex-col gap-2 rounded-lg border border-border p-4">
      <figcaption>
        <h3 className="font-semibold">{title}</h3>
        <p className="text-xs text-muted">{basis}</p>
      </figcaption>
      {children}
      <div className="sr-only">{table}</div>
    </figure>
  );
}

function DataTable({ title, points, format }: { title: string; points: Point[]; format: (v: number) => string }) {
  return (
    <table>
      <caption>{title}</caption>
      <tbody>
        {points.map((p) => (
          <tr key={p.label}>
            <th scope="row">{p.label}</th>
            <td>{p.value === null ? "no data" : format(p.value)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const W = 600;
const H = 160;
const PAD = 24;

/** Bars, one per point; null points are drawn as a gap. */
export function BarChart({
  title,
  basis,
  points,
  format = (v) => String(Math.round(v)),
  max,
}: {
  title: string;
  basis: string;
  points: Point[];
  format?: (v: number) => string;
  max?: number;
}) {
  const top = max ?? Math.max(1, ...points.map((p) => p.value ?? 0));
  const step = (W - PAD) / Math.max(1, points.length);
  return (
    <Frame title={title} basis={basis} table={<DataTable title={title} points={points} format={format} />}>
      <svg viewBox={`0 0 ${W} ${H + 18}`} role="img" aria-label={title} className="w-full">
        <line x1={PAD} y1={H} x2={W} y2={H} stroke="var(--color-border)" />
        <text x={PAD - 4} y={10} textAnchor="end" fontSize="10" fill="var(--color-muted)">
          {format(top)}
        </text>
        {points.map((p, i) => {
          const h = p.value === null ? 0 : (p.value / top) * (H - 12);
          const x = PAD + i * step + step * 0.15;
          return (
            <g key={p.label}>
              {p.value !== null && (
                <rect x={x} y={H - h} width={step * 0.7} height={Math.max(h, p.value > 0 ? 1 : 0)} rx={2} fill="var(--color-accent)">
                  <title>
                    {p.label}: {format(p.value)}
                  </title>
                </rect>
              )}
              {(i % Math.ceil(points.length / 6) === 0 || i === points.length - 1) && (
                <text x={x + step * 0.35} y={H + 13} textAnchor="middle" fontSize="10" fill="var(--color-muted)">
                  {p.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </Frame>
  );
}

/** A line over points in [0, max]; gaps where there is no data. */
export function LineChart({
  title,
  basis,
  points,
  format,
  max = 1,
}: {
  title: string;
  basis: string;
  points: Point[];
  format: (v: number) => string;
  max?: number;
}) {
  const step = (W - PAD) / Math.max(1, points.length - 1);
  const y = (v: number) => H - (v / max) * (H - 12);
  const segments: string[] = [];
  let current = "";
  points.forEach((p, i) => {
    if (p.value === null) {
      if (current) segments.push(current);
      current = "";
      return;
    }
    current += `${current ? "L" : "M"}${PAD + i * step},${y(p.value)} `;
  });
  if (current) segments.push(current);
  return (
    <Frame title={title} basis={basis} table={<DataTable title={title} points={points} format={format} />}>
      <svg viewBox={`0 0 ${W} ${H + 18}`} role="img" aria-label={title} className="w-full">
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={PAD} y1={y(max * f)} x2={W} y2={y(max * f)} stroke="var(--color-border)" strokeDasharray={f ? "3 3" : undefined} />
            <text x={PAD - 4} y={y(max * f) + 3} textAnchor="end" fontSize="10" fill="var(--color-muted)">
              {format(max * f)}
            </text>
          </g>
        ))}
        {segments.map((d) => (
          <path key={d} d={d} fill="none" stroke="var(--color-accent)" strokeWidth={2} />
        ))}
        {points.map((p, i) =>
          p.value === null ? null : (
            <circle key={p.label} cx={PAD + i * step} cy={y(p.value)} r={3} fill="var(--color-accent)">
              <title>
                {p.label}: {format(p.value)}
              </title>
            </circle>
          ),
        )}
        {points.map((p, i) =>
          i % Math.ceil(points.length / 6) === 0 || i === points.length - 1 ? (
            <text key={`l-${p.label}`} x={PAD + i * step} y={H + 13} textAnchor="middle" fontSize="10" fill="var(--color-muted)">
              {p.label}
            </text>
          ) : null,
        )}
      </svg>
    </Frame>
  );
}

/** Days as squares, Monday-first columns of weeks; darker = more activity. */
export function ActivityGrid({
  title,
  basis,
  days,
}: {
  title: string;
  basis: string;
  days: { day: string; events: number }[];
}) {
  const most = Math.max(1, ...days.map((d) => d.events));
  const size = 12;
  const columns = Math.ceil(days.length / 7);
  const active = days.filter((d) => d.events > 0).length;
  return (
    <Frame
      title={title}
      basis={basis}
      table={
        <p>
          Active on {active} of {days.length} days.
        </p>
      }
    >
      <svg
        viewBox={`0 0 ${columns * (size + 3)} ${7 * (size + 3)}`}
        role="img"
        aria-label={`${title}: active on ${active} of ${days.length} days`}
        className="w-full max-w-md"
      >
        {days.map((d, i) => (
          <rect
            key={d.day}
            x={Math.floor(i / 7) * (size + 3)}
            y={(i % 7) * (size + 3)}
            width={size}
            height={size}
            rx={2}
            fill={d.events ? "var(--color-accent)" : "var(--color-surface)"}
            fillOpacity={d.events ? 0.25 + 0.75 * (d.events / most) : 1}
            stroke="var(--color-border)"
          >
            <title>
              {d.day}: {d.events} study event{d.events === 1 ? "" : "s"}
            </title>
          </rect>
        ))}
      </svg>
    </Frame>
  );
}
