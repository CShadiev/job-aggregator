"""OpenSearch index mappings for the jobs corpus and assessments feed."""

from __future__ import annotations

JOBS_INDEX_SETTINGS: dict = {
    "settings": {
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": 100,
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "analysis": {
            "analyzer": {
                "job_english": {
                    "type": "standard",
                    "stopwords": "_english_",
                }
            }
        },
    },
    "mappings": {
        "properties": {
            "uid": {"type": "keyword"},
            "title": {"type": "text", "analyzer": "english"},
            "description": {"type": "text", "analyzer": "english"},
            "embedding": {
                "type": "knn_vector",
                "dimension": 1536,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "lucene",
                },
            },
            "source": {"type": "keyword"},
            "company": {"type": "keyword"},
            "location": {"type": "keyword"},
            "url": {"type": "keyword"},
            "job_types": {"type": "keyword"},
            "remote": {"type": "boolean"},
            "posted_at": {"type": "date"},
        }
    },
}

ASSESSMENTS_INDEX_SETTINGS: dict = {
    "settings": {
        "index": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        }
    },
    "mappings": {
        "properties": {
            "username": {"type": "keyword"},
            "job_uid": {"type": "keyword"},
            "cv_ats_match_score": {"type": "float"},
            "profile_ats_match_score": {"type": "float"},
            "deal_breakers": {"type": "keyword"},
            "summary": {"type": "text", "analyzer": "english"},
            "status": {
                "type": "object",
                "properties": {
                    "applied": {"type": "boolean"},
                    "skipped": {"type": "boolean"},
                    "stage": {"type": "keyword"},
                    "active": {"type": "boolean"},
                    "cover_letter_key": {"type": "keyword"},
                    "username": {"type": "keyword"},
                    "job_uid": {"type": "keyword"},
                },
            },
            "job": {
                "type": "object",
                "properties": {
                    "uid": {"type": "keyword"},
                    "title": {"type": "text", "analyzer": "english"},
                    "company": {"type": "text", "analyzer": "english"},
                    "location": {"type": "keyword"},
                    "remote": {"type": "boolean"},
                    "posted_at": {"type": "date"},
                    "description": {"type": "text", "analyzer": "english"},
                    "description_raw": {"type": "text", "index": False},
                    "source": {"type": "keyword"},
                    "url": {"type": "keyword"},
                    "job_types": {"type": "keyword"},
                    "tags": {"type": "keyword"},
                    "collected_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                    "company_normalized": {"type": "keyword"},
                    "title_normalized": {"type": "keyword"},
                },
            },
        }
    },
}
