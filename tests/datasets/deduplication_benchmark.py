from typing import TypedDict


class BenchmarkDatasetEntry(TypedDict):
    title: str
    company: str
    expected_normalized_title: str
    expected_normalized_company: str


def load_benchmark_dataset() -> list[BenchmarkDatasetEntry]:
    return [
        {
            "title": "Software Engineer",
            "company": "Google Inc.",
            "expected_normalized_title": "software engineer",
            "expected_normalized_company": "google", },
        {
            "title": "Sr. Software Engineer (m/w/d)",
            "company": "Google Inc.",
            "expected_normalized_title": "senior software engineer",
            "expected_normalized_company": "google", },
        {
            "title": "Senior Software Engineer",
            "company": "Google",
            "expected_normalized_title": "senior software engineer",
            "expected_normalized_company": "google", },
        {
            "title": "Jr. Developer",
            "company": "Meta LLC",
            "expected_normalized_title": "junior developer",
            "expected_normalized_company": "meta", },
        {
            "title": "Dev. Python",
            "company": "Amazon.com, Inc.",
            "expected_normalized_title": "developer python",
            "expected_normalized_company": "amazon", },
        {
            "title": "Eng.",
            "company": "Microsoft Corp.",
            "expected_normalized_title": "engineer",
            "expected_normalized_company": "microsoft", },
        {
            "title": "Mgr. Engineering",
            "company": "Apple Inc.",
            "expected_normalized_title": "engineering manager",
            "expected_normalized_company": "apple", },
        {
            "title": "Backend Developer (Remote)",
            "company": "Spotify AB",
            "expected_normalized_title": "backend developer",
            "expected_normalized_company": "spotify", },
        {
            "title": "Senior Web Developer Python FastAPI",
            "company": "Acme GmbH",
            "expected_normalized_title": "senior web developer python fastapi",
            "expected_normalized_company": "acme", },
        {
            "title": "Data Scientist (Hybrid, Berlin)",
            "company": "BMW AG",
            "expected_normalized_title": "data scientist",
            "expected_normalized_company": "bmw", },
        {
            "title": "Software Engineer",
            "company": "Société Générale",
            "expected_normalized_title": "software engineer",
            "expected_normalized_company": "societe generale", },
        {
            "title": "Full Stack Dev",
            "company": "AT&T Corp.",
            "expected_normalized_title": "full stack developer",
            "expected_normalized_company": "att", },
        {
            "title": "Sr. Eng. (m/f/d)",
            "company": "SAP SE",
            "expected_normalized_title": "senior engineer",
            "expected_normalized_company": "sap", },
        {
            "title": "Product Manager",
            "company": "Stripe, Inc.",
            "expected_normalized_title": "product manager",
            "expected_normalized_company": "stripe", },
        {
            "title": "Frontend Developer",
            "company": "Café Néstlé Ltd.",
            "expected_normalized_title": "frontend developer",
            "expected_normalized_company": "cafe nestle", },
        {
            "title": "Machine Learning Engineer",
            "company": "DeepMind Technologies Ltd.",
            "expected_normalized_title": "machine learning engineer",
            "expected_normalized_company": "deepmind", },
        {
            "title": "Technical Lead",
            "company": "Siemens Healthineers GmbH",
            "expected_normalized_title": "technical lead",
            "expected_normalized_company": "siemens healthineers", },
        {
            "title": "QA Engineer",
            "company": "ÖBB-Personenverkehr AG",
            "expected_normalized_title": "qa engineer",
            "expected_normalized_company": "obb personenverkehr", },
        {
            "title": "DevOps Engineer",
            "company": "Mailchimp",
            "expected_normalized_title": "devops engineer",
            "expected_normalized_company": "mailchimp", },
        {
            "title": "Software Developer",
            "company": "JPMorgan Chase & Co.",
            "expected_normalized_title": "software developer",
            "expected_normalized_company": "jpmorgan chase", }, ]
