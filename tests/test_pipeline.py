import pytest
from datetime import datetime, timezone, timedelta

from models.signals import KnowledgeSignal, SourceType
from models.articles import Article, ArticleStatus
from models.entities import Entity, EntityType
from pipeline.extractor import extract_entities_keyword, extract_entities
from pipeline.embedder import embed, cosine_similarity, is_duplicate
from pipeline.conflict import ConflictDetector, ConflictResult
from pipeline.scorer import ConfidenceScorer


class TestExtractor:
    def test_extract_entities_keyword_feature(self):
        text = "The Dashboard feature is not working properly"
        entities = extract_entities_keyword(text, "tenant-1")

        assert len(entities) > 0
        assert any(e.name == "Dashboard" for e in entities)

    def test_extract_entities_keyword_integration(self):
        text = "We need to fix the Salesforce integration"
        entities = extract_entities_keyword(text, "tenant-1")

        assert len(entities) > 0

    def test_extract_entities_keyword_workflow(self):
        text = "The Approval workflow is broken"
        entities = extract_entities_keyword(text, "tenant-1")

        assert len(entities) > 0

    def test_extract_entities_keyword_empty_text(self):
        entities = extract_entities_keyword("", "tenant-1")
        assert len(entities) == 0

    def test_extract_entities_uses_keyword_in_mock_mode(self):
        text = "The Analytics Dashboard is slow"
        entities = extract_entities(text, "tenant-1")

        assert isinstance(entities, list)


class TestEmbedder:
    @pytest.mark.asyncio
    async def test_embed_returns_vector(self):
        text = "This is a test sentence"
        embedding = await embed(text)

        assert isinstance(embedding, list)
        assert len(embedding) == 3072
        assert all(isinstance(x, float) for x in embedding)

    @pytest.mark.asyncio
    async def test_embed_deterministic_for_same_text(self):
        text = "Deterministic test"
        embedding1 = await embed(text)
        embedding2 = await embed(text)

        assert embedding1 == embedding2

    @pytest.mark.asyncio
    async def test_embed_different_for_different_text(self):
        embedding1 = await embed("First text")
        embedding2 = await embed("Completely different text")

        similarity = cosine_similarity(embedding1, embedding2)
        assert similarity < 1.0

    def test_cosine_similarity_identical(self):
        vec = [1.0, 2.0, 3.0]
        similarity = cosine_similarity(vec, vec)
        assert abs(similarity - 1.0) < 0.0001

    def test_cosine_similarity_orthogonal(self):
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [0.0, 1.0, 0.0]
        similarity = cosine_similarity(vec1, vec2)
        assert abs(similarity) < 0.0001

    def test_is_duplicate_true(self):
        vec = [1.0, 2.0, 3.0]
        existing = [[1.0, 2.0, 3.0]]
        assert is_duplicate(vec, existing, threshold=0.92) is True

    def test_is_duplicate_false(self):
        vec1 = [1.0, 0.0, 0.0]
        existing = [[0.0, 1.0, 0.0]]
        assert is_duplicate(vec1, existing, threshold=0.92) is False


class TestConflictDetector:
    @pytest.mark.asyncio
    async def test_detect_no_entities_no_conflict(self):
        detector = ConflictDetector()
        signal = KnowledgeSignal(
            tenant_id="tenant-1",
            source=SourceType.ticket,
            source_id="ticket-1",
            raw_text="Some text",
            authority=0.7,
        )

        result = await detector.detect(signal, [])

        assert result.has_conflict is False
        assert result.conflicting_article_id is None

    @pytest.mark.asyncio
    async def test_detect_with_entities_no_existing_articles(self):
        detector = ConflictDetector()
        signal = KnowledgeSignal(
            tenant_id="tenant-1",
            source=SourceType.ticket,
            source_id="ticket-1",
            raw_text="The Dashboard feature needs an update",
            authority=0.7,
        )
        entities = [
            Entity(
                tenant_id="tenant-1",
                name="Dashboard",
                type=EntityType.feature,
            )
        ]

        result = await detector.detect(signal, entities)

        assert result.has_conflict is False


class TestConfidenceScorer:
    @pytest.mark.asyncio
    async def test_score_basic(self):
        scorer = ConfidenceScorer()
        signal = KnowledgeSignal(
            tenant_id="tenant-1",
            source=SourceType.pr,
            source_id="pr-1",
            raw_text="Updated the authentication flow",
            authority=1.0,
        )
        conflict_result = ConflictResult(
            has_conflict=False,
            conflicting_article_id=None,
            delta_score=0.0,
        )

        score = await scorer.score(signal, conflict_result)

        assert 0.0 <= score <= 1.0
        assert score > 0.4

    @pytest.mark.asyncio
    async def test_score_with_high_authority(self):
        scorer = ConfidenceScorer()
        pr_signal = KnowledgeSignal(
            tenant_id="tenant-1",
            source=SourceType.pr,
            source_id="pr-1",
            raw_text="Test",
            authority=1.0,
        )
        slack_signal = KnowledgeSignal(
            tenant_id="tenant-1",
            source=SourceType.slack,
            source_id="slack-1",
            raw_text="Test",
            authority=0.5,
        )
        conflict_result = ConflictResult(
            has_conflict=False,
            conflicting_article_id=None,
            delta_score=0.0,
        )

        pr_score = await scorer.score(pr_signal, conflict_result)
        slack_score = await scorer.score(slack_signal, conflict_result)

        assert pr_score > slack_score

    @pytest.mark.asyncio
    async def test_score_recency_matters(self):
        scorer = ConfidenceScorer()
        conflict_result = ConflictResult(
            has_conflict=False,
            conflicting_article_id=None,
            delta_score=0.0,
        )

        recent_signal = KnowledgeSignal(
            tenant_id="tenant-1",
            source=SourceType.ticket,
            source_id="ticket-1",
            raw_text="Test",
            authority=0.7,
            ingested_at=datetime.now(timezone.utc),
        )

        old_signal = KnowledgeSignal(
            tenant_id="tenant-1",
            source=SourceType.ticket,
            source_id="ticket-2",
            raw_text="Test",
            authority=0.7,
            ingested_at=datetime.now(timezone.utc) - timedelta(days=30),
        )

        recent_score = await scorer.score(recent_signal, conflict_result)
        old_score = await scorer.score(old_signal, conflict_result)

        assert recent_score > old_score
