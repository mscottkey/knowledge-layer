# KnowledgeLayer — Claude Code Bootstrap Prompt

> Paste this in full as your first Claude Code message in a new project directory.

---

You are scaffolding a new Python/FastAPI project called **knowledgelayer** from scratch.

## Project purpose

An AI-native knowledge graph platform that ingests signals from support tools (tickets, Slack, PRs, call transcripts, docs), processes them through an NLP pipeline, detects conflicts with existing knowledge, synthesizes updated articles, scores confidence, and serves context to downstream AI agents via a retrieval API. A minimal React/Next.js frontend handles human-in-the-loop review.

---

## Tech stack

| Layer | Choice |
|---|---|
| API | Python 3.12, FastAPI, uvicorn |
| Graph store | Neo4j Aura (async neo4j python driver) |
| Vector + ops DB | Supabase — postgres + pgvector via asyncpg |
| LLM | OpenAI SDK — text-embedding-3-large, gpt-4o |
| NER | spaCy en_core_web_trf |
| Job queue | Redis via redis-py |
| Validation | Pydantic v2 |
| Config | python-dotenv |
| Testing | pytest + httpx |
| Frontend | Next.js 14 app router, Tailwind CSS, no component library |

---

## Project structure

Create this full directory and file tree before implementing anything:

```
knowledgelayer/
├── api/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, lifespan, router registration
│   ├── routers/
│   │   ├── ingest.py        # POST /ingest/{source_type}
│   │   ├── serve.py         # GET /context — RAG retrieval endpoint
│   │   ├── review.py        # GET/POST /review/queue — HITL queue
│   │   └── health.py        # GET /health
│   └── deps.py              # FastAPI dependency injection
├── core/
│   ├── __init__.py
│   ├── config.py            # Pydantic BaseSettings
│   └── logging.py           # Structured logging setup
├── models/
│   ├── __init__.py
│   ├── signals.py           # KnowledgeSignal, SourceType enum
│   ├── articles.py          # Article, ArticleVersion, ArticleStatus enum
│   ├── entities.py          # Entity, EntityType enum
│   └── events.py            # ReviewEvent, ReviewAction enum
├── pipeline/
│   ├── __init__.py
│   ├── extractor.py         # Entity extraction via spaCy NER
│   ├── embedder.py          # OpenAI embedding + cosine dedup
│   ├── conflict.py          # Conflict detector
│   ├── synthesizer.py       # LLM reconciliation
│   └── scorer.py            # Confidence score formula
├── graph/
│   ├── __init__.py
│   ├── client.py            # Neo4j Aura async driver
│   ├── queries.py           # All Cypher queries as named functions
│   └── schema.py            # Index + constraint creation on startup
├── vector/
│   ├── __init__.py
│   ├── client.py            # Supabase/asyncpg client
│   └── store.py             # Upsert embeddings, cosine similarity search
├── worker/
│   ├── __init__.py
│   └── processor.py         # Full pipeline orchestrator for one signal
├── web/
│   ├── package.json
│   ├── tailwind.config.js
│   └── app/
│       ├── layout.tsx
│       ├── page.tsx          # Redirects to /queue
│       └── queue/
│           └── page.tsx      # Placeholder — "HITL queue coming soon"
├── tests/
│   ├── __init__.py
│   ├── test_pipeline.py     # Unit tests: extractor, scorer, conflict
│   └── test_ingest.py       # Integration test: POST /ingest/ticket
├── .env.example
├── .gitignore
├── docker-compose.yml       # Redis only
├── pyproject.toml
└── README.md
```

---

## Implementation spec

Implement each section fully — no stubs, no placeholder comments. After completing each major section (models → graph → pipeline → api), confirm what was built before continuing.

---

### `core/config.py`

Pydantic `BaseSettings` with the following fields:

```python
NEO4J_URI: str
NEO4J_USERNAME: str
NEO4J_PASSWORD: str
SUPABASE_URL: str
SUPABASE_KEY: str
DATABASE_URL: str          # asyncpg direct connection string
OPENAI_API_KEY: str
REDIS_URL: str
CONFIDENCE_THRESHOLD: float = 0.80
EMBEDDING_MODEL: str = "text-embedding-3-large"
SYNTHESIS_MODEL: str = "gpt-4o"
LOG_LEVEL: str = "INFO"
ENVIRONMENT: str = "development"
```

---

### `models/` — Pydantic v2 throughout

