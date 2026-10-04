/** A topic's estimated strength as a thin bar; the number is in the text
 *  beside it, so the colour never carries the meaning on its own. */
export function StrengthBar({ value, lowData }: { value: number; lowData: boolean }) {
  const pct = Math.round(Math.min(Math.max(value, 0), 1) * 100);
  return (
    <div
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      aria-label={`Estimated strength ${pct}%${lowData ? ", low data" : ""}`}
      className="h-1.5 w-full overflow-hidden rounded-full bg-surface"
    >
      <div
        className={`h-full rounded-full ${lowData ? "bg-muted opacity-50" : "bg-accent"}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
