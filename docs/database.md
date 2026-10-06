# Database

PostgreSQL 16 with pgvector. Generated from the models by
`make db-docs` (`backend/scripts/database_doc.py`); do not edit by hand. The
reasoning is in ARCHITECTURE.md section 5 and the ADRs.

Conventions:

- **Every user's data carries `user_id`**, and every query is scoped by it.
  Where a row points at another user-owned row, the foreign key includes
  `user_id` too (`(module_id, user_id) -> modules (id, user_id)`), so the
  database itself refuses a link between two users' data.
- **Ids** are random UUIDs, except a few append-only logs, which are numbered.
- **Times** are `timestamp with time zone`, stored in UTC.
- **Soft delete:** `deleted_at` set means the item is in the trash; the
  scheduler removes it for good after 30 days.
- **Embeddings** are `vector` columns with the model that made them recorded
  alongside, so changing model is a re-index (`make reindex`), not a migration.
- **Exported** marks the tables a data export carries (Settings > Your data;
  `app/export/tables.py`).


## Accounts and settings

### `audit_log`

Append-only record of logins and destructive actions.

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | bigint |  |  |
| `user_id` | uuid | yes | users.id |
| `action` | varchar(64) |  |  |
| `target_type` | varchar(64) | yes |  |
| `target_id` | uuid | yes |  |
| `ip` | varchar(45) | yes |  |
| `user_agent` | varchar(512) | yes |  |
| `details` | jsonb | yes |  |
| `created_at` | timestamp with time zone |  |  |

### `auth_sessions`

A login session. Only SHA-256 hashes of the tokens are stored.

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | users.id |
| `token_hash` | bytea |  |  |
| `csrf_token_hash` | bytea |  |  |
| `created_at` | timestamp with time zone |  |  |
| `last_seen_at` | timestamp with time zone |  |  |
| `expires_at` | timestamp with time zone |  |  |
| `revoked_at` | timestamp with time zone | yes |  |
| `ip` | varchar(45) | yes |  |
| `user_agent` | varchar(512) | yes |  |

### `user_settings` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `user_id` (key) | uuid |  | users.id |
| `theme` | enum: light, dark, system |  |  |
| `accent_colour` | varchar(7) |  |  |
| `session_minutes` | smallint | yes |  |
| `max_sessions_per_day` | smallint | yes |  |
| `rest_weekdays` | smallint[] |  |  |
| `notify_exams` | boolean |  |  |
| `notify_quiz` | boolean |  |  |
| `notify_neglected` | boolean |  |  |
| `notify_flashcards` | boolean |  |  |
| `quiz_reminder_hour` | smallint | yes |  |
| `quiet_from` | smallint | yes |  |
| `quiet_to` | smallint | yes |  |
| `updated_at` | timestamp with time zone |  |  |

### `users`

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `email` | varchar(320) |  |  |
| `display_name` | varchar(80) |  |  |
| `password_hash` | text |  |  |
| `created_at` | timestamp with time zone |  |  |
| `updated_at` | timestamp with time zone |  |  |

## Years, modules and topics

### `academic_years` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | users.id |
| `label` | varchar(40) |  |  |
| `start_date` | date |  |  |
| `end_date` | date |  |  |
| `is_current` | boolean |  |  |
| `created_at` | timestamp with time zone |  |  |
| `updated_at` | timestamp with time zone |  |  |

### `modules` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | academic_years.user_id, users.id |
| `academic_year_id` | uuid |  | academic_years.id |
| `code` | varchar(20) |  |  |
| `title` | varchar(200) |  |  |
| `subject_tag` | varchar(60) | yes |  |
| `credits` | smallint | yes |  |
| `colour` | varchar(7) | yes |  |
| `status` | enum: active, archived |  |  |
| `deleted_at` | timestamp with time zone | yes |  |
| `created_at` | timestamp with time zone |  |  |
| `updated_at` | timestamp with time zone |  |  |

### `topics` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | modules.user_id, users.id |
| `module_id` | uuid |  | modules.id, topics.module_id |
| `parent_id` | uuid | yes | topics.id |
| `title` | varchar(200) |  |  |
| `position` | smallint |  |  |
| `importance` | smallint |  |  |
| `deleted_at` | timestamp with time zone | yes |  |
| `created_at` | timestamp with time zone |  |  |
| `updated_at` | timestamp with time zone |  |  |

## Uploaded documents

### `document_pages` · exported

