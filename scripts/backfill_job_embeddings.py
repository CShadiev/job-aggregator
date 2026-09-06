"""Embed historical Mongo jobs and upsert them into the OpenSearch jobs index."""

from __future__ import annotations

import argparse
import asyncio

from aiohttp import ClientSession
from pymongo import AsyncMongoClient

from config import ConfigProvider
from logger_provider import LoggerProvider
from repository.mongo_jobs_repository import MongoJobsRepository
from search.client import build_opensearch_client
from search.embeddings import EmbeddingClient
from search.models import IndexedJob
from search.search_service import SearchService
from search.text import job_embedding_text

log = LoggerProvider.get_logger()


async def backfill(*, batch_size: int) -> None:
    """Read all jobs from MongoDB, compute OpenAI text embeddings, and bulk index them into OpenSearch.

    Args:
        batch_size: Number of jobs to batch per embedding call and OpenSearch bulk request.
    """
    config = ConfigProvider.get_config()
    mongo = AsyncMongoClient(
        host=config.MONGODB_HOST,
        port=config.MONGODB_PORT,
        username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD,
    )
    search = SearchService(build_opensearch_client(config), config=config)
    try:
        await search.ensure_indices()
        repo = MongoJobsRepository(mongo)
        async with ClientSession() as session:
            embedder = EmbeddingClient(session, config=config)
            batch: list = []
            indexed = 0
            async for posting in repo.iter_jobs():
                batch.append(posting)
                if len(batch) >= batch_size:
                    indexed += await _flush(embedder, search, batch)
                    batch = []
            if batch:
                indexed += await _flush(embedder, search, batch)
        log.info("Backfilled {n} job embeddings", n=indexed)
    finally:
        await search.close()
        await mongo.close()


async def _flush(embedder: EmbeddingClient, search: SearchService, postings: list) -> int:
    """Generate vector embeddings for a chunk of postings and write them to OpenSearch."""
    texts = [job_embedding_text(p.title, p.description_raw) for p in postings]
    vectors = await embedder.embed_texts(texts)
    docs = [
        IndexedJob.from_posting(posting, vector)
        for posting, vector in zip(postings, vectors, strict=True)
    ]
    await search.bulk_index_jobs(docs)
    return len(docs)


def main() -> None:
    """Parse CLI arguments and run the job embedding backfill process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    asyncio.run(backfill(batch_size=args.batch_size))


if __name__ == "__main__":
    main()
