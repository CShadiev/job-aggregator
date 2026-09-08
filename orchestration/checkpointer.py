"""LangGraph MongoDB checkpointer instrumented with write-latency metrics."""

from __future__ import annotations

from time import perf_counter

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import ChannelVersions, Checkpoint, CheckpointMetadata
from langgraph.checkpoint.mongodb import MongoDBSaver

from monitoring.metrics import mongo_checkpoint_duration_seconds


class InstrumentedMongoDBSaver(MongoDBSaver):
    """MongoDBSaver that reports checkpoint write latency to Prometheus.

    Only ``put`` is overridden: ``aput`` runs it in an executor thread, so both the
    sync and async write paths are covered by the single override.
    """

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Persist a checkpoint, observing how long the MongoDB write took."""
        start = perf_counter()
        try:
            return super().put(config, checkpoint, metadata, new_versions)
        finally:
            mongo_checkpoint_duration_seconds.observe(perf_counter() - start)