One page, slide, sheet or section as Markdown with LaTeX maths.

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `document_id` (key) | uuid |  | documents.id |
| `page_no` (key) | smallint |  |  |
| `markdown` | text |  |  |
| `extraction_method` | enum: text, vision, corrected, unreadable |  |  |
| `maths_damage_score` | float |  |  |
| `needs_review` | boolean |  |  |
| `review_note` | varchar(300) | yes |  |
| `created_at` | timestamp with time zone |  |  |
| `updated_at` | timestamp with time zone |  |  |

### `documents` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | modules.user_id, users.id |
| `module_id` | uuid |  | modules.id, topics.module_id |
| `topic_id` | uuid | yes | topics.id |
| `original_filename` | varchar(255) |  |  |
| `storage_key` | varchar(255) |  |  |
| `mime` | varchar(100) |  |  |
| `size_bytes` | bigint |  |  |
| `sha256` | bytea |  |  |
| `source_tier` | enum: university, own |  |  |
| `material_kind` | enum: lecture, problem_sheet, solutions, past_paper, notes, other |  |  |
| `week` | smallint | yes |  |
| `status` | enum: queued, processing, ready, failed |  |  |
| `stage` | varchar(40) |  |  |
| `progress` | smallint |  |  |
| `error_code` | varchar(64) | yes |  |
| `page_count` | smallint | yes |  |
| `deleted_at` | timestamp with time zone | yes |  |
| `created_at` | timestamp with time zone |  |  |
| `updated_at` | timestamp with time zone |  |  |

## Search

### `chunks` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | documents.user_id, users.id |
| `document_id` | uuid |  | documents.id |
| `module_id` | uuid |  | modules.id |
| `topic_id` | uuid | yes | topics.id |
| `source_tier` | enum: university, own |  |  |
| `page_no` | smallint |  |  |
| `position` | smallint |  |  |
| `heading_path` | text |  |  |
| `content` | text |  |  |
| `token_estimate` | integer |  |  |
| `embedding` | vector(384) |  |  |
| `embedding_model` | varchar(100) |  |  |
| `tsv` | tsvector |  |  |
| `created_at` | timestamp with time zone |  |  |

## Claude usage

### `ai_interactions` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | users.id |
| `feature` | varchar(64) |  |  |
| `requested_model` | varchar(100) |  |  |
| `served_model` | varchar(100) | yes |  |
| `effort` | varchar(10) | yes |  |
| `prompt_version` | varchar(64) |  |  |
| `status` | enum: ok, refused, error, budget_blocked |  |  |
| `stop_reason` | varchar(32) | yes |  |
| `error_code` | varchar(64) | yes |  |
| `latency_ms` | integer | yes |  |
| `request_id` | varchar(100) | yes |  |
| `document_id` | uuid | yes | documents.id |
| `tool_calls` | jsonb | yes |  |
| `created_at` | timestamp with time zone |  |  |

### `ai_usage` · exported

Tokens and estimated cost of one call. Append-only; budgets sum it.

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | bigint |  |  |
| `user_id` | uuid |  | users.id |
| `interaction_id` | uuid |  | ai_interactions.id |
| `feature` | varchar(64) |  |  |
| `model` | varchar(100) |  |  |
| `module_id` | uuid | yes | modules.id |
| `input_tokens` | integer |  |  |
| `output_tokens` | integer |  |  |
| `cache_write_tokens` | integer |  |  |
| `cache_read_tokens` | integer |  |  |
| `estimated_cost_usd` | float |  |  |
| `created_at` | timestamp with time zone |  |  |

## The assistant

### `conversations` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | users.id |
| `title` | varchar(200) |  |  |
| `module_id` | uuid | yes | modules.id |
| `topic_id` | uuid | yes | topics.id |
| `created_at` | timestamp with time zone |  |  |
| `updated_at` | timestamp with time zone |  |  |

### `messages` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `conversation_id` | uuid |  | conversations.id |
| `user_id` | uuid |  | users.id |
| `role` | enum: user, assistant |  |  |
| `content` | text |  |  |
| `citations` | jsonb |  |  |
| `provenance` | jsonb |  |  |
| `steps` | jsonb |  |  |
| `links` | jsonb |  |  |
| `status` | enum: complete, stopped, error |  |  |
| `error_code` | varchar(64) | yes |  |
| `created_at` | timestamp with time zone |  |  |

### `pending_actions`

