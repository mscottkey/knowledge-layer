"""Every query must be scoped to a tenant. These checks keep a new query from forgetting."""
import inspect
import re

import pytest

from graph import queries
from graph.client import execute_query

TENANT = "12345678-1234-5678-1234-567812345678"


async def test_a_query_without_a_tenant_filter_is_refused():
    with pytest.raises(ValueError, match="tenant_id"):
        await execute_query("MATCH (a:Article) RETURN a", {}, TENANT)


async def test_a_mismatched_tenant_parameter_is_refused():
    with pytest.raises(ValueError, match="does not match"):
        await execute_query("MATCH (a:Article {tenant_id: $tenant_id}) RETURN a", {"tenant_id": "other"}, TENANT)


def _cypher_strings() -> list[tuple[str, str]]:
    """Every Cypher string literal in queries.py, with the function it lives in."""
    found = []
    for name, fn in inspect.getmembers(queries, inspect.iscoroutinefunction):
        if fn.__module__ != queries.__name__:
            continue
        source = inspect.getsource(fn)
        for text in re.findall(r'"""(.*?)"""', source, re.S):
            if re.search(r"\b(MATCH|CREATE|MERGE)\b", text):
                found.append((name, text))
    return found


def test_there_are_queries_to_check():
    assert len(_cypher_strings()) >= 15


@pytest.mark.parametrize("name,text", _cypher_strings(), ids=lambda v: v if len(v) < 40 else "")
def test_every_node_pattern_names_its_tenant(name, text):
    """Each `(x:Label ...)` pattern for tenant data must carry tenant_id, or the query must filter on it."""
    for pattern in re.findall(r"\((\w+):(Article|Entity|Signal|ReviewEvent)\b([^)]*)\)", text):
        variable, label, body = pattern
        scoped = "tenant_id" in body or re.search(rf"\b{variable}\.tenant_id\s*=\s*\$tenant_id", text)
        assert scoped, f"{name}: ({variable}:{label}) is not scoped to a tenant"
