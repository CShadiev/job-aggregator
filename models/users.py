"""Pydantic models for user profiles stored in MongoDB."""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class Contact(BaseModel):
    """Public contact details for a user profile."""

    email: str
    linkedin: Optional[str] = None
    website: Optional[str] = None
    telegram: Optional[str] = None


class Profile(BaseModel):
    """Basic identity and contact information."""

    name: str
    title: str
    location: str
    contact: Contact


class Summary(BaseModel):
    """Short professional summary."""

    headline: str
    description: str


class KeyDifferentiator(BaseModel):
    """A concise differentiator highlighting the candidate's strengths."""

    title: str
    description: str


class Certification(BaseModel):
    """Professional certification or credential."""

    name: str
    issuer: str
    date: str
    score: Optional[str] = None
    details: Optional[str] = None
    link: Optional[str] = None


class TechnicalSkill(BaseModel):
    """A single technical skill with proficiency and supporting evidence."""

    name: str
    proficiency: int
    evidence: list[str] = Field(default_factory=list)


class TechnicalSkills(BaseModel):
    """Technical skills grouped by domain."""

    backend: list[TechnicalSkill] = Field(default_factory=list)
    frontend: list[TechnicalSkill] = Field(default_factory=list)
    infrastructure: list[TechnicalSkill] = Field(default_factory=list)
    databases: list[TechnicalSkill] = Field(default_factory=list)
    aiMl: list[TechnicalSkill] = Field(default_factory=list)


class Experience(BaseModel):
    """A single employment history entry."""

    title: str
    company: str
    startDate: str
    endDate: str
    responsibilities: list[str]
    companyDescription: Optional[str] = None
    impact: Optional[str] = None
    stack: Optional[list[str]] = None


class Education(BaseModel):
    """An academic qualification."""

    degree: str
    institution: str
    location: str
    year: int
    classification: Optional[str] = None
    modules: Optional[list[str]] = None
    focus: Optional[list[str]] = None


class LocationPreferences(BaseModel):
    """Geographic and remote-work preferences."""

    primary: str
    remote: str
    relocation: str


class IndustryPreferences(BaseModel):
    """Industry sectors the candidate prefers or wants to avoid."""

    strongInterest: list[str]
    lessInterested: list[str]


class CareerGoals(BaseModel):
    """Target roles, constraints, and values guiding the job search."""

    targetRoles: list[str]
    avoidRoles: list[str]
    locationPreferences: LocationPreferences
    industryPreferences: IndustryPreferences
    values: list[str]
    seekingInRole: list[str]


class WorkAuthorization(BaseModel):
    """Work authorization status for a specific country or region."""

    status: str
    location: str
    sponsorshipRequired: bool
    sponsorshipNotes: Optional[str] = None
    partTimeImmediate: bool
    partTimeLimit: Optional[int] = None


class RoleFitSignals(BaseModel):
    """Heuristic fit signals used when matching roles to the profile."""

    strongFit: list[str]
    moderateFit: list[str]
    weakFit: list[str]


class Language(BaseModel):
    """Spoken language proficiency."""

    language: str
    level: str
    context: str


class UserProfile(BaseModel):
    """Full user profile document as stored in MongoDB.

    Field names mirror the persisted document schema (camelCase) so that
    ``model_validate`` works against MongoDB exports without aliases.
    """

    model_config = ConfigDict(populate_by_name=True)

    profile: Profile
    summary: Summary
    keyDifferentiators: list[KeyDifferentiator]
    certifications: list[Certification]
    technicalSkills: TechnicalSkills
    coreCompetencies: list[str]
    experience: list[Experience]
    education: list[Education]
    careerGoals: CareerGoals
    workAuthorization: list[WorkAuthorization]
    roleFitSignals: RoleFitSignals
    languages: list[Language]
    username: str
