"""Generador de documentos de prueba con estructuras distintas.

Ejecutar «python -m tests.samples» regenera los archivos de tests/documentos/.
"""
from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

LOREM = ("El sueño cumple funciones esenciales en la consolidación de la memoria y en la regulación "
         "emocional, según diversos estudios realizados durante las últimas décadas. ")


def tiny_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
    pixels = b"".join(b"\x00" + b"\x3b\x7b\xf6" * 2 for _ in range(2))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


def add_hyperlink(paragraph, url: str, text: str) -> None:
    rel_id = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rel_id)
    run = OxmlElement("w:r")
    node = OxmlElement("w:t")
    node.text = text
    run.append(node)
    link.append(run)
    paragraph._p.append(link)


def build_full(path: Path) -> Path:
    """Trabajo académico completo con portada, niveles, lista, tabla, imagen y referencias."""
    doc = Document()
    doc.add_paragraph("Efectos del sueño en la memoria", style="Title")
    author = doc.add_paragraph("Ana Pérez Gómez")
    author.alignment = WD_ALIGN_PARAGRAPH.CENTER
    university = doc.add_paragraph("Universidad Nacional")
    university.alignment = WD_ALIGN_PARAGRAPH.CENTER
    university.add_run().add_break(WD_BREAK.PAGE)

    doc.add_paragraph("Resumen")
    doc.add_paragraph("Este trabajo revisa la relación entre el sueño y la memoria en estudiantes universitarios.")
    keywords = doc.add_paragraph("Palabras clave: sueño, memoria, aprendizaje")
    keywords.add_run().add_break(WD_BREAK.PAGE)

    doc.add_heading("Introducción", level=1)
    body = doc.add_paragraph(LOREM * 3)
    body.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    body.paragraph_format.line_spacing = 1.15
    body.paragraph_format.space_after = Pt(8)
    doc.add_paragraph("Según García (2019), el descanso favorece el aprendizaje (Martínez y Soto, 2021; Pérez, 2018).")
    link_paragraph = doc.add_paragraph("Consulte la guía oficial en ")
    add_hyperlink(link_paragraph, "https://apastyle.apa.org", "apastyle.apa.org")

    doc.add_heading("Antecedentes", level=2)
    doc.add_paragraph("Primer hallazgo relevante", style="List Bullet")
    doc.add_paragraph("Segundo hallazgo relevante", style="List Bullet")
    quote = doc.add_paragraph(LOREM * 2)
    quote.paragraph_format.left_indent = Cm(1.27)

    doc.add_heading("Método", level=3)
    doc.add_paragraph("Tabla 1")
    doc.add_paragraph("Horas de sueño por grupo")
    table = doc.add_table(rows=2, cols=2)
    for row, values in zip(table.rows, (("Grupo", "Horas"), ("Control", "7.5"))):
        for cell, value in zip(row.cells, values):
            cell.text = value
    doc.add_paragraph("Nota. Datos simulados para la prueba.")
    doc.add_paragraph("Figura 1")
    doc.add_paragraph("Evolución del sueño")
    doc.add_picture(io.BytesIO(tiny_png()), width=Cm(2))
    doc.add_paragraph(LOREM)

    doc.add_heading("Referencias", level=1)
    doc.add_paragraph("García, L. (2019). Sueño y aprendizaje. Editorial Académica. https://doi.org/10.1000/xyz123")
    doc.add_paragraph("Martínez, R., & Soto, P. (2021). Memoria y descanso. Revista de Psicología, 12(3), 45–60. doi:10.1234/rp.2021")
    doc.add_paragraph("Walker, M. (2017). Why we sleep. Scribner.")
    doc.save(path)
    return path


def build_plain(path: Path) -> Path:
    """Solo párrafos, sin encabezados ni portada."""
    doc = Document()
    for _ in range(4):
        doc.add_paragraph(LOREM * 2)
    doc.save(path)
    return path


def build_sections(path: Path) -> Path:
    """Dos secciones (una horizontal), encabezado con texto y primera página distinta."""
    doc = Document()
    first = doc.sections[0]
    first.different_first_page_header_footer = True
    first.header.paragraphs[0].text = "Informe interno"
    doc.add_heading("Resultados", level=1)
    doc.add_paragraph(LOREM)
    landscape = doc.add_section()
    landscape.orientation = WD_ORIENT.LANDSCAPE
    landscape.page_width, landscape.page_height = landscape.page_height, landscape.page_width
    doc.add_paragraph(LOREM)
    doc.save(path)
    return path


BUILDERS = {
    "trabajo_completo.docx": build_full,
    "solo_parrafos.docx": build_plain,
    "secciones_y_encabezado.docx": build_sections,
}

if __name__ == "__main__":
    target = Path(__file__).parent / "documentos"
    target.mkdir(exist_ok=True)
    for name, builder in BUILDERS.items():
        print(builder(target / name))
