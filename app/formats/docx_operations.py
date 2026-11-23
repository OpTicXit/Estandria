"""Operaciones de formato sobre DOCX: cada una sabe *comprobar* y *aplicar*.

Los catálogos JSON referencian estas operaciones por nombre (campo «tipo»), de modo
que agregar una normativa nueva no exige escribir código mientras use operaciones
existentes. Las operaciones nunca modifican texto: solo propiedades de formato.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Length, Mm, Pt, RGBColor
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.core import citations
from app.core.document_analyzer import CITING_KINDS
from app.formats.docx_handler import UNKNOWN, FormatResolver, ends_with_page_break, text_runs

PARRAFO = "parrafo"
SECCION = "seccion"


@dataclass
class CheckResult:
    cumple: bool | None  # None = no se pudo determinar
    actual: str
    esperado: str


@dataclass
class Target:
    label: str
    obj: Any  # Paragraph o Section
    index: int


@dataclass
class OpContext:
    doc: Any
    resolver: FormatResolver
    structure: Any = None  # DocumentStructure, para las comprobaciones que cruzan elementos
    cache: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Operation:
    nivel: str
    # Propiedades de formato que escribe: el motor rechaza catálogos donde dos reglas compatibles
    # escriben la misma propiedad sobre el mismo tipo de elemento (configuración contradictoria).
    propiedades: frozenset
    # Parámetros que necesita: nombre → (tipo, valores admitidos o None).
    requiere: dict
    check: Callable[[Target, dict, OpContext], CheckResult]
    # apply devuelve notas para el usuario (lista vacía o None si no hay nada que avisar)
    apply: Callable[[Target, dict, OpContext], list[str] | None] | None
    tablas: bool = False  # puede aplicarse también a tablas (a todo el texto de sus celdas)
    verificacion: bool = False  # solo comprueba: corregirlo exigiría cambiar el contenido


OPERATIONS: dict[str, Operation] = {}


def _register(name: str, nivel: str, propiedades: set, requiere: dict, check, apply, **flags) -> None:
    OPERATIONS[name] = Operation(nivel, frozenset(propiedades), requiere, check, apply, **flags)


_NUM = ("numero", None)


ALIGNMENTS = {
    "izquierda": WD_ALIGN_PARAGRAPH.LEFT,
    "centro": WD_ALIGN_PARAGRAPH.CENTER,
    "derecha": WD_ALIGN_PARAGRAPH.RIGHT,
    "justificada": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
_ALIGN_NAMES = {value: name for name, value in ALIGNMENTS.items()}
_LEN_TOLERANCE = Cm(0.01)


def _same_length(a, b) -> bool:
    return abs(int(a) - int(b)) <= _LEN_TOLERANCE


def _cm(value) -> str:
    return f"{Length(value).cm:.2f} cm"


def _align_name(value) -> str:
    if value is UNKNOWN:
        return "no determinada"
    return _ALIGN_NAMES.get(value or WD_ALIGN_PARAGRAPH.LEFT, str(value).lower())


def _value(ctx: OpContext, target: Target, attr: str):
    return ctx.resolver.paragraph_value(target.obj, attr)


# --------------------------------------------------------------------------- tipografía

def _runs_of(target: Target) -> list[tuple]:
    """(fragmento, párrafo) del elemento; para una tabla, de todas sus celdas (incluidas tablas anidadas)."""
    obj = target.obj
    paragraphs = [Paragraph(p, obj) for p in obj._tbl.iter(qn("w:p"))] if isinstance(obj, Table) else [obj]
    return [(run, paragraph) for paragraph in paragraphs for run in text_runs(paragraph)]


def _check_family(t, p, ctx):
    expected = p["familia"]
    runs = _runs_of(t)
    if not runs:
        return CheckResult(True, "sin texto", expected)
    fonts = {ctx.resolver.run_font(r, para) for r, para in runs}
    if UNKNOWN in fonts:
        return CheckResult(None, "fuente del tema sin resolver", expected)
    ok = all(font.casefold() == expected.casefold() for font in fonts)
    return CheckResult(ok, ", ".join(sorted(fonts)), expected)


def _apply_family(t, p, ctx):
    for run, _ in _runs_of(t):
        fonts = run._r.get_or_add_rPr().get_or_add_rFonts()
        # Los atributos de tema prevalecen sobre la fuente explícita: hay que quitarlos.
        for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme"):
            fonts.attrib.pop(qn(attr), None)
        for attr in ("w:ascii", "w:hAnsi", "w:cs"):
            fonts.set(qn(attr), p["familia"])


def _check_size(t, p, ctx):
    expected = float(p["tamano"])
    runs = _runs_of(t)
    if not runs:
        return CheckResult(True, "sin texto", f"{expected:g} pt")
    sizes = sorted({ctx.resolver.run_size(r, para) for r, para in runs})
    ok = all(abs(size - expected) < 0.01 for size in sizes)
    return CheckResult(ok, ", ".join(f"{s:g} pt" for s in sizes), f"{expected:g} pt")


def _apply_size(t, p, ctx):
    for run, _ in _runs_of(t):
        run.font.size = Pt(float(p["tamano"]))


_HEX = re.compile(r"^[0-9A-F]{6}$")


def _check_color(t, p, ctx):
    expected = str(p["color"]).upper()
    runs = _runs_of(t)
    if not runs:
        return CheckResult(True, "sin texto", expected)
    colors = {ctx.resolver.run_color(r, para) for r, para in runs}
    normalized = {"000000" if c == "AUTO" else c for c in colors}  # «automático» se muestra negro
    return CheckResult(normalized == {expected}, ", ".join(sorted(colors)), expected)


def _apply_color(t, p, ctx):
    expected = str(p["color"]).upper()
    if not _HEX.match(expected):
        return [f"el color «{expected}» no es un valor hexadecimal válido (por ejemplo 000000); no se modificó."]
    for run, _ in _runs_of(t):
        run.font.color.rgb = RGBColor.from_string(expected)
    return None


# --------------------------------------------------------------------------- etiqueta inicial

_LABEL = re.compile(r"\s*[^:.]{1,40}?[:.]")  # «Palabras clave:», «Nota.»


def _label_parts(paragraph) -> tuple[list, int] | None:
    """Fragmentos del párrafo y posición donde termina la etiqueta inicial."""
    runs = text_runs(paragraph)
    match = _LABEL.match("".join(r.text for r in runs))
    return (runs, match.end()) if match else None


def _split_run(run, offset: int) -> bool:
    """Divide un fragmento en dos sin alterar su texto. Solo si es un fragmento simple (un único w:t)."""
    element = run._r
    content = [child for child in element if child.tag != qn("w:rPr")]
    if len(content) != 1 or content[0].tag != qn("w:t"):
        return False
    text_node = content[0]
    full = text_node.text or ""
    clone = copy.deepcopy(element)
    clone_text = clone.find(qn("w:t"))
    text_node.text, clone_text.text = full[:offset], full[offset:]
    for node in (text_node, clone_text):
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    element.addnext(clone)
    return True


def _check_label(t, p, ctx):
    expected = "etiqueta en cursiva" if p["cursiva"] else "etiqueta sin cursiva"
    parts = _label_parts(t.obj)
    if parts is None:
        return CheckResult(None, "sin etiqueta reconocible", expected)
    runs, end = parts
    flags, position = [], 0
    for run in runs:
        if position < end and run.text[: end - position].strip():
            flags.append(ctx.resolver.run_flag(run, t.obj, "w:i"))
        position += len(run.text)
    actual = _flags_text(flags, "etiqueta en cursiva", "etiqueta sin cursiva")
    return CheckResult(all(f == p["cursiva"] for f in flags), actual, expected)


def _apply_label(t, p, ctx):
    parts = _label_parts(t.obj)
    if parts is None:
        return ["no se reconoció la etiqueta inicial; no se modificó."]
    runs, end = parts
    position = 0
    for run in runs:  # primero se separa la etiqueta si comparte fragmento con el resto del texto
        start, position = position, position + len(run.text)
        if start < end < position:
            if not _split_run(run, end - start):
                return ["la etiqueta comparte formato complejo con el texto siguiente; no se modificó."]
            break
    position = 0
    for run in text_runs(t.obj):
        if position >= end:
            break
        run.font.italic = bool(p["cursiva"])
        position += len(run.text)
    return None


# --------------------------------------------------------------------------- bloques

def _check_block(t, p, ctx):
    align, left, first = (_value(ctx, t, a) for a in ("alignment", "left_indent", "first_line_indent"))
    expected = f"{p['alineacion']}, izq. {float(p['izquierda_cm']):.2f} cm, 1.ª línea {float(p['primera_cm']):.2f} cm"
    if UNKNOWN in (align, left, first):
        return CheckResult(None, "no determinado", expected)
    left, first = left or Length(0), first or Length(0)
    actual = f"{_align_name(align)}, izq. {Length(left).cm:.2f} cm, 1.ª línea {Length(first).cm:.2f} cm"
    ok = (_align_name(align) == p["alineacion"] and _same_length(left, Cm(float(p["izquierda_cm"])))
          and _same_length(first, Cm(float(p["primera_cm"]))))
    return CheckResult(ok, actual, expected)


def _apply_block(t, p, ctx):
    fmt = t.obj.paragraph_format
    fmt.alignment = ALIGNMENTS[p["alineacion"]]
    fmt.left_indent = Cm(float(p["izquierda_cm"]))
    fmt.first_line_indent = Cm(float(p["primera_cm"]))


# --------------------------------------------------------------------------- párrafos

def _spacing_text(value) -> str:
    if value is UNKNOWN:
        return "no determinado"
    if value is None:
        return "1 (sencillo)"
    if isinstance(value, Length):
        return f"fijo/mínimo {value.pt:g} pt"
    return f"{value:g}"


def _check_line_spacing(t, p, ctx):
    expected = float(p["multiplo"])
    value = _value(ctx, t, "line_spacing")
    if value is UNKNOWN:
        return CheckResult(None, "no determinado", f"{expected:g}")
    ok = value is not None and not isinstance(value, Length) and abs(float(value) - expected) < 0.01
    if value is None:
        ok = abs(expected - 1.0) < 0.01
    return CheckResult(ok, _spacing_text(value), f"{expected:g}")


def _apply_line_spacing(t, p, ctx):
    t.obj.paragraph_format.line_spacing = float(p["multiplo"])  # float ⇒ interlineado múltiple


def _check_alignment(t, p, ctx):
    expected = p["alineacion"]
    value = _value(ctx, t, "alignment")
    if value is UNKNOWN:
        return CheckResult(None, "no determinada", expected)
    return CheckResult(_align_name(value) == expected, _align_name(value), expected)


def _apply_alignment(t, p, ctx):
    t.obj.paragraph_format.alignment = ALIGNMENTS[p["alineacion"]]


def _length_operation(attr: str, param: str):
    def check(t, p, ctx):
        expected = Cm(float(p[param]))
        value = _value(ctx, t, attr)
        if value is UNKNOWN:
            return CheckResult(None, "no determinada", _cm(expected))
        value = value or Length(0)
        return CheckResult(_same_length(value, expected), _cm(value), _cm(expected))

    def apply(t, p, ctx):
        setattr(t.obj.paragraph_format, attr, Cm(float(p[param])))

    return check, apply


def _check_side_indents(t, p, ctx):
    left, right = _value(ctx, t, "left_indent"), _value(ctx, t, "right_indent")
    expected = f"izq. {float(p['izquierda_cm']):.2f} cm · der. {float(p['derecha_cm']):.2f} cm"
    if UNKNOWN in (left, right):
        return CheckResult(None, "no determinada", expected)
    left, right = left or Length(0), right or Length(0)
    ok = _same_length(left, Cm(float(p["izquierda_cm"]))) and _same_length(right, Cm(float(p["derecha_cm"])))
    return CheckResult(ok, f"izq. {Length(left).cm:.2f} cm · der. {Length(right).cm:.2f} cm", expected)


def _apply_side_indents(t, p, ctx):
    t.obj.paragraph_format.left_indent = Cm(float(p["izquierda_cm"]))
    t.obj.paragraph_format.right_indent = Cm(float(p["derecha_cm"]))


def _spacing_operation(attr: str, param: str):
    def check(t, p, ctx):
        expected = Pt(float(p[param]))
        value = _value(ctx, t, attr)
        if value is UNKNOWN:
            return CheckResult(None, "no determinado", f"{float(p[param]):g} pt")
        value = value or Length(0)
        ok = abs(int(value) - int(expected)) <= Pt(0.1)
        return CheckResult(ok, f"{Length(value).pt:g} pt", f"{float(p[param]):g} pt")

    def apply(t, p, ctx):
        setattr(t.obj.paragraph_format, attr, Pt(float(p[param])))

    return check, apply


def _check_hanging(t, p, ctx):
    size = Cm(float(p["sangria_cm"]))
    left, first = _value(ctx, t, "left_indent"), _value(ctx, t, "first_line_indent")
    expected = f"francesa {_cm(size)}"
    if UNKNOWN in (left, first):
        return CheckResult(None, "no determinada", expected)
    left, first = left or Length(0), first or Length(0)
    ok = _same_length(left, size) and _same_length(first, -size)
    if int(first) < 0:
        actual = f"francesa {_cm(-int(first))} (izq. {_cm(left)})"
    else:
        actual = f"primera línea {_cm(first)} · izq. {_cm(left)}"
    return CheckResult(ok, actual, expected)


def _apply_hanging(t, p, ctx):
    size = Cm(float(p["sangria_cm"]))
    t.obj.paragraph_format.left_indent = size
    t.obj.paragraph_format.first_line_indent = -size


def _flags_text(values: list[bool], on: str, off: str) -> str:
    if all(values):
        return on
    if not any(values):
        return off
    return f"{on} parcial"


def _check_heading_format(t, p, ctx):
    runs = text_runs(t.obj)
    align = _value(ctx, t, "alignment")
    first = _value(ctx, t, "first_line_indent")
    bold = [ctx.resolver.run_flag(r, t.obj, "w:b") for r in runs] or [p["negrita"]]
    italic = [ctx.resolver.run_flag(r, t.obj, "w:i") for r in runs] or [p["cursiva"]]
    indent = Cm(float(p["sangria_cm"]))
    expected = ", ".join([
        p["alineacion"],
        "negrita" if p["negrita"] else "sin negrita",
        "cursiva" if p["cursiva"] else "sin cursiva",
        f"sangría {_cm(indent)}",
    ])
    if UNKNOWN in (align, first):
        return CheckResult(None, "no determinado", expected)
    first = first or Length(0)
    actual = ", ".join([
        _align_name(align),
        _flags_text(bold, "negrita", "sin negrita"),
        _flags_text(italic, "cursiva", "sin cursiva"),
        f"sangría {_cm(first)}",
    ])
    ok = (
        _align_name(align) == p["alineacion"]
        and all(b == p["negrita"] for b in bold)
        and all(i == p["cursiva"] for i in italic)
        and _same_length(first, indent)
    )
    return CheckResult(ok, actual, expected)


def _apply_heading_format(t, p, ctx):
    fmt = t.obj.paragraph_format
    fmt.alignment = ALIGNMENTS[p["alineacion"]]
    fmt.first_line_indent = Cm(float(p["sangria_cm"]))
    for run in text_runs(t.obj):
        run.font.bold = bool(p["negrita"])
        run.font.italic = bool(p["cursiva"])


def _previous_block(p_element):
    sibling = p_element.getprevious()
    while sibling is not None and sibling.tag not in (qn("w:p"), qn("w:tbl"), qn("w:sdt")):
        sibling = sibling.getprevious()
    return sibling


def _check_page_break_before(t, p, ctx):
    expected = "comienza en página nueva"
    if _value(ctx, t, "page_break_before") is True:
        return CheckResult(True, "salto antes del párrafo", expected)
    previous = _previous_block(t.obj._p)
    if previous is None:
        return CheckResult(True, "primer elemento del documento", expected)
    if previous.tag == qn("w:p") and ends_with_page_break(previous):
        return CheckResult(True, "precedido por un salto de página o de sección", expected)
    return CheckResult(False, "continúa en la misma página", expected)


def _apply_page_break_before(t, p, ctx):
    t.obj.paragraph_format.page_break_before = True


# --------------------------------------------------------------------------- secciones

def _check_margins(t, p, ctx):
    section = t.obj
    names = (("superior_cm", "top_margin", "sup."), ("inferior_cm", "bottom_margin", "inf."),
             ("izquierdo_cm", "left_margin", "izq."), ("derecho_cm", "right_margin", "der."))
    expected = " · ".join(f"{short} {float(p[key]):.2f}" for key, _, short in names) + " cm"
    values = [getattr(section, attr) for _, attr, _ in names]
    if None in values:
        return CheckResult(None, "márgenes no definidos en la sección", expected)
    actual = " · ".join(f"{short} {Length(v).cm:.2f}" for (_, _, short), v in zip(names, values)) + " cm"
    ok = all(_same_length(v, Cm(float(p[key]))) for (key, _, _), v in zip(names, values))
    return CheckResult(ok, actual, expected)


def _apply_margins(t, p, ctx):
    section = t.obj
    section.top_margin = Cm(float(p["superior_cm"]))
    section.bottom_margin = Cm(float(p["inferior_cm"]))
    section.left_margin = Cm(float(p["izquierdo_cm"]))
    section.right_margin = Cm(float(p["derecho_cm"]))


PAPER_SIZES = {"Carta": (Mm(215.9), Mm(279.4)), "A4": (Mm(210), Mm(297)), "Oficio": (Mm(215.9), Mm(355.6))}


def _paper_name(short, long) -> str:
    for name, (w, h) in PAPER_SIZES.items():
        if abs(short - w) <= Mm(1) and abs(long - h) <= Mm(1):
            return name
    return f"{Length(short).mm:.0f} × {Length(long).mm:.0f} mm"


def _check_paper(t, p, ctx):
    width, height = t.obj.page_width, t.obj.page_height
    if width is None or height is None:
        return CheckResult(None, "tamaño no definido", p["papel"])
    short, long = sorted((int(width), int(height)))
    actual = _paper_name(short, long)
    return CheckResult(actual == p["papel"], actual, p["papel"])


def _apply_paper(t, p, ctx):
    section = t.obj
    short, long = PAPER_SIZES[p["papel"]]
    width, height = section.page_width, section.page_height
    landscape = section.orientation == WD_ORIENT.LANDSCAPE or (width and height and width > height)
    # Se conserva la orientación de cada sección (p. ej. una sección horizontal para una tabla).
    section.page_width, section.page_height = (long, short) if landscape else (short, long)


_PAGE_FIELD = re.compile(r"^\s*PAGE(\s|\\|$)", re.IGNORECASE)


def _headers_of(section, ctx) -> list[tuple[str, Any]]:
    headers = [("encabezado", section.header)]
    if section.different_first_page_header_footer:
        headers.append(("encabezado de primera página", section.first_page_header))
    if ctx.doc.settings.odd_and_even_pages_header_footer:
        headers.append(("encabezado de páginas pares", section.even_page_header))
    return headers


def _page_field_paragraph(header) -> Paragraph | None:
    """Busca el campo PAGE en todo el encabezado (también dentro de controles de contenido)."""
    root = header._element
    for simple in root.iter(qn("w:fldSimple")):
        if _PAGE_FIELD.match(simple.get(qn("w:instr")) or ""):
            return Paragraph(next(simple.iterancestors(qn("w:p"))), header)
    for instr in root.iter(qn("w:instrText")):
        if _PAGE_FIELD.match(instr.text or ""):
            return Paragraph(next(instr.iterancestors(qn("w:p"))), header)
    return None


def _header_state(header, index: int, position: str, ctx) -> tuple[bool | None, str]:
    if header.is_linked_to_previous:
        # Leer un encabezado vinculado de la primera sección lo crearía: se evita.
        return (True, "heredado de la sección anterior") if index > 0 else (False, "sin encabezado")
    paragraph = _page_field_paragraph(header)
    if paragraph is None:
        return False, "sin número de página"
    if paragraph._p.xpath(".//w:tab | .//w:ptab"):
        return None, "número colocado con tabulaciones"
    align = _align_name(ctx.resolver.paragraph_value(paragraph, "alignment"))
    return align == position, f"número a la {align}" if align != "centro" else "número centrado"


def _check_page_number(t, p, ctx):
    position = p["posicion"]
    expected = f"número de página ({position}) en todos los encabezados"
    states = [(label, *_header_state(h, t.index, position, ctx)) for label, h in _headers_of(t.obj, ctx)]
    actual = "; ".join(f"{label}: {desc}" for label, _, desc in states)
    values = [ok for _, ok, _ in states]
    if all(v is True for v in values):
        return CheckResult(True, actual, expected)
    return CheckResult(False if False in values else None, actual, expected)


def _append_page_field(paragraph: Paragraph) -> None:
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), " PAGE ")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "1"  # valor provisional: Word lo recalcula al abrir
    run.append(text)
    field.append(run)
    paragraph._p.append(field)


def _apply_page_number(t, p, ctx):
    notes = []
    position = p["posicion"]
    for label, header in _headers_of(t.obj, ctx):
        state, desc = _header_state(header, t.index, position, ctx)
        if state is True:
            continue
        if state is None:
            notes.append(f"{label}: {desc}; se conserva tal como está para no desplazar su contenido.")
            continue
        if header.is_linked_to_previous:
            header.is_linked_to_previous = False  # crea un encabezado propio vacío
        paragraph = _page_field_paragraph(header)
        if paragraph is None:
            has_content = header._element.xpath(".//w:t[normalize-space()] | .//w:drawing | .//w:pict")
            if has_content or not header.paragraphs:
                paragraph = header.add_paragraph()
                notes.append(f"{label}: tenía contenido; el número se agregó en un párrafo nuevo.")
            else:
                paragraph = header.paragraphs[0]
            _append_page_field(paragraph)
        paragraph.paragraph_format.alignment = ALIGNMENTS[position]
    return notes


def _check_orientation(t, p, ctx):
    width, height = t.obj.page_width, t.obj.page_height
    if width is None or height is None:
        return CheckResult(None, "tamaño no definido", p["orientacion"])
    actual = "horizontal" if width > height else "vertical"
    return CheckResult(actual == p["orientacion"], actual, p["orientacion"])


def _apply_orientation(t, p, ctx):
    section = t.obj
    landscape = p["orientacion"] == "horizontal"
    section.orientation = WD_ORIENT.LANDSCAPE if landscape else WD_ORIENT.PORTRAIT
    width, height = section.page_width, section.page_height
    if (width > height) != landscape:
        section.page_width, section.page_height = height, width


def _page_number_start(section) -> str | None:
    element = section._sectPr.find(qn("w:pgNumType"))
    return None if element is None else element.get(qn("w:start"))


def _check_numbering(t, p, ctx):
    start = _page_number_start(t.obj)
    if t.index == 0:
        return CheckResult(start in (None, "1"), "comienza en 1" if start in (None, "1") else f"comienza en {start}",
                           "comienza en 1")
    return CheckResult(start is None, "continúa la numeración" if start is None else f"reinicia en {start}",
                       "continúa la numeración")


def _apply_numbering(t, p, ctx):
    element = t.obj._sectPr.find(qn("w:pgNumType"))
    if element is not None:
        element.attrib.pop(qn("w:start"), None)  # sin «start», Word empieza en 1 o continúa


# --------------------------------------------------------------------------- verificaciones (no modifican)

def _citation_index(ctx) -> dict:
    """Citas por elemento, referencias y abreviaturas; se calcula una vez por documento."""
    if "citas" not in ctx.cache:
        by_element = {e.index: citations.extract_citations(e.text) for e in ctx.structure.of_kinds(CITING_KINDS)}
        everything = [c for found in by_element.values() for c in found]
        references = [(e, citations.reference_key(e.text)) for e in ctx.structure.of_kinds(["referencia"])]
        ctx.cache["citas"] = {"por_elemento": by_element, "todas": everything, "referencias": references,
                              "abreviaturas": citations.abbreviation_map(everything)}
    return ctx.cache["citas"]


def _check_cited_have_reference(t, p, ctx):
    index = _citation_index(ctx)
    found = index["por_elemento"].get(t.index, [])
    expected = "cada cita tiene su referencia"
    if not found:
        return CheckResult(True, "sin citas", expected)
    keys = [key for _, key in index["referencias"] if key]
    missing = [c.texto for c in found if not any(citations.matches(c, k, index["abreviaturas"]) for k in keys)]
    if missing:
        return CheckResult(False, "sin referencia: " + "; ".join(dict.fromkeys(missing)), expected)
    return CheckResult(True, f"{len(found)} cita(s) con referencia", expected)


def _check_reference_cited(t, p, ctx):
    index = _citation_index(ctx)
    key = citations.reference_key(t.obj.text)
    expected = "citada en el texto"
    if key is None:
        return CheckResult(None, "no se reconocen autor y año", expected)
    cited = any(citations.matches(c, key, index["abreviaturas"]) for c in index["todas"])
    return CheckResult(cited, "citada en el texto" if cited else "no se cita en el texto", expected)


def _check_alphabetical(t, p, ctx):
    references = [e for e, _ in _citation_index(ctx)["referencias"]]
    position = next(i for i, e in enumerate(references) if e.index == t.index)
    expected = "en orden alfabético"
    if position == 0:
        return CheckResult(True, "primera entrada", expected)
    previous = references[position - 1]
    if citations.sort_key(previous.text) <= citations.sort_key(t.obj.text):
        return CheckResult(True, "en orden", expected)
    return CheckResult(False, f"debería ir antes de «{previous.text[:40]}…»", expected)


_OLD_DOI = re.compile(r"\bdoi:\s*10\.|dx\.doi\.org", re.IGNORECASE)


def _check_doi(t, p, ctx):
    expected = "DOI como https://doi.org/…"
    if _OLD_DOI.search(t.obj.text):
        return CheckResult(False, "usa «doi:» o dx.doi.org", expected)
    return CheckResult(True, "correcto o sin DOI", expected)


def _check_year(t, p, ctx):
    ok = citations.has_reference_year(t.obj.text)
    return CheckResult(ok, "año entre paréntesis" if ok else "no se encontró «(año)» ni «(s. f.)»", "autor. (año).")


# --------------------------------------------------------------------------- registro

_ALIGN = ("opcion", frozenset(ALIGNMENTS))

_register("familia_fuente", PARRAFO, {"fuente"}, {"familia": ("opcion", None)}, _check_family, _apply_family, tablas=True)
_register("tamano_fuente", PARRAFO, {"tamano"}, {"tamano": _NUM}, _check_size, _apply_size, tablas=True)
_register("color_fuente", PARRAFO, {"color"}, {"color": ("opcion", None)}, _check_color, _apply_color, tablas=True)
_register("etiqueta_inicial", PARRAFO, {"cursiva"}, {"cursiva": ("booleano", None)}, _check_label, _apply_label)
_register("bloque", PARRAFO, {"alineacion", "sangria_izquierda", "sangria_primera"},
          {"alineacion": ("opcion", frozenset(ALIGNMENTS)), "izquierda_cm": _NUM, "primera_cm": _NUM},
          _check_block, _apply_block)
_register("orientacion", SECCION, {"orientacion"}, {"orientacion": ("opcion", frozenset({"vertical", "horizontal"}))},
          _check_orientation, _apply_orientation)
_register("numeracion_inicio", SECCION, {"numeracion"}, {}, _check_numbering, _apply_numbering)
_register("citas_con_referencia", PARRAFO, set(), {}, _check_cited_have_reference, None, verificacion=True)
_register("referencia_citada", PARRAFO, set(), {}, _check_reference_cited, None, verificacion=True)
_register("orden_alfabetico", PARRAFO, set(), {}, _check_alphabetical, None, verificacion=True)
_register("formato_doi", PARRAFO, set(), {}, _check_doi, None, verificacion=True)
_register("anio_referencia", PARRAFO, set(), {}, _check_year, None, verificacion=True)
_register("interlineado", PARRAFO, {"interlineado"}, {"multiplo": _NUM}, _check_line_spacing, _apply_line_spacing)
_register("alineacion", PARRAFO, {"alineacion"}, {"alineacion": _ALIGN}, _check_alignment, _apply_alignment)
_register("sangria_primera_linea", PARRAFO, {"sangria_primera"}, {"sangria_cm": _NUM},
          *_length_operation("first_line_indent", "sangria_cm"))
_register("sangrias_laterales", PARRAFO, {"sangria_izquierda", "sangria_derecha"},
          {"izquierda_cm": _NUM, "derecha_cm": _NUM}, _check_side_indents, _apply_side_indents)
_register("espaciado_anterior", PARRAFO, {"espacio_antes"}, {"puntos": _NUM}, *_spacing_operation("space_before", "puntos"))
_register("espaciado_posterior", PARRAFO, {"espacio_despues"}, {"puntos": _NUM}, *_spacing_operation("space_after", "puntos"))
_register("sangria_francesa", PARRAFO, {"sangria_izquierda", "sangria_primera"}, {"sangria_cm": _NUM},
          _check_hanging, _apply_hanging)
_register("formato_titulo", PARRAFO, {"alineacion", "sangria_primera", "negrita", "cursiva"},
          {"alineacion": _ALIGN, "negrita": ("booleano", None), "cursiva": ("booleano", None), "sangria_cm": _NUM},
          _check_heading_format, _apply_heading_format)
_register("salto_pagina_antes", PARRAFO, {"salto_antes"}, {}, _check_page_break_before, _apply_page_break_before)
_register("margenes", SECCION, {"margenes"},
          {"superior_cm": _NUM, "inferior_cm": _NUM, "izquierdo_cm": _NUM, "derecho_cm": _NUM},
          _check_margins, _apply_margins)
_register("tamano_papel", SECCION, {"papel"}, {"papel": ("opcion", frozenset(PAPER_SIZES))}, _check_paper, _apply_paper)
_register("numero_pagina", SECCION, {"numero_pagina"},
          {"posicion": ("opcion", frozenset({"derecha", "centro", "izquierda"}))}, _check_page_number, _apply_page_number)
