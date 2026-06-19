from __future__ import annotations

import html
import io
from pathlib import Path

from PIL import Image as PILImage
from docx import Document
from docx.document import Document as DocumentType
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "docs" / "RAPPORT_PFA_DETAILLE_DOCUAI.docx"
OUTPUT_PATH = ROOT / "docs" / "RAPPORT_PFA_DETAILLE_DOCUAI.pdf"

NAVY = colors.HexColor("#183B56")
BLUE = colors.HexColor("#2E74B5")
DARK_BLUE = colors.HexColor("#1F4D78")
TEAL = colors.HexColor("#2A8C82")
INK = colors.HexColor("#1D2733")
MUTED = colors.HexColor("#5F6B76")
LIGHT_BLUE = colors.HexColor("#EAF2F8")
LIGHT_GRAY = colors.HexColor("#F3F5F7")
BORDER = colors.HexColor("#C9D4DE")

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = 2.3 * cm
RIGHT_MARGIN = 2.1 * cm
TOP_MARGIN = 2.0 * cm
BOTTOM_MARGIN = 1.8 * cm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN


def register_fonts() -> tuple[str, str, str]:
    regular = Path(r"C:\Windows\Fonts\arial.ttf")
    bold = Path(r"C:\Windows\Fonts\arialbd.ttf")
    italic = Path(r"C:\Windows\Fonts\ariali.ttf")
    if regular.is_file():
        pdfmetrics.registerFont(TTFont("PFAArial", str(regular)))
        pdfmetrics.registerFont(TTFont("PFAArialBold", str(bold if bold.is_file() else regular)))
        pdfmetrics.registerFont(TTFont("PFAArialItalic", str(italic if italic.is_file() else regular)))
        return "PFAArial", "PFAArialBold", "PFAArialItalic"
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"


FONT, FONT_BOLD, FONT_ITALIC = register_fonts()


def iter_block_items(parent: DocumentType):
    body = parent.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield DocxParagraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield DocxTable(child, parent)


def paragraph_has_page_break(paragraph: DocxParagraph) -> bool:
    return bool(paragraph._p.xpath('.//w:br[@w:type="page"]'))


def paragraph_image_rel_ids(paragraph: DocxParagraph) -> list[str]:
    return paragraph._p.xpath(".//a:blip/@r:embed")


def paragraph_markup(paragraph: DocxParagraph) -> str:
    chunks: list[str] = []
    for run in paragraph.runs:
        text = html.escape(run.text).replace("\n", "<br/>")
        if not text:
            continue
        if run.bold:
            text = f"<b>{text}</b>"
        if run.italic:
            text = f"<i>{text}</i>"
        chunks.append(text)
    return "".join(chunks) or html.escape(paragraph.text)


def alignment_value(paragraph: DocxParagraph, default=TA_JUSTIFY) -> int:
    if paragraph.alignment == WD_ALIGN_PARAGRAPH.CENTER:
        return TA_CENTER
    if paragraph.alignment == WD_ALIGN_PARAGRAPH.RIGHT:
        return TA_RIGHT
    if paragraph.alignment == WD_ALIGN_PARAGRAPH.LEFT:
        return TA_LEFT
    if paragraph.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY:
        return TA_JUSTIFY
    return default


def max_run_size(paragraph: DocxParagraph) -> float:
    values = [run.font.size.pt for run in paragraph.runs if run.font.size is not None]
    return max(values) if values else 11.0


def is_run_bold(paragraph: DocxParagraph) -> bool:
    visible = [run for run in paragraph.runs if run.text.strip()]
    return bool(visible) and all(bool(run.bold) for run in visible)


def paragraph_style_for(paragraph: DocxParagraph, styles: dict[str, ParagraphStyle]) -> ParagraphStyle:
    name = paragraph.style.name if paragraph.style is not None else "Normal"
    if name == "Heading 1":
        return styles["h1"]
    if name == "Heading 2":
        return styles["h2"]
    if name == "Heading 3":
        return styles["h3"]
    if name.startswith("List Bullet"):
        return styles["bullet"]
    if name.startswith("List Number"):
        return styles["number"]

    size = max_run_size(paragraph)
    if size >= 26:
        return styles["cover_brand"]
    if size >= 23:
        return styles["cover_title"]
    if size >= 19:
        return styles["cover_subtitle"]
    if size >= 13 and is_run_bold(paragraph):
        return styles["lead"]
    if size <= 9.5 and paragraph.alignment == WD_ALIGN_PARAGRAPH.CENTER:
        return styles["caption"]
    return styles["body"]


def get_cell_shading(cell) -> str | None:
    shd = cell._tc.get_or_add_tcPr().find(qn("w:shd"))
    if shd is None:
        return None
    return shd.get(qn("w:fill"))


