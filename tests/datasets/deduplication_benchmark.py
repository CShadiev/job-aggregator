"""Benchmark dataset entries and loaders for deduplication normalization evaluation."""

from typing import TypedDict


class BenchmarkDatasetEntry(TypedDict):
    """Entry structure for job title and company deduplication benchmark evaluation."""

    title: str
    company: str
    expected_normalized_title: str
    expected_normalized_company: str
    is_duplicate: bool


def load_benchmark_dataset() -> list[BenchmarkDatasetEntry]:
    """Return a curated benchmark dataset of raw job entries and expected normalizations."""
    return [
        {
            "title": "Software Engineer",
            "company": "Google Inc.",
            "expected_normalized_title": "software engineer",
            "expected_normalized_company": "google",
            "is_duplicate": False,
        },
        {
            "title": "Sr. Software Engineer (m/w/d)",
            "company": "Google Inc.",
            "expected_normalized_title": "senior software engineer",
            "expected_normalized_company": "google",
            "is_duplicate": False,
        },
        {
            "title": "Staff Software Engineer",
            "company": "Google",
            "expected_normalized_title": "staff software engineer",
            "expected_normalized_company": "google",
            "is_duplicate": False,
        },
        {
            "title": "Jr. Developer",
            "company": "Meta LLC",
            "expected_normalized_title": "junior developer",
            "expected_normalized_company": "meta",
            "is_duplicate": False,
        },
        {
            "title": "Dev. Python",
            "company": "Amazon.com, Inc.",
            "expected_normalized_title": "developer python",
            "expected_normalized_company": "amazon",
            "is_duplicate": False,
        },
        {
            "title": "Eng.",
            "company": "Microsoft Corp.",
            "expected_normalized_title": "engineer",
            "expected_normalized_company": "microsoft",
            "is_duplicate": False,
        },
        {
            "title": "Mgr. Engineering",
            "company": "Apple Inc.",
            "expected_normalized_title": "manager engineering",
            "expected_normalized_company": "apple",
            "is_duplicate": False,
        },
        {
            "title": "Backend Developer (Remote)",
            "company": "Spotify AB",
            "expected_normalized_title": "backend developer",
            "expected_normalized_company": "spotify",
            "is_duplicate": False,
        },
        {
            "title": "Senior Web Developer Python FastAPI",
            "company": "Acme GmbH",
            "expected_normalized_title": "senior web developer python fastapi",
            "expected_normalized_company": "acme",
            "is_duplicate": False,
        },
        {
            "title": "Data Scientist (Hybrid, Berlin)",
            "company": "BMW AG",
            "expected_normalized_title": "data scientist",
            "expected_normalized_company": "bmw",
            "is_duplicate": False,
        },
        {
            "title": "Software Engineer",
            "company": "Société Générale",
            "expected_normalized_title": "software engineer",
            "expected_normalized_company": "societe generale",
            "is_duplicate": False,
        },
        {
            "title": "Full Stack Dev",
            "company": "AT&T Corp.",
            "expected_normalized_title": "full stack developer",
            "expected_normalized_company": "at and t",
            "is_duplicate": False,
        },
        {
            "title": "Sr. Eng. (m/f/d)",
            "company": "SAP SE",
            "expected_normalized_title": "senior engineer",
            "expected_normalized_company": "sap",
            "is_duplicate": False,
        },
        {
            "title": "Product Manager",
            "company": "Stripe, Inc.",
            "expected_normalized_title": "product manager",
            "expected_normalized_company": "stripe",
            "is_duplicate": False,
        },
        {
            "title": "Frontend Developer",
            "company": "Café Néstlé Ltd.",
            "expected_normalized_title": "frontend developer",
            "expected_normalized_company": "cafe nestle",
            "is_duplicate": False,
        },
        {
            "title": "Machine Learning Engineer",
            "company": "DeepMind Technologies Ltd.",
            "expected_normalized_title": "machine learning engineer",
            "expected_normalized_company": "deepmind",
            "is_duplicate": False,
        },
        {
            "title": "Technical Lead",
            "company": "Siemens Healthineers GmbH",
            "expected_normalized_title": "technical lead",
            "expected_normalized_company": "siemens healthineers",
            "is_duplicate": False,
        },
        {
            "title": "QA Engineer",
            "company": "ÖBB-Personenverkehr AG",
            "expected_normalized_title": "qa engineer",
            "expected_normalized_company": "obb personenverkehr",
            "is_duplicate": False,
        },
        {
            "title": "DevOps Engineer",
            "company": "Mailchimp",
            "expected_normalized_title": "devops engineer",
            "expected_normalized_company": "mailchimp",
            "is_duplicate": False,
        },
        {
            "title": "Software Developer",
            "company": "JPMorgan Chase & Co.",
            "expected_normalized_title": "software developer",
            "expected_normalized_company": "jpmorgan chase",
            "is_duplicate": False,
        },
        {
            "title": "Engineering Mng",
            "company": "Apple Inc.",
            "expected_normalized_title": "manager engineering",
            "expected_normalized_company": "apple",
            "is_duplicate": True,
        },
        {
            "title": "Software Eng.",
            "company": "Google Incorporated",
            "expected_normalized_title": "software engineer",
            "expected_normalized_company": "google",
            "is_duplicate": True,
        },
        {
            "title": "Junior Dev",
            "company": "Meta Platforms LLC",
            "expected_normalized_title": "junior developer",
            "expected_normalized_company": "meta",
            "is_duplicate": True,
        },
        {
            "title": "Python Developer",
            "company": "Amazon.com Inc",
            "expected_normalized_title": "developer python",
            "expected_normalized_company": "amazon",
            "is_duplicate": True,
        },
        {
            "title": "Engineer",
            "company": "Microsoft Corporation",
            "expected_normalized_title": "engineer",
            "expected_normalized_company": "microsoft",
            "is_duplicate": True,
        },
        {
            "title": "Backend Dev (Remote)",
            "company": "Spotify",
            "expected_normalized_title": "backend developer",
            "expected_normalized_company": "spotify",
            "is_duplicate": True,
        },
        {
            "title": "PM",
            "company": "Stripe Inc",
            "expected_normalized_title": "product manager",
            "expected_normalized_company": "stripe",
            "is_duplicate": True,
        },
        {
            "title": "ML Engineer",
            "company": "DeepMind Technologies",
            "expected_normalized_title": "machine learning engineer",
            "expected_normalized_company": "deepmind",
            "is_duplicate": True,
        },
        {
            "title": "Software Dev",
            "company": "JPMorgan Chase and Co.",
            "expected_normalized_title": "software developer",
            "expected_normalized_company": "jpmorgan chase",
            "is_duplicate": True,
        },
        {
            "title": "Data Scientist",
            "company": "Bayerische Motoren Werke AG",
            "expected_normalized_title": "data scientist",
            "expected_normalized_company": "bmw",
            "is_duplicate": True,
        },
    ]
