from graph import queries
from vector.store import delete_embedding
from core.logging import get_logger

logger = get_logger("worker.lifecycle")


async def publish_article(article_id: str, tenant_id: str) -> list[str]:
    """
    Make an article live and retire the versions it replaces.

    This is the only place an article becomes published, whether the confidence score cleared the
    threshold or a reviewer approved or edited it. The replaced versions are retired here, not when
    the replacement is created, so a pending replacement never takes the live article offline.
    Retired versions also lose their embeddings so retrieval stops spending slots on them.
    Returns the ids that were retired.
    """
    await queries.update_article_status(article_id, "published", tenant_id)
    retired = await queries.supersede_replaced_versions(article_id, tenant_id)
    for old_id in retired:
        await delete_embedding(old_id, tenant_id)

    logger.info(
        "Article published",
        extra={"article_id": article_id, "retired": retired, "tenant_id": tenant_id},
    )
    return retired
