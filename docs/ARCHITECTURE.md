# Revision OS — Architecture & Technical Design Proposal

Oct 1, 2026 · @Ewan

## Summary

Build Revision OS as a Python/FastAPI backend and a React single-page app on one PostgreSQL database that holds relational data, vector embeddings and keyword search together. Claude does the language work — reading your materials, generating content, tutoring, marking open answers. Scheduling, topic strength and recommendations run on documented algorithms that are fast, cheap, explainable and testable.

| Decision | Choice | Why it matters |
| --- | --- | --- |
| Backend | Python 3.12 + FastAPI | Your language; best libraries for documents, AI and maths |
| Data | PostgreSQL + pgvector + full-text search | One store for relational, semantic and keyword data; hybrid search with no extra service |
| Frontend | React + TypeScript SPA (Vite) | One backend of truth, no second server |
| AI split | Claude for language, algorithms for numbers | Opening the dashboard costs no API calls; every score can be explained |
| Maths extraction | Text layer first; Claude vision for maths-heavy, scanned and handwritten pages | Your own MATLAB notes already lose equations under plain extraction (section 7) |
| Destructive actions | Impossible for Claude by construction | Delete tools only create a pending request; only you can confirm it |
| Build environment | Claude Code in your local repo, this doc as the spec | This chat's sandbox resets and can't run your database or push to GitHub |

Before Phase 1 I need four answers, listed in section 18: API budget, hosting, module hierarchy and build environment. Everything else has a stated default you can override.

## 1. Recommended technology stack

Every choice favours boring, well-documented tools that run on a laptop with Docker and deploy unchanged later. Nothing is chosen for novelty.

| Layer | Choice | Why | Rejected |
| --- | --- | --- | --- |
| Backend framework | Python 3.12, FastAPI, Pydantic v2 | Your language; async; typed request models; OpenAPI docs generated automatically | Django (sync-first, heavier); Node (weaker parsing and maths ecosystem) |
| ORM and migrations | SQLAlchemy 2.0 (async) + Alembic | Mature, typed, explicit reversible migrations | SQLModel (less control at this schema size) |
| Database | PostgreSQL 16 | Real relational integrity for a heavily linked schema | SQLite (no pgvector, weak concurrency with workers) |
| Vector search | pgvector, HNSW index | Same database and transaction as the metadata; a personal corpus fits easily | Pinecone, Qdrant, Chroma (extra service and sync bugs; still swappable later) |
| Keyword search | Postgres full-text search (tsvector, GIN) | Exact hits on terms like "Black-Scholes" that embeddings blur | Elasticsearch (overkill) |
| Background jobs | Arq + Redis | Async-native and simple; Redis also carries rate limits and progress events | Celery (heavy configuration) |
| Document parsing | PyMuPDF, Pandoc, python-pptx, openpyxl/pandas, Pillow | Best tool per format; Pandoc converts Word equations to LaTeX | Unstructured.io (convenient, loses maths) |
| Maths and handwriting transcription | Claude vision per page, behind an interface | Handles handwriting and LaTeX far better than classic OCR | Tesseract (poor on maths); Mathpix (good, paid; possible swap) |
| Embeddings | Local BGE model via fastembed (ONNX, CPU) | Free, private, fast; swappable to Voyage AI | A second paid vendor by default |
| Reranking | Local cross-encoder, optional | Better top results at no API cost | — |
| AI | Anthropic Python SDK | Official; streaming, tool use, token counting | Framework wrappers (hide cost and control) |
| Spaced repetition | FSRS via py-fsrs | Current best open scheduler; Anki's modern default | SM-2 (older, less accurate) |
| Symbolic checking | SymPy | Deterministic equivalence checks for algebraic answers | Trusting the model to mark algebra |
| Frontend | React 18, TypeScript, Vite, TanStack Router + Query | Fast builds, typed routes, server-state caching | Next.js (a second server beside FastAPI; SSR not needed for a private app) |
| UI kit | Tailwind CSS + shadcn/ui (Radix) | Accessible primitives; clean Notion-like look | Heavier component suites |
| Maths rendering | KaTeX via react-markdown, remark-math, rehype-katex | Fast synchronous rendering | MathJax (slower; kept as fallback) |
| Charts, calendar, palette | Recharts, FullCalendar (MIT core), cmdk | Proven, small, accessible | — |
| Code practice | CodeMirror 6; Pyodide (Python) and WebR (R) in Web Workers | Code runs in the browser sandbox, never on the server | Server-side execution (needs hardened sandboxing) |
| PDF viewer | pdf.js | Opens a citation at the exact page | — |
| Tooling | uv, pnpm, Ruff, mypy, ESLint, pytest, Vitest, Playwright, Docker Compose, GitHub Actions | Standard, fast, CI-friendly | — |

WebR matters because MATH163 is taught in R; Pyodide covers your Python work. MATLAB (MATH111) cannot run in a browser — see section 18.

## 2. System architecture diagram

&#91;embedded content: system architecture · browser, backend packages, data stores, Anthropic API\]

Claude sits outside the backend boundary and is reached only through the AI orchestration layer. Ingestion, retrieval, the learning engine and the planner do most of their work without it.

## 3. Frontend architecture

A feature-sliced React SPA that talks only to the FastAPI backend, through a TypeScript client generated from the backend's OpenAPI schema. A backend change that breaks the frontend fails the build, not your revision session.

**State and data.** TanStack Query owns server state: caching, background refresh, optimistic updates for fast actions like flashcard ratings. A small Zustand store holds UI-only state such as theme and palette visibility. Claude replies and document-processing progress stream over Server-Sent Events.

**One maths renderer everywhere.** A single `MathMarkdown` component renders Markdown, KaTeX and citation chips in chat, flashcards, questions and materials, sanitised with rehype-sanitize because Claude output and document text are untrusted.

**Claude as a global drawer.** Besides the Ask Claude page, a right-hand drawer (Ctrl+J) opens anywhere and carries context: the module, topic or document you are looking at. Exam Mode uses a separate distraction-free layout with the drawer removed; the backend enforces the same rule (section 9).

**Theming and platform.** CSS variables drive light, dark and system themes plus a custom accent colour. The app is an installable PWA, which is what enables Web Push on phones.

**Accessibility.** Radix primitives supply focus management, keyboard support and ARIA. Visible focus rings, reduced-motion support and axe-core checks in CI are standard.

