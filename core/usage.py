import json
from uuid import UUID

from core.supabase import get_supabase_pool, get_mock_pool
from core.config import get_settings
from core.logging import get_logger

logger = get_logger("core.usage")

# List prices in US dollars per 1M tokens. These change often, so check them against the
# provider's pricing page before relying on the totals, or override them with MODEL_PRICES_JSON,
# for example '{"gemini-2.5-flash": {"input": 0.30, "output": 2.50}}'.
MODEL_PRICES_USD_PER_1M: dict[str, dict[str, float]] = {
    # Gemini
    "text-embedding-004": {"input": 0.025, "output": 0.0},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "text-embedding-3-large": {"input": 0.13, "output": 0.0},
}

_warned_models: set[str] = set()


def _prices() -> dict[str, dict[str, float]]:
    overrides = get_settings().MODEL_PRICES_JSON
    if not overrides:
        return MODEL_PRICES_USD_PER_1M
    return {**MODEL_PRICES_USD_PER_1M, **json.loads(overrides)}


def calculate_cost_microdollars(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> int:
    """
    Cost in microdollars (1/1,000,000 of a dollar).

    A price in dollars per million tokens is numerically the same as microdollars per token,
    so the cost is simply tokens times price.
    """
    prices = _prices().get(model_name)
    if prices is None:
        if model_name not in _warned_models:
            _warned_models.add(model_name)
            logger.warning(f"No price for model {model_name}; its usage will be logged at zero cost")
        return 0

    return round(prompt_tokens * prices["input"] + completion_tokens * prices["output"])


async def log_ai_usage(
    tenant_id: UUID,
    model_name: str,
    model_provider: str,
    feature_context: str,
    prompt_tokens: int,
    completion_tokens: int = 0,
    user_id: UUID | None = None,
    request_id: str | None = None,
    latency_ms: int | None = None,
) -> UUID | None:
    """Log AI usage for billing and analytics."""
    settings = get_settings()

    cost = calculate_cost_microdollars(model_name, prompt_tokens, completion_tokens)

    if settings.mock_stores:
        mock_pool = get_mock_pool()
        if mock_pool:
            from uuid import uuid4
            usage_id = uuid4()
            mock_pool.ai_usage_logs.append({
                "id": str(usage_id),
                "tenant_id": str(tenant_id),
                "model_name": model_name,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_microdollars": cost,
            })
            logger.debug(
                f"AI usage: {model_name}",
                extra={
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cost_microdollars": cost,
                }
            )
            return usage_id
        return None

    pool = await get_supabase_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO ai_usage_logs (
                tenant_id, user_id, model_name, model_provider,
                feature_context, prompt_tokens, completion_tokens,
                cost_microdollars, latency_ms, request_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            tenant_id,
            user_id,
            model_name,
            model_provider,
            feature_context,
            prompt_tokens,
            completion_tokens,
            cost,
            latency_ms,
            request_id,
        )
        return row["id"] if row else None


async def get_tenant_usage_this_month(tenant_id: UUID) -> dict:
    """Get tenant's AI usage for the current month."""
    settings = get_settings()

    if settings.mock_stores:
        mock_pool = get_mock_pool()
        if mock_pool:
            total_tokens = sum(
                log["prompt_tokens"] + log["completion_tokens"]
                for log in mock_pool.ai_usage_logs
                if log["tenant_id"] == str(tenant_id)
            )
            total_cost = sum(
                log["cost_microdollars"]
                for log in mock_pool.ai_usage_logs
                if log["tenant_id"] == str(tenant_id)
            )
            return {
                "total_tokens": total_tokens,
                "total_cost_microdollars": total_cost,
                "total_cost_dollars": total_cost / 1_000_000,
            }
        return {"total_tokens": 0, "total_cost_microdollars": 0, "total_cost_dollars": 0}

    pool = await get_supabase_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                COALESCE(SUM(cost_microdollars), 0) as total_cost
            FROM ai_usage_logs
            WHERE tenant_id = $1
              AND created_at >= date_trunc('month', NOW())
            """,
            tenant_id,
        )

        if row:
            return {
                "total_tokens": row["total_tokens"],
                "total_cost_microdollars": row["total_cost"],
                "total_cost_dollars": row["total_cost"] / 1_000_000,
            }

        return {"total_tokens": 0, "total_cost_microdollars": 0, "total_cost_dollars": 0}