def get_table_widths(table: DocxTable) -> list[float]:
    grid_cols = table._tbl.tblGrid.findall(qn("w:gridCol"))
    widths: list[int] = []
    for col in grid_cols:
        try:
            widths.append(int(col.get(qn("w:w")) or "0"))
        except ValueError:
            widths.append(0)
    if not widths or sum(widths) <= 0:
        count = max(len(table.columns), 1)
        return [CONTENT_WIDTH / count] * count
    total = sum(widths)
    return [CONTENT_WIDTH * value / total for value in widths]


def table_has_header(table: DocxTable) -> bool:
    if not table.rows:
        return False
    if not table.rows[0]._tr.xpath("./w:trPr/w:tblHeader"):
        return False
    fills = [get_cell_shading(cell) for cell in table.rows[0].cells]
    return bool(fills) and all(fill and is_dark_fill(fill) for fill in fills)


def is_dark_fill(fill: str | None) -> bool:
    if not fill or fill.lower() in {"auto", "ffffff"}:
        return False
    try:
        red = int(fill[0:2], 16)
        green = int(fill[2:4], 16)
        blue = int(fill[4:6], 16)
    except (ValueError, IndexError):
        return False
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
    return luminance < 0.52


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle(
            "PFABody",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=10.4,
            leading=14.1,
            textColor=INK,
            alignment=TA_JUSTIFY,
            spaceAfter=7,
        ),
        "h1": ParagraphStyle(
            "PFAH1",
            parent=base["Heading1"],
            fontName=FONT_BOLD,
            fontSize=16,
            leading=20,
            textColor=BLUE,
            spaceBefore=4,
            spaceAfter=10,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "PFAH2",
            parent=base["Heading2"],
            fontName=FONT_BOLD,
            fontSize=12.5,
            leading=16,
            textColor=BLUE,
            spaceBefore=9,
            spaceAfter=6,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "PFAH3",
            parent=base["Heading3"],
            fontName=FONT_BOLD,
            fontSize=11.3,
            leading=14,
            textColor=DARK_BLUE,
            spaceBefore=7,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "bullet": ParagraphStyle(
            "PFABullet",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=10.2,
            leading=13.5,
            leftIndent=14,
            firstLineIndent=-8,
            spaceAfter=4,
            textColor=INK,
        ),
        "number": ParagraphStyle(
            "PFANumber",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=10.2,
            leading=13.5,
            leftIndent=17,
            firstLineIndent=-12,
            spaceAfter=4,
            textColor=INK,
        ),
        "cover_title": ParagraphStyle(
            "PFACoverTitle",
            parent=base["Title"],
            fontName=FONT_BOLD,
            fontSize=23,
            leading=28,
            textColor=NAVY,
            alignment=TA_CENTER,
            spaceBefore=24,
            spaceAfter=8,
        ),
        "cover_subtitle": ParagraphStyle(
            "PFACoverSubtitle",
            parent=base["Title"],
            fontName=FONT_BOLD,
            fontSize=19,
            leading=24,
            textColor=BLUE,
            alignment=TA_CENTER,
            spaceAfter=14,
        ),
        "cover_brand": ParagraphStyle(
            "PFACoverBrand",
            parent=base["Title"],
            fontName=FONT_BOLD,
            fontSize=27,
            leading=32,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceBefore=8,
            spaceAfter=20,
        ),
        "lead": ParagraphStyle(
            "PFALead",
            parent=base["BodyText"],
            fontName=FONT_BOLD,
            fontSize=13,
            leading=17,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceAfter=14,
        ),
        "caption": ParagraphStyle(
            "PFACaption",
            parent=base["BodyText"],
            fontName=FONT_ITALIC,
            fontSize=8.7,
            leading=11,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "cell": ParagraphStyle(
            "PFACell",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8.3,
            leading=10.6,
            textColor=INK,
            spaceAfter=0,
        ),
        "cell_header": ParagraphStyle(
            "PFACellHeader",
            parent=base["BodyText"],
            fontName=FONT_BOLD,
            fontSize=8.4,
            leading=10.8,
            textColor=colors.white,
            alignment=TA_CENTER,
            spaceAfter=0,
        ),
        "code": ParagraphStyle(
            "PFACode",
            parent=base["Code"],
            fontName="Courier",
            fontSize=7.7,
            leading=9.5,
            textColor=colors.HexColor("#263238"),
            spaceAfter=0,
        ),
    }


def image_flowable(doc: DocumentType, rel_id: str) -> Image:
    part = doc.part.related_parts[rel_id]
    blob = part.blob
    with PILImage.open(io.BytesIO(blob)) as image:
        width, height = image.size
    max_width = CONTENT_WIDTH
    max_height = 11.2 * cm
    scale = min(max_width / width, max_height / height)
    return Image(io.BytesIO(blob), width=width * scale, height=height * scale, hAlign="CENTER")


def table_flowable(table: DocxTable, styles: dict[str, ParagraphStyle]) -> Table:
    has_header = table_has_header(table)
    data: list[list[Paragraph]] = []
    backgrounds: list[tuple[tuple[int, int], tuple[int, int], colors.Color]] = []
    for row_index, row in enumerate(table.rows):
        values: list[Paragraph] = []
        for col_index, cell in enumerate(row.cells):
            text = "<br/>".join(paragraph_markup(paragraph) for paragraph in cell.paragraphs)
            fill = get_cell_shading(cell)
            style = styles["cell_header"] if is_dark_fill(fill) else styles["cell"]
            if len(table.columns) == 1 and "Consolas" in str(cell._tc.xml):
                style = styles["code"]
            values.append(Paragraph(text or " ", style))
            if fill and fill.lower() not in {"auto", "ffffff"}:
                backgrounds.append(((col_index, row_index), (col_index, row_index), colors.HexColor(f"#{fill}")))
        data.append(values)

    widths = get_table_widths(table)
    result = Table(
        data,
        colWidths=widths,
        repeatRows=1 if has_header else 0,
        splitByRow=1,
        hAlign="LEFT",
    )
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.45, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if has_header:
        commands.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ]
        )
    for start, end, fill_color in backgrounds:
        commands.append(("BACKGROUND", start, end, fill_color))
    result.setStyle(TableStyle(commands))
    return result