| Route | Purpose |
| --- | --- |
| `/` | Dashboard: today's plan, quiz, streak, weak topics, exams, recommendation |
| `/y/:year/m/:module/*` | Module dashboard with tabs: overview, topics, materials, questions, flashcards, mistakes, progress, plan, ask |
| `/practice/quiz`, `/practice/flashcards`, `/practice/questions`, `/practice/mistakes`, `/practice/coding` | Practice modes |
| `/exam/:id` | Exam Mode, distraction-free |
| `/plan`, `/calendar`, `/exams` | Planner, calendar, exam entry |
| `/library/:kind` | University materials, my materials, Claude generated |
| `/doc/:id?page=n` | Document viewer opened by citations |
| `/analytics`, `/ai-usage` | Performance and API cost dashboards |
| `/ask`, `/search`, `/settings/*` | Full chat, search results, settings |

**Proposed sidebar** — a small change from your section 65:

- Top: Today, Search (Ctrl+K), Ask Claude (Ctrl+J), academic-year switcher
- Modules: the current year's real modules (MATH101 Calculus I, MATH103 Linear Algebra…), optionally grouped by subject
- Practice: Daily Quiz, Flashcards (due count), Question Bank, Mock Exams, Mistake Bank, Coding
- Plan: Revision Plan, Calendar, Exams
- Library: University Materials, My Materials, Claude Generated
- Analytics, Settings

The changes: modules are listed by real module per year, Exams sits under Plan, Coding joins Practice, and Claude is reachable from every screen rather than one page.

## 4. Backend architecture

A modular monolith: one FastAPI application plus one background worker, split into packages with clear interfaces. For one user and one developer this beats microservices on every axis, and the package boundaries still allow a split later.

**Layers.** Routers validate input and resolve the current user. Services hold the business rules and transaction boundaries. Repositories do all database access, and every repository method requires the current user, so no query can run unscoped. Models sit underneath.

**Domain packages** behind interfaces: `ingestion`, `retrieval`, `ai`, `learning`, `planner`, `storage`, `notifications`. Services call them; they never call routers.

**Processes.**

- `api` — FastAPI on uvicorn; REST plus SSE streams
- `worker` — Arq jobs: extraction, transcription, embedding, bulk generation, nightly recomputation of mastery, profile and plan, notification dispatch
- `scheduler` — Arq cron triggers for the nightly and hourly jobs

**API conventions.** REST under `/api/v1`, resource-oriented, cursor pagination. Errors use one envelope, `{error: {code, message, request_id}}`, and never include stack traces. Generation endpoints accept an idempotency key so a retried request is not charged twice.

| Endpoint group | Covers |
| --- | --- |
| `/auth` | Login, logout, session, 2FA |
| `/years`, `/modules`, `/topics` | Academic structure, tree reordering, archive |
| `/documents` | Upload, status stream, pages, corrected transcriptions, authenticated file stream |
| `/materials` | Materials, versions, diff, restore, drafts |
| `/search` | Global hybrid search |
| `/conversations` | Chat with Claude, streamed, with citations |
| `/questions`, `/quizzes`, `/attempts` | Question bank, quiz build, submit, marking, disputes |
| `/flashcards`, `/reviews` | Cards and FSRS reviews |
| `/mistakes`, `/profile` | Mistake bank and learning profile |
| `/exams`, `/availability`, `/plan`, `/sessions` | Planner and calendar |
| `/analytics`, `/ai-usage` | Dashboards and cost |
| `/pending-actions` | Confirm or cancel destructive actions |
| `/notifications`, `/export` | Notifications, push subscriptions, export jobs |

**Configuration.** Secrets come from environment variables through pydantic-settings. Every tunable number — half-lives, weights, limits, model choices — lives in a versioned `config/learning.yaml` and `config/ai.yaml`, never in code. That answers your "no magic numbers" rule and makes the algorithms auditable.

**Logging.** Structured JSON logs carry a request ID end to end, so a user-facing error code maps to the exact log line.

## 5. Database schema

About 35 normalised PostgreSQL tables managed by Alembic migrations. Every user-owned row carries `user_id`; attempts and reviews are append-only facts; scores, profile and plan are derived from them and can be recomputed whenever an algorithm changes.

