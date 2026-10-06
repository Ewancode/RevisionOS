/** Settings > Your data: export everything as a ZIP, or restore one (SPEC 50). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Button, ErrorText } from "@/components/ui";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { formatBytes, uploadRaw } from "@/lib/api/upload";

type Job = Schemas["DataJobOut"];

const KEY = ["exports"] as const;
const ACTIVE = new Set(["queued", "running"]);

export function useDataJobs() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => unwrap(api.GET("/api/v1/export")),
    // Follow a running export or restore until it finishes.
    refetchInterval: (query) => (query.state.data?.some((j) => ACTIVE.has(j.status)) ? 2000 : false),
  });
}

function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function JobRow({ job }: { job: Job }) {
  const label = job.kind === "export" ? "Export" : "Restore";
  let status: string;
  if (job.status === "queued") status = "Waiting to start…";
  else if (job.status === "running") status = job.kind === "export" ? "Building the archive…" : "Restoring…";
  else if (job.status === "failed") status = job.error_message ?? "Failed.";
  else if (job.kind === "restore") status = `Restored ${job.counts?.files ?? 0} files and all your data.`;
  else if (job.expires_at) status = `Ready (${formatBytes(job.size_bytes ?? 0)}), until ${when(job.expires_at)}`;
  else status = "Expired.";

  return (
    <li className="flex flex-wrap items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-surface">
      <span className="text-sm">
        <span className="font-medium">{label}</span> <span className="text-muted">· {when(job.created_at)}</span>
        <br />
        <span className={job.status === "failed" ? "text-danger" : "text-muted"} role="status">
          {status}
        </span>
      </span>
      {job.kind === "export" && job.status === "done" && job.expires_at && (
        <a
          href={`/api/v1/export/${job.id}/file`}
          download
          className="inline-flex h-7 items-center rounded-md border border-border bg-bg px-2 text-xs font-medium hover:bg-surface"
        >
          Download ZIP
        </a>
      )}
    </li>
  );
}

export function YourData() {
  const qc = useQueryClient();
  const jobs = useDataJobs();
  const busy = jobs.data?.some((j) => ACTIVE.has(j.status)) ?? false;
  const fileInput = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const wasRestoring = useRef(false);

  const start = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/export")),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  const restore = useMutation({
    mutationFn: (file: File) => uploadRaw<Job>("/api/v1/export/restore", file, setProgress),
    onSettled: () => setProgress(null),
    onSuccess: () => {
      wasRestoring.current = true;
      return qc.invalidateQueries({ queryKey: KEY });
    },
  });

  // When a restore finishes, everything on screen is stale.
  const restoring = jobs.data?.some((j) => j.kind === "restore" && ACTIVE.has(j.status)) ?? false;
  useEffect(() => {
    if (wasRestoring.current && !restoring && jobs.data) {
      wasRestoring.current = false;
      void qc.invalidateQueries();
    }
  }, [restoring, jobs.data, qc]);

  return (
    <section aria-labelledby="settings-your-data" className="flex flex-col gap-3 border-b border-border pb-6">
      <h2 id="settings-your-data" className="text-base font-semibold">
        Your data
      </h2>
      <p className="text-sm text-muted">
        Export everything as one ZIP: your files, materials and lecture text as Markdown, questions, answers
        and study history as spreadsheets, and your flashcards as an Anki deck. Downloads are kept for a week.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" disabled={busy || start.isPending} onClick={() => start.mutate()}>
          Export my data
        </Button>
        <Button disabled={busy || restore.isPending} onClick={() => fileInput.current?.click()}>
          Restore from an export…
        </Button>
        <input
          ref={fileInput}
          type="file"
          accept=".zip,application/zip"
          className="hidden"
          aria-label="Export to restore"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) restore.mutate(file);
          }}
        />
      </div>
      <p className="text-xs text-muted">
        Restoring needs an empty account (a new one, with no academic years): it brings back everything in
        the export, with your settings.
      </p>
      {progress !== null && (
        <p className="text-sm" role="status">
          Uploading… {Math.round(progress * 100)}%
        </p>
      )}
      <ErrorText error={start.error ?? restore.error} />
      {(jobs.data?.length ?? 0) > 0 && (
        <ul className="flex max-w-xl flex-col gap-1" aria-label="Exports and restores">
          {jobs.data?.map((job) => <JobRow key={job.id} job={job} />)}
        </ul>
      )}
    </section>
  );
}
