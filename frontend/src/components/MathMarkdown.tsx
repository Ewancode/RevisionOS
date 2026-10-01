/**
 * The one Markdown + maths renderer (ARCHITECTURE.md §3), used for document
 * pages now and for chat, flashcards and questions later.
 *
 * Content is untrusted (it comes from uploaded files and from Claude), so it
 * is sanitised *before* KaTeX runs: only an allow-list of tags survives, raw
 * HTML is never interpreted, and images are dropped so a document cannot make
 * the browser fetch remote URLs. KaTeX runs with `trust: false`, so \href,
 * \url and friends are refused.
 */
import "katex/dist/katex.min.css";

import { memo } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

const schema = {
  ...defaultSchema,
  tagNames: (defaultSchema.tagNames ?? []).filter((tag) => tag !== "img"),
  attributes: {
    ...defaultSchema.attributes,
    // remark-math marks maths as <code class="language-math math-inline|math-display">.
    code: [["className", /^language-./, "math-inline", "math-display"]],
  },
};

const katexOptions = { throwOnError: false, strict: "ignore" as const, trust: false };

const ONE_LINE_DISPLAY = /^([ \t]*)\$\$(.+?)\$\$[ \t]*$/gm;

/**
 * remark-math treats `$$...$$` as display maths only when the `$$` fences
 * sit on their own lines. Claude's transcriptions and Pandoc's output often
 * put a display equation on one line, so give such lines their own fences.
 */
export function normaliseDisplayMaths(markdown: string): string {
  return markdown.replace(
    ONE_LINE_DISPLAY,
    (_, indent: string, body: string) => `${indent}$$\n${indent}${body.trim()}\n${indent}$$`,
  );
}

export const MathMarkdown = memo(function MathMarkdown({
  children,
  className = "",
}: {
  children: string;
  className?: string;
}) {
  return (
    <div className={`math-markdown ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeSanitize, schema], [rehypeKatex, katexOptions]]}
      >
        {normaliseDisplayMaths(children)}
      </ReactMarkdown>
    </div>
  );
});
