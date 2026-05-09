import json
import time
from dataclasses import dataclass
from uuid import UUID

from google import genai
from google.genai import types

from models.signals import KnowledgeSignal
from models.articles import Article
from core.config import get_settings
from core.logging import get_logger
from core.usage import log_ai_usage

logger = get_logger("pipeline.synthesizer")

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        settings = get_settings()
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


SYSTEM_PROMPT = """You are a knowledge base editor. Given a new signal and optionally an existing article, produce an updated article. Be precise, structured, and conservative — do not invent facts not present in the signal.

Return JSON only with keys: title, body, diff_summary.

- title: A concise, descriptive title for the article
- body: The full article content in markdown format
- diff_summary: A brief description of what changed (or "New article" if no existing article)"""


@dataclass
class SynthesisResult:
    title: str
    body: str
    diff_summary: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class Synthesizer:
    async def synthesize(
        self,
        signal: KnowledgeSignal,
        existing_article: Article | None = None,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> SynthesisResult:
        settings = get_settings()

        # Use signal's tenant_id if not provided
        effective_tenant_id = tenant_id
        if effective_tenant_id is None and signal.tenant_id:
            try:
                effective_tenant_id = UUID(signal.tenant_id) if isinstance(signal.tenant_id, str) else signal.tenant_id
            except (ValueError, TypeError):
                effective_tenant_id = None

        if settings.use_mocks:
            result = self._mock_synthesize(signal, existing_article)

            # Log mock usage
            if effective_tenant_id:
                await log_ai_usage(
                    tenant_id=effective_tenant_id,
                    model_name=settings.SYNTHESIS_MODEL,
                    model_provider="google",
                    feature_context="synthesis",
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    user_id=user_id,
                )

            return result

        client = _get_client()
        start_time = time.time()

        user_content = f"Signal source: {signal.source.value}\n\n"
        user_content += f"Signal content:\n{signal.raw_text}\n\n"

        if existing_article:
            user_content += f"Existing article title: {existing_article.title}\n\n"
            user_content += f"Existing article body:\n{existing_article.body}"
        else:
            user_content += "No existing article. Create a new one."

        response = await client.aio.models.generate_content(
            model=settings.SYNTHESIS_MODEL,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=f"{SYSTEM_PROMPT}\n\n{user_content}")]
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )

        latency_ms = int((time.time() - start_time) * 1000)

        content = response.text
        if not content:
            raise ValueError("Empty response from synthesis model")

        data = json.loads(content)

        # Estimate tokens for Gemini (usage metadata may not always be available)
        prompt_tokens = _estimate_tokens(SYSTEM_PROMPT + user_content)
        completion_tokens = _estimate_tokens(content)

        # Use actual usage if available
        if response.usage_metadata:
            prompt_tokens = response.usage_metadata.prompt_token_count or prompt_tokens
            completion_tokens = response.usage_metadata.candidates_token_count or completion_tokens

        # Log AI usage
        if effective_tenant_id:
            await log_ai_usage(
                tenant_id=effective_tenant_id,
                model_name=settings.SYNTHESIS_MODEL,
                model_provider="google",
                feature_context="synthesis",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                user_id=user_id,
                latency_ms=latency_ms,
            )

        return SynthesisResult(
            title=data.get("title", "Untitled"),
            body=data.get("body", ""),
            diff_summary=data.get("diff_summary", ""),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def _mock_synthesize(
        self,
        signal: KnowledgeSignal,
        existing_article: Article | None = None,
    ) -> SynthesisResult:
        if existing_article:
            title = existing_article.title
            body = f"{existing_article.body}\n\n---\n\nUpdated from {signal.source.value}:\n{signal.raw_text}"
            diff_summary = f"Appended content from {signal.source.value} signal"
        else:
            words = signal.raw_text.split()[:5]
            title = " ".join(words) if words else "New Article"
            body = signal.raw_text
            diff_summary = "New article"

        # Estimate tokens for mock
        prompt_tokens = len(signal.raw_text) // 4
        completion_tokens = len(body) // 4

        return SynthesisResult(
            title=title,
            body=body,
            diff_summary=diff_summary,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
