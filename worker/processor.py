from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from models.signals import KnowledgeSignal
from models.articles import Article, ArticleStatus
from models.entities import Entity
from pipeline.extractor import extract_entities
from pipeline.embedder import embed, is_duplicate
from pipeline.conflict import ConflictDetector, ConflictResult
from pipeline.scorer import ConfidenceScorer
from pipeline.synthesizer import Synthesizer
from graph import queries
from vector.store import upsert_embedding, get_all_embeddings
from worker.lifecycle import publish_article
from core.config import get_settings
from core.logging import get_logger
from core.audit import log_audit

logger = get_logger("worker.processor")


def _to_uuid(value: str | UUID) -> UUID:
    """Convert string to UUID if needed."""
    if isinstance(value, UUID):
        return value
    return UUID(value)


@dataclass
class ProcessResult:
    article_id: str
    status: ArticleStatus
    confidence: float
    conflict_detected: bool
    entities: list[str]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # True when the signal matched existing knowledge closely enough to add nothing.
    duplicate: bool = False


class SignalProcessor:
    def __init__(self) -> None:
        self.conflict_detector = ConflictDetector()
        self.scorer = ConfidenceScorer()
        self.synthesizer = Synthesizer()

    async def process(
        self,
        signal: KnowledgeSignal,
        user_id: UUID | None = None,
    ) -> ProcessResult:
        settings = get_settings()
        tenant_uuid = _to_uuid(signal.tenant_id)

        logger.info(
            "Processing signal",
            extra={"signal_id": str(signal.id), "source": signal.source.value},
        )

        # Extract entities
        entities = extract_entities(signal.raw_text, signal.tenant_id)
        logger.info(
            "Extracted entities",
            extra={"signal_id": str(signal.id), "count": len(entities)},
        )

        # Embed signal (with usage tracking)
        signal_embedding = await embed(
            signal.raw_text,
            tenant_id=tenant_uuid,
            user_id=user_id,
        )

        # Check for duplicates
        existing_embeddings_data = await get_all_embeddings(tenant_uuid)
        existing_embeddings = [e["embedding"] for e in existing_embeddings_data]

        if is_duplicate(signal_embedding, existing_embeddings):
            logger.info(
                "Duplicate signal detected, skipping",
                extra={"signal_id": str(signal.id)},
            )
            return ProcessResult(
                article_id="",
                status=ArticleStatus.draft,
                confidence=0.0,
                conflict_detected=False,
                entities=[],
                duplicate=True,
            )

        # Detect conflicts
        conflict_result = await self.conflict_detector.detect(signal, entities)

        # Load existing article if conflict found
        existing_article: Article | None = None
        if conflict_result.conflicting_article_id:
            article_data = await queries.get_article_by_id(
                conflict_result.conflicting_article_id,
                signal.tenant_id,
            )
            if article_data:
                existing_article = Article(
                    id=article_data["id"],
                    tenant_id=article_data["tenant_id"],
                    title=article_data["title"],
                    body=article_data["body"],
                    version=article_data.get("version", 1),
                    status=ArticleStatus(article_data.get("status", "draft")),
                    confidence=article_data.get("confidence", 0.0),
                    entity_ids=article_data.get("entity_ids", []),
                )

        # Synthesize article (with usage tracking)
        synthesis_result = await self.synthesizer.synthesize(
            signal,
            existing_article,
            tenant_id=tenant_uuid,
            user_id=user_id,
        )

        # Score confidence
        entity_name = entities[0].name if entities else None
        confidence = await self.scorer.score(
            signal,
            conflict_result,
            existing_article,
            entity_name,
        )

        # Determine status based on confidence
        if confidence >= settings.CONFIDENCE_THRESHOLD:
            status = ArticleStatus.published
        else:
            status = ArticleStatus.pending_review

        # Create new article version
        version = 1
        if existing_article:
            version = existing_article.version + 1

        # Entities are merged by name, so use the ids the graph actually holds.
        entity_ids = [await queries.create_entity_node(entity) for entity in entities]

        article = Article(
            tenant_id=signal.tenant_id,
            title=synthesis_result.title,
            body=synthesis_result.body,
            version=version,
            status=status,
            confidence=confidence,
            entity_ids=entity_ids,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Write to Neo4j. The new version records what it replaces, but the old version stays
        # live until the new one is published.
        article_id = await queries.create_article_node(article)

        if existing_article:
            await queries.link_supersedes(
                article_id,
                str(existing_article.id),
                synthesis_result.diff_summary,
                signal.tenant_id,
            )

        await queries.create_signal_node(signal)

        for entity_id in entity_ids:
            await queries.link_article_to_entity(article_id, entity_id, signal.tenant_id)

        await queries.link_signal_to_article(
            str(signal.id),
            article_id,
            signal.authority,
            signal.tenant_id,
        )

        # Embed and store article (with usage tracking)
        article_embedding = await embed(
            article.body,
            tenant_id=tenant_uuid,
            user_id=user_id,
        )
        await upsert_embedding(
            article_id=article_id,
            embedding=article_embedding,
            tenant_id=tenant_uuid,
            metadata={
                "type": "article",
                "title": article.title,
                "version": article.version,
            },
        )

        # Publish last, once the new version is retrievable, so there is no gap in coverage.
        if status == ArticleStatus.published:
            await publish_article(article_id, signal.tenant_id)

        # Audit log
        await log_audit(
            tenant_id=tenant_uuid,
            action="article.create",
            actor_id=user_id,
            table_name="articles",
            record_id=article_id,
            status="success",
            new_values={
                "title": article.title,
                "status": status.value,
                "confidence": confidence,
                "version": version,
            },
        )

        logger.info(
            "Signal processed successfully",
            extra={
                "signal_id": str(signal.id),
                "article_id": article_id,
                "status": status.value,
                "confidence": confidence,
            },
        )

        return ProcessResult(
            article_id=article_id,
            status=status,
            confidence=confidence,
            conflict_detected=conflict_result.has_conflict,
            entities=[e.name for e in entities],
            prompt_tokens=synthesis_result.prompt_tokens,
            completion_tokens=synthesis_result.completion_tokens,
        )
