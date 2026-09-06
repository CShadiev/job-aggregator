"""OpenAI embedding client with a process-level profile-vector cache."""

from __future__ import annotations

from collections.abc import Sequence

from aiohttp import ClientSession

from config import Config, ConfigProvider
from logger_provider import LoggerProvider
from models.users import UserProfile
from search.text import flatten_profile, profile_text_hash

log = LoggerProvider.get_logger()

_OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
_profile_vector_cache: dict[str, list[float]] = {}


class EmbeddingClient:
    """Batches ``text-embedding-3-small`` requests over a shared aiohttp session."""

    def __init__(
        self,
        session: ClientSession,
        *,
        api_key: str | None = None,
        model: str | None = None,
        batch_size: int | None = None,
        config: Config | None = None,
    ) -> None:
        cfg = config or ConfigProvider.get_config()
        self._session = session
        self._api_key = api_key or cfg.OPENAI_API_KEY
        self._model = model or cfg.EMBEDDING_MODEL
        self._batch_size = batch_size or cfg.EMBEDDING_BATCH_SIZE

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def embed_profile(self, profile: UserProfile) -> list[float]:
        text = flatten_profile(profile)
        digest = profile_text_hash(text)
        cached = _profile_vector_cache.get(digest)
        if cached is not None:
            return cached
        vector = (await self.embed_texts([text]))[0]
        _profile_vector_cache[digest] = vector
        return vector

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self._model, "input": texts}
        async with self._session.post(
            _OPENAI_EMBEDDINGS_URL, json=payload, headers=headers
        ) as response:
            body = await response.json(content_type=None)
            if response.status >= 400:
                message = body.get("error", {}).get("message") if isinstance(body, dict) else body
                raise RuntimeError(f"OpenAI embeddings failed ({response.status}): {message}")
        items = sorted(body["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in items]


def clear_profile_embedding_cache() -> None:
    """Reset the process-level cache (tests)."""
    _profile_vector_cache.clear()
