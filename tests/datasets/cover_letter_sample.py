"""Sample profile, posting and fit assessment for cover-letter tests."""

from datetime import UTC, datetime

from models.collection_service import JobPosting
from models.fit_assessment import FitAssessment
from models.users import (
    CareerGoals,
    Certification,
    Contact,
    Education,
    Experience,
    IndustryPreferences,
    KeyDifferentiator,
    Language,
    LocationPreferences,
    Profile,
    RoleFitSignals,
    Summary,
    TechnicalSkill,
    TechnicalSkills,
    UserProfile,
    WorkAuthorization,
)

SAMPLE_USERNAME = "sample_user"


def make_sample_user_profile() -> UserProfile:
    """Return a realistic :class:`UserProfile` for a Python/AI backend engineer."""
    return UserProfile(
        username=SAMPLE_USERNAME,
        profile=Profile(
            name="Ada Lindqvist",
            title="Senior Backend Engineer",
            location="Berlin, Germany",
            contact=Contact(
                email="ada.lindqvist@example.com",
                linkedin="https://linkedin.com/in/adalindqvist",
                website="https://ada.dev",
            ),
        ),
        summary=Summary(
            headline="Backend engineer focused on production AI systems",
            description=(
                "Backend engineer with 8 years of experience building scalable, "
                "distributed Python services and taking AI features from prototype "
                "to production."
            ),
        ),
        keyDifferentiators=[
            KeyDifferentiator(
                title="End-to-end ownership",
                description=(
                    "Has delivered platforms solo, from architecture and API design "
                    "through deployment, monitoring and on-call."
                ),
            ),
            KeyDifferentiator(
                title="Applied LLM experience",
                description=(
                    "Built RAG pipelines and tool-using agents on top of vector "
                    "databases for internal knowledge assistants."
                ),
            ),
        ],
        certifications=[
            Certification(
                name="AWS Certified Developer – Associate",
                issuer="Amazon Web Services",
                date="2024-03",
                score="910/1000",
            ),
        ],
        technicalSkills=TechnicalSkills(
            backend=[
                TechnicalSkill(
                    name="Python",
                    proficiency=5,
                    evidence=["8 years of production FastAPI and asyncio services"],
                ),
                TechnicalSkill(
                    name="FastAPI",
                    proficiency=5,
                    evidence=["Designed REST APIs serving millions of requests/day"],
                ),
            ],
            frontend=[
                TechnicalSkill(name="React", proficiency=3, evidence=["Internal dashboards"]),
            ],
            infrastructure=[
                TechnicalSkill(
                    name="Docker", proficiency=4, evidence=["Containerised all services"]
                ),
                TechnicalSkill(
                    name="AWS", proficiency=4, evidence=["ECS, Lambda, RDS in production"]
                ),
            ],
            databases=[
                TechnicalSkill(
                    name="PostgreSQL", proficiency=4, evidence=["Schema design, indexing, tuning"]
                ),
                TechnicalSkill(
                    name="MongoDB", proficiency=3, evidence=["Document stores for job data"]
                ),
            ],
            aiMl=[
                TechnicalSkill(
                    name="LangChain",
                    proficiency=4,
                    evidence=["RAG pipelines with vector search and tool use"],
                ),
            ],
        ),
        coreCompetencies=[
            "Distributed systems",
            "API design",
            "RAG and agentic AI",
            "CI/CD",
        ],
        experience=[
            Experience(
                title="Senior Backend Engineer",
                company="Helios Data GmbH",
                startDate="2021-06",
                endDate="Present",
                responsibilities=[
                    "Led design of an event-driven document-processing platform",
                    "Built a retrieval-augmented assistant over an internal knowledge base",
                ],
                companyDescription="B2B analytics platform for logistics companies.",
                impact="Cut manual document triage time by 60%.",
                stack=["Python", "FastAPI", "PostgreSQL", "AWS", "LangChain"],
            ),
            Experience(
                title="Backend Engineer",
                company="Nordic Fintech AB",
                startDate="2018-01",
                endDate="2021-05",
                responsibilities=[
                    "Built broker API integrations and real-time reporting pipelines",
                    "Hardened auth and RBAC across the platform",
                ],
                stack=["Python", "Django", "RabbitMQ", "PostgreSQL"],
            ),
        ],
        education=[
            Education(
                degree="MSc Computer Science",
                institution="KTH Royal Institute of Technology",
                location="Stockholm, Sweden",
                year=2017,
                classification="Distinction",
                focus=["Distributed systems", "Machine learning"],
            ),
        ],
        careerGoals=CareerGoals(
            targetRoles=["Senior Backend Engineer", "AI Engineer"],
            avoidRoles=["Pure frontend", "Manual QA"],
            locationPreferences=LocationPreferences(
                primary="Berlin",
                remote="Remote-first preferred",
                relocation="Not seeking relocation",
            ),
            industryPreferences=IndustryPreferences(
                strongInterest=["AI platforms", "Fintech"],
                lessInterested=["Adtech"],
            ),
            values=["Autonomy", "Ownership", "Craft"],
            seekingInRole=["Production AI work", "Small senior team"],
        ),
        workAuthorization=[
            WorkAuthorization(
                status="EU citizen",
                location="Germany",
                sponsorshipRequired=False,
                partTimeImmediate=True,
            ),
        ],
        roleFitSignals=RoleFitSignals(
            strongFit=["Python backend", "Applied AI/RAG"],
            moderateFit=["Frontend polish"],
            weakFit=["SAP", "Java/Spring"],
        ),
        languages=[
            Language(language="English", level="C2", context="Professional working language"),
            Language(language="German", level="B1", context="Daily life, improving"),
            Language(language="Swedish", level="Native", context="Mother tongue"),
        ],
    )


def make_sample_job_posting() -> JobPosting:
    """Return a single :class:`JobPosting` well-matched to the sample profile."""
    return JobPosting(
        uid="sample:cover-letter-0001",
        source="sample",
        title="Senior AI Backend Engineer (m/f/d)",
        company="Lumen AI",
        location="Berlin / Remote",
        remote=True,
        url="https://example.com/jobs/sample-cover-letter-0001",
        tags=["python", "fastapi", "rag", "aws"],
        description_raw=(
            "Lumen AI builds production AI assistants for enterprise teams. We are "
            "looking for a Senior AI Backend Engineer to own features end-to-end: "
            "designing scalable Python/FastAPI services, building RAG pipelines over "
            "vector databases, and integrating LLM providers into reliable workflows.\n\n"
            "Requirements:\n"
            "- 5+ years of backend Python experience\n"
            "- Experience with FastAPI, PostgreSQL and AWS\n"
            "- Hands-on work with RAG, embeddings and agentic AI\n"
            "- Strong engineering practices: testing, monitoring, CI/CD\n\n"
            "Nice to have: experience taking AI prototypes to production at scale."
        ),
        job_types=["full-time"],
        posted_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
        collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        company_normalized="lumen ai",
        title_normalized="senior ai backend engineer",
    )


def make_sample_fit_assessment() -> FitAssessment:
    """Return a :class:`FitAssessment` of the sample user against the sample posting."""
    return FitAssessment(
        cv_ats_match_score=86.0,
        profile_ats_match_score=90.0,
        deal_breakers=[],
        summary=(
            "Strong match: 8 years of production Python/FastAPI on AWS with hands-on "
            "RAG and agentic AI work directly aligns with the role. EU work "
            "authorization and Berlin base fit the location requirements. Minor gap "
            "around large-scale LLM provider operations."
        ),
    )
