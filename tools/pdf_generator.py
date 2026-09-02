import fpdf
from fpdf.enums import XPos, YPos
from models.fit_assessment import CoverLetterContent

FONT = "Comfortaa"

FONT_SIZE_HEADER = 14
FONT_SIZE_SUBHEADER = 9
FONT_SIZE_CONTENT = 9


def generate_cover_letter(cover_letter_content: CoverLetterContent, output_path: str) -> int:
    pdf = fpdf.FPDF()
    pdf.add_font("Comfortaa", "", "tools/fonts/Comfortaa-Medium.ttf")
    pdf.add_font("Comfortaa", "B", "tools/fonts/Comfortaa-Bold.ttf")
    pdf.add_page()
    pdf.set_margins(18, 16, 18)
    pdf.set_auto_page_break(auto=True, margin=20)

    FONT = "Comfortaa"

    # Header - Name
    pdf.set_font(FONT, "B", FONT_SIZE_HEADER)
    pdf.cell(
        0, 8, cover_letter_content.name.upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C"
    )

    # Header - Title
    pdf.set_font(FONT, "", FONT_SIZE_SUBHEADER)
    pdf.cell(0, 6, cover_letter_content.title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")

    # Header - Contact
    # Build contact line with individual links
    line_y = pdf.get_y()
    separator = " | "
    email = cover_letter_content.email
    linkedin = cover_letter_content.linkedin["display"]
    website = cover_letter_content.website["display"]
    total_width = (
        pdf.get_string_width(email)
        + pdf.get_string_width(separator)
        + pdf.get_string_width(linkedin)
        + pdf.get_string_width(separator)
        + pdf.get_string_width(website)
    )
    start_x = (pdf.w - total_width) / 2

    pdf.set_xy(start_x, line_y)
    pdf.set_text_color(0, 76, 153)
    pdf.cell(pdf.get_string_width(email), 6, email, link=f"mailto:{email}")

    pdf.set_text_color(0, 0, 0)
    pdf.cell(pdf.get_string_width(separator), 6, separator)

    pdf.set_text_color(0, 76, 153)
    pdf.cell(pdf.get_string_width(linkedin), 6, linkedin, link=f"https://{linkedin}")

    pdf.set_text_color(0, 0, 0)
    pdf.cell(pdf.get_string_width(separator), 6, separator)

    pdf.set_text_color(0, 76, 153)
    pdf.cell(pdf.get_string_width(website), 6, website, link=f"https://{website}")

    pdf.set_text_color(0, 0, 0)  # Reset to black
    pdf.ln(12)

    # Sections
    for section in cover_letter_content.sections:
        pdf.set_font(FONT, "B", FONT_SIZE_SUBHEADER)
        pdf.cell(0, 6, section.title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)
        pdf.set_font(FONT, "", FONT_SIZE_CONTENT)
        for content in section.content:
            pdf.multi_cell(0, 5.5, content)
            pdf.ln(2)

    pdf.ln(8)
    pdf.set_font(FONT, "", FONT_SIZE_CONTENT)
    pdf.cell(0, 6, "Best regards,", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    pdf.set_font(FONT, "", FONT_SIZE_CONTENT)
    pdf.cell(0, 6, cover_letter_content.name, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.output(output_path)

    return pdf.pages_count