**`KnowledgeSignal`**
```
id: UUID (auto)
tenant_id: str
source: SourceType  # [ticket, slack, pr, call, doc]
source_id: str
raw_text: str
authority: float    # ticket=0.7, pr=1.0, slack=0.5, call=0.6, doc=0.8
ingested_at: datetime (auto)
metadata: dict
```

**`Article`**
```
id: UUID (auto)
tenant_id: str
title: str
body: str
version: int
status: ArticleStatus  # [draft, pending_review, published, superseded]
confidence: float
entity_ids: list[str]
created_at: datetime (auto)
updated_at: datetime (auto)
```

**`Entity`**
```
id: UUID (auto)
tenant_id: str
name: str
type: EntityType  # [feature, workflow, bug, persona, integration]
canonical: bool = True
```

**`ReviewEvent`**
```
id: UUID (auto)
tenant_id: str
article_id: str
reviewer_id: str
action: ReviewAction  # [approved, edited, rejected]
edited_body: str | None
note: str | None
created_at: datetime (auto)
```

---

### `graph/client.py`

Async Neo4j driver via `AsyncGraphDatabase.driver()`. Provide:

- `get_driver() -> AsyncDriver`
- `async execute_query(query, params, tenant_id)` — always injects `tenant_id` check as a safety assertion
- Lifespan-managed connection (open on startup, close on shutdown)

---

### `graph/queries.py`

All Cypher lives here. No inline Cypher anywhere else in the codebase. Implement these as async functions returning typed dicts:

```python
find_articles_for_entity(tenant_id, entity_name) -> list[dict]
create_article_node(article: Article) -> str
supersede_article(old_id, new_id, diff_summary) -> None
get_article_history(article_id) -> list[dict]
find_stale_articles(tenant_id, days_stale=30) -> list[dict]
find_coverage_gaps(tenant_id) -> list[dict]
create_entity_node(entity: Entity) -> str
link_article_to_entity(article_id, entity_id) -> None
link_signal_to_article(signal_id, article_id, weight: float) -> None
```

The versioning pattern is immutable — never mutate an existing Article node. Every update creates a new node and writes a `SUPERSEDES` edge with a `diff_summary` property.

---

### `graph/schema.py`

Run these on startup:

```cypher
CREATE CONSTRAINT article_id IF NOT EXISTS FOR (a:Article) REQUIRE a.id IS UNIQUE
CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE
CREATE INDEX article_tenant IF NOT EXISTS FOR (a:Article) ON (a.tenant_id, a.status)
CREATE INDEX entity_tenant IF NOT EXISTS FOR (e:Entity) ON (e.tenant_id, e.name)
CREATE INDEX signal_tenant IF NOT EXISTS FOR (s:Signal) ON (s.tenant_id, s.ingested_at)
```

---

### `pipeline/extractor.py`

Use spaCy `en_core_web_trf`. Extract entities from `raw_text` and map spaCy labels to `EntityType`:

- `PRODUCT`, `ORG` → `feature` or `integration` (heuristic on surrounding text)
- `EVENT`, `ACT` → `workflow`
- Unknown → `feature`

Return `list[Entity]` with `tenant_id` set. Include a lightweight keyword fallback extractor for when the spaCy model isn't loaded — this keeps test runs fast.

---

### `pipeline/embedder.py`

```python
async def embed(text: str) -> list[float]          # OpenAI embeddings API
def cosine_similarity(a, b) -> float
def is_duplicate(embedding, existing_embeddings, threshold=0.92) -> bool
```

Simple `lru_cache` on text hash for the embedding call.

---

### `pipeline/conflict.py`

`ConflictDetector` class with:

```python
async def detect(signal: KnowledgeSignal, entities: list[Entity]) -> ConflictResult
```

`ConflictResult`:
```
has_conflict: bool
conflicting_article_id: str | None
delta_score: float
```

Logic:
1. For each entity, query Neo4j for published articles covering it
2. Embed the signal `raw_text`
3. Embed the existing article body
4. Compute cosine similarity
5. Similarity < 0.75 AND article exists → conflict (content has diverged)
6. No article exists → no conflict (net new)

---

### `pipeline/scorer.py`

`ConfidenceScorer` with:

```python
async def score(signal, conflict_result, existing_article=None) -> float
```

Formula:
```
source_weight    = signal.authority * 0.40
frequency_weight = min(signal_count / 10, 1.0) * 0.30
recency_weight   = exp(-days_since_last_signal / 14) * 0.20
reviewer_boost   = 0.10 if existing_article had prior human approval else 0.0

confidence = min(source_weight + frequency_weight + recency_weight + reviewer_boost, 1.0)
```

