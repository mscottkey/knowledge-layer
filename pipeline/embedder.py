import hashlib
import time
from functools import lru_cache
from uuid import UUID

import numpy as np
from google import genai

from core.config import get_settings
from core.logging import get_logger
from core.usage import log_ai_usage

logger = get_logger("pipeline.embedder")

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        settings = get_settings()
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


@lru_cache(maxsize=1000)
def _cached_mock_embedding(text_hash: str, dimension: int) -> tuple[float, ...]:
    hash_bytes = bytes.fromhex(text_hash)
    np.random.seed(int.from_bytes(hash_bytes[:4], "big"))
    embedding = np.random.randn(dimension)
    embedding = embedding / np.linalg.norm(embedding)
    return tuple(embedding.tolist())


async def embed(
    text: str,
    tenant_id: UUID | None = None,
    user_id: UUID | None = None,
) -> list[float]:
    """Generate embedding for text, with optional usage logging."""
    settings = get_settings()

    if settings.mock_models:
        text_h = _text_hash(text)
        embedding = list(_cached_mock_embedding(text_h, settings.EMBEDDING_DIMENSION))

        # Still log mock usage if tenant provided
        if tenant_id:
            await log_ai_usage(
                tenant_id=tenant_id,
                model_name=settings.EMBEDDING_MODEL,
                model_provider="google",
                feature_context="embedding",
                prompt_tokens=_estimate_tokens(text),
                completion_tokens=0,
                user_id=user_id,
            )

        return embedding

    client = _get_client()
    start_time = time.time()

    response = await client.aio.models.embed_content(
        model=settings.EMBEDDING_MODEL,
        contents=text,
    )

    latency_ms = int((time.time() - start_time) * 1000)
    embedding = list(response.embeddings[0].values)

    # Log usage if tenant provided
    if tenant_id:
        await log_ai_usage(
            tenant_id=tenant_id,
            model_name=settings.EMBEDDING_MODEL,
            model_provider="google",
            feature_context="embedding",
            prompt_tokens=_estimate_tokens(text),
            completion_tokens=0,
            user_id=user_id,
            latency_ms=latency_ms,
        )

    return embedding


async def embed_batch(
    texts: list[str],
    tenant_id: UUID | None = None,
    user_id: UUID | None = None,
) -> list[list[float]]:
    """Generate embeddings for multiple texts."""
    settings = get_settings()

    if settings.mock_models:
        embeddings = []
        for text in texts:
            text_h = _text_hash(text)
            embeddings.append(list(_cached_mock_embedding(text_h, settings.EMBEDDING_DIMENSION)))

        if tenant_id:
            total_tokens = sum(_estimate_tokens(t) for t in texts)
            await log_ai_usage(
                tenant_id=tenant_id,
                model_name=settings.EMBEDDING_MODEL,
                model_provider="google",
                feature_context="embedding_batch",
                prompt_tokens=total_tokens,
                completion_tokens=0,
                user_id=user_id,
            )

        return embeddings

    client = _get_client()
    start_time = time.time()

    response = await client.aio.models.embed_content(
        model=settings.EMBEDDING_MODEL,
        contents=texts,
    )

    latency_ms = int((time.time() - start_time) * 1000)
    embeddings = [list(e.values) for e in response.embeddings]

    if tenant_id:
        total_tokens = sum(_estimate_tokens(t) for t in texts)
        await log_ai_usage(
            tenant_id=tenant_id,
            model_name=settings.EMBEDDING_MODEL,
            model_provider="google",
            feature_context="embedding_batch",
            prompt_tokens=total_tokens,
            completion_tokens=0,
            user_id=user_id,
            latency_ms=latency_ms,
        )

    return embeddings


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
