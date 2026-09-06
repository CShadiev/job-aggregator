from models.users import (
    CareerGoals,
    Contact,
    Experience,
    IndustryPreferences,
    LocationPreferences,
    Profile,
    RoleFitSignals,
    Summary,
    TechnicalSkill,
    TechnicalSkills,
    UserProfile,
)
from search.text import flatten_profile, job_embedding_text, profile_text_hash, strip_html


def test_strip_html_unescapes_and_collapses():
    raw = "<p>Hello&nbsp;<b>world</b></p>"
    assert "Hello" in strip_html(raw)
    assert "world" in strip_html(raw)
    assert "<" not in strip_html(raw)
    assert strip_html(raw) == "Hello world"


def test_job_embedding_text_joins_title_and_clean_description():
    text = job_embedding_text("Engineer", "<p>Build APIs</p>")
    assert text.startswith("Engineer")
    assert "Build APIs" in text
    assert "<p>" not in text
    assert text == "Engineer Build APIs"


def test_flatten_profile_includes_headline_skills_experience():
    profile = _profile()
    text = flatten_profile(profile)
    assert "Backend Python engineer" in text
    assert "Python" in text
    assert "FastAPI" in text
    assert profile_text_hash(text) == profile_text_hash(text)
    assert profile_text_hash(text) != profile_text_hash(text + "x")


def _profile() -> UserProfile:
    return UserProfile(
        profile=Profile(
            name="Ada",
            title="Backend Python engineer",
            location="Berlin",
            contact=Contact(email="ada@example.com"),
        ),
        summary=Summary(headline="API specialist", description="Builds FastAPI services."),
        keyDifferentiators=[],
        certifications=[],
        technicalSkills=TechnicalSkills(
            backend=[
                TechnicalSkill(name="Python", proficiency=5),
                TechnicalSkill(name="FastAPI", proficiency=5),
            ]
        ),
        coreCompetencies=[],
        experience=[
            Experience(
                title="Engineer",
                company="Acme",
                startDate="2020",
                endDate="2024",
                responsibilities=["Shipped APIs"],
                stack=["MongoDB"],
            )
        ],
        education=[],
        careerGoals=CareerGoals(
            targetRoles=["Backend"],
            avoidRoles=[],
            locationPreferences=LocationPreferences(
                primary="Berlin", remote="yes", relocation="no"
            ),
            industryPreferences=IndustryPreferences(strongInterest=[], lessInterested=[]),
            values=[],
            seekingInRole=[],
        ),
        workAuthorization=[],
        roleFitSignals=RoleFitSignals(strongFit=[], moderateFit=[], weakFit=[]),
        languages=[],
        username="ada",
    )