| Area | Table | Key columns and notes |
| --- | --- | --- |
| Identity | `users` | email, password\_hash (Argon2id), totp\_secret (encrypted), created\_at |
| Identity | `auth_sessions` | token\_hash, user\_id, expires\_at, last\_seen\_at, ip, user\_agent |
| Identity | `user_settings` | theme, accent, ai limits, notification prefs, FSRS target retention — typed columns |
| Identity | `push_subscriptions` | endpoint, keys, device label |
| Structure | `academic_years` | label ("2026/27"), start\_date, end\_date, is\_current |
| Structure | `modules` | academic\_year\_id, code ("MATH103"), title, subject\_tag, credits, colour, status (active/archived), deleted\_at |
| Structure | `topics` | module\_id, parent\_id (self-reference), title, position, importance, deleted\_at |
| Structure | `topic_relations` | from\_topic\_id, to\_topic\_id, kind (prerequisite/related); may cross years |
| Content | `documents` | module\_id, topic\_id, original\_filename, storage\_key, mime, size, sha256, source\_tier (university/own), material\_kind (lecture/problem sheet/solutions/past paper/notes), week, status, stage, progress, error\_code, page\_count |
| Content | `document_pages` | document\_id, page\_no, markdown, extraction\_method (text/vision/corrected), image\_key, maths\_damage\_score |
| Content | `chunks` | document\_id or material\_version\_id (exactly one), module\_id, topic\_id, page\_start, page\_end, heading\_path, content, tsv, embedding vector, embedding\_model, token\_count, source\_tier |
| Content | `materials` | module\_id, topic\_id, title, kind (guide/summary/formula sheet/concept map/worked example/notes), origin (user/claude), current\_version\_id, derived\_from\_id |
| Content | `material_versions` | material\_id, version\_no, content\_md, created\_by, ai\_interaction\_id, change\_note |
| Practice | `questions` | module\_id, topic\_id, type, difficulty\_label, elo\_difficulty, stem\_md, answer\_spec (JSONB, validated per type), solution\_md, origin, status (draft/active/retired), content\_hash, embedding |
| Practice | `question_sources` | question\_id, chunk\_id |
| Practice | `quizzes`, `quiz_items` | kind (daily/custom/mock/exam), config; ordered question list |
| Practice | `quiz_attempts` | quiz\_id, mode (normal/exam), started\_at, deadline, submitted\_at |
| Practice | `question_attempts` | question\_id, quiz\_attempt\_id, response (JSONB), response\_image\_key, score 0–1, marked\_by (rule/sympy/ai/override), marking\_confidence, time\_ms, self\_confidence, hints\_used |
| Practice | `mistakes` | question\_attempt\_id, topic\_id, category, description, embedding |
| Practice | `flashcards` | module\_id, topic\_id, front\_md, back\_md, origin, source\_chunk\_id, FSRS state (stability, difficulty, due, reps, lapses, state, last\_review) |
| Practice | `flashcard_reviews` | flashcard\_id, rating (1–4), reviewed\_at, elapsed\_days, scheduled\_days |
| Practice | `coding_exercises`, `coding_submissions` | language, prompt, starter code, tests; code, results |
| Derived | `topic_mastery` | topic\_id, strength, effective\_n, elo\_ability, last\_practised\_at, computed\_at |
| Derived | `learning_profile_snapshots` | metrics (JSONB snapshot), summary\_md, computed\_at |
| Planning | `exams`, `exam_topics` | module\_id, starts\_at, duration\_min, location, weighting, confidence; covered topics |
| Planning | `availability_rules`, `availability_overrides` | weekday + minutes; date + minutes |
| Planning | `revision_plans`, `study_sessions` | params, generated\_at; topic\_id, kind, planned\_start, minutes, status (planned/done/missed/skipped), locked\_by\_user, actual\_minutes |
| AI | `conversations`, `messages` | scope (module/topic/document), role, content, citations |
| AI | `ai_interactions` | feature, model, prompt\_version, tool\_calls, status, latency\_ms |
| AI | `ai_usage` | model, input/output/cache tokens, estimated\_cost, feature, module\_id |
| System | `pending_actions` | action, target, preview, token\_hash, expires\_at, status |
| System | `notifications`, `audit_log` | kind, payload, scheduled\_for, read\_at; destructive actions and logins |

**Design rules.**

1. One self-referencing `topics` table replaces a separate Subtopic table, so "Integration › Integration by Parts › Tabular method" works at any depth. A constraint keeps a child in its parent's module.
2. Years own modules. Moving to Year 2 hides nothing permanently; the year switcher filters.
3. JSONB is used only where the shape genuinely varies by type and is validated by Pydantic: a multiple-choice answer spec differs from a numeric tolerance or a SymPy expression. Anything you filter or sort on is a real column.
4. Chunks come from documents or from material versions, so one search index covers university files, your notes and Claude's materials.
5. Every Claude-made row links to its `ai_interaction_id`, so provenance and cost are always traceable.
6. Deletes are soft with a 30-day trash, on top of the confirmation rule.
7. Each embedding records its model, so switching embedding model is a re-index job, not a migration crisis.

## 6. File storage architecture

Raw files sit behind a `StorageBackend` interface with two implementations: local disk in development, and a private S3-compatible bucket (Cloudflare R2 or Backblaze B2) when deployed. Changing provider means writing one class.

**Interface.** `put(key, stream)`, `open(key)`, `delete(key)`, `exists(key)`, `signed_url(key, ttl)`.

**Keys never come from you.** Files are stored at `users/{user_id}/documents/{uuid}/original`, with derived page images under `pages/{n}.png`. Your filename lives only in the database and is sanitised for display. Path traversal is impossible by construction, not by filtering.

**Duplicates.** A SHA-256 of each upload catches re-uploads: "You already uploaded this as 103-L1-22."

**Access.** Files are served only through `GET /api/v1/documents/{id}/file`, which checks ownership and streams with an explicit Content-Type, `Content-Disposition` and `X-Content-Type-Options: nosniff`. When deployed, large files may use a pre-signed URL that expires in five minutes, issued after the same check. The bucket is never public.

**Upload flow.**

1. Stream to a temporary file with a size cap.
2. Validate type, size and structure (section 12).
3. Commit to storage, create the `documents` row, return `202 Accepted`.
4. The worker processes it; the UI follows progress over SSE.

**Backups.** Nightly `pg_dump` plus bucket object versioning. The user-facing ZIP export (Phase 13) is your own portable backup.

## 7. Document processing pipeline and RAG architecture

Every file becomes page-level Markdown with LaTeX maths, then structure-aware chunks tied to page numbers, indexed for keyword and semantic search. Claude answers from the few most relevant passages, never from a whole document.

**Why plain extraction is not enough.** Your own notes prove it. When the MATH111 Vectors PDF was read earlier, its component-wise product came out as "1 × 2 2 3 4 × × × −1", and the For Loops notes turned S\_n = n/2 (n+1) into "Sn = n2(n+ 1)" — the fraction vanished. A revision tool fed that text would teach you wrong formulas.

### Ingestion stages

1. **Validate and store** (section 6). Status `queued`.
2. **Extract per page** into blocks (heading, text, equation, table, figure), choosing the extractor by type:

| Format | Extractor | Maths handling |
| --- | --- | --- |
| PDF with text layer | PyMuPDF to Markdown | Each page gets a maths-damage score (maths fonts, orphan operators, broken glyphs); damaged pages are re-transcribed by Claude vision |
| Scanned PDF, photos, handwriting | Page image to Claude vision | Transcribed to Markdown + LaTeX with a confidence flag |
| DOCX | Pandoc | Word equations converted to LaTeX |
| PPTX | python-pptx: text, tables, speaker notes per slide | Equation or image slides rendered (LibreOffice, optional) and sent to vision |
| XLSX, CSV | pandas: schema, sample rows, summary per sheet | Large sheets summarised, not embedded row by row |
| TXT, Markdown | As is | Existing LaTeX preserved |

