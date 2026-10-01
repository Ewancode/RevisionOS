import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { AlertTriangle, CheckCircle2, FileText, Loader2, Upload } from "lucide-react";
import { useId, useRef, useState, type DragEvent } from "react";

import { Button, ErrorText } from "@/components/ui";
import type { TopicNode } from "@/features/structure/queries";
import { useTopicTree } from "@/features/structure/queries";

import {
  ACCEPT,
  MATERIAL_KINDS,
  uploadDocument,
  useDocumentProgress,
  useDocuments,
  type Doc,
  type MaterialKind,
  type SourceTier,
} from "./queries";

const STAGES: Record<string, string> = {
  queued: "Waiting to start",
  extracting: "Extracting text",
  transcribing: "Transcribing maths",
  ready: "Ready",
  failed: "Failed",
};

function flatten(nodes: TopicNode[], depth = 0): { id: string; label: string }[] {
  return nodes.flatMap((n) => [
    { id: n.id, label: `${" ".repeat(depth)}${n.title}` },
    ...flatten(n.children ?? [], depth + 1),
  ]);
}

interface Pending {
  key: number;
  name: string;
  fraction: number;
  error?: unknown;
}

let uploadCounter = 0;

function UploadPanel({ moduleId }: { moduleId: string }) {
  const qc = useQueryClient();
  const topics = useTopicTree(moduleId);
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [pending, setPending] = useState<Pending[]>([]);
  const [kind, setKind] = useState<MaterialKind>("lecture");
  const [tier, setTier] = useState<SourceTier>("university");
  const [topicId, setTopicId] = useState("");
  const [week, setWeek] = useState("");
  const ids = { kind: useId(), tier: useId(), topic: useId(), week: useId() };

  async function send(files: FileList | File[]) {
    for (const file of Array.from(files)) {
      const key = ++uploadCounter;
      setPending((p) => [...p, { key, name: file.name, fraction: 0 }]);
      const update = (patch: Partial<Pending>) =>
        setPending((p) => p.map((x) => (x.key === key ? { ...x, ...patch } : x)));
      try {
        await uploadDocument(
          file,
          {
            moduleId,
            materialKind: kind,
            sourceTier: tier,
            topicId: topicId || undefined,
            week: week === "" ? undefined : Number(week),
          },
          (fraction) => update({ fraction }),
        );
        setPending((p) => p.filter((x) => x.key !== key));
      } catch (error) {
        update({ error });
      }
      await qc.invalidateQueries({ queryKey: ["documents", moduleId] });
    }
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length) void send(event.dataTransfer.files);
  }

  const select = "h-8 rounded-md border border-border bg-bg px-2 text-sm";
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <label htmlFor={ids.kind} className="flex flex-col gap-1 text-xs font-medium">
          Type
          <select id={ids.kind} className={select} value={kind} onChange={(e) => setKind(e.target.value as MaterialKind)}>
            {MATERIAL_KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor={ids.tier} className="flex flex-col gap-1 text-xs font-medium">
          Source
          <select id={ids.tier} className={select} value={tier} onChange={(e) => setTier(e.target.value as SourceTier)}>
            <option value="university">University material</option>
            <option value="own">My own material</option>
          </select>
        </label>
        <label htmlFor={ids.topic} className="flex flex-col gap-1 text-xs font-medium">
          Topic (optional)
          <select id={ids.topic} className={select} value={topicId} onChange={(e) => setTopicId(e.target.value)}>
            <option value="">—</option>
            {flatten(topics.data ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor={ids.week} className="flex flex-col gap-1 text-xs font-medium">
          Week
          <input id={ids.week} type="number" min={0} max={60} className={`${select} w-20`} value={week} onChange={(e) => setWeek(e.target.value)} />
        </label>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`flex flex-col items-center gap-2 rounded-lg border-2 border-dashed p-6 text-center text-sm ${
          dragging ? "border-accent bg-surface" : "border-border"
        }`}
      >
        <Upload size={20} className="text-muted" aria-hidden />
        <p>Drag lecture notes, slides, sheets or photos here</p>
        <Button size="sm" onClick={() => input.current?.click()}>
          Choose files
        </Button>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT}
          className="sr-only"
          aria-label="Upload files"
          onChange={(e) => {
            if (e.target.files?.length) void send(e.target.files);
            e.target.value = "";
          }}
        />
        <p className="text-xs text-muted">PDF, Word, PowerPoint, Excel, CSV, text, Markdown and images</p>
      </div>

      {pending.map((p) => (
        <div key={p.key} className="flex flex-col gap-1 text-sm">
          <div className="flex justify-between">
            <span>{p.name}</span>
            {!p.error && <span className="text-muted">Uploading {Math.round(p.fraction * 100)}%</span>}
          </div>
          {p.error ? (
            <div className="flex items-center justify-between gap-2">
              <ErrorText error={p.error} />
              <Button size="sm" variant="ghost" onClick={() => setPending((all) => all.filter((x) => x.key !== p.key))}>
                Dismiss
              </Button>
            </div>
          ) : (
            <progress className="w-full" max={1} value={p.fraction} aria-label={`Uploading ${p.name}`} />
          )}
        </div>
      ))}
    </div>
  );
}

function DocumentRow({ doc }: { doc: Doc }) {
  useDocumentProgress(doc);
  const busy = doc.status === "queued" || doc.status === "processing";
  return (
    <li className="flex items-center gap-3 rounded-md px-2 py-2 hover:bg-surface">
      <FileText size={16} className="shrink-0 text-muted" aria-hidden />
      <div className="min-w-0 flex-1">
        <Link to="/doc/$documentId" params={{ documentId: doc.id }} className="block truncate text-sm font-medium hover:underline">
          {doc.original_filename}
        </Link>
        <p className="text-xs text-muted">
          {MATERIAL_KINDS.find((k) => k.value === doc.material_kind)?.label}
          {doc.week !== null && ` · Week ${doc.week}`}
          {doc.source_tier === "own" && " · My material"}
          {doc.page_count !== null && ` · ${doc.page_count} page${doc.page_count === 1 ? "" : "s"}`}
        </p>
        {busy && (
          <progress className="mt-1 w-full" max={100} value={doc.progress} aria-label={`Processing ${doc.original_filename}`} />
        )}
      </div>
      <span className="flex shrink-0 items-center gap-1 text-xs" aria-live="polite">
        {busy && <Loader2 size={14} className="animate-spin" aria-hidden />}
        {doc.status === "ready" && <CheckCircle2 size={14} className="text-success" aria-hidden />}
        {doc.status === "failed" && <AlertTriangle size={14} className="text-danger" aria-hidden />}
        {busy ? `${STAGES[doc.stage] ?? doc.stage} · ${doc.progress}%` : STAGES[doc.status]}
      </span>
    </li>
  );
}

export function Materials({ moduleId }: { moduleId: string }) {
  const documents = useDocuments(moduleId);
  return (
    <section aria-labelledby="materials-heading" className="flex flex-col gap-3">
      <h2 id="materials-heading" className="text-base font-semibold">
        Materials
      </h2>
      <UploadPanel moduleId={moduleId} />
      <ErrorText error={documents.error} />
      {documents.data?.length === 0 && <p className="text-sm text-muted">No materials uploaded yet.</p>}
      <ul aria-label="Documents" className="flex flex-col">
        {documents.data?.map((doc) => <DocumentRow key={doc.id} doc={doc} />)}
      </ul>
    </section>
  );
}
