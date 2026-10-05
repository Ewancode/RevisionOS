/**
 * Markdown with maths whose `[[n]](#cite-n)` markers (from assistant answers
 * and generated materials) become links to the cited page, plus the list of
 * sources. Citations are verified by the server before they get here.
 */
import { Link } from "@tanstack/react-router";

import { MathMarkdown } from "@/components/MathMarkdown";
import type { Schemas } from "@/lib/api/client";

export type Citation = Schemas["CitationOut"];

const CITE_HREF = /^#(?:user-content-)?cite-(\d+)$/;

function citationTitle(c: Citation) {
  return `${c.filename} — page ${c.page_no}`;
}

/** Answer text, with `[[n]](#cite-n)` markers drawn as links to the cited page. */
export function CitedMarkdown({
  content,
  citations,
  className = "text-sm",
}: {
  content: string;
  citations: Citation[];
  className?: string;
}) {
  return (
    <MathMarkdown
      className={className}
      components={{
        a({ href, children }) {
          const match = href ? CITE_HREF.exec(href) : null;
          if (match) {
            const citation = citations[Number(match[1]) - 1];
            if (!citation) return null;
            return (
              <Link
                to="/doc/$documentId"
                params={{ documentId: citation.document_id }}
                search={{ page: citation.page_no }}
                title={citationTitle(citation)}
                aria-label={`Source ${citation.n}: ${citationTitle(citation)}`}
                className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-surface px-1 align-super text-[10px] font-semibold text-accent-text no-underline hover:underline"
              >
                {citation.n}
              </Link>
            );
          }
          return (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          );
        },
      }}
    >
      {content}
    </MathMarkdown>
  );
}

export function Sources({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null;
  return (
    <section aria-label="Sources" className="flex flex-col gap-1 border-t border-border pt-2">
      <h3 className="text-xs font-medium text-muted">Sources</h3>
      <ol className="flex flex-col gap-1 text-xs">
        {citations.map((c) => (
          <li key={c.n} className="flex gap-2">
            <span className="w-4 shrink-0 text-right font-semibold text-accent-text">{c.n}</span>
            <span className="min-w-0">
              <Link
                to="/doc/$documentId"
                params={{ documentId: c.document_id }}
                search={{ page: c.page_no }}
                className="font-medium hover:underline"
              >
                {citationTitle(c)}
              </Link>
              <span className="text-muted">
                {" "}
                · {c.module_code} · {c.source_tier === "university" ? "University material" : "My notes"}
                {c.heading_path && ` · ${c.heading_path}`}
              </span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
