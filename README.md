# Player Support Copilot

AI support assistant for an online game (**Rainbow Six Siege**): answers player questions from a
knowledge base with citations (RAG), checks the player's account through tools (agent), and
moderates toxic chat messages (ML classifier). Built as a portfolio project for an
AI Engineer role in game online services.

> Status: **stage 1 of 6 — data & ingest.** Next: RAG with hybrid search.

| Stage | Scope | Status |
| --- | --- | --- |
| 1. Data | Wiki ingest, cleaning, near-dup detection, incremental re-index, EDA, CI | ✅ |
| 2. RAG | 3 chunking strategies, pgvector + BM25 + RRF + reranker, cited answers, SSE | ⏳ |
| 3. Evaluation | golden set, recall@5 / MRR / faithfulness, LLM-as-a-judge, Langfuse | ⏳ |
| 4. Agent | Account API tools via MCP, router, human-in-the-loop for risky actions, guardrails | ⏳ |
| 5. ML | toxicity: TF-IDF+LR → DistilBERT fine-tune → LoRA → zero-shot LLM | ⏳ |
| 6. LLMOps | eval quality gate in CI, MLflow, serving, cloud deploy | ⏳ |

## Quick start

Requirements: Python 3.12 (installed automatically by [uv](https://docs.astral.sh/uv/)),
PostgreSQL 16.

```bash
uv sync                                   # deps + dev tools
cp .env.example .env                      # set DATABASE_URL
uv run alembic upgrade head               # schema
uv run copilot ingest --limit 10          # 10 pages per category, ~45 s
uv run copilot ingest                     # everything (~420 pages, ~6 min); re-runs take seconds
uv run copilot stats
uv run uvicorn copilot.api.main:app --reload   # http://localhost:8000/docs
```

Checks (same as CI):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests
uv run pytest --cov                       # integration tests use a throwaway schema in DATABASE_URL
```

EDA: `uv sync --group eda && uv run --group eda jupyter lab notebooks/01_eda.ipynb`

## Stage 1 — data pipeline

```
MediaWiki API ──list (revid)──► changed revision? ──no──► skip (no download)
                                     │yes
                                     ▼
                     parse HTML ─► clean → Markdown ─► sha256 same? ──yes──► unchanged
                                                          │no
                                                          ▼
                         length / language filter ─► MinHash LSH near-dup ─► upsert documents
```

- **Source:** [Rainbow Six Wiki](https://rainbowsix.fandom.com) via the MediaWiki API, CC BY-SA 3.0
  (license and attribution stored per document). Categories: patch notes, operators, maps,
  weapons, gadgets, playlists, guides. Polite client: throttling, retries with backoff on
  429/5xx only, no retries on 4xx.
- **Cleaning:** HTML → Markdown that keeps the heading hierarchy (stage 2 chunks by structure).
  Removes infoboxes, navboxes, galleries, TOC, edit links, references, disambiguation hatnotes
  and patch navigation bars; flattens Fandom's table-based quotes into plain quotes.
- **Filters:** min 200 chars, English only (`langdetect`, seeded for determinism).
- **Near-duplicates:** MinHash (128 permutations) over 5-word shingles, LSH lookup, candidate
  confirmed by estimated Jaccard ≥ 0.85. Exact duplicates are covered by the same check.
- **Incremental re-index, two levels:** (1) one cheap listing call returns each page's latest
  revision id — unchanged pages are not downloaded at all; (2) a new revision whose cleaned text
  hash is the same (e.g. a category edit) is `unchanged`. Stage 2 will re-chunk only documents
  whose `content_hash` differs from the hash stored on their chunks.
- **Patch version** (`5.1.0`, `Y9S3.2`) is extracted into its own indexed column for
  freshness filtering in RAG.

<!-- EDA:START -->
<!-- EDA:END -->

### API

| Method | Path | |
| --- | --- | --- |
| `GET` | `/health` | DB connectivity |
| `POST` | `/ingest` | starts a background run: `{"categories": ["patch"], "limit_per_source": 20, "force": false}` → `202` + run |
| `GET` | `/ingest/runs/{id}` | status and per-category stats |

## Decisions and trade-offs

- **PostgreSQL only, no MongoDB.** Raw documents fit a table with a `JSONB` metadata column; the
  same database will hold pgvector embeddings and BM25 data in stage 2. One fewer service to run,
  back up and deploy; transactions span documents and chunks.
- **GitHub Actions now, GitLab CI later.** The pipeline (lint → tests on a real Postgres → later
  eval gate and deploy) is CI-agnostic; a `.gitlab-ci.yml` mirror is planned for stage 6.
- **Sync pipeline.** The wiki API is the bottleneck and must be throttled anyway, so async would
  add complexity without speed-up. The API runs ingest as a background task.
- **MinHash instead of exact hashing only.** Fandom has near-identical pages (game variants,
  renamed pages); exact hashes miss them.
- **Integration tests on real PostgreSQL** in an isolated, auto-dropped schema — no SQLite
  substitute, because JSONB and later pgvector behave differently.

## How I used AI in development

Development is done with an AI coding assistant (Claude Code). An example where it got things
wrong: the first version of the hatnote filter ("For similarly named pages, see …") matched
the page's *root* `<div>`, whose text also starts with that phrase, and deleted the whole
article — the operator page *Fuze* came out empty and was silently marked `too_short`.
It was caught by inspecting real ingested documents, not by unit tests (the test HTML had no
wrapper). Fix: only drop short nodes without content blocks, plus a regression test with the
real page structure.

## License

Code: MIT. Wiki content: CC BY-SA 3.0, © Rainbow Six Wiki contributors.
Jigsaw dataset: CC BY-SA 3.0.
