"""Pydantic models for user profiles stored in MongoDB."""

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    """User model for the authenticated user."""

    sub: str  # auth0 user id
    username: str
    email: str | None = None


class Contact(BaseModel):
    """Public contact details for a user profile."""

    email: str
    linkedin: str | None = None
    website: str | None = None
    telegram: str | None = None


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
    score: str | None = None
    details: str | None = None
    link: str | None = None


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
    companyDescription: str | None = None
    impact: str | None = None
    stack: list[str] | None = None


class Education(BaseModel):
    """An academic qualification."""

    degree: str
    institution: str
    location: str
    year: int
    classification: str | None = None
    modules: list[str] | None = None
    focus: list[str] | None = None


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
    sponsorshipNotes: str | None = None
    partTimeImmediate: bool
    partTimeLimit: int | None = None


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


class LoginRequest(BaseModel):
    """
    Request model for user login.
    """

    username: str
    password: str


class LoginResponse(BaseModel):
    """
    Response model for successful login.
    """

    access_token: str
    id_token: str
    token_type: str
    expires_in: int
    refresh_token: str | None = None


class LogoutRequest(BaseModel):
    """
    Request model for user logout.
    """

    refresh_token: str | None = None


class RefreshTokenRequest(BaseModel):
    """
    Request model for refreshing a token.
    """

    refresh_token: str
