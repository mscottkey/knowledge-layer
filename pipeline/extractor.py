import re
from typing import Callable

from models.entities import Entity, EntityType
from core.config import get_settings
from core.logging import get_logger

logger = get_logger("pipeline.extractor")

_nlp = None
_use_spacy = True


def _get_spacy_nlp():
    global _nlp, _use_spacy

    if not _use_spacy:
        return None

    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_trf")
            logger.info("Loaded spaCy model en_core_web_trf")
        except (ImportError, OSError) as e:
            logger.warning(f"spaCy model not available: {e}, using keyword fallback")
            _use_spacy = False
            return None

    return _nlp


SPACY_TO_ENTITY_TYPE: dict[str, EntityType] = {
    "PRODUCT": EntityType.feature,
    "ORG": EntityType.integration,
    "EVENT": EntityType.workflow,
    "WORK_OF_ART": EntityType.feature,
    "LAW": EntityType.workflow,
}

INTEGRATION_KEYWORDS = {
    "api", "sdk", "integration", "connector", "webhook", "oauth", "sso",
    "zapier", "slack", "github", "jira", "salesforce", "stripe", "aws",
}

WORKFLOW_KEYWORDS = {
    "process", "workflow", "flow", "pipeline", "automation", "trigger",
    "action", "step", "stage", "approval", "review",
}

BUG_KEYWORDS = {
    "bug", "error", "issue", "crash", "fail", "broken", "fix", "patch",
    "problem", "defect", "regression",
}

FEATURE_KEYWORDS = {
    "feature", "capability", "function", "tool", "option", "setting",
    "dashboard", "report", "analytics", "export", "import",
}


def _classify_entity_type(text: str, surrounding_context: str = "") -> EntityType:
    text_lower = text.lower()
    context_lower = surrounding_context.lower()
    combined = f"{text_lower} {context_lower}"

    if any(kw in combined for kw in BUG_KEYWORDS):
        return EntityType.bug

    if any(kw in combined for kw in INTEGRATION_KEYWORDS):
        return EntityType.integration

    if any(kw in combined for kw in WORKFLOW_KEYWORDS):
        return EntityType.workflow

    return EntityType.feature


def extract_entities_spacy(text: str, tenant_id: str) -> list[Entity]:
    nlp = _get_spacy_nlp()
    if nlp is None:
        return extract_entities_keyword(text, tenant_id)

    doc = nlp(text)
    entities = []
    seen_names: set[str] = set()

    for ent in doc.ents:
        name = ent.text.strip()
        if not name or name.lower() in seen_names:
            continue

        start = max(0, ent.start_char - 50)
        end = min(len(text), ent.end_char + 50)
        context = text[start:end]

        if ent.label_ in SPACY_TO_ENTITY_TYPE:
            entity_type = SPACY_TO_ENTITY_TYPE[ent.label_]
            if entity_type == EntityType.feature:
                entity_type = _classify_entity_type(name, context)
        else:
            entity_type = _classify_entity_type(name, context)

        entities.append(Entity(
            tenant_id=tenant_id,
            name=name,
            type=entity_type,
        ))
        seen_names.add(name.lower())

    if not entities:
        return extract_entities_keyword(text, tenant_id)

    return entities


def extract_entities_keyword(text: str, tenant_id: str) -> list[Entity]:
    entities = []
    seen_names: set[str] = set()

    patterns = [
        (r'\b(?:the\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:feature|tool|dashboard|system)\b', EntityType.feature),
        (r'\b(?:the\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:integration|API|connector)\b', EntityType.integration),
        (r'\b(?:the\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:workflow|process|flow)\b', EntityType.workflow),
        (r'\b(?:the\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:bug|issue|error)\b', EntityType.bug),
    ]

    for pattern, entity_type in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            name = match.group(1).strip()
            if name and name.lower() not in seen_names and len(name) > 2:
                entities.append(Entity(
                    tenant_id=tenant_id,
                    name=name,
                    type=entity_type,
                ))
                seen_names.add(name.lower())

    capitalized_pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b'
    for match in re.finditer(capitalized_pattern, text):
        name = match.group(1).strip()
        if name and name.lower() not in seen_names and len(name) > 2:
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            context = text[start:end]

            entity_type = _classify_entity_type(name, context)
            entities.append(Entity(
                tenant_id=tenant_id,
                name=name,
                type=entity_type,
            ))
            seen_names.add(name.lower())

    return entities[:10]


def extract_entities(text: str, tenant_id: str) -> list[Entity]:
    settings = get_settings()

    if settings.use_mocks:
        return extract_entities_keyword(text, tenant_id)

    return extract_entities_spacy(text, tenant_id)
