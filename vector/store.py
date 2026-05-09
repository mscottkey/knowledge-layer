import json
from typing import Any

import numpy as np

from vector.client import get_pool, get_mock_store, MockVectorStore
from core.config import get_settings
from core.logging import get_logger

logger = get_logger("vector.store")


async def upsert_embedding(
    id: str,
    embedding: list[float],
    tenant_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    settings = get_settings()

    if settings.use_mocks:
        store = get_mock_store()
        if store:
            store.embeddings[id] = {
                "id": id,
                "tenant_id": tenant_id,
                "embedding": embedding,
                "metadata": metadata or {},
            }
        return

    pool = await get_pool()

    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    metadata_json = json.dumps(metadata or {})

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO embeddings (id, tenant_id, embedding, metadata)
            VALUES ($1, $2, $3::vector, $4::jsonb)
            ON CONFLICT (id) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata
            """,
            id,
            tenant_id,
            embedding_str,
            metadata_json,
        )


async def search_similar(
    embedding: list[float],
    tenant_id: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    settings = get_settings()

    if settings.use_mocks:
        store = get_mock_store()
        if store:
            return _mock_search(store, embedding, tenant_id, limit)
        return []

    pool = await get_pool()

    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, metadata, 1 - (embedding <=> $1::vector) AS similarity
            FROM embeddings
            WHERE tenant_id = $2
            ORDER BY embedding <=> $1::vector
            LIMIT $3
            """,
            embedding_str,
            tenant_id,
            limit,
        )

    return [
        {
            "id": row["id"],
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

    for id, data in store.embeddings.items():
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
            "id": id,
            "metadata": data.get("metadata", {}),
            "similarity": similarity,
        })

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:limit]


async def get_all_embeddings(tenant_id: str) -> list[dict[str, Any]]:
    settings = get_settings()

    if settings.use_mocks:
        store = get_mock_store()
        if store:
            return [
                {
                    "id": data["id"],
                    "embedding": data["embedding"],
                    "metadata": data.get("metadata", {}),
                }
                for data in store.embeddings.values()
                if data["tenant_id"] == tenant_id
            ]
        return []

    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, embedding::text, metadata
            FROM embeddings
            WHERE tenant_id = $1
            """,
            tenant_id,
        )

    results = []
    for row in rows:
        embedding_str = row["embedding"]
        embedding = [float(x) for x in embedding_str.strip("[]").split(",")]
        results.append({
            "id": row["id"],
            "embedding": embedding,
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
        })

    return results
