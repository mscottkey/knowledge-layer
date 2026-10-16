import pytest

from core.usage import calculate_cost_microdollars, log_ai_usage
from core.supabase import get_supabase_pool
from uuid import UUID
from tests.conftest import TEST_TENANT_ID


def test_a_price_per_million_tokens_is_microdollars_per_token():
    # gpt-4o is $2.50 per 1M input tokens, so one million tokens cost $2.50 = 2,500,000 microdollars.
    assert calculate_cost_microdollars("gpt-4o", 1_000_000, 0) == 2_500_000
    assert calculate_cost_microdollars("gpt-4o", 0, 1_000_000) == 10_000_000


def test_input_and_output_are_priced_separately_and_added():
    assert calculate_cost_microdollars("gpt-4o", 1_000, 500) == 2_500 + 5_000


def test_a_small_call_costs_a_realistic_amount():
    # 2,000 tokens in and 300 out on gemini-2.5-flash is a fraction of a cent.
    cost = calculate_cost_microdollars("gemini-2.5-flash", 2_000, 300)
    assert 0 < cost < 10_000  # under one cent


def test_an_unknown_model_costs_nothing_and_does_not_raise():
    assert calculate_cost_microdollars("model-that-does-not-exist", 10_000, 10_000) == 0


def test_prices_can_be_overridden_from_settings(settings):
    settings.MODEL_PRICES_JSON = '{"gemini-2.5-flash": {"input": 1.0, "output": 2.0}, "my-model": {"input": 3.0, "output": 4.0}}'
    assert calculate_cost_microdollars("gemini-2.5-flash", 1_000_000, 1_000_000) == 3_000_000
    assert calculate_cost_microdollars("my-model", 1_000, 1_000) == 7_000
    assert calculate_cost_microdollars("gpt-4o", 1_000_000, 0) == 2_500_000  # others keep their prices


async def test_usage_is_logged_with_its_cost():
    await log_ai_usage(UUID(TEST_TENANT_ID), "gpt-4o", "openai", "synthesis", prompt_tokens=1_000_000, completion_tokens=0)
    row = (await get_supabase_pool()).ai_usage_logs[-1]
    assert row["cost_microdollars"] == 2_500_000