`signal_count` comes from a graph query — number of distinct signals that have touched this entity in the past 30 days.

---

### `pipeline/synthesizer.py`

`Synthesizer` with:

```python
async def synthesize(signal, existing_article=None) -> SynthesisResult
```

`SynthesisResult`:
```
title: str
body: str
diff_summary: str
```

System prompt:
> You are a knowledge base editor. Given a new signal and optionally an existing article, produce an updated article. Be precise, structured, and conservative — do not invent facts not present in the signal. Return JSON only with keys: title, body, diff_summary.

If `existing_article` is `None` → create a new article from the signal alone.

---

### `worker/processor.py`

`SignalProcessor` — the full pipeline orchestrator:

```python
async def process(signal: KnowledgeSignal) -> ProcessResult:
    # 1. Extract entities
    # 2. Embed signal
    # 3. Deduplicate — skip if cosine sim > 0.92 with existing embedding
    # 4. Detect conflicts
    # 5. Synthesize article
    # 6. Score confidence
    # 7a. score >= CONFIDENCE_THRESHOLD → write to graph, status=published
    # 7b. score <  CONFIDENCE_THRESHOLD → write to graph, status=pending_review
    # 8. Return ProcessResult: article_id, status, confidence, conflict_detected
```

---

### `api/routers/ingest.py`

**`POST /ingest/{source_type}`**
- Accept raw webhook payload as `dict`
- Map to `KnowledgeSignal` via source-specific mapper (implement for: `ticket` Zendesk shape, `slack`, `pr` GitHub shape, `doc`)
- Enqueue to Redis for async processing
- Return `202 Accepted` with `signal_id`

**`POST /ingest/process/{signal_id}`** *(sync, for dev/testing)*
- Pull signal from Redis or DB
- Run `processor.process()` synchronously
- Return full `ProcessResult`

> The sync endpoint is critical for your dev loop — use it constantly to test the pipeline without a running worker.

---

### `api/routers/serve.py`

**`GET /context?query=...&tenant_id=...&limit=5`**
1. Embed the query string
2. Vector search pgvector for top-k article embeddings
3. Fetch full article bodies from Neo4j by ID
4. Return ranked list:
```json
[{ "article_id": "", "title": "", "body": "", "confidence": 0.0, "version": 1 }]
```

---

### `api/routers/review.py`

**`GET /review/queue?tenant_id=...`**
- All articles with `status=pending_review` for tenant
- Include: conflict flag, confidence, source signal counts

**`POST /review/{article_id}/approve`**
**`POST /review/{article_id}/reject`**
**`POST /review/{article_id}/edit`** — body: `{ "edited_body": str }`

Each action:
- Creates a `ReviewEvent` node in graph
- `approve` / `edit` → set article `status=published`
- `reject` → set article `status=draft`
- On `approve`: if a superseded article exists, mark it `superseded`

---

### `docker-compose.yml`

Redis only:

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

Neo4j and Supabase are cloud — do not run locally.

---

### `.env.example`

All config keys with placeholder values and a one-line comment for each explaining where to find the value (Neo4j Aura console, Supabase dashboard, etc.).

---

### `pyproject.toml`

All dependencies pinned to current stable versions. Include:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

---

### `README.md`

Setup steps in order:
1. Clone repo
2. Copy `.env.example` → `.env`, fill in values
3. `pip install -e .`
4. `python -m spacy download en_core_web_trf`
5. `docker compose up -d`
6. `uvicorn api.main:app --reload`

Include links to:
- [Neo4j Aura free tier](https://neo4j.com/cloud/platform/aura-graph-database/)
- [Supabase](https://supabase.com)

---

## Hard constraints

- **Every graph query must include `tenant_id` in the `WHERE` clause — no exceptions**
- **All Cypher lives in `graph/queries.py` only — no inline Cypher anywhere else**
- No sync blocking calls inside async route handlers
- Pydantic v2 syntax throughout (`model_config`, not `class Config`)
- Type hints on every function signature
- No placeholder comments — if something isn't implemented, omit it entirely

---

## Out of scope for this session

Do not implement:
- Authentication or API key middleware
- Slack OAuth connector (map the payload shape only)
- The Next.js frontend beyond the directory scaffold and placeholder page
- The coverage gap dashboard
- Any background worker beyond Redis enqueue

---

*Start by creating the full directory structure, then implement each file in the order listed above. Confirm after each major section before continuing.*