A destructive request from Claude. Nothing happens until you confirm it yourself (POST /pending-actions/{id}/confirm); no tool can do that.

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | users.id |
| `conversation_id` | uuid | yes | conversations.id |
| `message_id` | uuid | yes |  |
| `action` | enum: delete_document, delete_topic, delete_module |  |  |
| `target_id` | uuid |  |  |
| `preview` | text |  |  |
| `status` | enum: pending, confirmed, cancelled, expired |  |  |
| `expires_at` | timestamp with time zone |  |  |
| `resolved_at` | timestamp with time zone | yes |  |
| `created_at` | timestamp with time zone |  |  |

## Materials, questions, flashcards and quizzes

### `drafts` · exported

Generated content awaiting Save, Edit, Regenerate or Cancel (SPEC 40). Kept until you decide, so nothing generated is lost.

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | modules.user_id, users.id |
| `module_id` | uuid |  | modules.id, topics.module_id |
| `topic_id` | uuid | yes | topics.id |
| `kind` | enum: material, questions, flashcards, coding |  |  |
| `request` | jsonb |  |  |
| `status` | enum: generating, ready, failed, saved, discarded |  |  |
| `payload` | jsonb | yes |  |
| `error_code` | varchar(64) | yes |  |
| `ai_interaction_id` | uuid | yes | ai_interactions.id |
| `created_at` | timestamp with time zone |  |  |
| `updated_at` | timestamp with time zone |  |  |

### `flashcards` · exported

A card and its FSRS scheduling state (ARCHITECTURE.md section 10).

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | modules.user_id, users.id |
| `module_id` | uuid |  | modules.id, topics.module_id |
| `topic_id` | uuid | yes | topics.id |
| `front_md` | text |  |  |
| `back_md` | text |  |  |
| `origin` | enum: user, claude |  |  |
| `sources` | jsonb |  |  |
| `embedding` | vector(384) | yes |  |
| `fsrs_state` | smallint |  |  |
| `fsrs_step` | smallint | yes |  |
| `stability` | float | yes |  |
| `fsrs_difficulty` | float | yes |  |
| `due` | timestamp with time zone |  |  |
| `last_review` | timestamp with time zone | yes |  |
| `reps` | integer |  |  |
| `lapses` | integer |  |  |
| `deleted_at` | timestamp with time zone | yes |  |
| `created_at` | timestamp with time zone |  |  |
| `updated_at` | timestamp with time zone |  |  |

### `material_versions` · exported

Versions are never edited: a change is a new version (SPEC 19-20).

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `material_id` | uuid |  | materials.id |
| `user_id` | uuid |  | materials.user_id, users.id |
| `version_no` | integer |  |  |
| `content_md` | text |  |  |
| `citations` | jsonb |  |  |
| `created_by` | enum: user, claude |  |  |
| `change_note` | varchar(300) | yes |  |
| `ai_interaction_id` | uuid | yes | ai_interactions.id |
| `created_at` | timestamp with time zone |  |  |

### `materials` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | modules.user_id, users.id |
| `module_id` | uuid |  | modules.id, topics.module_id |
| `topic_id` | uuid | yes | topics.id |
| `title` | varchar(200) |  |  |
| `kind` | enum: guide, summary, formula_sheet, worked_examples, definitions, explanation, concept_map, notes |  |  |
| `origin` | enum: user, claude |  |  |
| `current_version_id` | uuid | yes |  |
| `deleted_at` | timestamp with time zone | yes |  |
| `created_at` | timestamp with time zone |  |  |
| `updated_at` | timestamp with time zone |  |  |

### `question_attempts` · exported

One answer to one question in one quiz attempt.

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | questions.user_id, quiz_attempts.user_id, users.id |
| `quiz_attempt_id` | uuid |  | quiz_attempts.id |
| `question_id` | uuid |  | questions.id |
| `response` | jsonb | yes |  |
| `response_image_key` | varchar(255) | yes |  |
| `time_ms` | integer | yes |  |
| `self_confidence` | smallint | yes |  |
| `hints_used` | smallint |  |  |
| `score` | float | yes |  |
| `marked_by` | enum: rule, sympy, ai, override | yes |  |
| `marking_confidence` | enum: high, medium, low | yes |  |
| `feedback` | jsonb | yes |  |
| `mistake_category` | varchar(64) | yes |  |
| `original_score` | float | yes |  |
| `created_at` | timestamp with time zone |  |  |
| `marked_at` | timestamp with time zone | yes |  |