3. **Chunk** at structural boundaries — headings, definitions, theorems, examples — never inside an equation, table or proof. Target 300–800 tokens with a small overlap. Each chunk keeps page\_start, page\_end and a heading path such as "Lecture 2 › Argument › Quadrant rule".
4. **Contextualise.** The embedded text gets a short header (module, document, section path), so a chunk that only says "multiply by the conjugate" is still found for "complex division". Anthropic's Contextual Retrieval technique — a one-sentence, Claude-written context per chunk — is available as an opt-in per document.
5. **Embed and index**: local embedding model into a pgvector HNSW index; a tsvector column for keywords.
6. **Analyse** (your choice per upload): Claude returns structured JSON of topics, definitions, theorems, formulas, worked examples, likely exam material and prerequisites. These arrive as suggestions — topic placement, flashcards, questions, summary — that you accept or reject.

Stages are idempotent and resumable; one bad page never fails the whole document. You can view any page's transcription beside the original and correct it, and the correction re-indexes only that page. Progress streams as: Uploaded → Extracting (page 37 of 200) → Transcribing maths (6 pages) → Indexing → Ready.

### Retrieval at question time

1. **Scope** by year, module and topic from where you are asking; widen automatically if results are thin.
2. **Rewrite** follow-ups like "what about the second one?" into a standalone query (fast model, only when needed).
3. **Hybrid search**: keyword ranking and vector top-k, fused with Reciprocal Rank Fusion.
4. **Rerank** the top \~40 with a local cross-encoder; keep \~8.
5. **Tier weighting**: university material, then your own, then Claude-generated, applied as a ranking boost, not a filter. Your three priority levels are honoured without hiding useful material.
6. **Assemble context**: merge neighbouring chunks, de-duplicate, fit a token budget, label each passage with an ID, tier, document and page.
7. **Relevance floor**: if nothing clears the threshold, Claude is told plainly that no material was found, and the answer is badged "General knowledge — not from your materials".

### Citations and provenance

- Claude cites passage IDs. The server checks every cited ID was actually in the context it sent; anything else is dropped and logged. This is a deterministic check, not trust.
- The provenance badge — University, My notes, Claude-generated, General knowledge — is computed from what was actually cited, never from what Claude says it used. This enforces your section 68.
- Clicking a citation opens pdf.js at the page, with the passage highlighted where a text layer exists.
- When passages from different tiers disagree, the prompt requires naming both sources and explaining the difference. Conflict cases join the evaluation set.

**Global search** uses the same engine over chunks plus the entity tables (modules, topics, questions, flashcards, mistakes), grouped by result type. The command palette calls it too.

**Replaceable parts.** `Extractor`, `EmbeddingProvider`, `VectorStore` and `Reranker` are interfaces. Moving from pgvector to Qdrant is one new class and a re-index job.

## 8. Claude API architecture

All Claude traffic flows browser → FastAPI → AI orchestration layer → Anthropic API. The API key exists only in the backend's environment; no response, log or page ever contains it.

**Components of the AI layer.**

- `ClaudeClient` wraps the official SDK: timeouts, exponential backoff on rate-limit and overload errors, streaming, and capture of every response's token usage into `ai_usage`.
- `ModelRouter` maps each task type to a model from `config/ai.yaml`.
- `PromptRegistry` stores prompts as versioned template files with tests. Each interaction records its prompt version, so a quality drop traces to a prompt change.
- `ContextBuilder` assembles system rules, your learning-profile summary, retrieved passages and conversation history within a token budget.
- `BudgetGuard` enforces daily and monthly caps, warns at 75%, and asks for confirmation before large jobs using the token-counting endpoint: "Generating flashcards from 6 lectures will use about 180k tokens. Continue?" At the cap, AI features pause; flashcard reviews, quizzes from the existing bank and the planner keep working.
- `CostEstimator` reads per-model prices from config, which you update from Anthropic's pricing page.

**Model routing defaults** — all editable in config or Settings:

| Task | Default model | Reason |
| --- | --- | --- |
| Query rewriting, classification, mistake labelling | Haiku 4.5 | Short, high-volume |
| Flashcards, multiple-choice and short-answer questions, simple marking | Haiku 4.5, escalating on validation failure | Volume; validated deterministically |
| Maths transcription of damaged or handwritten pages | Sonnet 5.5 | Notation accuracy outweighs cost; done once per page |
| Tutoring, explanations, revision guides, document analysis | Sonnet 5.5 | Quality default |
| Marking proofs and derivations; exam-level questions | Sonnet 5.5, escalating to Opus 5.5 on low confidence or your dispute | Correctness matters most |
| Explaining the revision plan | Haiku 4.5 | The plan itself is computed (section 11) |

The model strings (`claude-haiku-4-5-20251001`, `claude-sonnet-5-5`, `claude-opus-5-5`) live only in config.

**Cost levers.**

1. Prompt caching for the stable prefix: system rules, tool definitions, profile summary, a document being analysed page by page.
2. The Message Batches API for non-urgent bulk work, such as overnight question generation for a whole module, at a lower price.
3. The fast model by default; stronger models only where quality demands it.
4. No model calls in hot paths: dashboard, search ranking, scheduling and mastery are pure computation.

**Structured outputs.** Generation requests use JSON schemas derived from Pydantic models. Responses are validated; one repair retry follows a failure, then the error surfaces to you rather than saving bad data.

**Streaming.** Chat and tutor replies stream over SSE, with tool steps shown as status lines such as "Searching your MATH103 lectures…".

**Citations.** The API also offers native citations on supplied documents. Phase 5 benchmarks it against the passage-ID approach in section 7 and keeps whichever validates more reliably on your golden set.

