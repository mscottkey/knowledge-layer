# KnowledgeLayer

AI-native knowledge graph platform that ingests signals from support tools (tickets, Slack, PRs, call transcripts, docs), processes them through an NLP pipeline, detects conflicts with existing knowledge, synthesizes updated articles, scores confidence, and serves context to downstream AI agents via a retrieval API.

## Tech Stack

| Layer | Technology |
|-------|------------|
| API | Python 3.12, FastAPI, uvicorn |
| Graph Store | Neo4j Aura |
| Vector + Ops DB | Supabase (PostgreSQL + pgvector) |
| Embeddings | Gemini (text-embedding-004) |
| Synthesis | Gemini (gemini-2.5-flash) |
| NER | spaCy en_core_web_trf |
| Job Queue | Redis (acknowledged queue with retries) |
| Frontend | Next.js 14, Tailwind CSS |

## Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd knowledgelayer
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

- **Neo4j Aura**: Get URI and credentials from [Neo4j Aura Console](https://console.neo4j.io)
- **Supabase**: Get URL and key from [Supabase Dashboard](https://supabase.com/dashboard/project/_/settings/api)
- **Gemini**: Get API key from [Google AI Studio](https://aistudio.google.com/apikey)

For local development without cloud services, set `USE_MOCKS=true`. Mocked stores run without authentication; with real stores an API key is required (see below).

### 3. Install Python dependencies (requires [Poetry](https://python-poetry.org))

```bash
poetry install
```

### 4. Download spaCy model (optional, for production NER)

```bash
python -m spacy download en_core_web_trf
```

Skip this step if using `USE_MOCKS=true` (keyword fallback extractor will be used).

### 5. Run database migrations

Apply the Supabase migrations to create the tenant, embeddings, audit and API key tables:

```bash
# Option A: Using Supabase CLI
supabase db push

# Option B: Run SQL directly in Supabase Dashboard → SQL Editor
# Copy contents of supabase/migrations/20240101000000_tenant_infrastructure.sql
```

### 6. Start Redis

```bash
docker compose up -d
```

### 7. Run the API server and the worker

```bash
uvicorn api.main:app --reload     # the API, on http://localhost:8000
python -m worker.consumer         # the worker, in a second terminal
```

The API only accepts signals. `POST /ingest/ticket` and the other `/ingest/*` endpoints put them
on a Redis queue and return `202`. The worker takes each one off the queue, extracts entities,
embeds it, drafts or updates an article and decides whether to publish it or send it to review.
Signals that fail are retried up to three times, then moved to a failed list in Redis
(`knowledgelayer:signals:failed`). If a worker crashed mid-signal, start one worker with
`python -m worker.consumer --recover` to put the orphaned signals back on the queue.

### 8. Create an API key

Every request needs a key tied to one tenant. The tenant comes from the key, so a key cannot read
or write another tenant's knowledge.

```bash
python -m scripts.create_api_key --tenant acme --name "support bot" --scopes read write
python -m scripts.create_api_key --tenant acme --name "review console" --scopes review
```

Scopes: `read` (retrieve context), `write` (ingest signals), `review` (approve, edit, reject),
`admin` (all of them). The key is shown once and stored only as a hash. Tenants are UUIDs; the
script creates the tenant if you give it a name.

## API Endpoints

Send the key in the `X-API-Key` header. Without `AUTH_REQUIRED=true` and with mocked stores
(`USE_MOCKS=true`), you can instead identify a tenant with `X-Tenant-ID: <uuid>` for local work.

```bash
export KL_KEY=kl_live_...
```

### Health Check

```bash
curl http://localhost:8000/health
```

### Ingest a Signal

```bash
# Async: queued, then processed by the worker
curl -X POST http://localhost:8000/ingest/ticket \
  -H "X-API-Key: $KL_KEY" -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "123",
    "subject": "Dashboard not loading",
    "description": "Users report the Analytics Dashboard is slow"
  }'

# Sync: processed before the response returns, for development and tests
curl -X POST http://localhost:8000/ingest/process/my-signal-id \
  -H "X-API-Key: $KL_KEY" -H "Content-Type: application/json" \
  -d '{
    "source_id": "doc-1",
    "raw_text": "The Dashboard feature allows users to view Analytics reports"
  }'
```

### Retrieve Context

Returns only published articles, with their confidence and the sources behind them.

```bash
curl -H "X-API-Key: $KL_KEY" "http://localhost:8000/context?query=dashboard&limit=5"
```

### Review Queue

New knowledge below the confidence threshold, or in conflict with something already published,
waits here and is not served to agents until a reviewer approves it.

```bash
# Pending reviews
curl -H "X-API-Key: $KL_KEY" "http://localhost:8000/review/queue"

# Approve, reject, or edit (an edit publishes the reviewer's text as a new version)
curl -X POST -H "X-API-Key: $KL_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/review/{article_id}/approve -d '{"notes": "checked against the docs"}'
```

The reviewer recorded in the audit log is the API key's name, not anything in the request.

## Article lifecycle

- A new article is `pending_review` or, above the threshold, `published`.
- A replacement for a live article links back to it (`SUPERSEDES`) but does not take it offline.
  The old version retires only when the replacement is published, so retrieval never has a gap.
- Editing creates a new version; versions are immutable.

## Running Tests

```bash
# Unit tests: mock backends, no services needed
pytest

# Integration tests: real Neo4j, Postgres with pgvector, and Redis
NEO4J_URI=bolt://localhost:7687 NEO4J_USERNAME=neo4j NEO4J_PASSWORD=... \
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres \
REDIS_URL=redis://localhost:6379 \
pytest tests_integration
```

The integration tests exist because the Cypher and SQL are never run by the mock backends. They
use fake embeddings and synthesis but real stores, and are skipped unless the variables are set.
The database needs `supabase/migrations` applied. CI runs both suites.

## Project Structure

```
knowledgelayer/
├── api/                 # FastAPI application
│   ├── main.py          # App entry point, lifespan
│   ├── deps.py          # Dependency injection
│   └── routers/         # API route handlers
├── core/                # Configuration and logging
├── models/              # Pydantic data models
├── pipeline/            # NLP processing components
│   ├── extractor.py     # Entity extraction (spaCy/keyword)
│   ├── embedder.py      # Gemini embeddings
│   ├── conflict.py      # Conflict detection
│   ├── scorer.py        # Confidence scoring
│   └── synthesizer.py   # Article synthesis (Gemini)
├── graph/               # Neo4j graph operations
│   ├── client.py        # Driver management
│   ├── schema.py        # Constraints and indexes
│   └── queries.py       # All Cypher queries
├── vector/              # pgvector operations
├── worker/              # Redis queue, consumer and the signal processor
├── web/                 # Next.js frontend scaffold
├── scripts/             # create_api_key and dev helpers
├── tests/               # unit tests (mock backends)
└── tests_integration/   # tests against real Neo4j, Postgres and Redis
```

## Architecture

1. **Signals** are ingested from various sources (tickets, Slack, PRs, docs, calls)
2. **Entities** are extracted using spaCy NER or keyword fallback
3. **Embeddings** are generated via Gemini text-embedding-004
4. **Conflicts** are detected by comparing signal embeddings to existing articles
5. **Articles** are synthesized using Gemini
6. **Confidence** is scored based on source authority, signal frequency, and recency
7. Articles with confidence >= 0.80 are auto-published; others go to HITL review

## Mock Mode

`USE_MOCKS=true` runs everything in memory, with no accounts or keys:

- Neo4j, pgvector, Supabase and the Redis queue: in-memory fakes
- Embeddings: deterministic hash-based vectors
- Synthesis: template-based articles

To mock only one side, use `MOCK_STORES=true` (real models, fake stores) or `MOCK_MODELS=true`
(real stores, fake models; this is what the integration tests do).

## Deployment

This is a monorepo with two deployable services:

```
┌─────────────┐     ┌─────────────┐
│   Vercel    │────▶│  Railway    │────▶ Neo4j Aura
│  (Next.js)  │     │  (FastAPI)  │────▶ Supabase
└─────────────┘     └─────────────┘────▶ Redis (Railway)
```

### Deploy API to Railway

1. Create a new project on [Railway](https://railway.app)
2. Connect your GitHub repository
3. Set the root directory to `knowledgelayer/`
4. Add environment variables from `.env.example`
5. Add a Redis service from Railway's marketplace
6. Deploy
7. Add a second service from the same repository for the worker, with the start command
   `python -m worker.consumer`, and the same environment variables. Without it, signals queue
   but are never processed.
8. Create a key with `python -m scripts.create_api_key` (run it with the production `DATABASE_URL`)

Railway will auto-detect the `Dockerfile` and `railway.toml`. The image does not include the
spaCy model, so entity extraction uses the keyword fallback unless you add
`python -m spacy download en_core_web_trf` to the Dockerfile.

### Deploy Frontend to Vercel

1. Create a new project on [Vercel](https://vercel.com)
2. Connect your GitHub repository
3. Set the root directory to `knowledgelayer/web`
4. Add environment variable:
   ```
   NEXT_PUBLIC_API_URL=https://your-api.railway.app
   ```
5. Deploy

### Environment Variables

**API (Railway):**
| Variable | Description |
|----------|-------------|
| `NEO4J_URI` | Neo4j Aura connection URI |
| `NEO4J_USERNAME` | Neo4j username |
| `NEO4J_PASSWORD` | Neo4j password |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon key |
| `DATABASE_URL` | Supabase PostgreSQL connection string |
| `GEMINI_API_KEY` | Google AI API key for embeddings and synthesis |
| `AUTH_REQUIRED` | Defaults to true with real stores |
| `CORS_ALLOW_ORIGINS` | Comma-separated origins allowed to call the API |
| `MODEL_PRICES_JSON` | Optional override of model prices (USD per 1M tokens) for cost logging |
| `REDIS_URL` | Railway Redis URL (auto-injected) |
| `ENVIRONMENT` | Set to `production` |

**Frontend (Vercel):**
| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_URL` | Your Railway API URL |

## License

MIT
