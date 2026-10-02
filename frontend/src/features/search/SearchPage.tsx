import { Link, useNavigate } from "@tanstack/react-router";
import { BookOpen, FileText, FolderOpen, Hash, X } from "lucide-react";
import { useEffect, useState } from "react";

import { MathMarkdown } from "@/components/MathMarkdown";
import { ErrorText } from "@/components/ui";
import { useModule } from "@/features/structure/queries";

import { useDebounced, useSearch, type Passage } from "./queries";

const TIER_LABEL: Record<Passage["source_tier"], string> = {
  university: "University material",
  own: "My material",
};

function PassageCard({ passage }: { passage: Passage }) {
  const [open, setOpen] = useState(false);
  const long = passage.content.length > 700;
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <Link
          to="/doc/$documentId"
          params={{ documentId: passage.document_id }}
          search={{ page: passage.page_no }}
          className="font-medium hover:underline"
        >
          {passage.filename} — page {passage.page_no}
        </Link>
        <span className="text-xs text-muted">
          {passage.module_code} · {TIER_LABEL[passage.source_tier]}
          {passage.matched === "meaning" && " · related meaning"}
        </span>
      </header>
      {passage.heading_path && <p className="text-xs text-muted">{passage.heading_path}</p>}
      <div className={open || !long ? "" : "max-h-48 overflow-hidden [mask-image:linear-gradient(to_bottom,black_70%,transparent)]"}>
        <MathMarkdown className="text-sm">{passage.content}</MathMarkdown>
      </div>
      {long && (
        <button type="button" className="self-start text-xs text-muted hover:underline" onClick={() => setOpen((o) => !o)}>
          {open ? "Show less" : "Show more"}
        </button>
      )}
    </li>
  );
}

export function SearchPage({ q, moduleId }: { q: string; moduleId?: string }) {
  const navigate = useNavigate();
  const [text, setText] = useState(q);
  const debounced = useDebounced(text);
  const search = useSearch(debounced, moduleId);
  const scopeModule = useModule(moduleId ?? "", moduleId !== undefined);

  // Keep the URL in step, so results can be bookmarked and Back works.
  useEffect(() => {
    if (debounced !== q) {
      void navigate({ to: "/search", search: { q: debounced, module_id: moduleId }, replace: true });
    }
  }, [debounced, q, moduleId, navigate]);

  const data = search.data;
  const nothing =
    data && !data.passages.length && !data.modules.length && !data.topics.length && !data.documents.length;

  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <h1 className="text-2xl font-semibold tracking-tight">Search</h1>
      <input
        type="search"
        aria-label="Search your materials"
        placeholder="Search notes, slides, sheets… e.g. “ratio test” or “why is exp its own derivative”"
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="h-11 rounded-lg border border-border bg-bg px-3"
      />
      {moduleId && (
        <p className="flex items-center gap-2 text-sm">
          Searching {scopeModule.data ? `${scopeModule.data.code} ${scopeModule.data.title}` : "one module"}
          <Link to="/search" search={{ q: text }} className="inline-flex items-center gap-1 text-xs text-muted hover:underline">
            <X size={12} /> search everything
          </Link>
        </p>
      )}
      <ErrorText error={search.error} />
      {search.isFetching && <p className="text-xs text-muted" role="status">Searching…</p>}
      {data?.widened && (
        <p className="text-xs text-muted">Few matches in this scope, so results from your other materials are included below.</p>
      )}
      {nothing && <p className="text-sm text-muted">No matches in your materials.</p>}

      {data && (data.modules.length > 0 || data.topics.length > 0 || data.documents.length > 0) && (
        <section aria-labelledby="names-heading" className="flex flex-col gap-1">
          <h2 id="names-heading" className="text-sm font-semibold">
            Names
          </h2>
          <ul className="flex flex-col gap-1 text-sm">
            {data.modules.map((m) => (
              <li key={m.id}>
                <Link to="/y/$yearId/m/$moduleId" params={{ yearId: m.academic_year_id, moduleId: m.id }} className="inline-flex items-center gap-2 hover:underline">
                  <FolderOpen size={14} aria-hidden /> {m.code} {m.title}
                </Link>
              </li>
            ))}
            {data.topics.map((t) => (
              <li key={t.id} className="inline-flex items-center gap-2">
                <Hash size={14} aria-hidden /> Topic: {t.title}
              </li>
            ))}
            {data.documents.map((d) => (
              <li key={d.id}>
                <Link to="/doc/$documentId" params={{ documentId: d.id }} className="inline-flex items-center gap-2 hover:underline">
                  <FileText size={14} aria-hidden /> {d.original_filename}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {data && data.passages.length > 0 && (
        <section aria-labelledby="passages-heading" className="flex flex-col gap-2">
          <h2 id="passages-heading" className="flex items-center gap-2 text-sm font-semibold">
            <BookOpen size={14} aria-hidden /> In your materials
          </h2>
          <ol className="flex flex-col gap-3">
            {data.passages.map((p) => (
              <PassageCard key={p.chunk_id} passage={p} />
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}
