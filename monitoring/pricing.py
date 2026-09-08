"""Model rate cards for LLM cost estimation.

Rates live in the MongoDB ``pricing`` collection so they can be updated without a
deploy, and are served from an in-memory TTL cache. Static defaults cover the models
in :class:`agents.model_factory.Model` so cost accounting keeps working before the
first successful read and whenever MongoDB is unreachable.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Any

from config import Config, ConfigProvider
from logger_provider import LoggerProvider

if TYPE_CHECKING:
    from pymongo import AsyncMongoClient
    from pymongo.asynchronous.collection import AsyncCollection

log = LoggerProvider.get_logger()


@dataclass(frozen=True)
class ModelRate:
    """USD price per one million prompt and completion tokens."""

    input_usd_per_1m: float
    output_usd_per_1m: float


DEFAULT_RATES: dict[str, ModelRate] = {
    "gpt-5.6-luna": ModelRate(input_usd_per_1m=0.20, output_usd_per_1m=1.2),
    "gpt-5-mini": ModelRate(input_usd_per_1m=0.25, output_usd_per_1m=2.0),
    "grok-4.3": ModelRate(input_usd_per_1m=3.0, output_usd_per_1m=15.0),
    "grok-4.5": ModelRate(input_usd_per_1m=3.0, output_usd_per_1m=15.0),
    "text-embedding-3-small": ModelRate(input_usd_per_1m=0.02, output_usd_per_1m=0.0),
}

UNPRICED = ModelRate(input_usd_per_1m=0.0, output_usd_per_1m=0.0)


class PricingCache:
    """Serves model rate cards from a TTL cache over the MongoDB ``pricing`` collection.

    Until :meth:`bind` is called the cache serves ``defaults`` only, which is what
    happens in unit tests and in any process without a MongoDB connection.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float,
        defaults: dict[str, ModelRate] | None = None,
    ) -> None:
        """Initialize the cache with a refresh interval and a static fallback rate card.

        Args:
            ttl_seconds: How long a MongoDB read stays authoritative before a refresh.
            defaults: Fallback rates; defaults to :data:`DEFAULT_RATES`.
        """
        self._ttl = ttl_seconds
        self._defaults = dict(DEFAULT_RATES if defaults is None else defaults)
        self._collection: AsyncCollection | None = None
        self._rates: dict[str, ModelRate] = {}
        self._loaded_at: float | None = None
        self._lock = asyncio.Lock()
        self._unpriced_seen: set[str] = set()

    def bind(self, collection: AsyncCollection) -> None:
        """Point the cache at a MongoDB collection and invalidate anything already cached."""
        self._collection = collection
        self._rates = {}
        self._loaded_at = None

    async def get_rate(self, model_name: str) -> ModelRate:
        """Return the rate card for *model_name*, refreshing from MongoDB when stale.

        Falls back to the static defaults, then to a zero rate for models nobody has
        priced yet — an unknown model costs 0 USD rather than breaking the agent run.
        """
        await self._refresh_if_stale()
        rate = self._rates.get(model_name) or self._defaults.get(model_name)
        if rate is None:
            self._warn_once_unpriced(model_name)
            return UNPRICED
        return rate

    def estimate_cost_usd(self, rate: ModelRate, input_tokens: int, output_tokens: int) -> float:
        """Compute estimated USD spend for a single call against *rate*."""
        return (
            input_tokens * rate.input_usd_per_1m + output_tokens * rate.output_usd_per_1m
        ) / 1_000_000

    async def _refresh_if_stale(self) -> None:
        """Reload rate cards from MongoDB if bound and the TTL has elapsed."""
        if self._collection is None or not self._is_stale():
            return
        async with self._lock:
            if not self._is_stale():
                return
            try:
                self._rates = await self._read_rates(self._collection)
            except Exception as exc:
                log.warning(
                    "Pricing refresh from MongoDB failed, serving cached/default rates: {exc}",
                    exc=str(exc),
                )
            finally:
                # Stamp even on failure so a broken collection is retried once per TTL
                # instead of on every single agent call.
                self._loaded_at = monotonic()

    @staticmethod
    async def _read_rates(collection: AsyncCollection) -> dict[str, ModelRate]:
        """Read every rate card document from the pricing collection."""
        rates: dict[str, ModelRate] = {}
        async for doc in collection.find({}):
            payload: dict[str, Any] = doc
            name = payload.get("model_name")
            if not name:
                continue
            rates[str(name)] = ModelRate(
                input_usd_per_1m=float(payload.get("input_usd_per_1m") or 0.0),
                output_usd_per_1m=float(payload.get("output_usd_per_1m") or 0.0),
            )
        return rates

    def _is_stale(self) -> bool:
        """Report whether the cached rates have aged past the TTL."""
        return self._loaded_at is None or (monotonic() - self._loaded_at) >= self._ttl

    def _warn_once_unpriced(self, model_name: str) -> None:
        """Log the first time a model is seen with no rate card anywhere."""
        if model_name in self._unpriced_seen:
            return
        self._unpriced_seen.add(model_name)
        log.warning(
            "No rate card for model {model}; cost will be reported as 0 USD",
            event="pricing_model_unpriced",
            model=model_name,
        )


_cache: PricingCache | None = None


def get_pricing_cache() -> PricingCache:
    """Return the process-wide pricing cache, creating it on first use."""
    global _cache
    if _cache is None:
        _cache = PricingCache(ttl_seconds=ConfigProvider.get_config().PRICING_CACHE_TTL_SECONDS)
    return _cache


def configure_pricing(client: AsyncMongoClient, *, config: Config | None = None) -> None:
    """Bind the process-wide pricing cache to the ``pricing`` collection of *client*."""
    cfg = config or ConfigProvider.get_config()
    collection = client[cfg.MONGODB_DATABASE][cfg.MONGODB_PRICING_COLLECTION]
    get_pricing_cache().bind(collection)
    log.info(
        "LLM pricing bound to MongoDB collection {collection}",
        event="pricing_configured",
        collection=cfg.MONGODB_PRICING_COLLECTION,
    )
