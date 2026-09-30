"""PDF renderer for a candidate CV from a ``UserProfile``."""

from pathlib import Path

import fpdf
from fpdf.enums import XPos, YPos

from models.users import TechnicalSkill, UserProfile

_FONT = "Comfortaa"
_FONT_DIR = Path(__file__).resolve().parent / "fonts"
_SIZE_NAME = 16
_SIZE_TITLE = 11
_SIZE_SECTION = 10
_SIZE_BODY = 9
_LINE = 5.0


def generate_cv_pdf(profile: UserProfile, output_path: str) -> int:
    """Render *profile* as a plain multi-page CV PDF.

    Args:
        profile: Prompt-facing user profile.
        output_path: Filesystem path to write.

    Returns:
        Number of pages in the generated PDF.
    """
    pdf = fpdf.FPDF()
    pdf.add_font(_FONT, "", str(_FONT_DIR / "Comfortaa-Medium.ttf"))
    pdf.add_font(_FONT, "B", str(_FONT_DIR / "Comfortaa-Bold.ttf"))
    pdf.add_page()
    pdf.set_margins(16, 14, 16)
    pdf.set_auto_page_break(auto=True, margin=16)

    identity = profile.profile
    pdf.set_font(_FONT, "B", _SIZE_NAME)
    pdf.cell(0, 8, identity.name, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_font(_FONT, "", _SIZE_TITLE)
    pdf.cell(0, 6, identity.title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_font(_FONT, "", _SIZE_BODY)
    pdf.cell(0, 5, identity.location, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    contact_parts = [identity.contact.email]
    if identity.contact.linkedin:
        contact_parts.append(identity.contact.linkedin)
    if identity.contact.website:
        contact_parts.append(identity.contact.website)
    pdf.multi_cell(
        0, _LINE, " | ".join(contact_parts), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT
    )
    pdf.ln(4)

    _section(pdf, "Summary")
    pdf.set_font(_FONT, "B", _SIZE_BODY)
    _text(pdf, profile.summary.headline)
    pdf.set_font(_FONT, "", _SIZE_BODY)
    _text(pdf, profile.summary.description)
    pdf.ln(2)

    if profile.keyDifferentiators:
        _section(pdf, "Key differentiators")
        for item in profile.keyDifferentiators:
            pdf.set_font(_FONT, "B", _SIZE_BODY)
            _text(pdf, item.title)
            pdf.set_font(_FONT, "", _SIZE_BODY)
            _text(pdf, item.description)
            pdf.ln(1)

    _section(pdf, "Experience")
    for job in profile.experience:
        dates = f"{job.startDate} - {job.endDate}"
        pdf.set_font(_FONT, "B", _SIZE_BODY)
        _text(pdf, f"{job.title}  |  {job.company}")
        pdf.set_font(_FONT, "", _SIZE_BODY)
        _text(pdf, dates)
        if job.companyDescription:
            _text(pdf, job.companyDescription)
        for line in job.responsibilities:
            _text(pdf, f"- {line}")
        if job.impact:
            pdf.set_font(_FONT, "B", _SIZE_BODY)
            _text(pdf, f"Impact: {job.impact}")
            pdf.set_font(_FONT, "", _SIZE_BODY)
        if job.stack:
            _text(pdf, "Stack: " + ", ".join(job.stack))
        pdf.ln(2)

    _section(pdf, "Technical skills")
    skills = profile.technicalSkills
    _skill_group(pdf, "Backend", skills.backend)
    _skill_group(pdf, "Frontend", skills.frontend)
    _skill_group(pdf, "Infrastructure", skills.infrastructure)
    _skill_group(pdf, "Databases", skills.databases)
    _skill_group(pdf, "AI / ML", skills.aiMl)

    if profile.coreCompetencies:
        _section(pdf, "Core competencies")
        _text(pdf, ", ".join(profile.coreCompetencies))
        pdf.ln(2)

    if profile.certifications:
        _section(pdf, "Certifications")
        for cert in profile.certifications:
            score = f" ({cert.score})" if cert.score else ""
            _text(pdf, f"{cert.name}, {cert.issuer}, {cert.date}{score}")

    if profile.education:
        _section(pdf, "Education")
        for edu in profile.education:
            extra = f", {edu.classification}" if edu.classification else ""
            pdf.set_font(_FONT, "B", _SIZE_BODY)
            _text(pdf, f"{edu.degree}, {edu.institution}{extra}")
            pdf.set_font(_FONT, "", _SIZE_BODY)
            _text(pdf, f"{edu.location}, {edu.year}")
            if edu.focus:
                _text(pdf, "Focus: " + ", ".join(edu.focus))
            pdf.ln(1)

    if profile.languages:
        _section(pdf, "Languages")
        for lang in profile.languages:
            _text(pdf, f"{lang.language} ({lang.level}): {lang.context}")

    if profile.workAuthorization:
        _section(pdf, "Work authorisation")
        for auth in profile.workAuthorization:
            sponsor = (
                "sponsorship required" if auth.sponsorshipRequired else "no sponsorship required"
            )
            _text(pdf, f"{auth.location}: {auth.status}; {sponsor}")
            if auth.sponsorshipNotes:
                _text(pdf, auth.sponsorshipNotes)

    pdf.output(output_path)
    return pdf.pages_count


def _text(pdf: fpdf.FPDF, text: str) -> None:
    """Write wrapped body text and return the cursor to the left margin."""
    pdf.multi_cell(0, _LINE, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _section(pdf: fpdf.FPDF, title: str) -> None:
    """Write a section heading."""
    pdf.ln(2)
    pdf.set_font(_FONT, "B", _SIZE_SECTION)
    pdf.cell(0, 6, title.upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font(_FONT, "", _SIZE_BODY)
    pdf.ln(1)


def _skill_group(pdf: fpdf.FPDF, heading: str, skills: list[TechnicalSkill]) -> None:
    """Write a named skill group, skipping empty groups."""
    if not skills:
        return
    pdf.set_font(_FONT, "B", _SIZE_BODY)
    _text(pdf, heading)
    pdf.set_font(_FONT, "", _SIZE_BODY)
    for skill in skills:
        evidence = "; ".join(skill.evidence) if skill.evidence else ""
        suffix = f" - {evidence}" if evidence else ""
        _text(pdf, f"{skill.name} (proficiency {skill.proficiency}/5){suffix}")
    pdf.ln(1)
