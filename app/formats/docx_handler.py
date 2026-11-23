"""Acceso de bajo nivel a documentos DOCX (Open XML).

Reúne lo que depende de la estructura interna del formato: apertura validada,
recorrido del cuerpo en orden, resolución del formato *efectivo* de párrafos y
fragmentos de texto, e instantáneas de integridad para comparar antes/después.
"""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.parfmt import ParagraphFormat
from docx.text.run import Run
from lxml import etree

MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


class DocxError(Exception):
    """Problema comprensible para el usuario al abrir un DOCX."""


class _Unknown:
    """Marcador de un valor de formato que no se pudo interpretar."""

    def __repr__(self) -> str:
        return "UNKNOWN"

    def __bool__(self) -> bool:
        return False


UNKNOWN = _Unknown()


def open_docx(path):
    """Abre un DOCX comprobando antes que el paquete ZIP esté íntegro."""
    path = Path(path)
    if not path.is_file():
        raise DocxError(f"No se encontró el archivo «{path}».")
    try:
        with zipfile.ZipFile(path) as package:
            damaged = package.testzip()
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocxError(f"«{path.name}» no es un paquete DOCX válido ({exc}).") from exc
    if damaged:
        raise DocxError(f"«{path.name}» está dañado: la parte «{damaged}» no supera la verificación de integridad.")
    try:
        return Document(str(path))
    except Exception as exc:  # python-docx lanza distintos tipos según el defecto
        raise DocxError(f"No se pudo interpretar «{path.name}» como documento de Word: {exc}") from exc


# --------------------------------------------------------------------------- recorrido

def iter_body_blocks(doc):
    """Recorre el cuerpo en orden: Paragraph, Table o el elemento XML sin interpretar."""
    for child in doc.element.body.iterchildren():
        if not isinstance(child.tag, str) or child.tag == qn("w:sectPr"):
            continue
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc._body)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc._body)
        elif child.tag in (qn("w:bookmarkStart"), qn("w:bookmarkEnd")):
            continue
        else:
            yield child


# Fragmentos de texto del párrafo, incluidos los de hipervínculos y campos simples,
# pero no los de cuadros de texto anidados (esos se conservan intactos).
_RUN_XPATH = "./w:r | ./w:hyperlink/w:r | ./w:ins/w:r | ./w:smartTag/w:r | ./w:fldSimple/w:r | ./w:customXml/w:r"


def text_runs(paragraph: Paragraph) -> list[Run]:
    return [Run(r, paragraph) for r in paragraph._p.xpath(_RUN_XPATH) if r.find(qn("w:t")) is not None]


def has_drawing(element) -> bool:
    return bool(element.xpath(".//w:drawing | .//w:pict | .//w:object"))


def ends_with_page_break(p_element) -> bool:
    """True si el párrafo termina en salto de página o cierra una sección."""
    if p_element.xpath("./w:pPr/w:sectPr"):
        return True
    last_break = last_text = -1
    for position, element in enumerate(p_element.iter()):
        if element.tag == qn("w:br") and element.get(qn("w:type")) == "page":
            last_break = position
        elif element.tag == qn("w:t") and (element.text or "").strip():
            last_text = position
    return last_break > last_text


def count_elements(root, *tags: str) -> int:
    return sum(1 for tag in tags for _ in root.iter(qn(tag)))


def footnote_count(doc) -> int:
    try:
        part = doc.part.part_related_by(RT.FOOTNOTES)
    except KeyError:
        return 0
    root = etree.fromstring(part.blob)
    # Las notas con w:type son separadores internos de Word, no notas del autor.
    return sum(1 for note in root.iter(qn("w:footnote")) if note.get(qn("w:type")) is None)


def integrity_snapshot(doc) -> dict[str, object]:
    """Huella del contenido del cuerpo: debe ser idéntica antes y después de aplicar formato."""
    body = doc.element.body
    text = "".join(t.text or "" for t in body.iter(qn("w:t")))
    return {
        "caracteres": len(text),
        "texto": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        "parrafos": count_elements(body, "w:p"),
        "tablas": count_elements(body, "w:tbl"),
        "imagenes": count_elements(body, "w:drawing", "w:pict"),
        "hipervinculos": count_elements(body, "w:hyperlink"),
        "secciones": len(doc.sections),
        "notas_al_pie": footnote_count(doc),
    }


# --------------------------------------------------------------------------- formato efectivo

def style_chain(style):
    """El estilo y sus estilos base, del más específico al más general."""
    seen = set()
    while style is not None:
        key = style.style_id or style.name
        if key in seen:
            return
        seen.add(key)
        yield style
        style = style.base_style


