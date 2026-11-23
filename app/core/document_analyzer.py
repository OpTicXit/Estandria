"""Etapa 1 — Análisis: identifica los componentes del documento sin modificarlo.

Cada bloque del cuerpo recibe un «tipo» (párrafo, encabezado, referencia…). Las reglas
se aplican por tipo, de modo que, por ejemplo, la sangría francesa solo llega a los
párrafos identificados como referencias. Lo que no se sabe interpretar se marca para
conservarlo intacto.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from docx.enum.section import WD_SECTION_START
from docx.oxml.ns import qn
from docx.shared import Cm
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.core.citations import extract_citations
from app.formats.docx_handler import (
    MATH_NS, UNKNOWN, FormatResolver, count_elements, ends_with_page_break,
    footnote_count, has_drawing, iter_body_blocks, style_chain,
)

KIND_LABELS = {
    "portada": "Portada",
    "titulo": "Título",
    "subtitulo": "Subtítulo",
    "parrafo": "Párrafo",
    "lista": "Elemento de lista",
    "cita_bloque": "Cita en bloque",
    "titulo_resumen": "Título del resumen",
    "resumen": "Resumen",
    "palabras_clave": "Palabras clave",
    "leyenda": "Número de tabla/figura",
    "titulo_leyenda": "Título de tabla/figura",
    "nota_tabla": "Nota de tabla/figura",
    "leyenda_combinada": "Rótulo combinado de tabla/figura",
    "titulo_referencias": "Título de referencias",
    "referencia": "Referencia bibliográfica",
    "imagen": "Imagen",
    "tabla": "Tabla",
    "vacio": "Párrafo vacío",
    "salto_pagina": "Salto de página",
    "indice": "Tabla de contenido",
    "control_contenido": "Control de contenido",
    "desconocido": "Elemento no reconocido",
    "secciones": "Secciones del documento",
}


def known_scopes() -> set[str]:
    """Alcances que puede usar un catálogo: los tipos de elemento que el analizador produce."""
    return set(KIND_LABELS) | {f"encabezado_{n}" for n in range(1, 10)}


def kind_label(kind: str) -> str:
    if kind.startswith("encabezado_"):
        return f"Encabezado de nivel {kind.split('_')[1]}"
    return KIND_LABELS.get(kind, kind)


@dataclass
class Element:
    index: int  # posición en el cuerpo, desde 1
    kind: str
    text: str
    style: str
    level: int | None = None
    obj: object = field(default=None, repr=False)  # Paragraph, Table o elemento XML
    paginas: tuple[int, int] = (1, 1)  # primera y última página (estimadas) que ocupa

    @property
    def label(self) -> str:
        preview = " ".join(self.text.split())
        if len(preview) > 48:
            preview = preview[:47] + "…"
        return f"#{self.index} · {kind_label(self.kind)}" + (f" «{preview}»" if preview else "")

    @property
    def is_heading(self) -> bool:
        return self.kind.startswith("encabezado_") or self.kind in ("titulo", "titulo_resumen", "titulo_referencias")


@dataclass
class DocumentStructure:
    elements: list[Element]
    resumen: dict[str, int]  # conteos que muestra la interfaz
    conservados: list[str]  # elementos que no se interpretan y quedan intactos
    paginacion: str = ""  # de dónde salen los números de página estimados

    def of_kinds(self, kinds) -> list[Element]:
        kinds = set(kinds)
        return [e for e in self.elements if e.kind in kinds]

    @property
    def total_paginas(self) -> int:
        return max((e.paginas[1] for e in self.elements), default=1)


_HEADING_STYLE = re.compile(r"^(heading|t[ií]tulo|encabezado)\s*(\d)$", re.IGNORECASE)
_TOC_STYLE = re.compile(r"^(toc|tdc)\s*\d", re.IGNORECASE)
_TITLE_STYLES = {"title", "título", "titulo"}
_SUBTITLE_STYLES = {"subtitle", "subtítulo", "subtitulo"}
_CAPTION_STYLES = {"caption", "descripción", "descripcion", "epígrafe", "epigrafe", "leyenda"}
_CAPTION_LABEL = re.compile(r"^(tabla|figura|table|figure)\s+\d+[.:]?(\s|$)", re.IGNORECASE)
_CAPTION_ALONE = re.compile(r"^(tabla|figura|table|figure)\s+\d+\.?$", re.IGNORECASE)  # APA: número en su propia línea
_KEYWORDS = re.compile(r"^(palabras clave|keywords)\s*:")
_NOTE = re.compile(r"^(nota|note)\.", re.IGNORECASE)
_LIST_STYLE = re.compile(r"^(list|lista)", re.IGNORECASE)
_REFERENCE_TITLES = {
    "referencias", "references", "referencias bibliograficas", "bibliografia",
    "bibliography", "lista de referencias", "obras citadas", "works cited",
}
_ABSTRACT_TITLES = {"resumen", "abstract"}
# El título del trabajo conserva su tipo dentro de la portada: así recibe su propia regla (centrado y negrita).
_TEXT_KINDS_FOR_COVER = {"parrafo", "subtitulo", "cita_bloque", "leyenda", "leyenda_combinada"}
CITING_KINDS = ("parrafo", "lista", "cita_bloque", "nota_tabla", "resumen")


def _style_name(block) -> str:
    try:
        return block.style.name if block.style is not None else ""
    except Exception:  # estilo dañado o inexistente
        return ""


def _normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return " ".join(plain.casefold().split()).strip(" :.")


def _ppr_layers(paragraph: Paragraph) -> list:
    layers = [paragraph._p.pPr]
    layers += [s.element.pPr for s in style_chain(paragraph.style)]
    return [layer for layer in layers if layer is not None]


def _heading_level(paragraph: Paragraph, style_name: str) -> int | None:
    match = _HEADING_STYLE.match(style_name.strip())
    if match:
        return int(match.group(2))
    for ppr in _ppr_layers(paragraph):
        outline = ppr.find(qn("w:outlineLvl"))
        if outline is not None:
            level = int(outline.get(qn("w:val"), "9"))
            return level + 1 if level < 9 else None  # 9 = texto independiente
    return None


def _is_list(paragraph: Paragraph, style_name: str) -> bool:
    for ppr in _ppr_layers(paragraph):
        num_id = ppr.find(f"{qn('w:numPr')}/{qn('w:numId')}")
        if num_id is not None:
            return num_id.get(qn("w:val")) != "0"
    return bool(_LIST_STYLE.match(style_name))


def _classify_paragraph(paragraph: Paragraph, resolver: FormatResolver) -> tuple[str, int | None]:
    style_name = _style_name(paragraph)
    text = paragraph.text
    if has_drawing(paragraph._p):
        return "imagen", None
    if _TOC_STYLE.match(style_name):
        return "indice", None
    lowered = style_name.casefold()
    if lowered in _TITLE_STYLES:
        return "titulo", None
    if lowered in _SUBTITLE_STYLES:
        return "subtitulo", None
    level = _heading_level(paragraph, style_name)
    if level:
        return f"encabezado_{level}", level
    if not text.strip():
        return ("salto_pagina" if paragraph._p.xpath(".//w:br[@w:type='page']") else "vacio"), None
    if _CAPTION_ALONE.match(text.strip()):
        return "leyenda", None
    if lowered in _CAPTION_STYLES or (len(text) < 150 and _CAPTION_LABEL.match(text.strip())):
        return "leyenda_combinada", None  # número y título en la misma línea: se conserva
    if _KEYWORDS.match(_normalize(text)):
        return "palabras_clave", None
    if _is_list(paragraph, style_name):
        return "lista", None
    left = resolver.paragraph_value(paragraph, "left_indent")
    first = resolver.paragraph_value(paragraph, "first_line_indent")
    hanging = first not in (None, UNKNOWN) and int(first) < 0
    if left not in (None, UNKNOWN) and left >= Cm(1.0) and not hanging:
        return "cita_bloque", None
    return "parrafo", None


def _mark_cover(elements: list[Element]) -> None:
    """Si hay un salto de página antes del primer encabezado, lo anterior es la portada."""
    limit = next((i for i, e in enumerate(elements) if e.kind.startswith("encabezado_")), len(elements))
    for i in range(min(limit, 25)):
        block = elements[i].obj
        if not isinstance(block, Paragraph):
            continue
        if i > 0 and block.paragraph_format.page_break_before:
            end = i
        elif ends_with_page_break(block._p):
            end = i + 1
        else:
            continue
        for element in elements[:end]:
            if element.kind in _TEXT_KINDS_FOR_COVER:
                element.kind = "portada"
        return


def _mark_section(elements: list[Element], titles: set[str], title_kind: str, body_kind: str) -> None:
    """Tras un título reconocido («Referencias», «Resumen»), los párrafos siguientes pertenecen a esa
    sección hasta el próximo encabezado, salto de página o salto de sección."""
    stops = {"titulo", "titulo_referencias", "titulo_resumen", "salto_pagina", "control_contenido", "palabras_clave"}
    i = 0
    while i < len(elements):
        element = elements[i]
        candidate = element.kind.startswith("encabezado_") or element.kind in ("titulo", "parrafo")
        if not (candidate and _normalize(element.text) in titles):
            i += 1
            continue
        element.kind = title_kind
        j = i + 1
        while j < len(elements):
            current = elements[j]
            if current.kind.startswith("encabezado_") or current.kind in stops:
                break
            block = current.obj
            if isinstance(block, Paragraph) and block.paragraph_format.page_break_before:
                break
            if current.kind in ("parrafo", "cita_bloque"):
                current.kind = body_kind
            j += 1
            if isinstance(block, Paragraph) and ends_with_page_break(block._p):
                break
        i = j


def _mark_captions(elements: list[Element]) -> None:
    """APA: «Tabla 1» / título en cursiva / tabla o figura / «Nota.» debajo."""
    for i, element in enumerate(elements):
        if element.kind == "leyenda" and i + 2 < len(elements):
            title, block = elements[i + 1], elements[i + 2]
            if (title.kind in ("parrafo", "leyenda_combinada") and not _CAPTION_LABEL.match(title.text.strip())
                    and block.kind in ("tabla", "imagen")):
                title.kind = "titulo_leyenda"
        if element.kind == "parrafo" and _NOTE.match(element.text.strip()):
            previous = next((e for e in reversed(elements[:i]) if e.kind != "vacio"), None)
            if previous is not None and previous.kind in ("tabla", "imagen"):
                element.kind = "nota_tabla"


PAGINATION_RENDERED = "según la última paginación guardada por Word"
PAGINATION_EXPLICIT = "solo por saltos de página y de sección explícitos (el archivo no guarda la paginación de Word)"


def _xml_of(block):
    return block._p if isinstance(block, Paragraph) else block._tbl if isinstance(block, Table) else block


def _assign_pages(doc, elements: list[Element]) -> str:
    """Estima la página de cada elemento.

    Un DOCX no contiene páginas: las calcula Word al mostrarlo. Word sí anota dónde cortó cada
    página la última vez (w:lastRenderedPageBreak); si esas marcas existen se usan, y si no, solo
    se cuentan los saltos explícitos, que dan menos páginas que las reales.
    """
    rendered = bool(doc.element.body.xpath(".//w:lastRenderedPageBreak"))
    sections = doc.sections
    page, section = 1, 0
    for position, element in enumerate(elements):
        block = element.obj
        if (not rendered and position > 0 and isinstance(block, Paragraph)
                and block.paragraph_format.page_break_before):
            page += 1
        start, first, last = page, None, None
        for node in _xml_of(block).iter():
            if rendered:
                is_break = node.tag == qn("w:lastRenderedPageBreak")
            else:
                is_break = node.tag == qn("w:br") and node.get(qn("w:type")) == "page"
            if is_break:
                page += 1
            elif node.tag == qn("w:t") and (node.text or "").strip():
                first = first or page
                last = page
        element.paginas = (first, last) if first else (start, start)
        if not rendered and isinstance(block, Paragraph) and block._p.xpath("./w:pPr/w:sectPr"):
            section += 1
            if section < len(sections) and sections[section].start_type != WD_SECTION_START.CONTINUOUS:
                page += 1
    return PAGINATION_RENDERED if rendered else PAGINATION_EXPLICIT


def _header_footer_count(doc) -> int:
    count = 0
    for section in doc.sections:
        parts = [section.header, section.footer]
        if section.different_first_page_header_footer:
            parts += [section.first_page_header, section.first_page_footer]
        for part in parts:
            # Solo se consultan las definiciones propias: leer una vinculada la crearía.
            if not part.is_linked_to_previous and part._element.xpath(".//w:t[normalize-space()]"):
                count += 1
    return count


def _summary(doc, elements: list[Element]) -> dict[str, int]:
    body = doc.element.body
    kinds = Counter(e.kind for e in elements)
    return {
        "Párrafos de texto": kinds["parrafo"],
        "Encabezados": sum(n for k, n in kinds.items() if k.startswith("encabezado_")),
        "Elementos de lista": kinds["lista"],
        "Referencias": kinds["referencia"],
        "Citas en el texto": sum(len(extract_citations(e.text)) for e in elements if e.kind in CITING_KINDS),
        "Citas en bloque": kinds["cita_bloque"],
        "Párrafos de resumen": kinds["resumen"],
        "Tablas/figuras numeradas": kinds["leyenda"],
        "Tablas": count_elements(body, "w:tbl"),
        "Imágenes": count_elements(body, "w:drawing", "w:pict"),
        "Hipervínculos": count_elements(body, "w:hyperlink"),
        "Secciones": len(doc.sections),
        "Saltos de página": len(body.xpath(".//w:br[@w:type='page'] | .//w:pPr/w:pageBreakBefore")),
        "Notas al pie": footnote_count(doc),
        "Encabezados/pies con contenido": _header_footer_count(doc),
    }


def _preserved_notes(doc, elements: list[Element]) -> list[str]:
    body = doc.element.body
    kinds = Counter(e.kind for e in elements)
    notes = [f"{e.label}: se conserva sin modificar (su contenido no se interpreta)."
             for e in elements if e.kind in ("control_contenido", "desconocido")]
    tables = count_elements(body, "w:tbl")
    if tables:
        notes.append(f"{tables} tabla(s): se conservan su estructura, bordes y alineación; solo la tipografía de las "
                     "celdas puede cambiar si las reglas tipográficas están activas.")
    images = count_elements(body, "w:drawing", "w:pict")
    if images:
        notes.append(f"{images} imagen(es): se conservan sin modificar.")
    if kinds["leyenda_combinada"]:
        notes.append(f"{kinds['leyenda_combinada']} rótulo(s) con número y título en la misma línea: APA los separa en dos "
                     "líneas (número en negrita, título en cursiva). Separarlos cambia el contenido, así que solo reciben "
                     "tipografía y espaciado.")
    boxes = count_elements(body, "w:txbxContent")
    if boxes:
        notes.append(f"{boxes} cuadro(s) de texto: su contenido se conserva sin modificar.")
    equations = sum(1 for _ in body.iter(f"{{{MATH_NS}}}oMath"))
    if equations:
        notes.append(f"{equations} ecuación(es): se conservan sin modificar.")
    revisions = count_elements(body, "w:ins", "w:del")
    if revisions:
        notes.append(f"Hay {revisions} marca(s) de control de cambios: se conservan. Acéptelas o rechácelas en Word para obtener mejores resultados.")
    if kinds["indice"]:
        notes.append("Tabla de contenido: se conserva; actualícela en Word después de exportar.")
    deep = sum(1 for e in elements if e.kind.startswith("encabezado_") and (e.level or 0) > 5)
    if deep:
        notes.append(f"{deep} encabezado(s) de nivel mayor que 5: APA define cinco niveles; se conservan.")
    if kinds["portada"]:
        notes.append(f"Se detectó una portada ({kinds['portada']} párrafo(s) además del título): solo recibe las reglas "
                     "que la incluyen expresamente; las del texto principal, como la sangría, no la afectan.")
    notes.append("Los encabezados y pies de página existentes se conservan; solo la regla de número de página puede modificarlos.")
    return notes


def analyze_document(doc) -> DocumentStructure:
    resolver = FormatResolver(doc)
    elements: list[Element] = []
    for index, block in enumerate(iter_body_blocks(doc), start=1):
        if isinstance(block, Paragraph):
            kind, level = _classify_paragraph(block, resolver)
            elements.append(Element(index, kind, block.text, _style_name(block), level, block))
        elif isinstance(block, Table):
            elements.append(Element(index, "tabla", f"{len(block.rows)} fila(s)", _style_name(block), None, block))
        else:
            text = "".join(t.text or "" for t in block.iter(qn("w:t")))
            kind = "control_contenido" if block.tag == qn("w:sdt") else "desconocido"
            elements.append(Element(index, kind, text, "", None, block))
    _mark_cover(elements)
    _mark_section(elements, _ABSTRACT_TITLES, "titulo_resumen", "resumen")
    _mark_section(elements, _REFERENCE_TITLES, "titulo_referencias", "referencia")
    _mark_captions(elements)
    pagination = _assign_pages(doc, elements)
    return DocumentStructure(elements, _summary(doc, elements), _preserved_notes(doc, elements), pagination)
