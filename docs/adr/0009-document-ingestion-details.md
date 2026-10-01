# 9. Document ingestion details

Date: 2026-10-01 · Status: Accepted (refines ARCHITECTURE.md sections 6, 7 and 12)

## Decision

**Upload transport.** `POST /api/v1/documents` takes the file as the raw
request body, with metadata in the query string, streamed to a temporary
file with a hard byte cap (checked against Content-Length first, then while
streaming). This avoids multipart parsing, whose spooling has no size limit
of its own. The browser uses XHR so it can show upload progress.

**Validation** (`app/ingestion/validation.py`). The file's bytes decide its
type, and the extension must agree. Office files are zip archives and are
rejected for too many entries, absurd expansion, encryption or macros.
PDFs must open, be unencrypted and fit `max_pdf_pages`. Images are decoded
under a pixel cap and re-encoded, which applies the camera rotation and
drops all metadata (phone GPS). HEIC becomes JPEG and WebP becomes PNG.
Text must be UTF-8 with no NUL bytes. Display filenames are sanitised
(directories, control characters and bidi overrides removed) and are never
used in storage keys.

**Storage.** Keys are built only from server UUIDs (`users/{u}/documents/{d}/…`)
and re-validated by the backend; the local backend also refuses any path
outside its root. The S3-compatible backend arrives with deployment (Phase 13).
Originals download as attachments; page images are rendered on demand and
cached.

**Pages.** One row per page, slide, sheet or file, as Markdown with LaTeX.
`extraction_method` records how: `text`, `vision`, `corrected` or `unreadable`.
Re-processing never overwrites `vision` or `corrected` pages. A page that
could not be transcribed (no key, budget reached, refusal) keeps its text and
is flagged `needs_review` with the reason.

**Which pages go to Claude** (`app/ingestion/maths_damage.py`). A
maths-damage score per page combines four signals: maths-font share, orphan
symbol lines, operator density and broken glyphs. Weights, saturations and the
threshold are in `config/platform.yaml`. Pages over the threshold go to
vision, as do text-less pages with images or drawings (scans, diagrams) and all
photos. Clean text pages never leave the machine.

**Calibration on real lecture notes (2026-10-01).** On four real LaTeX
documents (a 110-page set of notes, 18 beamer slides, two problem sheets),
text extraction lost structure on almost every page with mathematics:
subscripts (`a_n` became `an`), superscripts (`x^2` became `x2`),
fractions, integral limits and blackboard letters (ℝ became R). Pages
scoring 0.15–0.3 were still damaged, so the threshold is 0.15. That sends 103
of 110 note pages, 11 of 18 slides and both sheets to vision. Measured cost
with Sonnet at `high` effort is about $0.005 per slide and $0.019 per dense
notes page (about 1,000 output tokens), so a 110-page set of notes costs about
£1.60 to transcribe, once. Transcriptions of the hardest pages matched the
originals exactly, and the notes field flagged genuine typos in the source,
transcribed as printed. PyMuPDF's table detector fired on 30 graphs and
boxed theorems, and none were real tables, so a detected table must now be
at least 80% filled and contain no stacks of axis numbers.

**Extractors.** PyMuPDF for PDFs (headings by relative font size, tables to
Markdown), Pandoc (`pypandoc-binary`, bundled) for Word, so equations come
out as LaTeX, python-pptx for slides (text, tables, speaker notes),
openpyxl and `csv` for spreadsheets (schema, sample rows, numeric summaries).
pandas, listed in the design, is not needed for that and is not a dependency.

**Slides with Office equations** are detected in the slide XML. When
LibreOffice is installed (Docker build arg `WITH_LIBREOFFICE=true`, about
500 MB) they are rendered and transcribed; otherwise they are flagged for
review.

**Progress.** `GET /documents/{id}/events` is a server-sent-events stream that
polls the document row (`progress_poll_seconds`) until it is ready or failed.
Redis pub/sub, as the design suggested, can replace the polling later
without changing the API.

**Limits.** The worker container has a 2 GB memory limit (Docker) and each
job a timeout (`job_timeout_seconds`); Pandoc and LibreOffice run with their
own timeouts.

**Licensing.** PyMuPDF is AGPL-3.0. That is compatible with a private,
single-user app whose source is public on GitHub. A future hosted
multi-user service would need either to keep its source public or to replace
PyMuPDF (pypdfium2 is the likely swap behind the same extractor interface).

## Consequences

Real lecture files are never committed: tests generate their own PDFs, Office
files and images, and a local-only `pytest -m samples` run checks extraction on
files you put in the git-ignored `samples/` folder.