def draw_first_page(canvas, _doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(TEAL)
    canvas.setLineWidth(2)
    canvas.line(LEFT_MARGIN, 1.25 * cm, PAGE_WIDTH - RIGHT_MARGIN, 1.25 * cm)
    canvas.setFont(FONT, 8)
    canvas.setFillColor(MUTED)
    canvas.drawCentredString(PAGE_WIDTH / 2, 0.78 * cm, "DocuAI / pfaEXTRACT - Projet de fin d'etudes 2025-2026")
    canvas.restoreState()


def draw_later_pages(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.6)
    canvas.line(LEFT_MARGIN, PAGE_HEIGHT - 1.2 * cm, PAGE_WIDTH - RIGHT_MARGIN, PAGE_HEIGHT - 1.2 * cm)
    canvas.setFont(FONT_BOLD, 8)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, PAGE_HEIGHT - 0.9 * cm, "DocuAI - Rapport PFA detaille")
    canvas.setFont(FONT, 8)
    canvas.drawCentredString(PAGE_WIDTH / 2, 0.72 * cm, f"Projet de fin d'etudes 2025-2026  |  Page {doc.page}")
    canvas.restoreState()


def build_pdf() -> Path:
    source = Document(INPUT_PATH)
    styles = make_styles()
    story = []
    number_index = 0

    for block in iter_block_items(source):
        if isinstance(block, DocxParagraph):
            if paragraph_has_page_break(block):
                story.append(PageBreak())
                number_index = 0
                continue

            rel_ids = paragraph_image_rel_ids(block)
            if rel_ids:
                for rel_id in rel_ids:
                    story.append(image_flowable(source, rel_id))
                    story.append(Spacer(1, 0.12 * cm))
                continue

            text = paragraph_markup(block).strip()
            if not text:
                story.append(Spacer(1, 0.12 * cm))
                continue

            style_name = block.style.name if block.style is not None else "Normal"
            style = paragraph_style_for(block, styles)
            if style_name.startswith("List Bullet"):
                story.append(Paragraph(f"&#8226;&nbsp;&nbsp;{text}", style))
            elif style_name.startswith("List Number"):
                number_index += 1
                story.append(Paragraph(f"{number_index}.&nbsp;&nbsp;{text}", style))
            else:
                if not style_name.startswith("List"):
                    number_index = 0
                custom = ParagraphStyle(
                    f"Dynamic{len(story)}",
                    parent=style,
                    alignment=alignment_value(block, style.alignment),
                )
                story.append(Paragraph(text, custom))
        else:
            story.append(table_flowable(block, styles))
            story.append(Spacer(1, 0.18 * cm))

    pdf = SimpleDocTemplate(
        str(OUTPUT_PATH),
        pagesize=A4,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title="Rapport PFA detaille - DocuAI / pfaEXTRACT",
        author="[Nom et prenom]",
        subject="Plateforme intelligente d'extraction d'informations",
    )
    pdf.build(story, onFirstPage=draw_first_page, onLaterPages=draw_later_pages)
    return OUTPUT_PATH


if __name__ == "__main__":
    print(build_pdf())
