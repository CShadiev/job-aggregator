from config import ConfigProvider
from logger_provider import LoggerProvider
from repository.mongo_jobs_repository import AsyncMongoClient
from pymongo import UpdateOne
from urllib.parse import unquote

log = LoggerProvider.get_logger()


async def clean_uids():
    config = ConfigProvider.get_config()
    mongo_client = AsyncMongoClient(
        host=config.MONGODB_HOST, port=config.MONGODB_PORT, username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD)
    mdb = mongo_client.get_database(config.MONGODB_DATABASE)

    job_updates: list[UpdateOne] = []
    status_updates: list[UpdateOne] = []
    assessment_updates: list[UpdateOne] = []
    existing_jobs = await mdb.get_collection(config.MONGODB_JOBS_COLLECTION).find({"source": "linkedin"}).to_list()

    for job in existing_jobs:
        uid, uid_parsed = job['uid'], unquote(job['uid'])
        if uid != uid_parsed:
            job_updates.append(UpdateOne({'_id': job['_id']}, {'$set': {'uid': uid_parsed}}))
            status_updates.append(UpdateOne({"job_uid": uid}, {'$set': {'job_uid': uid_parsed}}))
            assessment_updates.append(UpdateOne({"job_uid": uid}, {'$set': {'job_uid': uid_parsed}}))

    log.info(f"Found {len(job_updates)} job ids to update")
    for update in job_updates[:10]:
        log.info(f"{update}")

    await mdb.get_collection(config.MONGODB_JOBS_COLLECTION).bulk_write(job_updates)
    await mdb.get_collection(config.MONGODB_JOB_APPLICATIONS_COLLECTION).bulk_write(status_updates)
    await mdb.get_collection(config.MONGODB_ASSESSMENTS_COLLECTION).bulk_write(assessment_updates)


if __name__ == "__main__":
    import asyncio
    asyncio.run(clean_uids())
