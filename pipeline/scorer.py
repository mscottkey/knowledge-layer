import math
from datetime import datetime, timezone

from models.signals import KnowledgeSignal
from models.articles import Article
from pipeline.conflict import ConflictResult
from graph import queries
from core.logging import get_logger

logger = get_logger("pipeline.scorer")


class ConfidenceScorer:
    async def score(
        self,
        signal: KnowledgeSignal,
        conflict_result: ConflictResult,
        existing_article: Article | None = None,
        entity_name: str | None = None,
    ) -> float:
        source_weight = signal.authority * 0.40

        signal_count = 1
        if entity_name:
            signal_count = await queries.get_signal_count_for_entity(
                signal.tenant_id,
                entity_name,
                days=30,
            )
            signal_count = max(signal_count, 1)

        frequency_weight = min(signal_count / 10, 1.0) * 0.30

        days_since_signal = 0.0
        now = datetime.now(timezone.utc)
        signal_time = signal.ingested_at
        if signal_time.tzinfo is None:
            signal_time = signal_time.replace(tzinfo=timezone.utc)
        delta = now - signal_time
        days_since_signal = delta.total_seconds() / 86400

        recency_weight = math.exp(-days_since_signal / 14) * 0.20

        reviewer_boost = 0.0
        if existing_article:
            has_approval = await queries.has_prior_approval(
                str(existing_article.id),
                existing_article.tenant_id,
            )
            if has_approval:
                reviewer_boost = 0.10

        confidence = source_weight + frequency_weight + recency_weight + reviewer_boost
        confidence = min(confidence, 1.0)

        logger.info(
            "Confidence score calculated",
            extra={
                "signal_id": str(signal.id),
                "source_weight": source_weight,
                "frequency_weight": frequency_weight,
                "recency_weight": recency_weight,
                "reviewer_boost": reviewer_boost,
                "total": confidence,
            },
        )

        return confidence
