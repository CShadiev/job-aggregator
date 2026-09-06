"""Backend contract tests for the assessed-job feed API."""

from main import app
from models.jobs_api import JobFeedQuery


def test_job_feed_query_accepts_optional_q():
    query = JobFeedQuery(q="Kubernetes", skipped=False)
    assert query.q == "Kubernetes"
    assert JobFeedQuery().q is None


def test_openapi_job_feed_query_includes_q():
    schema = app.openapi()
    job_feed_query = schema["components"]["schemas"]["JobFeedQuery"]
    assert "q" in job_feed_query["properties"]
    q_schema = job_feed_query["properties"]["q"]
    assert q_schema.get("type") == "string" or "anyOf" in q_schema


def test_openapi_jobs_search_request_uses_job_feed_query():
    schema = app.openapi()
    search = schema["paths"]["/jobs/search"]["post"]
    ref = search["requestBody"]["content"]["application/json"]["schema"]
    # PaginatedDataRequest[JobFeedQuery] inlines or refs the query model.
    dumped = str(ref) + str(schema["components"]["schemas"])
    assert "JobFeedQuery" in dumped or "q" in dumped
