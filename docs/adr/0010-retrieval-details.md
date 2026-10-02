# 10. Retrieval details

Date: 2026-10-02 · Status: Accepted (refines ARCHITECTURE.md sections 8 and 9)

## Decision

**Chunks never cross a page.** Each chunk belongs to exactly one page, so every
search hit and (from Phase 5) every citation links to a real page
(`/doc/<id>?page=n`). Within a page, text splits at structural boundaries
(headings, Theorem/Definition/Proof/Example labels, display maths, code
fences, tables) and then by size, with a short overlap carried across size
cuts. The heading path carries over from earlier pages, so a page that
continues a section still knows its section. Sizes are in
`config/retrieval.yaml` (`chunking`).

**Embeddings run locally.** fastembed with `BAAI/bge-small-en-v1.5`
(384 dimensions, ONNX on the CPU). There is no API cost and no lecture text
leaves the machine for indexing. Passages are embedded with a header
(module, file, heading path) in front of the text. Queries use the model's
own query instruction (`query_embed`). The model downloads once into
`data/models` (`MODEL_CACHE_DIR`) and the worker and API warm it on start.

**Hybrid search with weighted fusion.** Two candidate lists are fused with
reciprocal rank fusion (`rrf_k` 60), with keyword hits weighted at
`keyword_weight` 0.5:

- Keyword search uses Postgres full-text search: a generated `tsvector`
  (heading weight A, content weight B). The query is an OR of stemmed terms,
  because AND ranking missed paraphrased questions.
- Vector search uses an HNSW cosine index, with
  `hnsw.iterative_scan = relaxed_order` so filters by user and scope do not
  starve the result list. Vector-only hits below `min_vector_similarity`
  (0.55) are dropped, so nonsense queries return nothing rather than noise.

University material outranks your own notes slightly (`tier_weights`). Only
the best chunk per page is kept.

**Scope widening appends, never replaces.** A search scoped to a topic or
module that finds fewer than `widen_below` results adds results from the
next scope out (topic, then module, then year, then everything), after the
in-scope ones. The response says so (`widened`). Names (modules, topics,
files) are matched separately and shown above passages.

**No reranker for now.** A cross-encoder (`ms-marco-MiniLM-L-6-v2`) was
tried and made results slightly worse on maths lecture text while adding
latency. It stays in config (`rerank.enabled: false`) so it can be
re-evaluated.

**Indexing is part of ingestion** (stage `indexing`, 95%). If indexing fails,
the document is still usable, with `error_code = index_failed`, and
`make reindex` rebuilds it. A hand correction reindexes only that page.
Changing a document's topic or tier updates its chunks in place.

## Evidence

The golden set has 62 paraphrased questions over the MATH101 materials.
They live in `samples/golden.yaml`, which is git-ignored. `make eval-search`
measures them.

Offline comparison (413 chunks):

| Method | Recall@5 | MRR |
|---|---|---|
| BM25 alone | 0.85 | 0.65 |
| bge-small vectors | 0.90 | 0.79 |
| bge-base vectors | 0.92 | 0.79 |
| Equal-weight hybrid | 0.89 | 0.74 |
| Hybrid + MiniLM reranker | 0.89 | 0.72 |

bge-base costs twice the memory and time for little gain. A keyword weight
of 0.5 scores the same as vectors alone (0.90/0.77 against 0.90/0.79), but
keeps exact terms such as "Leibniz rule" findable.

The live system scores **Recall@5 0.87 and MRR 0.78**, against targets of
0.85 and 0.70.

## Consequences

- Changing the embedding model means changing `EMBEDDING_DIMENSIONS`, adding
  a migration, and running `make reindex`.
- The worker needs about 300 MB more memory for the model; its 2 GB limit
  covers this.
