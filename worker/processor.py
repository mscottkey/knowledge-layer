from dataclasses import dataclass
from datetime import datetime, timezone

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
from core.config import get_settings
from core.logging import get_logger

logger = get_logger("worker.processor")


@dataclass
class ProcessResult:
    article_id: str
    status: ArticleStatus
    confidence: float
    conflict_detected: bool
    entities: list[str]


class SignalProcessor:
    def __init__(self) -> None:
        self.conflict_detector = ConflictDetector()
        self.scorer = ConfidenceScorer()
        self.synthesizer = Synthesizer()

    async def process(self, signal: KnowledgeSignal) -> ProcessResult:
        settings = get_settings()

        logger.info(
            "Processing signal",
            extra={"signal_id": str(signal.id), "source": signal.source.value},
        )

        entities = extract_entities(signal.raw_text, signal.tenant_id)
        logger.info(
            "Extracted entities",
            extra={"signal_id": str(signal.id), "count": len(entities)},
        )

        signal_embedding = await embed(signal.raw_text)

        existing_embeddings_data = await get_all_embeddings(signal.tenant_id)
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
            )

        conflict_result = await self.conflict_detector.detect(signal, entities)

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

        synthesis_result = await self.synthesizer.synthesize(signal, existing_article)

        entity_name = entities[0].name if entities else None
        confidence = await self.scorer.score(
            signal,
            conflict_result,
            existing_article,
            entity_name,
        )

        if confidence >= settings.CONFIDENCE_THRESHOLD:
            status = ArticleStatus.published
        else:
            status = ArticleStatus.pending_review

        version = 1
        if existing_article:
            version = existing_article.version + 1

        article = Article(
            tenant_id=signal.tenant_id,
            title=synthesis_result.title,
            body=synthesis_result.body,
            version=version,
            status=status,
            confidence=confidence,
            entity_ids=[str(e.id) for e in entities],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        article_id = await queries.create_article_node(article)

        if existing_article:
            await queries.supersede_article(
                str(existing_article.id),
                article_id,
                synthesis_result.diff_summary,
                signal.tenant_id,
            )

        await queries.create_signal_node(signal)

        for entity in entities:
            entity_id = await queries.create_entity_node(entity)
            await queries.link_article_to_entity(article_id, entity_id, signal.tenant_id)

        await queries.link_signal_to_article(
            str(signal.id),
            article_id,
            signal.authority,
            signal.tenant_id,
        )

        article_embedding = await embed(article.body)
        await upsert_embedding(
            id=article_id,
            embedding=article_embedding,
            tenant_id=signal.tenant_id,
            metadata={
                "type": "article",
                "title": article.title,
                "version": article.version,
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
        )
