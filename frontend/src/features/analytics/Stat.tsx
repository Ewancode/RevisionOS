import { Info } from "lucide-react";
import { useId, useState } from "react";

import { formatValue, type Format, type MetricValue } from "./queries";

/**
 * One figure and what it was computed from. The basis is always one click
 * away (and in the tooltip), so every number on screen can be traced to the
 * stored data behind it.
 */
export function Stat({
  label,
  metric,
  format = "count",
  size = "md",
}: {
  label: string;
  metric: MetricValue;
  format?: Format;
  size?: "sm" | "md";
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div role="group" aria-label={label} className="flex flex-col gap-0.5" title={metric.basis}>
      <p className="flex items-center gap-1 text-xs text-muted">
        {label}
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          aria-label={`How ${label.toLowerCase()} is worked out`}
          onClick={() => setOpen(!open)}
          className="rounded text-muted hover:text-fg"
        >
          <Info size={12} />
        </button>
      </p>
      <p className={size === "sm" ? "text-base font-semibold" : "text-2xl font-semibold tracking-tight"}>
        {formatValue(metric.value, format)}
      </p>
      <p id={id} hidden={!open} className="text-xs text-muted">
        {metric.basis}
      </p>
    </div>
  );
}
