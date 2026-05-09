from dataclasses import dataclass

from models.signals import KnowledgeSignal
from models.entities import Entity
from graph import queries
from pipeline.embedder import embed, cosine_similarity
from core.logging import get_logger

logger = get_logger("pipeline.conflict")


@dataclass
class ConflictResult:
    has_conflict: bool
    conflicting_article_id: str | None
    delta_score: float


class ConflictDetector:
    async def detect(
        self,
        signal: KnowledgeSignal,
        entities: list[Entity],
    ) -> ConflictResult:
        if not entities:
            return ConflictResult(
                has_conflict=False,
                conflicting_article_id=None,
                delta_score=0.0,
            )

        signal_embedding = await embed(signal.raw_text)

        for entity in entities:
            articles = await queries.find_articles_for_entity(
                signal.tenant_id,
                entity.name,
            )

            if not articles:
                continue

            for article in articles:
                article_body = article.get("body", "")
                if not article_body:
                    continue

                article_embedding = await embed(article_body)
                similarity = cosine_similarity(signal_embedding, article_embedding)

                if similarity < 0.75:
                    logger.info(
                        "Conflict detected",
                        extra={
                            "signal_id": str(signal.id),
                            "article_id": article.get("id"),
                            "similarity": similarity,
                            "entity": entity.name,
                        },
                    )
                    return ConflictResult(
                        has_conflict=True,
                        conflicting_article_id=article.get("id"),
                        delta_score=1.0 - similarity,
                    )

        return ConflictResult(
            has_conflict=False,
            conflicting_article_id=None,
            delta_score=0.0,
        )
