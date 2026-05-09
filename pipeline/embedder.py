import hashlib
from functools import lru_cache

import numpy as np
from openai import AsyncOpenAI

from core.config import get_settings
from core.logging import get_logger

logger = get_logger("pipeline.embedder")

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@lru_cache(maxsize=1000)
def _cached_mock_embedding(text_hash: str) -> tuple[float, ...]:
    hash_bytes = bytes.fromhex(text_hash)

    np.random.seed(int.from_bytes(hash_bytes[:4], "big"))
    embedding = np.random.randn(3072)
    embedding = embedding / np.linalg.norm(embedding)

    return tuple(embedding.tolist())


async def embed(text: str) -> list[float]:
    settings = get_settings()

    if settings.use_mocks:
        text_h = _text_hash(text)
        return list(_cached_mock_embedding(text_h))

    client = _get_client()

    response = await client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=text,
    )

    return response.data[0].embedding


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr = np.array(a)
    b_arr = np.array(b)

    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))


def is_duplicate(
    embedding: list[float],
    existing_embeddings: list[list[float]],
    threshold: float = 0.92,
) -> bool:
    for existing in existing_embeddings:
        if cosine_similarity(embedding, existing) >= threshold:
            return True
    return False
