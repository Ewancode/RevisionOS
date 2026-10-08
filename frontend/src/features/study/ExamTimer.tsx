/**
 * The mock exam timer, in the top right of every page while an exam is open
 * (the clock runs on the server, so it keeps going if you leave the page).
 * "Stop" ends the exam early: your answers are submitted for marking. When
 * time runs out the exam is submitted by itself.
 *
 * On the exam's own page, the page registers how to finish (save every answer
 * still waiting to be saved, then submit), so nothing typed is lost; anywhere
 * else every answer is already saved, and finishing is just submitting.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { Clock, Square } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { Button, ErrorText, Modal } from "@/components/ui";
import { api, ApiError, unwrap } from "@/lib/api/client";

type Finish = () => Promise<void>;

const ACTIVE_EXAM = ["attempts", "active-exam"] as const;

const FinishersContext = createContext<Map<string, Finish> | null>(null);

export function ExamControlProvider({ children }: { children: ReactNode }) {
  const [finishers] = useState(() => new Map<string, Finish>());
  return <FinishersContext.Provider value={finishers}>{children}</FinishersContext.Provider>;
}

/** The exam page says how to finish it (saving answers still in the editor first). */
export function useExamFinisher(attemptId: string, finish: Finish) {
  const finishers = useContext(FinishersContext);
  const latest = useRef(finish);
  latest.current = finish;
  useEffect(() => {
    if (!finishers) return;
    finishers.set(attemptId, () => latest.current());
    return () => {
      finishers.delete(attemptId);
    };
  }, [finishers, attemptId]);
}

export function useActiveExam() {
  return useQuery({
    queryKey: ACTIVE_EXAM,
    queryFn: () => unwrap(api.GET("/api/v1/attempts/active-exam")),
    refetchInterval: 60_000,
  });
}

function clock(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = String(seconds % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

export function ExamTimer() {
  const exam = useActiveExam().data;
  if (!exam?.deadline) return null;
  // Keyed by attempt, so a new exam starts with fresh state.
  return <RunningTimer key={exam.attempt_id} attemptId={exam.attempt_id} title={exam.title} deadline={exam.deadline} />;
}

function RunningTimer({ attemptId, title, deadline }: { attemptId: string; title: string; deadline: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const finishers = useContext(FinishersContext);
  const onExamPage = useRouterState({ select: (s) => s.location.pathname === `/attempts/${attemptId}` });
  const [left, setLeft] = useState(() => new Date(deadline).getTime() - Date.now());
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const finished = useRef(false);
  const timedOut = useRef(false);

  const finish = useCallback(async () => {
    if (finished.current) return;
    finished.current = true;
    setBusy(true);
    setError(null);
    try {
      try {
        const own = finishers?.get(attemptId);
        if (own) await own();
        else
          await unwrap(api.POST("/api/v1/attempts/{attempt_id}/submit", { params: { path: { attempt_id: attemptId } } }));
      } catch (e) {
        // Already submitted (another tab, or the server at the deadline): done.
        if (!(e instanceof ApiError && ["attempt_closed", "time_up"].includes(e.code))) throw e;
      }
      setConfirming(false);
      await qc.invalidateQueries({ queryKey: ["attempts"] });
      await qc.invalidateQueries({ queryKey: ["attempt", attemptId] });
      await navigate({ to: "/attempts/$attemptId", params: { attemptId } });
    } catch (e) {
      finished.current = false;
      setError(e);
    } finally {
      setBusy(false);
    }
  }, [attemptId, finishers, navigate, qc]);

  useEffect(() => {
    const timer = setInterval(() => {
      const ms = new Date(deadline).getTime() - Date.now();
      setLeft(ms);
      // Submit once when time runs out; a failure offers a retry below.
      if (ms <= 0 && !timedOut.current) {
        timedOut.current = true;
        void finish();
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [deadline, finish]);

  const text = clock(left);
  const urgent = left < 5 * 60_000;
  return (
    <>
      <div
        role="region"
        aria-label="Mock exam"
        className="fixed right-3 top-[52px] z-40 flex items-center gap-2 rounded-full border border-border bg-bg py-1 pl-3 pr-1 shadow-lg md:right-4 md:top-3"
      >
        <span className="hidden max-w-48 truncate text-xs text-muted sm:inline">{title}</span>
        <span
          role="timer"
          aria-label={`Time left: ${text}`}
          className={`flex items-center gap-1 font-mono text-sm tabular-nums ${urgent ? "font-semibold text-danger" : ""}`}
        >
          <Clock size={14} aria-hidden /> {text}
        </span>
        {!onExamPage && (
          <Link
            to="/attempts/$attemptId"
            params={{ attemptId }}
            className="rounded-full px-2 py-0.5 text-xs font-medium hover:bg-surface"
          >
            Open
          </Link>
        )}
        <Button size="sm" variant="danger" className="rounded-full" disabled={busy} onClick={() => setConfirming(true)}>
          <Square size={10} aria-hidden fill="currentColor" /> Stop
        </Button>
      </div>
      <Modal
        open={confirming}
        onOpenChange={setConfirming}
        title="Stop the exam now?"
        description="Your answers so far are submitted for marking, and unanswered questions score nothing. You can't go back to it."
      >
        <ErrorText error={error} />
        <div className="flex justify-end gap-2">
          <Button onClick={() => setConfirming(false)}>Keep going</Button>
          <Button variant="danger" disabled={busy} onClick={() => void finish()}>
            Stop and submit
          </Button>
        </div>
      </Modal>
      {/* A failure when time ran out shows here, as the modal is closed. */}
      {!confirming && error ? (
        <div className="fixed right-3 top-[96px] z-40 max-w-xs rounded-md border border-border bg-bg p-2 text-sm shadow-lg md:top-14">
          <ErrorText error={error} />
          <Button size="sm" onClick={() => void finish()}>
            Try submitting again
          </Button>
        </div>
      ) : null}
    </>
  );
}
