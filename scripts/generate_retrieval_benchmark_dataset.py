"""Generate or export a comprehensive retrieval benchmark dataset.

Connects to MongoDB when available or falls back to committed historical
benchmark datasets (benchmarks/screening and benchmarks/fit_assessment).
Constructs a gold-standard dataset of ~100 queries and ~387 corpus documents
with precomputed 1536-d embeddings (via OpenAI text-embedding-3-small or
deterministic unit vectors for offline use) and multi-graded relevance labels (Q8).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import shutil
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp
from pymongo import AsyncMongoClient

from benchmarks.retrieval.dataset import load_dataset
from benchmarks.retrieval.labels import ats_score_to_grade
from config import ConfigProvider
from logger_provider import LoggerProvider
from models.users import UserProfile
from search.embeddings import EmbeddingClient
from search.text import flatten_profile, job_embedding_text, strip_html

log = LoggerProvider.get_logger()

_DIM = 1536
_DEFAULT_ROOT = Path("benchmarks/retrieval/dataset")
_DEFAULT_SCREENING_ENTRIES = Path("benchmarks/screening/dataset/05082026/entries.jsonl")
_DEFAULT_FIT_ENTRIES = Path("benchmarks/fit_assessment/dataset/01082026/entries.jsonl")
_DEFAULT_PROFILE_JSON = Path("benchmarks/fit_assessment/dataset/01082026/profile.json")


def _utc_today_ddmmyyyy() -> str:
    return datetime.now(UTC).strftime("%d%m%Y")


@dataclass
class RawJobCandidate:
    uid: str
    title: str
    description_raw: str
    company: str = ""
    location: str = ""
    remote: bool = False
    source: str = "synthetic"
    url: str = ""
    posted_at: str = "2026-01-01T00:00:00Z"
    cv_ats_match_score: float | None = None
    profile_ats_match_score: float | None = None
    worth_full_assessment: bool = False

    @property
    def clean_description(self) -> str:
        return strip_html(self.description_raw)

    @property
    def embedding_text(self) -> str:
        return job_embedding_text(self.title, self.description_raw)

    @property
    def ats_score(self) -> float | None:
        if self.profile_ats_match_score is not None:
            return self.profile_ats_match_score
        return self.cv_ats_match_score


def _deterministic_unit_vector(seed: str) -> list[float]:
    """Generate a deterministic 1536-d unit vector from a seed string."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    values: list[float] = []
    counter = 0
    while len(values) < _DIM:
        block = hashlib.sha256(digest + struct.pack(">I", counter)).digest()
        for i in range(0, len(block), 4):
            if len(values) >= _DIM:
                break
            unsigned = int.from_bytes(block[i : i + 4], "big")
            values.append((unsigned / 0xFFFFFFFF) * 2.0 - 1.0)
        counter += 1
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def _grade_job_by_rules(
    job: RawJobCandidate,
    *,
    role_terms: list[str],
    primary_tech: list[str],
    secondary_tech: list[str] | None = None,
    exclude_terms: list[str] | None = None,
) -> int:
    """Assign multi-graded relevance (0-3) based on role title and technology match."""
    t = job.title.lower()
    d = job.clean_description.lower()

    if exclude_terms and any(term.lower() in t for term in exclude_terms):
        return 0

    role_hits = sum(1 for term in role_terms if term.lower() in t)
    prim_hits = sum(1 for tech in primary_tech if tech.lower() in d)
    sec_hits = sum(1 for tech in (secondary_tech or []) if tech.lower() in d)

    # Grade 3: Perfect / strong match (title matches role AND core tech strongly present)
    if role_hits >= len(role_terms) and prim_hits >= max(1, len(primary_tech) // 2):
        return 3

    # Grade 2: Relevant (title matches role, or strong tech match with partial role match)
    if role_hits >= len(role_terms) or (role_hits >= 1 and prim_hits >= 1):
        return 2
    if prim_hits >= max(2, len(primary_tech)):
        return 2

    # Grade 1: Marginally relevant (partial role match or secondary tech match)
    if role_hits >= 1 or prim_hits >= 1 or sec_hits >= 2:
        return 1

    return 0


# Catalog of 100 benchmark queries with query text and evaluation rules
_QUERY_DEFINITIONS: list[dict[str, Any]] = [
    # --- Candidate Personas (q001 - q006) ---
    {
        "id": "q001",
        "type": "candidate_profile",
        "text": "__PROFILE_FULL__",  # replaced dynamically by flatten_profile(profile)
    },
    {
        "id": "q002",
        "type": "persona",
        "text": "Backend Engineer Python FastAPI SQLAlchemy Pydantic RESTful APIs async microservices",
        "roles": ["backend", "python"],
        "primary": ["fastapi", "sqlalchemy", "pydantic"],
        "secondary": ["async", "microservices", "docker"],
        "exclude": ["frontend", "angular", "ios", "android"],
    },
    {
        "id": "q003",
        "type": "persona",
        "text": "Full-Stack Engineer React TypeScript Python FastAPI Redux TanStack Query",
        "roles": ["full", "stack"],
        "primary": ["react", "typescript", "python"],
        "secondary": ["fastapi", "redux", "api"],
        "exclude": ["ios", "android", "embedded"],
    },
    {
        "id": "q004",
        "type": "persona",
        "text": "AI Application Developer LangChain LangGraph RAG systems Vector Databases Agentic AI",
        "roles": ["ai"],
        "primary": ["rag", "llm", "langchain"],
        "secondary": ["embeddings", "vector", "python"],
        "exclude": ["sales", "recruiter"],
    },
    {
        "id": "q005",
        "type": "persona",
        "text": "Cloud Software Engineer AWS Docker GitHub Actions CI/CD RabbitMQ Nginx",
        "roles": ["cloud"],
        "primary": ["aws", "docker", "ci/cd"],
        "secondary": ["terraform", "kubernetes", "linux"],
        "exclude": ["marketing", "sales"],
    },
    {
        "id": "q006",
        "type": "persona",
        "text": "Fintech Software Engineer Python CFA MSc Finance quantitative analytics trading platforms",
        "roles": ["engineer"],
        "primary": ["python", "finance", "fintech"],
        "secondary": ["banking", "trading", "sql"],
        "exclude": ["hardware", "construction"],
    },
    # --- Python & Backend Architecture (q007 - q021) ---
    {
        "id": "q007",
        "type": "search",
        "text": "Senior Python Backend Engineer FastAPI Docker PostgreSQL",
        "roles": ["senior", "python"],
        "primary": ["fastapi", "docker", "postgresql"],
        "secondary": ["backend", "microservices"],
        "exclude": ["frontend"],
    },
    {
        "id": "q008",
        "type": "search",
        "text": "Python Django Developer REST API Celery Redis",
        "roles": ["python", "developer"],
        "primary": ["django", "rest", "api"],
        "secondary": ["celery", "redis", "postgresql"],
        "exclude": ["angular"],
    },
    {
        "id": "q009",
        "type": "search",
        "text": "Backend Engineer Python microservices distributed systems",
        "roles": ["backend", "engineer"],
        "primary": ["python", "microservices"],
        "secondary": ["distributed", "docker", "kubernetes"],
        "exclude": ["ios"],
    },
    {
        "id": "q010",
        "type": "search",
        "text": "Async Python Developer asyncio FastAPI high-throughput",
        "roles": ["python"],
        "primary": ["fastapi", "asyncio"],
        "secondary": ["python", "backend", "performance"],
        "exclude": ["frontend"],
    },
    {
        "id": "q011",
        "type": "search",
        "text": "Python API Developer Flask SQLAlchemy PostgreSQL",
        "roles": ["python"],
        "primary": ["flask", "api", "sqlalchemy"],
        "secondary": ["postgresql", "rest"],
        "exclude": ["android"],
    },
    {
        "id": "q012",
        "type": "search",
        "text": "Lead Python Software Engineer system architecture scalable backend",
        "roles": ["lead", "python"],
        "primary": ["architecture", "backend", "python"],
        "secondary": ["scalability", "cloud"],
        "exclude": ["junior"],
    },
    {
        "id": "q013",
        "type": "search",
        "text": "Python Developer event-driven architecture Kafka RabbitMQ",
        "roles": ["python"],
        "primary": ["kafka", "rabbitmq"],
        "secondary": ["event-driven", "backend"],
        "exclude": ["mobile"],
    },
    {
        "id": "q014",
        "type": "search",
        "text": "Staff Backend Engineer Python distributed databases performance",
        "roles": ["staff", "backend"],
        "primary": ["python", "distributed", "databases"],
        "secondary": ["performance", "scaling"],
        "exclude": ["intern"],
    },
    {
        "id": "q015",
        "type": "search",
        "text": "Python Cloud Developer AWS serverless Lambda API Gateway",
        "roles": ["python"],
        "primary": ["aws", "lambda", "serverless"],
        "secondary": ["cloud", "api gateway"],
        "exclude": ["hardware"],
    },
    {
        "id": "q016",
        "type": "search",
        "text": "Backend Software Engineer Python gRPC protocol buffers",
        "roles": ["backend"],
        "primary": ["python", "grpc"],
        "secondary": ["microservices", "api"],
        "exclude": ["design"],
    },
    {
        "id": "q017",
        "type": "search",
        "text": "Junior Python Developer backend API web development",
        "roles": ["junior", "python"],
        "primary": ["python", "api"],
        "secondary": ["web", "backend"],
        "exclude": ["principal", "staff"],
    },
    {
        "id": "q018",
        "type": "search",
        "text": "Python Backend Developer relational databases SQL indexing",
        "roles": ["python", "backend"],
        "primary": ["sql", "databases"],
        "secondary": ["postgresql", "mysql"],
        "exclude": ["frontend"],
    },
    {
        "id": "q019",
        "type": "search",
        "text": "Senior Python Developer Docker Kubernetes microservices",
        "roles": ["senior", "python"],
        "primary": ["docker", "kubernetes"],
        "secondary": ["microservices", "ci/cd"],
        "exclude": ["intern"],
    },
    {
        "id": "q020",
        "type": "search",
        "text": "Python Integration Engineer third-party APIs REST OAuth",
        "roles": ["integration"],
        "primary": ["python", "api"],
        "secondary": ["rest", "oauth"],
        "exclude": ["graphic"],
    },
    {
        "id": "q021",
        "type": "search",
        "text": "Python Backend Softwareentwickler Django FastAPI remote",
        "roles": ["entwickler", "python"],
        "primary": ["fastapi", "django"],
        "secondary": ["remote", "backend"],
        "exclude": ["ios"],
    },
    # --- Full Stack Engineering (q022 - q036) ---
    {
        "id": "q022",
        "type": "search",
        "text": "Full Stack Developer React TypeScript Python FastAPI",
        "roles": ["full", "stack"],
        "primary": ["react", "typescript", "python"],
        "secondary": ["fastapi", "rest"],
        "exclude": ["ios"],
    },
    {
        "id": "q023",
        "type": "search",
        "text": "Senior Full Stack Engineer React Node.js TypeScript AWS",
        "roles": ["senior", "full", "stack"],
        "primary": ["react", "node", "typescript"],
        "secondary": ["aws", "cloud"],
        "exclude": ["embedded"],
    },
    {
        "id": "q024",
        "type": "search",
        "text": "Full Stack Developer Vue.js Python Django PostgreSQL",
        "roles": ["full", "stack"],
        "primary": ["vue", "python"],
        "secondary": ["django", "postgresql"],
        "exclude": ["flutter"],
    },
    {
        "id": "q025",
        "type": "search",
        "text": "Fullstack Developer Next.js TypeScript Tailwind CSS Node",
        "roles": ["fullstack"],
        "primary": ["next.js", "typescript"],
        "secondary": ["node", "tailwind"],
        "exclude": ["c++"],
    },
    {
        "id": "q026",
        "type": "search",
        "text": "Full Stack Software Engineer React Python Docker REST API",
        "roles": ["full", "stack"],
        "primary": ["react", "python", "docker"],
        "secondary": ["api", "rest"],
        "exclude": ["driver"],
    },
    {
        "id": "q027",
        "type": "search",
        "text": "Senior Fullstack Entwickler Java Spring Boot React",
        "roles": ["senior", "fullstack"],
        "primary": ["java", "spring", "react"],
        "secondary": ["boot", "microservices"],
        "exclude": ["ruby"],
    },
    {
        "id": "q028",
        "type": "search",
        "text": "Full Stack Web Developer Angular TypeScript Node.js",
        "roles": ["full", "stack"],
        "primary": ["angular", "typescript"],
        "secondary": ["node", "web"],
        "exclude": ["c++"],
    },
    {
        "id": "q029",
        "type": "search",
        "text": "Fullstack Engineer modern web applications CI/CD cloud",
        "roles": ["fullstack"],
        "primary": ["web", "cloud"],
        "secondary": ["ci/cd", "javascript"],
        "exclude": ["hardware"],
    },
    {
        "id": "q030",
        "type": "search",
        "text": "Lead Full Stack Developer React TypeScript Node architecture",
        "roles": ["lead", "full"],
        "primary": ["react", "typescript", "architecture"],
        "secondary": ["node", "leadership"],
        "exclude": ["intern"],
    },
    {
        "id": "q031",
        "type": "search",
        "text": "Junior Full Stack Developer JavaScript Python web apps",
        "roles": ["junior", "full"],
        "primary": ["javascript", "python"],
        "secondary": ["web", "html", "css"],
        "exclude": ["principal", "staff"],
    },
    {
        "id": "q032",
        "type": "search",
        "text": "Fullstack Entwickler TypeScript Node.js React cloud-native",
        "roles": ["fullstack", "entwickler"],
        "primary": ["typescript", "node", "react"],
        "secondary": ["cloud", "docker"],
        "exclude": ["cobol"],
    },
    {
        "id": "q033",
        "type": "search",
        "text": "Full Stack Developer GraphQL React Node TypeScript",
        "roles": ["full", "stack"],
        "primary": ["graphql", "react"],
        "secondary": ["typescript", "node"],
        "exclude": ["assembly"],
    },
    {
        "id": "q034",
        "type": "search",
        "text": "Full Stack Engineer micro-frontends microservices cloud",
        "roles": ["full", "stack"],
        "primary": ["microservices", "cloud"],
        "secondary": ["frontend", "backend"],
        "exclude": ["mainframe"],
    },
    {
        "id": "q035",
        "type": "search",
        "text": "Senior Fullstack Developer PHP Laravel Vue.js",
        "roles": ["fullstack"],
        "primary": ["php", "vue"],
        "secondary": ["laravel", "javascript"],
        "exclude": ["c#"],
    },
    {
        "id": "q036",
        "type": "search",
        "text": "Full Stack Software Engineer Kotlin React cloud platforms",
        "roles": ["full", "stack"],
        "primary": ["kotlin", "react"],
        "secondary": ["cloud", "api"],
        "exclude": ["perl"],
    },
    # --- AI, Machine Learning & NLP (q037 - q050) ---
    {
        "id": "q037",
        "type": "search",
        "text": "AI Engineer LangChain LangGraph RAG LLMs",
        "roles": ["ai", "engineer"],
        "primary": ["langchain", "rag", "llm"],
        "secondary": ["python", "embeddings"],
        "exclude": ["hardware"],
    },
    {
        "id": "q038",
        "type": "search",
        "text": "Machine Learning Engineer PyTorch NLP embeddings retrieval",
        "roles": ["machine", "learning"],
        "primary": ["pytorch", "nlp", "embeddings"],
        "secondary": ["retrieval", "python"],
        "exclude": ["frontend"],
    },
    {
        "id": "q039",
        "type": "search",
        "text": "Senior GenAI Engineer Large Language Models RAG Python",
        "roles": ["genai"],
        "primary": ["rag", "python", "llm"],
        "secondary": ["openai", "embeddings"],
        "exclude": ["sales"],
    },
    {
        "id": "q040",
        "type": "search",
        "text": "Applied AI Engineer autonomous agents LLM workflow automation",
        "roles": ["ai", "engineer"],
        "primary": ["agents", "llm", "automation"],
        "secondary": ["python", "workflows"],
        "exclude": ["accounting"],
    },
    {
        "id": "q041",
        "type": "search",
        "text": "NLP Research Engineer transformers embeddings semantic search",
        "roles": ["nlp"],
        "primary": ["transformers", "embeddings"],
        "secondary": ["search", "pytorch"],
        "exclude": ["mobile"],
    },
    {
        "id": "q042",
        "type": "search",
        "text": "AI Software Engineer generative AI prompt engineering vector database",
        "roles": ["ai"],
        "primary": ["generative", "vector"],
        "secondary": ["python", "prompt"],
        "exclude": ["qa"],
    },
    {
        "id": "q043",
        "type": "search",
        "text": "Voice AI Engineer speech recognition audio models streaming",
        "roles": ["voice", "ai"],
        "primary": ["audio", "speech"],
        "secondary": ["streaming", "python"],
        "exclude": ["web"],
    },
    {
        "id": "q044",
        "type": "search",
        "text": "Agentic Systems Engineer multi-agent workflows tool calling",
        "roles": ["agentic"],
        "primary": ["agent", "workflow"],
        "secondary": ["python", "llm"],
        "exclude": ["recruiting"],
    },
    {
        "id": "q045",
        "type": "search",
        "text": "Staff AI Research Engineer LLM pre-training fine-tuning",
        "roles": ["research", "engineer"],
        "primary": ["llm", "pre-training"],
        "secondary": ["fine-tuning", "gpu"],
        "exclude": ["intern"],
    },
    {
        "id": "q046",
        "type": "search",
        "text": "Computer Vision Engineer PyTorch OpenCV image processing",
        "roles": ["vision"],
        "primary": ["opencv", "pytorch"],
        "secondary": ["image", "deep learning"],
        "exclude": ["php"],
    },
    {
        "id": "q047",
        "type": "search",
        "text": "Junior AI Developer Python machine learning data science",
        "roles": ["junior", "ai"],
        "primary": ["python", "machine learning"],
        "secondary": ["data", "models"],
        "exclude": ["staff", "principal"],
    },
    {
        "id": "q048",
        "type": "search",
        "text": "AI Evaluation Engineer model benchmarking LLM assessment",
        "roles": ["ai"],
        "primary": ["benchmark", "evaluation"],
        "secondary": ["llm", "testing"],
        "exclude": ["construction"],
    },
    {
        "id": "q049",
        "type": "search",
        "text": "MLOps Engineer model deployment Triton MLflow Docker",
        "roles": ["mlops"],
        "primary": ["docker", "deployment"],
        "secondary": ["triton", "mlflow", "python"],
        "exclude": ["frontend"],
    },
    {
        "id": "q050",
        "type": "search",
        "text": "AI Solutions Architect enterprise LLM integration cloud",
        "roles": ["architect"],
        "primary": ["ai", "cloud"],
        "secondary": ["llm", "integration"],
        "exclude": ["junior"],
    },
    # --- Cloud, Platform, DevOps & SRE (q051 - q064) ---
    {
        "id": "q051",
        "type": "search",
        "text": "Cloud Engineer AWS Terraform Infrastructure as Code",
        "roles": ["cloud", "engineer"],
        "primary": ["aws", "terraform"],
        "secondary": ["infrastructure", "iac"],
        "exclude": ["designer"],
    },
    {
        "id": "q052",
        "type": "search",
        "text": "DevOps Engineer Kubernetes CI/CD GitHub Actions Docker",
        "roles": ["devops", "engineer"],
        "primary": ["kubernetes", "ci/cd", "docker"],
        "secondary": ["github actions", "linux"],
        "exclude": ["sales"],
    },
    {
        "id": "q053",
        "type": "search",
        "text": "Site Reliability Engineer SRE Kubernetes Prometheus Grafana",
        "roles": ["reliability", "engineer"],
        "primary": ["kubernetes", "prometheus"],
        "secondary": ["grafana", "sre", "monitoring"],
        "exclude": ["marketing"],
    },
    {
        "id": "q054",
        "type": "search",
        "text": "Platform Engineer Kubernetes Terraform Go cloud infrastructure",
        "roles": ["platform", "engineer"],
        "primary": ["kubernetes", "terraform"],
        "secondary": ["go", "cloud", "infra"],
        "exclude": ["recruiter"],
    },
    {
        "id": "q055",
        "type": "search",
        "text": "Senior Cloud Architect AWS Azure GCP multi-cloud",
        "roles": ["cloud", "architect"],
        "primary": ["aws", "azure", "gcp"],
        "secondary": ["architecture", "cloud"],
        "exclude": ["intern"],
    },
    {
        "id": "q056",
        "type": "search",
        "text": "DevOps Infrastructure Engineer Linux automation Ansible",
        "roles": ["devops"],
        "primary": ["linux", "automation"],
        "secondary": ["ansible", "ci/cd"],
        "exclude": ["frontend"],
    },
    {
        "id": "q057",
        "type": "search",
        "text": "Cloud Security Engineer AWS IAM threat modeling compliance",
        "roles": ["security"],
        "primary": ["aws", "security"],
        "secondary": ["iam", "compliance"],
        "exclude": ["artist"],
    },
    {
        "id": "q058",
        "type": "search",
        "text": "Kubernetes Platform Engineer cluster management Helm GitOps",
        "roles": ["kubernetes"],
        "primary": ["helm", "gitops"],
        "secondary": ["cluster", "platform"],
        "exclude": ["sales"],
    },
    {
        "id": "q059",
        "type": "search",
        "text": "Senior DevOps Engineer AWS Terraform CI/CD pipeline optimization",
        "roles": ["senior", "devops"],
        "primary": ["aws", "terraform", "ci/cd"],
        "secondary": ["pipeline", "docker"],
        "exclude": ["intern"],
    },
    {
        "id": "q060",
        "type": "search",
        "text": "Cloud Native Engineer microservices service mesh Envoy",
        "roles": ["cloud"],
        "primary": ["microservices", "cloud"],
        "secondary": ["mesh", "docker"],
        "exclude": ["lawyer"],
    },
    {
        "id": "q061",
        "type": "search",
        "text": "Build and Release Engineer GitHub Actions Docker packaging",
        "roles": ["release"],
        "primary": ["github actions", "docker"],
        "secondary": ["build", "ci/cd"],
        "exclude": ["accountant"],
    },
    {
        "id": "q062",
        "type": "search",
        "text": "Observability Engineer OpenTelemetry Prometheus Jaeger logging",
        "roles": ["engineer"],
        "primary": ["prometheus", "monitoring"],
        "secondary": ["opentelemetry", "logging"],
        "exclude": ["dentist"],
    },
    {
        "id": "q063",
        "type": "search",
        "text": "Infrastructure Platform Developer Go Python Kubernetes",
        "roles": ["infrastructure"],
        "primary": ["python", "kubernetes"],
        "secondary": ["go", "docker"],
        "exclude": ["receptionist"],
    },
    {
        "id": "q064",
        "type": "search",
        "text": "Lead DevOps Architect enterprise cloud migration Terraform",
        "roles": ["lead", "devops"],
        "primary": ["terraform", "cloud"],
        "secondary": ["migration", "architecture"],
        "exclude": ["junior"],
    },
    # --- Data Engineering & Analytics (q065 - q076) ---
    {
        "id": "q065",
        "type": "search",
        "text": "Data Engineer Spark Airflow ETL Pipeline SQL",
        "roles": ["data", "engineer"],
        "primary": ["spark", "airflow", "sql"],
        "secondary": ["etl", "pipeline", "python"],
        "exclude": ["ios"],
    },
    {
        "id": "q066",
        "type": "search",
        "text": "Senior Data Engineer Google Cloud Platform BigQuery Python",
        "roles": ["senior", "data", "engineer"],
        "primary": ["gcp", "bigquery", "python"],
        "secondary": ["cloud", "sql"],
        "exclude": ["frontend"],
    },
    {
        "id": "q067",
        "type": "search",
        "text": "Analytics Engineer dbt Snowflake SQL data modeling",
        "roles": ["analytics"],
        "primary": ["dbt", "snowflake", "sql"],
        "secondary": ["modeling", "warehouse"],
        "exclude": ["mobile"],
    },
    {
        "id": "q068",
        "type": "search",
        "text": "Data Platform Engineer Python SQL Cloud Data Warehouse",
        "roles": ["data", "platform"],
        "primary": ["python", "sql"],
        "secondary": ["warehouse", "cloud"],
        "exclude": ["design"],
    },
    {
        "id": "q069",
        "type": "search",
        "text": "Real-time Streaming Data Engineer Kafka Flink Spark",
        "roles": ["data", "engineer"],
        "primary": ["kafka", "streaming"],
        "secondary": ["spark", "real-time"],
        "exclude": ["frontend"],
    },
    {
        "id": "q070",
        "type": "search",
        "text": "Data Pipeline Developer Python Airflow PostgreSQL",
        "roles": ["data"],
        "primary": ["python", "airflow"],
        "secondary": ["postgresql", "pipeline"],
        "exclude": ["android"],
    },
    {
        "id": "q071",
        "type": "search",
        "text": "Lead Data Engineer data architecture lakehouse Databricks",
        "roles": ["lead", "data"],
        "primary": ["lakehouse", "databricks"],
        "secondary": ["architecture", "spark"],
        "exclude": ["junior"],
    },
    {
        "id": "q072",
        "type": "search",
        "text": "Big Data Engineer Hadoop Spark Scala distributed computing",
        "roles": ["big", "data"],
        "primary": ["hadoop", "spark"],
        "secondary": ["scala", "distributed"],
        "exclude": ["vue"],
    },
    {
        "id": "q073",
        "type": "search",
        "text": "Data Integration Specialist ETL REST APIs SQL Server",
        "roles": ["data", "integration"],
        "primary": ["etl", "sql"],
        "secondary": ["api", "database"],
        "exclude": ["graphic"],
    },
    {
        "id": "q074",
        "type": "search",
        "text": "Senior Analytics Developer Looker Tableau SQL dashboarding",
        "roles": ["analytics"],
        "primary": ["sql", "dashboard"],
        "secondary": ["looker", "tableau"],
        "exclude": ["embedded"],
    },
    {
        "id": "q075",
        "type": "search",
        "text": "Data Warehouse Architect Snowflake dimensional modeling ETL",
        "roles": ["warehouse", "architect"],
        "primary": ["snowflake", "modeling"],
        "secondary": ["etl", "sql"],
        "exclude": ["intern"],
    },
    {
        "id": "q076",
        "type": "search",
        "text": "Database Administrator PostgreSQL MySQL performance tuning",
        "roles": ["database"],
        "primary": ["postgresql", "mysql"],
        "secondary": ["performance", "sql"],
        "exclude": ["frontend"],
    },
    # --- Java, Go, C# & Enterprise Backend (q077 - q088) ---
    {
        "id": "q077",
        "type": "search",
        "text": "Senior Java Backend Developer Spring Boot Microservices Kafka",
        "roles": ["senior", "java"],
        "primary": ["spring", "boot", "microservices"],
        "secondary": ["kafka", "backend"],
        "exclude": ["php"],
    },
    {
        "id": "q078",
        "type": "search",
        "text": "Java Software Engineer Spring Cloud PostgreSQL REST",
        "roles": ["java"],
        "primary": ["spring", "postgresql"],
        "secondary": ["rest", "cloud"],
        "exclude": ["ruby"],
    },
    {
        "id": "q079",
        "type": "search",
        "text": "Principal Backend Developer Java Microservices Cloud Fintech",
        "roles": ["principal", "backend"],
        "primary": ["java", "microservices"],
        "secondary": ["cloud", "fintech"],
        "exclude": ["junior"],
    },
    {
        "id": "q080",
        "type": "search",
        "text": "Golang Backend Developer Cloud Microservices Go",
        "roles": ["backend", "developer"],
        "primary": ["go", "golang"],
        "secondary": ["cloud", "microservices"],
        "exclude": ["php"],
    },
    {
        "id": "q081",
        "type": "search",
        "text": "Senior Go Engineer distributed systems concurrent networking",
        "roles": ["senior", "engineer"],
        "primary": ["go", "golang"],
        "secondary": ["distributed", "concurrency"],
        "exclude": ["junior"],
    },
    {
        "id": "q082",
        "type": "search",
        "text": "C# .NET Backend Developer Azure Microservices Kubernetes",
        "roles": ["backend"],
        "primary": ["c#", ".net", "azure"],
        "secondary": ["microservices", "kubernetes"],
        "exclude": ["python"],
    },
    {
        "id": "q083",
        "type": "search",
        "text": "Senior Software Developer C# .NET Core SQL Server",
        "roles": ["senior", "software", "developer"],
        "primary": ["c#", ".net"],
        "secondary": ["sql server", "core"],
        "exclude": ["intern"],
    },
    {
        "id": "q084",
        "type": "search",
        "text": "Kotlin Backend Developer Spring Boot WebFlux Microservices",
        "roles": ["kotlin"],
        "primary": ["spring", "boot"],
        "secondary": ["microservices", "backend"],
        "exclude": ["ruby"],
    },
    {
        "id": "q085",
        "type": "search",
        "text": "Rust Systems Engineer performance low-latency concurrency",
        "roles": ["rust"],
        "primary": ["systems", "performance"],
        "secondary": ["concurrency", "low-latency"],
        "exclude": ["php"],
    },
    {
        "id": "q086",
        "type": "search",
        "text": "Enterprise Application Developer Java Spring Boot Oracle",
        "roles": ["java", "developer"],
        "primary": ["spring", "boot"],
        "secondary": ["oracle", "enterprise"],
        "exclude": ["flutter"],
    },
    {
        "id": "q087",
        "type": "search",
        "text": "Scala Backend Engineer functional programming Akka Kafka",
        "roles": ["scala"],
        "primary": ["functional", "kafka"],
        "secondary": ["backend", "distributed"],
        "exclude": ["php"],
    },
    {
        "id": "q088",
        "type": "search",
        "text": "C++ Software Engineer high performance multithreading Linux",
        "roles": ["c++"],
        "primary": ["performance", "linux"],
        "secondary": ["multithreading", "systems"],
        "exclude": ["html"],
    },
    # --- Frontend & Mobile (q089 - q094) ---
    {
        "id": "q089",
        "type": "search",
        "text": "Senior Frontend Engineer React TypeScript modern web",
        "roles": ["senior", "frontend"],
        "primary": ["react", "typescript"],
        "secondary": ["web", "css"],
        "exclude": ["embedded"],
    },
    {
        "id": "q090",
        "type": "search",
        "text": "Frontend Developer Next.js Tailwind CSS design systems",
        "roles": ["frontend"],
        "primary": ["next.js", "tailwind"],
        "secondary": ["css", "design"],
        "exclude": ["database"],
    },
    {
        "id": "q091",
        "type": "search",
        "text": "Web Frontend Entwickler Micro-Frontends TypeScript",
        "roles": ["frontend", "entwickler"],
        "primary": ["typescript", "frontend"],
        "secondary": ["web", "architecture"],
        "exclude": ["c++"],
    },
    {
        "id": "q092",
        "type": "search",
        "text": "Frontend UI UX Developer React Component Libraries",
        "roles": ["frontend"],
        "primary": ["react", "ui"],
        "secondary": ["components", "ux"],
        "exclude": ["driver"],
    },
    {
        "id": "q093",
        "type": "search",
        "text": "Mobile App Developer React Native iOS Android TypeScript",
        "roles": ["mobile"],
        "primary": ["react native", "typescript"],
        "secondary": ["ios", "android"],
        "exclude": ["backend"],
    },
    {
        "id": "q094",
        "type": "search",
        "text": "iOS Software Engineer Swift UIKit SwiftUI mobile",
        "roles": ["ios"],
        "primary": ["swift", "mobile"],
        "secondary": ["swiftui", "uikit"],
        "exclude": ["java"],
    },
    # --- Specialized Domains, QA & Management (q095 - q100) ---
    {
        "id": "q095",
        "type": "search",
        "text": "Fintech Software Engineer Python Trading Financial Systems",
        "roles": ["engineer"],
        "primary": ["fintech", "python"],
        "secondary": ["trading", "financial"],
        "exclude": ["gaming"],
    },
    {
        "id": "q096",
        "type": "search",
        "text": "Digital Health Oncology Software Developer Python Cloud",
        "roles": ["developer"],
        "primary": ["health", "python"],
        "secondary": ["digital", "cloud"],
        "exclude": ["gambling"],
    },
    {
        "id": "q097",
        "type": "search",
        "text": "Aerospace and Defence Software Developer Linux C++ Python",
        "roles": ["developer"],
        "primary": ["aerospace", "linux"],
        "secondary": ["c++", "python"],
        "exclude": ["marketing"],
    },
    {
        "id": "q098",
        "type": "search",
        "text": "QA Automation Engineer Playwright Cypress Pytest test automation",
        "roles": ["qa"],
        "primary": ["automation", "test"],
        "secondary": ["playwright", "pytest", "cypress"],
        "exclude": ["sales"],
    },
    {
        "id": "q099",
        "type": "search",
        "text": "Application Security Engineer threat modeling penetration testing",
        "roles": ["security"],
        "primary": ["security", "threat"],
        "secondary": ["penetration", "appsec"],
        "exclude": ["design"],
    },
    {
        "id": "q100",
        "type": "search",
        "text": "Technical Product Manager software engineering roadmap agile",
        "roles": ["product", "manager"],
        "primary": ["roadmap", "agile"],
        "secondary": ["product", "engineering"],
        "exclude": ["intern"],
    },
]


async def _try_load_from_mongo(
    username: str,
) -> tuple[list[RawJobCandidate], UserProfile | None] | None:
    """Attempt to load real jobs, assessments, and candidate profile from MongoDB."""
    config = ConfigProvider.get_config()
    client: AsyncMongoClient | None = None
    try:
        client = AsyncMongoClient(
            host=config.MONGODB_HOST,
            port=config.MONGODB_PORT,
            username=config.MONGODB_USER,
            password=config.MONGODB_PASSWORD,
            serverSelectionTimeoutMS=2000,
        )
        await client.admin.command("ping")
        db = client[config.MONGODB_DATABASE]

        # 1. Load user profile
        user_doc = await db[config.MONGODB_USER_PROFILES_COLLECTION].find_one(
            {"username": username}
        )
        profile = UserProfile.model_validate(user_doc) if user_doc else None

        # 2. Load assessments for username
        assessments: dict[str, dict[str, Any]] = {}
        async for doc in db[config.MONGODB_ASSESSMENTS_COLLECTION].find({"username": username}):
            assess = doc.get("assessment") or {}
            assessments[doc["job_uid"]] = {
                "cv_score": assess.get("cv_ats_match_score"),
                "profile_score": assess.get("profile_ats_match_score"),
                "worth": assess.get("worth_full_assessment", False),
            }

        # 3. Load all jobs
        raw_jobs: list[RawJobCandidate] = []
        async for doc in db[config.MONGODB_JOBS_COLLECTION].find({}):
            uid = doc.get("uid")
            if not uid:
                continue
            assess_info = assessments.get(uid, {})
            raw_jobs.append(
                RawJobCandidate(
                    uid=uid,
                    title=doc.get("title", ""),
                    description_raw=doc.get("description_raw", ""),
                    company=doc.get("company", ""),
                    location=doc.get("location", ""),
                    remote=bool(doc.get("remote", False)),
                    source=doc.get("source", "mongo"),
                    url=doc.get("url", ""),
                    posted_at=str(doc.get("posted_at", "2026-01-01T00:00:00Z")),
                    cv_ats_match_score=assess_info.get("cv_score"),
                    profile_ats_match_score=assess_info.get("profile_score"),
                    worth_full_assessment=assess_info.get("worth", False),
                )
            )

        if raw_jobs:
            log.info(
                "Loaded %d jobs and profile from MongoDB for username=%s",
                len(raw_jobs),
                username,
            )
            return raw_jobs, profile
        return None
    except Exception as exc:
        log.warning("Could not load from MongoDB: %s", exc)
        return None
    finally:
        if client is not None:
            await client.close()


def _load_from_entries(
    screening_path: Path,
    fit_path: Path,
    profile_path: Path,
    username: str,
) -> tuple[list[RawJobCandidate], UserProfile]:
    """Load candidates and profile from committed historical benchmark entries."""
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile JSON not found at {profile_path}")

    profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
    if "username" not in profile_data:
        profile_data["username"] = username
    profile = UserProfile.model_validate(profile_data)

    candidates_by_uid: dict[str, RawJobCandidate] = {}

    def _process_file(path: Path) -> None:
        if not path.exists():
            return
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                doc = json.loads(line)
                job_dict = doc.get("job", {})
                gold = doc.get("gold", {})
                uid = job_dict.get("uid")
                if not uid:
                    continue

                cv_score = gold.get("cv_ats_match_score")
                profile_score = gold.get("profile_ats_match_score")
                worth = gold.get("worth_full_assessment", True if (cv_score or 0) >= 50 else False)

                if uid in candidates_by_uid:
                    existing = candidates_by_uid[uid]
                    if profile_score is not None:
                        existing.profile_ats_match_score = profile_score
                    if cv_score is not None:
                        existing.cv_ats_match_score = cv_score
                    existing.worth_full_assessment = existing.worth_full_assessment or worth
                else:
                    candidates_by_uid[uid] = RawJobCandidate(
                        uid=uid,
                        title=job_dict.get("title", ""),
                        description_raw=job_dict.get("description_raw", ""),
                        company=job_dict.get("company", ""),
                        location=job_dict.get("location", ""),
                        remote=bool(job_dict.get("remote", False)),
                        source=job_dict.get("source", "benchmark"),
                        url=job_dict.get("url", ""),
                        posted_at=str(job_dict.get("posted_at", "2026-01-01T00:00:00Z")),
                        cv_ats_match_score=cv_score,
                        profile_ats_match_score=profile_score,
                        worth_full_assessment=worth,
                    )

    _process_file(fit_path)
    _process_file(screening_path)

    jobs = list(candidates_by_uid.values())
    log.info("Loaded %d unique candidate jobs from entries datasets", len(jobs))
    return jobs, profile


async def _embed_texts(
    texts: list[str],
    *,
    use_deterministic: bool,
    session: aiohttp.ClientSession,
) -> list[list[float]]:
    """Compute embeddings via OpenAI or fall back to deterministic unit vectors."""
    config = ConfigProvider.get_config()
    if not use_deterministic and config.OPENAI_API_KEY:
        try:
            log.info("Generating embeddings for %d texts with OpenAI...", len(texts))
            client = EmbeddingClient(session)
            return await client.embed_texts(texts)
        except Exception as exc:
            log.warning(
                "OpenAI embedding generation failed (%s); falling back to deterministic vectors",
                exc,
            )

    log.info("Generating %d deterministic unit vectors...", len(texts))
    return [_deterministic_unit_vector(t) for t in texts]


async def generate_dataset(
    *,
    out_dir: Path,
    dataset_version: str,
    source: str = "auto",
    username: str = "cshadiev",
    n_queries: int = 100,
    deterministic_vectors: bool = False,
    screening_path: Path = _DEFAULT_SCREENING_ENTRIES,
    fit_path: Path = _DEFAULT_FIT_ENTRIES,
    profile_path: Path = _DEFAULT_PROFILE_JSON,
    overwrite: bool = True,
) -> Path:
    """Build, embed, and freeze the comprehensive retrieval benchmark dataset."""
    if out_dir.exists():
        if overwrite:
            log.warning("Target directory %s exists; overwriting", out_dir)
            shutil.rmtree(out_dir)
        else:
            raise FileExistsError(f"Directory already exists: {out_dir}")
    out_dir.mkdir(parents=True)

    # 1. Acquire raw data
    jobs: list[RawJobCandidate] | None = None
    profile: UserProfile | None = None
    source_type = source

    if source in ("auto", "mongo"):
        mongo_res = await _try_load_from_mongo(username)
        if mongo_res is not None:
            jobs, profile = mongo_res
            source_type = "mongo"

    if jobs is None or profile is None:
        if source == "mongo":
            raise RuntimeError("Requested --source mongo but MongoDB is unreachable or empty")
        jobs, profile = _load_from_entries(screening_path, fit_path, profile_path, username)
        source_type = "entries"

    log.info("Using %d jobs in corpus for version %s", len(jobs), dataset_version)

    # 2. Prepare query list
    candidate_profile_text = flatten_profile(profile)
    selected_query_defs = _QUERY_DEFINITIONS[:n_queries]
    queries_data: list[dict[str, Any]] = []

    for qdef in selected_query_defs:
        qid = qdef["id"]
        qtext = candidate_profile_text if qid == "q001" else qdef["text"]
        queries_data.append({"id": qid, "text": qtext, "def": qdef})

    # 3. Generate relevance labels (qrels)
    # q001 uses historical ATS assessment scores (Q8)
    qrels_rows: list[dict[str, Any]] = []
    for q_item in queries_data:
        qid = q_item["id"]
        qdef = q_item["def"]

        if qid == "q001":
            for job in jobs:
                grade = ats_score_to_grade(
                    job.ats_score, screened_through=job.worth_full_assessment
                )
                if grade > 0:
                    qrels_rows.append({"query_id": qid, "uid": job.uid, "grade": grade})
        elif qdef.get("type") in ("persona", "search"):
            for job in jobs:
                grade = _grade_job_by_rules(
                    job,
                    role_terms=qdef.get("roles", []),
                    primary_tech=qdef.get("primary", []),
                    secondary_tech=qdef.get("secondary"),
                    exclude_terms=qdef.get("exclude"),
                )
                if grade > 0:
                    qrels_rows.append({"query_id": qid, "uid": job.uid, "grade": grade})

    # Ensure every query has at least one relevant document
    qrels_by_query: dict[str, list[dict]] = {}
    for r in qrels_rows:
        qrels_by_query.setdefault(r["query_id"], []).append(r)

    for q_item in queries_data:
        qid = q_item["id"]
        if qid not in qrels_by_query:
            # Fallback: rank jobs by lexical overlap so no query is empty
            qtext_lower = q_item["text"].lower()
            tokens = [w for w in qtext_lower.split() if len(w) > 3]
            best_job = max(
                jobs,
                key=lambda j: sum(1 for tok in tokens if tok in j.clean_description.lower()),
            )
            qrels_rows.append({"query_id": qid, "uid": best_job.uid, "grade": 2})

    # 4. Compute embeddings
    job_texts = [j.embedding_text for j in jobs]
    query_texts = [q["text"] for q in queries_data]

    async with aiohttp.ClientSession() as session:
        job_vectors = await _embed_texts(
            job_texts,
            use_deterministic=deterministic_vectors,
            session=session,
        )
        query_vectors = await _embed_texts(
            query_texts,
            use_deterministic=deterministic_vectors,
            session=session,
        )

    # 5. Write artifacts
    corpus_path = out_dir / "corpus.jsonl"
    with corpus_path.open("w", encoding="utf-8") as f:
        for job, vec in zip(jobs, job_vectors, strict=True):
            record = {
                "uid": job.uid,
                "title": job.title,
                "description": job.clean_description,
                "embedding": vec,
                "source": job.source,
                "company": job.company,
                "location": job.location,
                "url": job.url,
                "remote": job.remote,
                "posted_at": job.posted_at,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    queries_path = out_dir / "queries.jsonl"
    with queries_path.open("w", encoding="utf-8") as f:
        for q_item, vec in zip(queries_data, query_vectors, strict=True):
            record = {
                "query_id": q_item["id"],
                "text": q_item["text"],
                "embedding": vec,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    qrels_path = out_dir / "qrels.jsonl"
    with qrels_path.open("w", encoding="utf-8") as f:
        for row in qrels_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Smoke query ids: first 10 queries
    smoke_ids = [q["id"] for q in queries_data[:10]]

    manifest = {
        "schema_version": 1,
        "dataset_version": dataset_version,
        "n_queries": len(queries_data),
        "n_corpus": len(jobs),
        "n_qrels": len(qrels_rows),
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": _DIM,
        "label_source": (
            "ATS-band proxy (Q8) from historical assessments and multi-graded role relevance"
        ),
        "source_type": source_type,
        "username": username,
        "exported_at": datetime.now(UTC).isoformat(),
        "smoke_query_ids": smoke_ids,
        "ks": [5, 10, 20],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    baseline = {
        "dataset_version": dataset_version,
        "metric": "ndcg@10",
        "hybrid_ndcg_at_10": 0.35,
        "note": "Conservative baseline floor for comprehensive evaluation harness.",
    }
    (out_dir / "baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")

    log.info(
        "Successfully wrote retrieval dataset %s: %d queries, %d corpus docs, %d qrels to %s",
        dataset_version,
        len(queries_data),
        len(jobs),
        len(qrels_rows),
        out_dir,
    )

    # Validate output with dataset loader
    loaded = load_dataset(out_dir)
    assert len(loaded.corpus) == len(jobs)
    assert len(loaded.queries) == len(queries_data)
    log.info(
        "Validation successful: load_dataset loaded %d docs and %d queries",
        len(loaded.corpus),
        len(loaded.queries),
    )

    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate / export comprehensive retrieval benchmark dataset",
    )
    default_version = f"{_utc_today_ddmmyyyy()}_comprehensive"
    parser.add_argument(
        "--dataset-version",
        default=default_version,
        help=f"Dataset version tag (default: {default_version})",
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=_DEFAULT_ROOT,
        help="Root directory for retrieval datasets",
    )
    parser.add_argument(
        "--source",
        choices=["auto", "mongo", "entries"],
        default="auto",
        help="Data source (default: auto - try Mongo, fall back to historical entries)",
    )
    parser.add_argument(
        "--username",
        default="cshadiev",
        help="Target username for candidate profile / assessments (default: cshadiev)",
    )
    parser.add_argument(
        "--n-queries",
        type=int,
        default=100,
        help="Number of queries to include in the benchmark (default: 100)",
    )
    parser.add_argument(
        "--deterministic-vectors",
        action="store_true",
        help="Use deterministic unit vectors instead of calling OpenAI embedding API",
    )
    parser.add_argument(
        "--screening-path",
        type=Path,
        default=_DEFAULT_SCREENING_ENTRIES,
        help="Path to screening entries JSONL",
    )
    parser.add_argument(
        "--fit-path",
        type=Path,
        default=_DEFAULT_FIT_ENTRIES,
        help="Path to fit assessment entries JSONL",
    )
    parser.add_argument(
        "--profile-path",
        type=Path,
        default=_DEFAULT_PROFILE_JSON,
        help="Path to profile JSON",
    )
    args = parser.parse_args()

    out_dir = args.dataset_root / args.dataset_version
    asyncio.run(
        generate_dataset(
            out_dir=out_dir,
            dataset_version=args.dataset_version,
            source=args.source,
            username=args.username,
            n_queries=args.n_queries,
            deterministic_vectors=args.deterministic_vectors,
            screening_path=args.screening_path,
            fit_path=args.fit_path,
            profile_path=args.profile_path,
        )
    )


if __name__ == "__main__":
    main()
