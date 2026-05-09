# KnowledgeLayer

AI-native knowledge graph platform that ingests signals from support tools (tickets, Slack, PRs, call transcripts, docs), processes them through an NLP pipeline, detects conflicts with existing knowledge, synthesizes updated articles, scores confidence, and serves context to downstream AI agents via a retrieval API.

## Tech Stack

| Layer | Technology |
|-------|------------|
| API | Python 3.12, FastAPI, uvicorn |
| Graph Store | Neo4j Aura |
| Vector + Ops DB | Supabase (PostgreSQL + pgvector) |
| Embeddings | Gemini (text-embedding-004) |
| Synthesis | OpenAI (gpt-4o) |
| NER | spaCy en_core_web_trf |
| Job Queue | Redis |
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
- **OpenAI**: Get API key from [OpenAI Platform](https://platform.openai.com/api-keys) (for synthesis)

For local development without cloud services, set `USE_MOCKS=true`.

### 3. Install Python dependencies

```bash
pip install -e ".[dev]"
```

### 4. Download spaCy model (optional, for production NER)

```bash
python -m spacy download en_core_web_trf
```

Skip this step if using `USE_MOCKS=true` (keyword fallback extractor will be used).

### 5. Run database migrations

Apply the Supabase migrations to create the embeddings table:

```bash
# Option A: Using Supabase CLI
supabase db push

# Option B: Run SQL directly in Supabase Dashboard → SQL Editor
# Copy contents of supabase/migrations/20240101000000_create_embeddings.sql
```

### 6. Start Redis

```bash
docker compose up -d
```

### 7. Run the API server

```bash
uvicorn api.main:app --reload
```

The API will be available at `http://localhost:8000`.

## API Endpoints

### Health Check

```bash
curl http://localhost:8000/health
```

### Ingest a Signal

```bash
# Async (queues for background processing)
curl -X POST http://localhost:8000/ingest/ticket \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "my-tenant",
    "ticket_id": "123",
    "subject": "Dashboard not loading",
    "description": "Users report the Analytics Dashboard is slow"
  }'

# Sync (processes immediately, for dev/testing)
curl -X POST http://localhost:8000/ingest/process/my-signal-id \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "my-tenant",
    "source_id": "doc-1",
    "raw_text": "The Dashboard feature allows users to view Analytics reports"
  }'
```

### Retrieve Context

```bash
curl "http://localhost:8000/context?query=dashboard&tenant_id=my-tenant&limit=5"
```

### Review Queue

```bash
# Get pending reviews
curl "http://localhost:8000/review/queue?tenant_id=my-tenant"

# Approve an article
curl -X POST "http://localhost:8000/review/{article_id}/approve?tenant_id=my-tenant" \
  -H "Content-Type: application/json" \
  -d '{"reviewer_id": "reviewer-1"}'
```

## Running Tests

```bash
# Run all tests (uses mock backends)
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_pipeline.py
```

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
│   ├── embedder.py      # OpenAI embeddings
│   ├── conflict.py      # Conflict detection
│   ├── scorer.py        # Confidence scoring
│   └── synthesizer.py   # Article synthesis (GPT-4o)
├── graph/               # Neo4j graph operations
│   ├── client.py        # Driver management
│   ├── schema.py        # Constraints and indexes
│   └── queries.py       # All Cypher queries
├── vector/              # pgvector operations
├── worker/              # Signal processor orchestrator
├── web/                 # Next.js frontend scaffold
└── tests/               # pytest test suite
```

## Architecture

1. **Signals** are ingested from various sources (tickets, Slack, PRs, docs, calls)
2. **Entities** are extracted using spaCy NER or keyword fallback
3. **Embeddings** are generated via OpenAI text-embedding-3-large
4. **Conflicts** are detected by comparing signal embeddings to existing articles
5. **Articles** are synthesized using GPT-4o
6. **Confidence** is scored based on source authority, signal frequency, and recency
7. Articles with confidence >= 0.80 are auto-published; others go to HITL review

## Mock Mode

Set `USE_MOCKS=true` in `.env` to run without cloud services:

- Neo4j: In-memory graph storage
- pgvector: In-memory embedding storage
- OpenAI embeddings: Deterministic hash-based vectors
- OpenAI synthesis: Template-based article generation

This enables local development and testing without API keys or cloud accounts.

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

Railway will auto-detect the `Dockerfile` and `railway.toml`.

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
| `OPENAI_API_KEY` | OpenAI API key |
| `REDIS_URL` | Railway Redis URL (auto-injected) |
| `ENVIRONMENT` | Set to `production` |

**Frontend (Vercel):**
| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_URL` | Your Railway API URL |

## License

MIT