### `questions` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | modules.user_id, users.id |
| `module_id` | uuid |  | modules.id, topics.module_id |
| `topic_id` | uuid | yes | topics.id |
| `type` | enum: multiple_choice, true_false, numerical, expression, short_answer, explanation, derivation |  |  |
| `difficulty` | enum: easy, medium, hard, exam |  |  |
| `rating` | float |  |  |
| `stem_md` | text |  |  |
| `answer_spec` | jsonb |  |  |
| `solution_md` | text |  |  |
| `origin` | enum: user, claude |  |  |
| `status` | enum: active, retired |  |  |
| `sources` | jsonb |  |  |
| `embedding` | vector(384) | yes |  |
| `created_at` | timestamp with time zone |  |  |

### `quiz_attempts` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | quizzes.user_id, users.id |
| `quiz_id` | uuid |  | quizzes.id |
| `mode` | enum: normal, exam |  |  |
| `status` | enum: in_progress, marking, marked |  |  |
| `started_at` | timestamp with time zone |  |  |
| `deadline` | timestamp with time zone | yes |  |
| `submitted_at` | timestamp with time zone | yes |  |
| `marked_at` | timestamp with time zone | yes |  |
| `score` | float | yes |  |

### `quiz_items` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `quiz_id` (key) | uuid |  | quizzes.id |
| `position` (key) | smallint |  |  |
| `user_id` | uuid |  | questions.user_id, quizzes.user_id, users.id |
| `question_id` | uuid |  | questions.id |

### `quizzes` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | modules.user_id, users.id |
| `module_id` | uuid | yes | modules.id |
| `kind` | enum: practice, mock, daily |  |  |
| `title` | varchar(200) |  |  |
| `time_limit_minutes` | smallint | yes |  |
| `config` | jsonb |  |  |
| `created_at` | timestamp with time zone |  |  |

## Adaptive learning

### `flashcard_reviews` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | bigint |  |  |
| `user_id` | uuid |  | flashcards.user_id, users.id |
| `flashcard_id` | uuid |  | flashcards.id |
| `rating` | smallint |  |  |
| `reviewed_at` | timestamp with time zone |  |  |
| `state_before` | smallint |  |  |
| `elapsed_days` | float | yes |  |
| `stability` | float | yes |  |
| `difficulty` | float | yes |  |
| `scheduled_days` | float |  |  |
| `duration_ms` | integer | yes |  |

### `learning_profile_snapshots` · exported

Weekly measured statistics, with Claude's short summary of them.

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | bigint |  |  |
| `user_id` | uuid |  | users.id |
| `week_start` | date |  |  |
| `metrics` | jsonb |  |  |
| `summary_md` | text | yes |  |
| `ai_interaction_id` | uuid | yes | ai_interactions.id |
| `computed_at` | timestamp with time zone |  |  |

### `topic_mastery` · exported

Derived per topic (or per module, for questions with no topic): recomputed from attempts and reviews after each change.

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | bigint |  |  |
| `user_id` | uuid |  | users.id |
| `module_id` | uuid |  | modules.id |
| `topic_id` | uuid | yes | topics.id |
| `strength` | float |  |  |
| `accuracy` | float |  |  |
| `retrievability` | float | yes |  |
| `weight` | float |  |  |
| `attempts` | integer |  |  |
| `ability` | float |  |  |
| `last_practised_at` | timestamp with time zone | yes |  |
| `computed_at` | timestamp with time zone |  |  |

## Planner and notifications

### `availability_overrides` · exported

A specific date's minutes, replacing its weekday's ("2 hours today").

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `user_id` (key) | uuid |  | users.id |
| `day` (key) | date |  |  |
| `minutes` | smallint |  |  |
| `note` | varchar(200) | yes |  |

### `availability_rules` · exported

Minutes available on each weekday (0 Monday ... 6 Sunday).

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `user_id` (key) | uuid |  | users.id |
| `weekday` (key) | smallint |  |  |
| `minutes` | smallint |  |  |

### `exam_topics` · exported

Topics an exam covers (none listed: the whole module).

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `exam_id` (key) | uuid |  | exams.id |
| `topic_id` (key) | uuid |  | topics.id |
| `module_id` | uuid |  | exams.module_id, topics.module_id |

### `exams` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | modules.user_id, users.id |
| `module_id` | uuid |  | modules.id |
| `title` | varchar(200) |  |  |
| `starts_at` | timestamp with time zone |  |  |
| `duration_minutes` | smallint |  |  |
| `location` | varchar(200) | yes |  |
| `weighting` | smallint | yes |  |
| `confidence` | smallint | yes |  |
| `notes` | text | yes |  |
| `created_at` | timestamp with time zone |  |  |
| `updated_at` | timestamp with time zone |  |  |

