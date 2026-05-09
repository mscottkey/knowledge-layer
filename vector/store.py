import json
from typing import Any
from uuid import UUID

import numpy as np

from vector.client import get_pool, get_mock_store, MockVectorStore
from core.config import get_settings
from core.logging import get_logger

logger = get_logger("vector.store")


async def upsert_embedding(
    article_id: str,
    embedding: list[float],
    tenant_id: UUID | str,
    metadata: dict[str, Any] | None = None,
    model: str | None = None,
) -> UUID | None:
    """Upsert an embedding for an article."""
    settings = get_settings()

    # Normalize tenant_id to string for mock, UUID for real
    tenant_id_str = str(tenant_id)

    if settings.use_mocks:
        store = get_mock_store()
        if store:
            store.embeddings[article_id] = {
                "article_id": article_id,
                "tenant_id": tenant_id_str,
                "embedding": embedding,
                "metadata": metadata or {},
            }
        return None

    pool = await get_pool()

    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    metadata_json = json.dumps(metadata or {})
    tenant_uuid = tenant_id if isinstance(tenant_id, UUID) else UUID(tenant_id)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO embeddings (tenant_id, article_id, embedding, metadata, model)
            VALUES ($1, $2, $3::vector, $4::jsonb, $5)
            ON CONFLICT (tenant_id, article_id) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata,
                model = EXCLUDED.model,
                updated_at = NOW()
            RETURNING id
            """,
            tenant_uuid,
            article_id,
            embedding_str,
            metadata_json,
            model or settings.EMBEDDING_MODEL,
        )
        return row["id"] if row else None


async def search_similar(
    embedding: list[float],
    tenant_id: UUID | str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search for similar articles by embedding."""
    settings = get_settings()

    tenant_id_str = str(tenant_id)

    if settings.use_mocks:
        store = get_mock_store()
        if store:
            return _mock_search(store, embedding, tenant_id_str, limit)
        return []

    pool = await get_pool()

    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    tenant_uuid = tenant_id if isinstance(tenant_id, UUID) else UUID(tenant_id)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT article_id, metadata, 1 - (embedding <=> $1::vector) AS similarity
            FROM embeddings
            WHERE tenant_id = $2
            ORDER BY embedding <=> $1::vector
            LIMIT $3
            """,
            embedding_str,
            tenant_uuid,
            limit,
        )

    return [
        {
            "id": row["article_id"],
            "article_id": row["article_id"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
            "similarity": float(row["similarity"]),
        }
        for row in rows
    ]


def _mock_search(
    store: MockVectorStore,
    query_embedding: list[float],
    tenant_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    results = []
    query_vec = np.array(query_embedding)

    for article_id, data in store.embeddings.items():
        if data["tenant_id"] != tenant_id:
            continue

        stored_vec = np.array(data["embedding"])

        if np.linalg.norm(query_vec) == 0 or np.linalg.norm(stored_vec) == 0:
            similarity = 0.0
        else:
            similarity = float(
                np.dot(query_vec, stored_vec)
                / (np.linalg.norm(query_vec) * np.linalg.norm(stored_vec))
            )

        results.append({
            "id": article_id,
            "article_id": article_id,
            "metadata": data.get("metadata", {}),
            "similarity": similarity,
        })

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:limit]


async def get_all_embeddings(tenant_id: UUID | str) -> list[dict[str, Any]]:
    """Get all embeddings for a tenant."""
    settings = get_settings()

    tenant_id_str = str(tenant_id)

    if settings.use_mocks:
        store = get_mock_store()
        if store:
            return [
                {
                    "id": data["article_id"],
                    "article_id": data["article_id"],
                    "embedding": data["embedding"],
                    "metadata": data.get("metadata", {}),
                }
                for data in store.embeddings.values()
                if data["tenant_id"] == tenant_id_str
            ]
        return []

    pool = await get_pool()
    tenant_uuid = tenant_id if isinstance(tenant_id, UUID) else UUID(tenant_id)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT article_id, embedding::text, metadata
            FROM embeddings
            WHERE tenant_id = $1
            """,
            tenant_uuid,
        )

    results = []
    for row in rows:
        embedding_str = row["embedding"]
        embedding = [float(x) for x in embedding_str.strip("[]").split(",")]
        results.append({
            "id": row["article_id"],
            "article_id": row["article_id"],
            "embedding": embedding,
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
        })

    return results


async def delete_embedding(article_id: str, tenant_id: UUID | str) -> bool:
    """Delete an embedding by article ID."""
    settings = get_settings()

    tenant_id_str = str(tenant_id)

    if settings.use_mocks:
        store = get_mock_store()
        if store and article_id in store.embeddings:
            if store.embeddings[article_id]["tenant_id"] == tenant_id_str:
                del store.embeddings[article_id]
                return True
        return False

    pool = await get_pool()
    tenant_uuid = tenant_id if isinstance(tenant_id, UUID) else UUID(tenant_id)

    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM embeddings
            WHERE article_id = $1 AND tenant_id = $2
            """,
            article_id,
            tenant_uuid,
        )
        return result == "DELETE 1"