**Billing.** The Claude API is billed separately from your Pro subscription, on pay-as-you-go credits through the Claude Console ([Anthropic support](https://support.claude.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan)). Keep the key in the project's `.env` file and never export it in your shell: if `ANTHROPIC_API_KEY` is set in your environment, Claude Code bills that key instead of your Pro plan.

## 9. AI tool architecture and action permissions

Claude acts through a typed tool registry in which every tool declares a risk level. Destructive tools cannot delete anything: they create a request that only you can confirm, from the UI, in a separate authenticated request.

| Risk level | Runs | Example tools |
| --- | --- | --- |
| Read | Automatically | `search_materials`, `get_document_section`, `get_topic_performance`, `get_weak_topics`, `get_due_reviews`, `get_upcoming_exams`, `get_study_history`, `list_structure` |
| Draft | Automatically, shown as a preview card | `draft_material`, `draft_mock_exam`, `propose_topic_map` |
| Write | Automatically; versioned and undoable | `save_questions`, `save_flashcards`, `create_topic`, `assign_document`, `update_plan`, `create_material_version`, `log_study_session` |
| Destructive | Never directly — creates a pending action | `request_delete_material`, `request_delete_document`, `request_delete_topic`, `request_delete_flashcards` |

**Each tool** is a Pydantic input schema, a handler that calls ordinary services (so tools obey the same user scoping as the UI), a risk level and a preview flag. The registry generates the JSON schemas sent to Claude.

**The agent loop** alternates Claude turns and tool calls, capped by step count and token budget, and logs every call to `ai_interactions`.

**Deletion flow.**

1. Claude calls `request_delete_material(id)`.
2. The server creates a `pending_actions` row with a human-readable preview and a 10-minute expiry, and tells Claude "awaiting user confirmation".
3. The UI shows: "Delete 'Calculus Week 4 Revision Guide'? It has 3 versions and 12 linked flashcards."
4. Only `POST /pending-actions/{id}/confirm`, sent from your logged-in session with a CSRF token, executes it. No tool can call that endpoint.
5. The item moves to a 30-day trash, so even a confirmed mistake is recoverable.

**Preview before saving.** Revision guides, summaries, formula sheets and mock exams arrive as drafts with Save, Edit, Regenerate and Cancel. Daily-quiz questions and in-session flashcards save automatically, as your section 40 allows. Improving one of your own materials always creates a new version; your original is never overwritten.

**Prompt-injection defence.** Text inside uploaded files is data. Retrieved passages are wrapped and labelled as untrusted content. Because tools cannot delete or send data anywhere outside the app, a hostile instruction hidden in a PDF can at worst produce a bad answer — never data loss or leakage.

**Tutor mode.** A hint ladder is enforced by the server, not by trusting the prompt alone:

1. A guiding question ("Which method fits a product of two functions?")
2. A hint
3. A stronger hint
4. The next step worked through
5. The full solution

Each request includes only what the current level permits; the reference solution enters the prompt only at level 5. You move up a level by button. Practice questions unlock the full worked solution after you submit an attempt.

**Exam Mode.** While an exam attempt is open, the backend rejects chat, tutor and hint requests for your account until you submit. Hiding the buttons is not the safeguard; the server is. Marking afterwards still uses AI where needed.

## 10. Adaptive learning architecture

Four mechanisms work together: attempts and reviews are stored as facts; FSRS schedules memory; a transparent mastery score estimates topic strength; a priority score chooses what to practise next. Claude labels mistakes and writes explanations, but every number comes from a documented formula in `config/learning.yaml`.

The flow after each attempt: mark → classify the mistake → update mastery and difficulty → nightly profile snapshot → quiz selection and planner read the results.

### Marking

| Answer type | Marked by | Notes |
| --- | --- | --- |
| Multiple choice, true/false | Exact match | Deterministic |
| Numerical | Absolute or relative tolerance, units checked | Deterministic |
| Algebraic expression | SymPy: simplify the difference, plus numeric spot checks | Deterministic |
| Derivation, proof, explanation | Claude against a rubric: score per rubric point, feedback, confidence | Labelled AI-marked; dispute triggers re-marking with a stronger model, or you override |
| Handwritten working | Photo → vision transcription you confirm → the rows above | Matches how you work now |
| Code | Tests run in the browser | Deterministic |

Wrong answers get the five-part explanation from your section 25: why it is wrong, the correct answer, the reasoning, the identified mistake, and how to avoid it.

### Mistake bank

Claude assigns each error a category from a fixed taxonomy plus a one-line description. Your own errors this week show why categories beat a bare "incorrect":

| Category | Your example this week |
| --- | --- |
| Arithmetic or algebra slip | √36 carried as 36 in z² + 4z + 13 = 0 |
| Sign error | Multiplying by 4 − i instead of the conjugate 4 + i |
| Wrong tool or method | `linspace(0,1,5)` answered as if it were the colon range |
| Concept confusion | Loop accumulator and loop index merged into one variable |
| Incomplete justification | "Some truncation exceeds b" asserted without citing a = sup of the truncations |
| Instance instead of general claim | Q4 proved for 0.123123… rather than for general digits |
| Notation | −√−1 written instead of −i |

A pattern becomes "recurring" at three or more of one category in one topic within 30 days (configurable), with embedding similarity grouping near-identical descriptions. Recurring patterns are deliberately targeted by future quizzes.

### Topic strength

Each attempt i has score s in \[0, 1\] (partial credit allowed, reduced for hints used), a difficulty weight d (easy 0.6, medium 1.0, hard 1.4, exam 1.7) and an age in days. Older attempts fade with half-life h = 21 days:

```latex
w_i = d_i \cdot 2^{-\mathrm{age}_i / h}
```

Accuracy is smoothed towards a prior p₀ = 0.5 with weight α = 2, so one correct answer never reads as 100%:

```latex
\hat{p} = \frac{\sum_i w_i s_i + \alpha p_0}{\sum_i w_i + \alpha}
```

Where a topic has flashcards, their mean FSRS retrievability R̄ is blended in with λ = 0.7:

```latex
\text{strength} = \lambda \hat{p} + (1 - \lambda) \bar{R}
```

The UI shows it as an estimate with its evidence — "est. 72% · 14 attempts · last practised 6 days ago" — and flags "low data" while the total weight is under 5. Parent topics aggregate their children by weight.

### Difficulty adaptation

An Elo-style rating per topic (your ability θ) and per question (difficulty b) predicts success:

```latex
P(\text{correct}) = \frac{1}{1 + 10^{(b - \theta)/400}}
```

After each attempt, θ moves by K(s − P) and b moves the opposite way, so question labels recalibrate from real outcomes. Selection targets a predicted success of 0.65–0.80. Easy questions you always get right raise θ and pull harder ones in; repeated failure on hard ones drops θ and brings intermediate practice. When the bank lacks a question at the needed difficulty, Claude generates one grounded in your materials.

### Spaced repetition

Flashcards use FSRS at a target retention of 0.90; Again, Hard, Good and Easy map to ratings 1–4. Before an exam, due dates for its topics are capped so every card is seen at least once in the final fortnight. Questions are applications rather than memory items, so they are scheduled by the priority score below, not FSRS.

### Daily quiz selection

Each topic gets a priority from weakness, overdue time, exam urgency (weighting × decay with days to exam), recurring mistakes and coverage gaps:

```latex
\text{priority} = w_1 (1 - \text{strength}) + w_2\,\text{overdue} + w_3\,\text{urgency} + w_4\,\text{recurring} + w_5\,\text{gap}
```

Questions are allocated in proportion to priority with a floor per active module, so with no data yet the spread is even, as you asked. Modules interleave, formats and difficulties vary, and one or two questions target recurring mistakes. Quiz length comes from today's available time divided by your median time per question type, clamped to a sensible range. You submit the whole quiz before any marking.

### Learning profile

A weekly snapshot of measured statistics only: accuracy by question type, timed versus untimed accuracy, error-category rates, hint dependence, and the gap between flashcard recall and question application. Claude writes a short summary that must cite those numbers, with no personality claims. Generation prompts receive it as compact JSON — for example, "3 of the last 5 errors were sign errors; include sign-sensitive steps."

## 11. Revision planner architecture

The schedule is computed by a deterministic allocator; Claude turns your plain-English availability into structured rules and explains the plan, but never does the arithmetic. That keeps plans fast, repeatable, testable and free to regenerate.

**Inputs.**

- Exams: module, date, time, duration, location, weighting, topics covered, your confidence
- Availability: a weekly template plus date overrides. "3 hours every weekday, 1 hour at weekends" becomes rules through one Claude tool call, shown back to you to confirm.
- Preferences: session length, maximum sessions per day, rest days
- Live state: topic strength, due flashcards, recurring mistakes, unfinished sessions

**Allocation.**

1. Compute each topic's demand: exam weighting × (1 − strength) × a coverage factor, rising as the exam nears. Topics with no exam get light maintenance time.
2. Reserve daily time for due flashcards and the daily quiz.
3. Fill each day's available minutes greedily by demand, with at most one block per topic per day, the same topic at least two days apart until the final days, modules interleaved, and mock exams weighted into the final week.
4. Treat sessions you have moved or edited as locked constraints.
5. If demand exceeds capacity, say so instead of cramming: "14 hours of need, 9 available before MATH101. Lowest-priority topics left out: …"

**Rebalancing.** Completing or missing a session, finishing a quiz, adding an exam or changing availability triggers a replan; a full replan also runs nightly. Only future, unlocked sessions move. If greedy plans prove poor, the allocator interface allows swapping in OR-Tools CP-SAT.

**"I have 45 minutes."** A session builder fills the time from today's priority list, for example: 10 minutes of due flashcards, 25 minutes on the weakest topic, 10 minutes drilling a recurring mistake — each with its reason.

**Recommendations are explainable** because they expose the engine's actual factors: "Integration by Parts: est. 43%, 4 mistakes in 30 days, last practised 6 days ago, exam in 34 days." Claude phrases it; the numbers are real.

**Calendar.** Today, day, week and month views show sessions, exams, quizzes, flashcard reviews and deadlines, each planned, done, missed or skipped. Dragging a session locks it and rebalances the rest.

**Notifications.** A scheduler job creates them: quiz not done by your chosen time, exam at 14, 7 and 1 days, a topic untouched for N days, flashcards due. In-app always; browser push once deployed (section 18). Quiet hours and per-type toggles live in Settings.

## 12. Authentication and security architecture

A single-owner app built to multi-user standards: every row is scoped to a user, so a second account genuinely cannot see your data, and the access-control tests have something real to prove. Security baseline lands in Phases 2–3, not at the end.

| Area | Measures |
| --- | --- |
| Accounts | Argon2id password hashing; optional TOTP two-factor; passkeys later. Public sign-up disabled; the first account is created with `make create-user`. |
| Sessions | Random 256-bit token in an httpOnly, Secure, SameSite=Lax cookie; stored hashed; idle and absolute expiry; rotated at login; revocable. No tokens in localStorage. |
| CSRF | Double-submit token header required on every state-changing request |
| Access control | Repository methods require the current user; every ID from the client is ownership-checked, which prevents IDOR; a test iterates every route as a second user |
| Input | Pydantic validation and size limits on all input |
| Output | Markdown sanitised before render; strict Content-Security-Policy; HSTS, `X-Frame-Options: DENY`, `nosniff`, strict Referrer-Policy |
| File type | Magic-byte detection against an allow-list, and the extension must agree — a renamed executable is rejected |
| File structure | Size caps per type; Office files checked for zip bombs (entry count, expanded size) and macro formats (.docm, .xlsm, .pptm) rejected; PDFs parsed in the worker under time and memory limits; images re-encoded with a decompression-bomb limit, which also strips EXIF location from phone photos |
| Storage | Server-generated keys, private bucket, authenticated streaming, five-minute signed URLs at most |
| Secrets | Environment variables via pydantic-settings; `.env` git-ignored; `.env.example` with placeholders; gitleaks in pre-commit and CI; the Anthropic key never reaches the browser |
| Abuse limits | Redis rate limits on login, upload and AI routes; login back-off; the AI budget guard on top |
| Dependencies | pip-audit, npm audit and Dependabot in CI |
| Audit | Logins and destructive actions written to `audit_log` |

**Privacy of your materials.** Lecture files stay in your storage. Per question, only the retrieved passages and your question go to the Anthropic API; whole pages go only for one-off maths transcription. Check Anthropic's commercial terms for API data retention, and the University of Liverpool's guidance on putting course materials into third-party AI tools — lecture notes are the university's copyright, so the app stays private and has no public sharing feature.

## 13. Testing strategy

Every phase ships with its tests, and CI blocks a merge on any failure. No test calls the real Claude API except an opt-in evaluation suite with its own spending cap; everything else uses a scripted fake client, so tests are free, fast and deterministic.

| Layer | Tools | What it proves |
| --- | --- | --- |
| Unit | pytest | Mastery, Elo, priority and planner maths; FSRS wrapper; validators; the chunker never splits an equation, table or proof |
| Property-based | Hypothesis | Plans never exceed availability, never move locked sessions, give every exam topic time; strength stays in \[0, 1\] and rises with score |
| Database | pytest + Testcontainers (real Postgres with pgvector) | Migrations up and down, constraints, hybrid search SQL. SQLite cannot stand in: it has no pgvector |
| API | httpx AsyncClient | Contracts, error envelope, and an auto-generated check that every route rejects anonymous requests |
| Security | pytest | IDOR across every resource with two users; path-traversal filenames; a PDF renamed .png; zip bomb; macro file; oversized upload; missing CSRF; session fixation; rate limits |
| AI permissions | Fake Claude client | Destructive tools only create pending actions; no tool reaches the confirm endpoint; a PDF containing "delete everything" deletes nothing; Exam Mode blocks AI routes |
| RAG evaluation | Golden set from your real lectures: about 50 questions mapped to the right document and page | Recall@5 and MRR above agreed thresholds; 100% of citations point at passages actually supplied; re-run whenever chunking or embeddings change |
| AI content evaluation (opt-in, live) | Live API, capped budget | Generated questions are schema-valid; multiple choice has exactly one correct option; numeric answers recomputed in Python or SymPy; answers supported by their cited passages, judged by a second model; near-duplicate rate; labelled difficulty matches real outcomes |
| Adaptive behaviour | Simulated learner with known ability per topic | Quizzes shift towards the weak topic within a few sessions; strong topics appear less; FSRS intervals grow after Good; the planner moves time when strength changes |
| Frontend | Vitest + Testing Library | Maths rendering, forms, components |
| End-to-end | Playwright | Log in → upload → ask → cited answer → quiz → results, including one keyboard-only run |
| Accessibility | axe-core inside Playwright | No serious violations |
| Performance | k6 | Search and dashboard response targets on a seeded database (targets set in Phase 12) |

**CI pipeline** on GitHub Actions: Ruff and ESLint, mypy (strict on core packages) and tsc, the test suites above except the live evaluation, gitleaks, and dependency audits.

## 14. Development folder structure

One monorepo with backend, frontend, docs and infrastructure side by side, so one pull request can change an API and its client together.

```
revision-os/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/            # settings, security, logging, errors
│   │   ├── db/              # engine, session, base model
│   │   ├── models/          # SQLAlchemy models
│   │   ├── schemas/         # Pydantic request/response models
│   │   ├── repositories/    # user-scoped data access
│   │   ├── services/        # business rules per domain
│   │   ├── api/v1/          # routers
│   │   ├── ingestion/       # validators, extractors/, chunker, pipeline
│   │   ├── retrieval/       # embeddings/, vector_store/, hybrid, rerank, context
│   │   ├── ai/              # client, router, budget, prompts/, tools/, agent, marking
│   │   ├── learning/        # fsrs, mastery, elo, selection, mistakes, profile
│   │   ├── planner/         # demand, allocator, rebalance, session builder
│   │   ├── storage/         # base, local, s3
│   │   ├── notifications/
│   │   └── workers/         # Arq tasks and cron
│   ├── migrations/          # Alembic
│   ├── config/              # learning.yaml, ai.yaml
│   ├── tests/               # unit, integration, security, rag_eval, ai_eval
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── app/             # router, providers, layout, sidebar
│   │   ├── features/        # dashboard, modules, library, search, chat, quiz,
│   │   │                    # flashcards, exams, planner, calendar, analytics,
│   │   │                    # coding, settings
│   │   ├── components/      # ui primitives, MathMarkdown, PdfViewer
│   │   ├── lib/             # generated API client, hooks, utils
│   │   └── workers/         # pyodide, webr
│   ├── e2e/                 # Playwright
│   └── package.json
├── docs/
│   ├── architecture.md
│   ├── adr/                 # one file per architectural decision
│   ├── algorithms.md        # every formula from sections 10–11
│   ├── database.md, api.md, security.md, deployment.md
├── infra/                   # docker-compose.yml, Dockerfiles
├── .github/workflows/
├── .env.example
├── .gitignore
├── Makefile                 # make dev, test, migrate, create-user, eval
└── README.md
```

## 15. Development phases

Your 13-phase order holds, with three changes: the security baseline moves into Phases 2–3 instead of waiting for Phase 12; tests are written inside every phase; and Phase 5 ends with the first genuinely usable tool — upload a lecture, ask a question, get a cited answer. Every phase ends with the review loop from your section 74.

| Phase | Builds | Done when |
| --- | --- | --- |
| 1. Architecture and scaffold | Repo, Docker Compose (Postgres with pgvector, Redis), config loading, CI, first ADRs | `make dev` runs an empty app and CI is green |
| 2. Foundation | Auth, sessions, CSRF, user scoping, years, modules, topic tree, app shell, theming, settings skeleton | You log in, create MATH103 with a topic tree; IDOR tests pass |
| 3. Files | Upload, validation, storage, extraction, vision transcription, page viewer with corrections, progress stream | Your MATH103 and MATH111 PDFs process with equations intact |
| 4. Search and RAG | Chunking, embeddings, hybrid search, reranker, global search, golden evaluation set | Recall@5 meets the target on your golden set |
| 5. Claude core | Client, router, budget guard, usage dashboard, streamed chat with citations, read tools, pending actions | "Where did my lecturer explain the argument's quadrant rule?" returns the right page. First usable milestone |
| 6. Revision materials | Drafts with preview, versions and diff, flashcards, question generation with validation, mock exams, attempts, marking including photos | Generated questions pass validation; marking works for every answer type |
| 7. Adaptive learning | FSRS reviews, mastery, Elo difficulty, mistake bank, learning profile, daily quiz | Simulated-learner tests pass |
| 8. Planner | Exams, availability, allocator, rebalancing, calendar, session builder, recommendations, in-app notifications | Property tests pass; "I have 45 minutes" gives a sensible, explained session |
| 9. Analytics | Main and module dashboards, charts, exam readiness | Every number on screen traces to stored data |
| 10. Coding practice | Pyodide and WebR runners, exercises with tests, tutor hints | Python and R exercises run and mark in the browser |
| 11. Polish | Responsive layouts, PWA and push, command palette, shortcuts, accessibility pass | axe clean; usable on your phone |
| 12. Hardening | Security audit, full AI evaluations, performance tests | No high-severity findings; targets met |
| 13. Documentation and deployment | README, docs, deployment guide, export (JSON, CSV, Markdown, ZIP, Anki .apkg) and restore | A fresh clone runs from the README alone |

Phases 1–5 are roughly a third of the total work and already give you a cited, searchable knowledge base of your lectures. Data from Phase 6 attempts accumulates early, so the adaptive algorithms in Phase 7 have history to work on.

## 16. Potential technical risks

The two risks most likely to sink the project are unreliable maths extraction and never reaching a usable version. Both have mitigations built into the plan.

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Maths mangled during extraction | High | High | Damage scoring, vision transcription, per-page correction UI, golden pages from your own notes in tests |
| Scope: the project stalls before it is useful | High | High | Usable milestone at Phase 5; each phase leaves a working app |
| AI marks a proof or derivation wrongly | Medium | High | Deterministic marking wherever possible; rubrics; confidence shown; dispute and override; low-confidence marks count half in mastery |
| Generated questions with wrong answers | Medium | High | Numeric and symbolic answers recomputed; grounding check against sources; a flag button that retires the question |
| API spending creeps up | Medium | Medium | Budget guard, cheap model by default, caching, batches, no model calls in hot paths |
| Adaptive features have no data at first | High | Low | Priors, an even initial spread, "low data" labels |
| Mobile use and push notifications need hosting | Medium | Medium | Local-first build; deployment in Phase 13 (section 18) |
| Prompt injection through an uploaded document | Low | Medium | Tools structurally cannot delete or exfiltrate; passages treated as data |
| Lecture-material copyright and data handling | Low | Medium | Private use only, no public sharing; check Liverpool guidance and API data terms |
| Heavy optional dependencies (LibreOffice, Pandoc) | Medium | Low | Optional extras in the Docker image; the app degrades gracefully without them |
| Code tests run client-side, so answers are inspectable | Low | Low | Acceptable for a personal app; documented |

## 17. Estimated complexity of each component

The hardest parts are the ones where correctness is genuinely uncertain — maths extraction, question validation, marking and planning — not the volume of screens.

| Component | Complexity | Main difficulty |
| --- | --- | --- |
| Maths-aware extraction and vision transcription | High | Detecting damaged pages; faithful LaTeX; correction workflow |
| Question generation with validation | High | Proving answers correct, not just plausible |
| Marking (SymPy, rubric, photo) | High | Equivalence of expressions; reliable rubric scoring |
| Revision planner | High | Constraints, rebalancing, never overloading you |
| Testing and evaluation harness | High | Golden sets, simulated learner, live-eval budget |
| MATLAB execution (deferred) | High | Requires a hardened server sandbox |
| Hybrid search, reranking, chunking | Medium–High | Tuning against your real documents |
| Auth and security baseline | Medium | Many small things that must all be right |
| File upload, validation, storage | Medium | Hostile-file handling |
| Citations and provenance | Medium | Validation and page-accurate linking |
| Claude client, router, budget, usage | Medium | Accounting and graceful degradation |
| Tool registry and pending actions | Medium | Getting the permission model airtight |
| Streaming chat UI | Medium | SSE, tool status, citation rendering |
| Materials with versions and diff | Medium | Diff of Markdown with maths |
| Mastery, Elo, quiz selection | Medium | Tuning weights sensibly |
| Mistake bank and learning profile | Medium | Consistent categorisation |
| Calendar UI | Medium | Drag, lock, rebalance interplay |
| Analytics dashboards | Medium | Honest, traceable numbers |
| Coding practice (Pyodide, WebR) | Medium | Worker lifecycle, package loading |
| Notifications and PWA | Medium | Push setup; needs HTTPS hosting |
| Export and restore | Medium | Complete, re-importable archives |
| Module and topic system | Low | Tree ordering |
| FSRS flashcards | Low | Library does the scheduling |

Taken whole, this is a project measured in months of part-time work, not weeks, even with Claude Code writing most of the code. That is why Phase 5 is the milestone that matters.

## 18. Requirements needing clarification and default decisions

Four questions need your answer before Phase 1. Everything else below has a default I will build unless you object.

### Questions for you

- [ ] **API budget.** The Claude API is billed separately from Pro, pay-as-you-go. What monthly cap should the budget guard enforce? Default if you don't say: a low hard cap with a warning at 75%, raised by you in Settings.
- [ ] **Hosting.** Local-only on your laptop, or deployed? Phone access and push notifications need an HTTPS server (a small VPS or platform host, managed Postgres and an R2 bucket, typically a few pounds a month). Default: build local-first, deploy in Phase 13.
- [ ] **Module hierarchy.** Your example sidebar groups by subject (Mathematics, Finance, Statistics), but your real units are modules such as MATH101 and ACFI113. Default: Year → Module (with code) → Topic tree, with subject as an optional grouping tag.
- [ ] **Where we build.** This chat's sandbox resets between sessions and cannot run your database or push to your GitHub. Claude Code, included with your Pro plan, works directly in your repo, runs the tests each phase and commits. Default: build in Claude Code, using this doc as the spec.

### Contradictions resolved by default

| In the spec | Tension | Default |
| --- | --- | --- |
| "Claude should choose which model" (46) vs "easy to change" | Asking Claude to pick its own model adds a call, cost and unpredictability | A config-driven router by task type, with automatic escalation on low confidence |
| "Claude determines what the dashboard shows" (4) vs "fast" (59) | A model call on every page load is slow and costly | Widgets ranked by the recommendation engine; Claude's recommendation text cached a few times a day |
| Personal app (48) vs "no other user can access" | One user makes access control untestable | Multi-user-safe schema with registration closed |
| Large documents need a "high-context model" (46) | Retrieval removes most need for whole-document context | Whole-document analysis runs in page batches with caching |
| Exam Mode "no AI" vs "automatic marking" (36) | Marking may need AI | No AI assistance during the attempt; AI marking after submission |

### Other defaults

- Local embeddings; Voyage AI available as a switch.
- Handwritten answer photos accepted for marking, since you work on paper.
- Python and R run in the browser. MATLAB cannot: MATH111 exercises are reviewed by reading, not executing, until an optional sandboxed GNU Octave runner after Phase 13.
- Soft delete with a 30-day trash, on top of confirmations.
- Flashcards also export to Anki (.apkg).
- Term dates and the exam timetable are entered by you; there is no Canvas integration, because Liverpool's single sign-on blocks it.
- Academic integrity: assessed coursework gets tutor-mode hints and error-checking, never finished solutions; formative and practice work unlocks full solutions after an attempt.

Once you answer the four questions or accept the defaults, Phase 1 starts.