class _PPrHolder:
    """Adaptador mínimo para leer un <w:pPr> suelto (docDefaults) con ParagraphFormat."""

    def __init__(self, pPr):
        self.pPr = pPr


def _theme_fonts(doc) -> dict[str, str]:
    try:
        part = doc.part.part_related_by(RT.THEME)
    except KeyError:
        return {}
    root = etree.fromstring(part.blob)
    fonts = {}
    for kind in ("major", "minor"):
        latin = root.find(f".//{{{DRAWING_NS}}}{kind}Font/{{{DRAWING_NS}}}latin")
        if latin is not None and latin.get("typeface"):
            fonts[f"{kind}HAnsi"] = fonts[f"{kind}Ascii"] = latin.get("typeface")
    return fonts


class FormatResolver:
    """Calcula el formato que Word mostrará realmente: directo → estilos → valores por defecto.

    shortcut: las propiedades «alternantes» (negrita/cursiva heredadas de varios estilos
    que se anulan entre sí) se resuelven tomando el nivel más específico; basta para el
    contenido académico habitual y se puede refinar si aparecen documentos que lo requieran.
    """

    DEFAULT_FONT = "Times New Roman"  # lo que usa Word si ningún nivel define la fuente
    DEFAULT_SIZE_PT = 10.0

    def __init__(self, doc):
        styles = doc.styles.element
        ppr = styles.xpath("./w:docDefaults/w:pPrDefault/w:pPr")
        rpr = styles.xpath("./w:docDefaults/w:rPrDefault/w:rPr")
        self._default_pf = ParagraphFormat(_PPrHolder(ppr[0])) if ppr else None
        self._default_rpr = rpr[0] if rpr else None
        self._theme = _theme_fonts(doc)

    # párrafos
    def paragraph_value(self, paragraph: Paragraph, attr: str):
        """Valor efectivo de un atributo de ParagraphFormat; None si nadie lo define."""
        sources = [paragraph.paragraph_format]
        sources += [style.paragraph_format for style in style_chain(paragraph.style)]
        if self._default_pf is not None:
            sources.append(self._default_pf)
        for fmt in sources:
            try:
                value = getattr(fmt, attr)
            except Exception:  # valor XML que python-docx no sabe interpretar
                return UNKNOWN
            if value is not None:
                return value
        return None

    # fragmentos de texto
    def _rpr_layers(self, run: Run, paragraph: Paragraph) -> list:
        layers = []
        rpr = run._r.rPr
        if rpr is not None:
            layers.append(rpr)
            if rpr.rStyle is not None:
                layers += [s.element.rPr for s in style_chain(run.style) if s.element.rPr is not None]
        layers += [s.element.rPr for s in style_chain(paragraph.style) if s.element.rPr is not None]
        if self._default_rpr is not None:
            layers.append(self._default_rpr)
        return layers

    def run_font(self, run: Run, paragraph: Paragraph):
        for rpr in self._rpr_layers(run, paragraph):
            fonts = rpr.find(qn("w:rFonts"))
            if fonts is None:
                continue
            theme = fonts.get(qn("w:asciiTheme"))  # en Word, el tema prevalece sobre w:ascii
            if theme:
                return self._theme.get(theme, UNKNOWN)
            if fonts.get(qn("w:ascii")):
                return fonts.get(qn("w:ascii"))
        return self.DEFAULT_FONT

    def run_size(self, run: Run, paragraph: Paragraph) -> float:
        for rpr in self._rpr_layers(run, paragraph):
            size = rpr.find(qn("w:sz"))
            if size is not None and size.get(qn("w:val")):
                return int(size.get(qn("w:val"))) / 2
        return self.DEFAULT_SIZE_PT

    def run_color(self, run: Run, paragraph: Paragraph) -> str:
        for rpr in self._rpr_layers(run, paragraph):
            color = rpr.find(qn("w:color"))
            if color is None:
                continue
            if color.get(qn("w:themeColor")):
                return f"tema:{color.get(qn('w:themeColor'))}"
            return (color.get(qn("w:val")) or "auto").upper()
        return "AUTO"

    def run_flag(self, run: Run, paragraph: Paragraph, tag: str) -> bool:
        """Negrita (w:b) o cursiva (w:i) efectiva."""
        for rpr in self._rpr_layers(run, paragraph):
            element = rpr.find(qn(tag))
            if element is not None:
                return element.get(qn("w:val"), "true") not in ("0", "false", "off", "none")
        return False
