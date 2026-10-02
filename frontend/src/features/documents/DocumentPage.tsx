import { Link, useNavigate } from "@tanstack/react-router";
import { Download, Pencil, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { MathMarkdown } from "@/components/MathMarkdown";
import { Button, ConfirmDelete, ErrorText } from "@/components/ui";
import { useModule } from "@/features/structure/queries";

import {
  MATERIAL_KINDS,
  useBudget,
  useDocument,
  useDocumentMutations,
  useDocumentProgress,
  usePages,
  type Doc,
  type Page,
} from "./queries";

const METHOD_LABEL: Record<Page["extraction_method"], string> = {
  text: "Extracted text",
  vision: "Transcribed by Claude",
  corrected: "Corrected by you",
  unreadable: "Not readable yet",
};

const PREVIEWABLE = new Set(["application/pdf", "image/png", "image/jpeg"]);
const TRANSCRIBABLE = new Set([
  "application/pdf",
  "image/png",
  "image/jpeg",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
]);

function PageCard({ doc, page }: { doc: Doc; page: Page }) {
  const { correct, retranscribe } = useDocumentMutations(doc.id);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(page.markdown);
  const label = doc.page_count === 1 ? "Content" : `Page ${page.page_no}`;

  return (
    <article
      id={`doc-page-${page.page_no}`}
      tabIndex={-1}
      aria-labelledby={`page-${page.page_no}`}
      className={`grid scroll-mt-4 gap-4 rounded-lg border p-4 ${page.needs_review ? "border-danger" : "border-border"} ${
        PREVIEWABLE.has(doc.mime) ? "lg:grid-cols-2" : ""
      }`}
    >
      {PREVIEWABLE.has(doc.mime) && (
        <img
          src={`/api/v1/documents/${doc.id}/pages/${page.page_no}/preview`}
          alt={`${label} of ${doc.original_filename} as uploaded`}
          loading="lazy"
          className="w-full rounded border border-border bg-white"
        />
      )}
      <div className="flex min-w-0 flex-col gap-3">
        <header className="flex flex-wrap items-center justify-between gap-2">
          <h3 id={`page-${page.page_no}`} className="text-sm font-semibold">
            {label}{" "}
            <span className="ml-1 rounded bg-surface px-1.5 py-0.5 text-xs font-normal text-muted">
              {METHOD_LABEL[page.extraction_method]}
            </span>
          </h3>
          <div className="flex gap-1">
            {TRANSCRIBABLE.has(doc.mime) && (
              <Button
                size="sm"
                variant="ghost"
                disabled={retranscribe.isPending}
                onClick={() => retranscribe.mutate(page.page_no)}
                title="Ask Claude to read this page from its image"
              >
                <Sparkles size={14} /> {retranscribe.isSuccess ? "Queued" : "Transcribe"}
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => setEditing((e) => !e)} aria-expanded={editing}>
              <Pencil size={14} /> {editing ? "Close editor" : "Correct"}
            </Button>
          </div>
        </header>

        {page.needs_review && (
          <p role="note" className="rounded bg-surface px-2 py-1 text-xs text-danger">
            Check this page{page.review_note ? `: ${page.review_note}` : "."}
          </p>
        )}
        {!page.needs_review && page.review_note && (
          <p role="note" className="text-xs text-muted">
            Note from Claude: {page.review_note}
          </p>
        )}

        {editing ? (
          <form
            className="flex flex-col gap-2"
            onSubmit={async (e) => {
              e.preventDefault();
              await correct.mutateAsync({ pageNo: page.page_no, markdown: draft });
              setEditing(false);
            }}
          >
            <label className="text-xs font-medium" htmlFor={`edit-${page.page_no}`}>
              Markdown with LaTeX ($…$ inline, $$…$$ display)
            </label>
            <textarea
              id={`edit-${page.page_no}`}
              className="min-h-64 rounded-md border border-border bg-bg p-2 font-mono text-sm"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <p className="text-xs text-muted">Preview</p>
            <MathMarkdown className="rounded border border-border p-2 text-sm">{draft}</MathMarkdown>
            <ErrorText error={correct.error} />
            <div className="flex gap-2">
              <Button type="submit" variant="primary" size="sm" disabled={correct.isPending}>
                Save correction
              </Button>
              <Button size="sm" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </div>
          </form>
        ) : page.markdown.trim() ? (
          <MathMarkdown className="text-sm">{page.markdown}</MathMarkdown>
        ) : (
          <p className="text-sm text-muted">No text on this page.</p>
        )}
        <ErrorText error={retranscribe.error} />
      </div>
    </article>
  );
}

function BudgetNote() {
  const budget = useBudget();
  if (!budget.data) return null;
  const b = budget.data;
  const money = (n: number) => new Intl.NumberFormat("en-GB", { style: "currency", currency: b.currency }).format(n);
  if (!b.configured) {
    return <p className="text-xs text-muted">Claude is not configured, so damaged maths pages cannot be transcribed yet.</p>;
  }
  return (
    <p className={`text-xs ${b.warning ? "text-danger" : "text-muted"}`}>
      AI spend this month: {money(b.spent_this_month)} of {money(b.monthly_cap)}
      {b.exhausted && " — budget reached; transcription paused"}
    </p>
  );
}

/** Scroll to (and focus, for screen readers) the page a citation points at. */
function useFocusPage(pageNo: number | undefined, loaded: boolean) {
  useEffect(() => {
    if (!pageNo || !loaded) return;
    const target = document.getElementById(`doc-page-${pageNo}`);
    if (!target) return;
    target.scrollIntoView?.({ block: "start" });
    target.focus({ preventScroll: true });
    target.classList.add("ring-2", "ring-accent");
    const timer = setTimeout(() => target.classList.remove("ring-2", "ring-accent"), 2500);
    return () => clearTimeout(timer);
  }, [pageNo, loaded]);
}

export function DocumentPage({ documentId, focusPage }: { documentId: string; focusPage?: number }) {
  const doc = useDocument(documentId);
  useDocumentProgress(doc.data);
  const ready = doc.data?.status === "ready" || doc.data?.status === "failed";
  const pages = usePages(documentId, doc.data !== undefined);
  const module = useModule(doc.data?.module_id ?? "", doc.data !== undefined);
  const { reprocess, remove } = useDocumentMutations(documentId);
  const navigate = useNavigate();
  const [deleting, setDeleting] = useState(false);
  useFocusPage(focusPage, pages.data !== undefined);

  if (doc.isPending) return <p className="text-sm text-muted">Loading…</p>;
  if (doc.isError) return <ErrorText error={doc.error} />;
  const d = doc.data;
  const review = pages.data?.filter((p) => p.needs_review).length ?? 0;

  return (
    <div className="flex max-w-6xl flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          {module.data && (
            <Link
              to="/y/$yearId/m/$moduleId"
              params={{ yearId: module.data.academic_year_id, moduleId: module.data.id }}
              className="text-sm text-muted hover:underline"
            >
              {module.data.code} {module.data.title}
            </Link>
          )}
          <h1 className="break-words text-2xl font-semibold tracking-tight">{d.original_filename}</h1>
          <p className="text-sm text-muted">
            {MATERIAL_KINDS.find((k) => k.value === d.material_kind)?.label}
            {d.week !== null && ` · Week ${d.week}`}
            {` · ${d.source_tier === "university" ? "University material" : "My material"}`}
            {d.page_count !== null && ` · ${d.page_count} pages`}
          </p>
          <BudgetNote />
        </div>
        <div className="flex flex-wrap gap-2">
          <a
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border px-2 text-xs font-medium hover:bg-surface"
            href={`/api/v1/documents/${d.id}/file`}
          >
            <Download size={14} /> Original
          </a>
          <Button size="sm" disabled={!ready || reprocess.isPending} onClick={() => reprocess.mutate()}>
            <RefreshCw size={14} /> Reprocess
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setDeleting(true)}>
            <Trash2 size={14} /> Delete
          </Button>
        </div>
      </header>
      <ErrorText error={reprocess.error} />

      {!ready && (
        <div role="status" className="flex flex-col gap-1">
          <p className="text-sm">
            Processing: {d.stage} ({d.progress}%)
          </p>
          <progress max={100} value={d.progress} className="w-full max-w-md" aria-label="Processing progress" />
        </div>
      )}
      {d.status === "failed" && (
        <p role="alert" className="text-sm text-danger">
          Processing failed ({d.error_code}). Try Reprocess; if it fails again the file may be damaged.
        </p>
      )}
      {review > 0 && (
        <p className="text-sm text-danger">
          {review} page{review === 1 ? " needs" : "s need"} checking. Compare with the original image and correct or
          re-transcribe.
        </p>
      )}

      <ErrorText error={pages.error} />
      <div className="flex flex-col gap-4">
        {pages.data?.map((page) => (
          <PageCard key={`${page.page_no}-${page.extraction_method}-${page.markdown.length}`} doc={d} page={page} />
        ))}
      </div>

      <ConfirmDelete
        open={deleting}
        onOpenChange={setDeleting}
        thing={`“${d.original_filename}”`}
        detail="The file and its extracted pages move to the trash. You can restore them from Settings for 30 days."
        onConfirm={async () => {
          await remove.mutateAsync();
          if (module.data) {
            await navigate({
              to: "/y/$yearId/m/$moduleId",
              params: { yearId: module.data.academic_year_id, moduleId: module.data.id },
            });
          } else {
            await navigate({ to: "/" });
          }
        }}
      />
    </div>
  );
}