### `notifications` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | bigint |  |  |
| `user_id` | uuid |  | users.id |
| `kind` | varchar(32) |  |  |
| `title` | varchar(200) |  |  |
| `body` | text |  |  |
| `link` | varchar(300) | yes |  |
| `dedupe_key` | varchar(200) |  |  |
| `read_at` | timestamp with time zone | yes |  |
| `pushed_at` | timestamp with time zone | yes |  |
| `created_at` | timestamp with time zone |  |  |
| `updated_at` | timestamp with time zone |  |  |

### `push_subscriptions`

A browser or phone that receives Web Push for you (Phase 11).

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | users.id |
| `endpoint` | text |  |  |
| `p256dh` | varchar(200) |  |  |
| `auth` | varchar(100) |  |  |
| `label` | varchar(100) | yes |  |
| `failures` | smallint |  |  |
| `last_sent_at` | timestamp with time zone | yes |  |
| `created_at` | timestamp with time zone |  |  |

### `revision_plans` · exported

One computation of the plan; the newest is current.

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | users.id |
| `generated_at` | timestamp with time zone |  |  |
| `params` | jsonb |  |  |
| `shortfalls` | jsonb |  |  |

### `study_sessions` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | modules.user_id, users.id |
| `plan_id` | uuid | yes | revision_plans.id |
| `module_id` | uuid |  | modules.id, topics.module_id |
| `topic_id` | uuid | yes | topics.id |
| `exam_id` | uuid | yes | exams.id |
| `kind` | enum: topic, mock_exam |  |  |
| `day` | date |  |  |
| `minutes` | smallint |  |  |
| `status` | enum: planned, done, missed, skipped |  |  |
| `locked` | boolean |  |  |
| `actual_minutes` | smallint | yes |  |
| `completed_at` | timestamp with time zone | yes |  |
| `reason` | text |  |  |
| `created_at` | timestamp with time zone |  |  |

## Coding practice

### `coding_exercises` · exported

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | modules.user_id, users.id |
| `module_id` | uuid |  | modules.id, topics.module_id |
| `topic_id` | uuid | yes | topics.id |
| `language` | enum: python, r |  |  |
| `title` | varchar(200) |  |  |
| `prompt_md` | text |  |  |
| `starter_code` | text |  |  |
| `solution_code` | text |  |  |
| `tests` | jsonb |  |  |
| `packages` | jsonb |  |  |
| `difficulty` | enum: easy, medium, hard, exam |  |  |
| `origin` | enum: user, claude |  |  |
| `assessed` | boolean |  |  |
| `sources` | jsonb |  |  |
| `deleted_at` | timestamp with time zone | yes |  |
| `created_at` | timestamp with time zone |  |  |
| `updated_at` | timestamp with time zone |  |  |

### `coding_submissions` · exported

One "Submit": your code and the test results your browser reported.

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | coding_exercises.user_id, users.id |
| `exercise_id` | uuid |  | coding_exercises.id |
| `code` | text |  |  |
| `results` | jsonb |  |  |
| `passed` | smallint |  |  |
| `total` | smallint |  |  |
| `error` | text | yes |  |
| `runtime_ms` | integer | yes |  |
| `created_at` | timestamp with time zone |  |  |

### `tutor_hints` · exported

A rung of the hint ladder, for a coding exercise or an answer in a practice quiz. The server decides which rung comes next.

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | bigint |  |  |
| `user_id` | uuid |  | coding_exercises.user_id, question_attempts.user_id, users.id |
| `exercise_id` | uuid | yes | coding_exercises.id |
| `question_attempt_id` | uuid | yes | question_attempts.id |
| `level` | smallint |  |  |
| `content_md` | text |  |  |
| `ai_interaction_id` | uuid | yes | ai_interactions.id |
| `created_at` | timestamp with time zone |  |  |

## Exports and restores

### `data_jobs`

One export (building a ZIP) or restore (reading one back).

| Column | Type | Null | References |
| --- | --- | --- | --- |
| `id` (key) | uuid |  |  |
| `user_id` | uuid |  | users.id |
| `kind` | enum: export, restore |  |  |
| `status` | enum: queued, running, done, failed |  |  |
| `storage_key` | varchar(200) | yes |  |
| `size_bytes` | bigint | yes |  |
| `counts` | jsonb | yes |  |
| `error_code` | varchar(64) | yes |  |
| `error_message` | varchar(500) | yes |  |
| `created_at` | timestamp with time zone |  |  |
| `finished_at` | timestamp with time zone | yes |  |
