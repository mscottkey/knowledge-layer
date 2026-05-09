import json
from dataclasses import dataclass

from openai import AsyncOpenAI

from models.signals import KnowledgeSignal
from models.articles import Article
from core.config import get_settings
from core.logging import get_logger

logger = get_logger("pipeline.synthesizer")

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


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


class Synthesizer:
    async def synthesize(
        self,
        signal: KnowledgeSignal,
        existing_article: Article | None = None,
    ) -> SynthesisResult:
        settings = get_settings()

        if settings.use_mocks:
            return self._mock_synthesize(signal, existing_article)

        client = _get_client()

        user_content = f"Signal source: {signal.source.value}\n\n"
        user_content += f"Signal content:\n{signal.raw_text}\n\n"

        if existing_article:
            user_content += f"Existing article title: {existing_article.title}\n\n"
            user_content += f"Existing article body:\n{existing_article.body}"
        else:
            user_content += "No existing article. Create a new one."

        response = await client.chat.completions.create(
            model=settings.SYNTHESIS_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty response from synthesis model")

        data = json.loads(content)

        return SynthesisResult(
            title=data.get("title", "Untitled"),
            body=data.get("body", ""),
            diff_summary=data.get("diff_summary", ""),
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

        return SynthesisResult(
            title=title,
            body=body,
            diff_summary=diff_summary,
        )
