/**
 * Drag the line between the sidebar and the page to make the sidebar wider
 * (and the page narrower) or the other way round. Also works from the
 * keyboard: focus the line, then use the arrow keys (Home and End for the
 * smallest and largest). Double-click it to go back to the usual width.
 *
 * The width is remembered in this browser only.
 */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

export const SIDEBAR_WIDTH = {
  default: 256,
  min: 200,
  max: 480,
  /** Pixels per arrow-key press. */
  step: 16,
  /** The page always keeps at least this much room. */
  minPage: 360,
} as const;

const STORAGE_KEY = "revision-os.sidebar-width";

/** The largest the sidebar may be in a window this wide. */
function largest(): number {
  const room = (globalThis.innerWidth ?? Infinity) - SIDEBAR_WIDTH.minPage;
  return Math.max(SIDEBAR_WIDTH.min, Math.min(SIDEBAR_WIDTH.max, room));
}

function clamp(width: number): number {
  return Math.round(Math.min(largest(), Math.max(SIDEBAR_WIDTH.min, width)));
}

function stored(): number {
  try {
    const value = Number(localStorage.getItem(STORAGE_KEY));
    return value ? clamp(value) : SIDEBAR_WIDTH.default;
  } catch {
    return SIDEBAR_WIDTH.default; // storage blocked: just use the usual width
  }
}

function remember(width: number): void {
  try {
    localStorage.setItem(STORAGE_KEY, String(width));
  } catch {
    // Not remembered; it still works for this visit.
  }
}

export function useSidebarWidth() {
  const [width, setWidth] = useState(stored);
  // A smaller window may no longer fit the chosen width.
  useEffect(() => {
    const fit = () => setWidth((w) => clamp(w));
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);
  const set = useCallback((next: number, save = true) => {
    const value = clamp(next);
    setWidth(value);
    if (save) remember(value);
  }, []);
  return [width, set] as const;
}

export function SidebarResizer({ width, onResize }: { width: number; onResize: (width: number, save?: boolean) => void }) {
  const drag = useRef<{ startX: number; startWidth: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    drag.current = { startX: event.clientX, startWidth: width };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setDragging(true);
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!drag.current) return;
    onResize(drag.current.startWidth + event.clientX - drag.current.startX, false);
  }

  function onPointerUp(event: PointerEvent<HTMLDivElement>) {
    if (!drag.current) return;
    onResize(drag.current.startWidth + event.clientX - drag.current.startX);
    drag.current = null;
    setDragging(false);
  }

  // While dragging, the whole page shows the resize cursor and no text gets selected.
  useEffect(() => {
    if (!dragging) return;
    const { cursor, userSelect } = document.body.style;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    return () => {
      document.body.style.cursor = cursor;
      document.body.style.userSelect = userSelect;
    };
  }, [dragging]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const moves: Record<string, number> = {
      ArrowLeft: width - SIDEBAR_WIDTH.step,
      ArrowRight: width + SIDEBAR_WIDTH.step,
      Home: SIDEBAR_WIDTH.min,
      End: SIDEBAR_WIDTH.max,
    };
    if (!(event.key in moves)) return;
    event.preventDefault();
    onResize(moves[event.key]!);
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize sidebar"
      aria-valuenow={width}
      aria-valuemin={SIDEBAR_WIDTH.min}
      aria-valuemax={largest()}
      tabIndex={0}
      title="Drag to resize · double-click to reset"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onDoubleClick={() => onResize(SIDEBAR_WIDTH.default)}
      onKeyDown={onKeyDown}
      // A wide, invisible grab area centred on the border; the line lights up on hover.
      className="group absolute inset-y-0 -right-1.5 z-20 flex w-3 cursor-col-resize touch-none justify-center outline-none"
    >
      <span
        aria-hidden="true"
        className={`h-full w-0.5 transition-colors group-hover:bg-accent group-focus-visible:bg-accent ${
          dragging ? "bg-accent" : "bg-transparent"
        }`}
      />
    </div>
  );
}
