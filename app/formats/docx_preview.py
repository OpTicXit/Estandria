"""Vista previa en HTML del formato efectivo de un DOCX.

Reproduce lo que las reglas cambian (fuente, tamaño, negrita, cursiva, color, alineación, sangrías,
interlineado, espaciado, márgenes y encabezado) para comparar antes y después. No reproduce la
paginación de Word ni dibuja las imágenes; es una aproximación visual, no el documento final.
"""
from __future__ import annotations

import html

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Length
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.formats.docx_handler import UNKNOWN, FormatResolver, ends_with_page_break, has_drawing, text_runs

SCALE = 0.8  # escala de la vista: los paneles conservan las proporciones de la página real
PX_PER_CM = 37.795 * SCALE
PX_PER_PT = 96 / 72 * SCALE
CHANGED_BACKGROUND = "#FFF3C4"
EXCLUDED_BACKGROUND = "#E3EAF7"
_ALIGN_CSS = {WD_ALIGN_PARAGRAPH.CENTER: "center", WD_ALIGN_PARAGRAPH.RIGHT: "right", WD_ALIGN_PARAGRAPH.JUSTIFY: "justify"}
_THEME_COLOR = "#2F5496"  # aproximación del color de tema que Word usa en los encabezados
_PAGE_BREAK = '<p style="text-align:center; color:#9aa3ad; font-size:7pt; margin:6px 0;">— salto de página —</p>'


def _px_cm(value) -> int:
    return round(Length(value).cm * PX_PER_CM) if value not in (None, UNKNOWN) else 0


def _px_pt(value) -> int:
    return round(Length(value).pt * PX_PER_PT) if value not in (None, UNKNOWN) else 0


def _run_html(run, paragraph, resolver: FormatResolver) -> str:
    font = resolver.run_font(run, paragraph)
    color = resolver.run_color(run, paragraph)
    color = "#000000" if color == "AUTO" else _THEME_COLOR if color.startswith("tema:") else f"#{color}"
    style = [
        f"font-family:'{font if font is not UNKNOWN else 'Calibri'}'",
        f"font-size:{resolver.run_size(run, paragraph) * SCALE:.1f}pt",
        f"color:{color}",
        "font-weight:bold" if resolver.run_flag(run, paragraph, "w:b") else "font-weight:normal",
        "font-style:italic" if resolver.run_flag(run, paragraph, "w:i") else "font-style:normal",
    ]
    text = html.escape(run.text).replace("\t", "&emsp;").replace("\n", "<br/>")
    return f'<span style="{"; ".join(style)}">{text}</span>'


def paragraph_html(paragraph: Paragraph, resolver: FormatResolver, background: str | None = None) -> str:
    value = lambda attr: resolver.paragraph_value(paragraph, attr)  # noqa: E731
    align = value("alignment")
    spacing = value("line_spacing")
    if spacing in (None, UNKNOWN):
        line_height = "100%"
    elif isinstance(spacing, Length):
        line_height = f"{_px_pt(spacing)}px"
    else:
        line_height = f"{round(float(spacing) * 100)}%"
    style = [
        f"text-align:{_ALIGN_CSS.get(align, 'left')}",
        f"margin-left:{_px_cm(value('left_indent'))}px",
        f"margin-right:{_px_cm(value('right_indent'))}px",
        f"text-indent:{_px_cm(value('first_line_indent'))}px",
        f"margin-top:{_px_pt(value('space_before'))}px",
        f"margin-bottom:{_px_pt(value('space_after'))}px",
        f"line-height:{line_height}",
    ]
    if background:
        style.append(f"background-color:{background}")
    content = "".join(_run_html(run, paragraph, resolver) for run in text_runs(paragraph))
    if has_drawing(paragraph._p):
        content += '<span style="color:#6b7280; font-size:8pt;">[imagen — se conserva sin cambios]</span>'
    before = _PAGE_BREAK if value("page_break_before") is True else ""
    after = _PAGE_BREAK if ends_with_page_break(paragraph._p) else ""
    return f'{before}<p style="{"; ".join(style)}">{content or "&nbsp;"}</p>{after}'


def _table_html(table: Table, resolver: FormatResolver, background: str | None) -> str:
    rows = []
    for row in table.rows:
        cells = "".join(
            "<td>" + "".join(paragraph_html(p, resolver) for p in cell.paragraphs) + "</td>" for cell in row.cells)
        rows.append(f"<tr>{cells}</tr>")
    bg = f' bgcolor="{background}"' if background else ""
    return f'<table border="1" cellspacing="0" cellpadding="3" width="100%"{bg}>{"".join(rows)}</table>'


def _section_banner(doc, resolver: FormatResolver) -> str:
    """Tamaño de página, márgenes y encabezado de la primera sección."""
    section = doc.sections[0]
    size = f"{Length(section.page_width).cm:.2f} × {Length(section.page_height).cm:.2f} cm"
    margins = " · ".join(f"{name} {Length(getattr(section, attr)).cm:.2f}" for name, attr in (
        ("sup.", "top_margin"), ("inf.", "bottom_margin"), ("izq.", "left_margin"), ("der.", "right_margin")))
    banner = (f'<p style="color:#6b7280; font-size:7.5pt; margin-bottom:6px;">Página {size} · márgenes {margins} cm</p>')
    if not section.header.is_linked_to_previous:  # leer un encabezado inexistente lo crearía
        content = "".join(paragraph_html(p, resolver) for p in section.header.paragraphs)
        banner += ('<table width="100%" cellspacing="0" cellpadding="2" style="border: 1px dashed #c0c6cf;">'
                   f'<tr><td><p style="color:#9aa3ad; font-size:6.5pt;">Encabezado de página</p>{content}</td></tr></table>')
    return banner


def render_html(doc, structure, changed: set[int] = frozenset(), excluded: set[int] = frozenset()) -> tuple[str, int]:
    """HTML del documento y ancho del texto en píxeles (ancho de página menos márgenes)."""
    resolver = FormatResolver(doc)
    parts = [_section_banner(doc, resolver)]
    for element in structure.elements:
        background = CHANGED_BACKGROUND if element.index in changed else EXCLUDED_BACKGROUND if element.index in excluded else None
        parts.append(f'<a name="e{element.index}"></a>')
        if isinstance(element.obj, Paragraph):
            parts.append(paragraph_html(element.obj, resolver, background))
        elif isinstance(element.obj, Table):
            parts.append(_table_html(element.obj, resolver, background))
        else:
            parts.append(f'<p style="color:#6b7280;">[{html.escape(element.label)} — se conserva sin cambios]</p>')
    section = doc.sections[0]
    width = section.page_width - (section.left_margin or 0) - (section.right_margin or 0)
    return "".join(parts), _px_cm(width)
