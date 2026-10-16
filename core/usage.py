from uuid import UUID

from core.supabase import get_supabase_pool, get_mock_pool
from core.config import get_settings
from core.logging import get_logger

logger = get_logger("core.usage")

# Cost per 1M tokens in microdollars (1 dollar = 1,000,000 microdollars)
MODEL_COSTS = {
    # Gemini
    "text-embedding-004": {"input": 25, "output": 0},  # $0.000025/1K tokens
    "gemini-2.5-flash": {"input": 75, "output": 300},  # $0.075/$0.30 per 1M (free tier available)
    "gemini-2.0-flash": {"input": 75, "output": 300},
    # OpenAI
    "gpt-4o": {"input": 2500, "output": 10000},  # $2.50/$10 per 1M
    "gpt-4o-mini": {"input": 150, "output": 600},
    "text-embedding-3-large": {"input": 130, "output": 0},
}


def calculate_cost_microdollars(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> int:
    """Calculate cost in microdollars (1/1,000,000 of a dollar)."""
    costs = MODEL_COSTS.get(model_name, {"input": 0, "output": 0})

    input_cost = (prompt_tokens / 1_000_000) * costs["input"] * 1_000_000
    output_cost = (completion_tokens / 1_000_000) * costs["output"] * 1_000_000

    return int(input_cost + output_cost)


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
