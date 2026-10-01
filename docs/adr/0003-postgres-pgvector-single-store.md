# 3. PostgreSQL 16 + pgvector as the single data store

Date: 2026-10-01 · Status: Accepted (ARCHITECTURE.md sections 1, 5, 7)

## Context

The schema is heavily relational, and retrieval needs both semantic (vector)
and keyword search over the same chunks, filtered by the same metadata.

## Decision

PostgreSQL 16 with the pgvector extension (HNSW) and built-in full-text
search. Migrations via Alembic; the first migration enables `vector`.
Database tests run against real Postgres (Testcontainers locally and in CI, or
`TEST_DATABASE_URL`) — never SQLite, which has no pgvector. CI fails if
database tests are skipped.

## Consequences

One service to run and back up; hybrid search in one query and one
transaction. The `VectorStore` interface (Phase 4) keeps a move to a
dedicated vector database possible.
