"""Excepciones del usuario, páginas estimadas y vista previa en memoria."""
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.shared import Cm

from app.core.document_analyzer import PAGINATION_EXPLICIT, PAGINATION_RENDERED, analyze_document
from app.core.document_loader import create_working_copy, inspect_file
from app.core.document_processor import apply_selection, process_document
from app.core.document_validator import validate
from app.core.exceptions import DocException, ExceptionSet, section_under
from app.formats.docx_handler import open_docx, text_runs
from app.formats.docx_preview import CHANGED_BACKGROUND, EXCLUDED_BACKGROUND, render_html
from tests.conftest import sha256


def structure_of(path):
    return analyze_document(open_docx(path))


def find(structure, text):
    return next(e for e in structure.elements if e.text == text)


# --------------------------------------------------------------------------- páginas

def test_pages_from_explicit_breaks(full_doc):
    structure = structure_of(full_doc)
    assert structure.paginacion == PAGINATION_EXPLICIT
    assert find(structure, "Efectos del sueño en la memoria").paginas == (1, 1)
    assert find(structure, "Resumen").paginas == (2, 2)
    assert find(structure, "Introducción").paginas == (3, 3)
    assert structure.total_paginas == 3


def test_pages_from_word_rendering(tmp_path):
    doc = Document()
    doc.add_paragraph("Primera página")
    spanning = doc.add_paragraph()
    spanning.add_run("empieza aquí ")
    run = spanning.add_run("y termina en la siguiente")
    run._r.insert(0, OxmlElement("w:lastRenderedPageBreak"))
    doc.add_paragraph("Segunda página")
    path = tmp_path / "paginado.docx"
    doc.save(path)
    structure = structure_of(path)
    assert structure.paginacion == PAGINATION_RENDERED
    assert [e.paginas for e in structure.elements] == [(1, 1), (1, 2), (2, 2)]


# --------------------------------------------------------------------------- tipos de excepción

def test_exception_kinds(full_doc):
    structure = structure_of(full_doc)
    exceptions = ExceptionSet()
    heading = find(structure, "Introducción")
    by_element = DocException("elemento", (heading.index,))
    by_kind = DocException("tipo", "referencia")
    by_page = DocException("pagina", 2)
    antecedentes = find(structure, "Antecedentes")
    by_section = DocException("seccion", antecedentes.index)
    assert [e.index for e in exceptions.elements_of(by_element, structure)] == [heading.index]
    assert len(exceptions.elements_of(by_kind, structure)) == 3
    assert {e.kind for e in exceptions.elements_of(by_page, structure)} == {"titulo_resumen", "resumen", "palabras_clave"}
    section = exceptions.elements_of(by_section, structure)
    texts = [e.text for e in section]
    assert texts[0] == "Antecedentes" and "Método" in texts, "un nivel 3 pertenece a la sección de nivel 2"
    assert "Referencias" not in texts, "la sección termina en el siguiente nivel 1"


def test_section_under_unknown_heading_is_empty(full_doc):
    assert section_under(structure_of(full_doc), 9999) == []


def test_excluded_only_for_chosen_rules(full_doc):
    structure = structure_of(full_doc)
    exceptions = ExceptionSet()
    exceptions.add(DocException("tipo", "parrafo", ("par_sangria_primera",)))
    assert exceptions.excluded(structure, "par_sangria_primera")
    assert not exceptions.excluded(structure, "par_interlineado")


def test_warnings(full_doc, selection):
    structure = structure_of(full_doc)
    exceptions = ExceptionSet()
    exceptions.add(DocException("elemento", (find(structure, "Introducción").index,)))
    exceptions.add(DocException("pagina", 99))
    exceptions.add(DocException("tipo", "parrafo", ("regla_de_otra_normativa",)))
    levels = [level for level, _ in exceptions.warnings(structure, selection)]
    assert levels == ["advertencia", "info", "info"]


# --------------------------------------------------------------------------- aplicación y exportación

def run(path, selection, exceptions, tmp_path):
    info = inspect_file(path)
    result = process_document(create_working_copy(info), info.ruta, tmp_path / "salida.docx", selection, exceptions)
    doc = open_docx(result.destino)
    return result, doc, analyze_document(doc)


def test_excluded_heading_keeps_original_format(full_doc, selection, tmp_path):
    structure = structure_of(full_doc)
    exceptions = ExceptionSet()
    exceptions.add(DocException("elemento", (find(structure, "Introducción").index,)))
    result, _, exported = run(full_doc, selection, exceptions, tmp_path)
    intro, refs = find(exported, "Introducción"), find(exported, "Referencias")
    assert intro.obj.paragraph_format.alignment is None, "el encabezado excluido no se tocó"
    assert not any(r.font.size for r in text_runs(intro.obj))
    assert refs.obj.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER, "los demás sí se formatean"
    assert any("excluido" in o for o in result.omitidos)
    nivel1 = next(r for r in result.cumplimiento.reglas if r.rule.id == "est_nivel_1")
    assert nivel1.excluidos == 1 and nivel1.estado == "sin_elementos"


def test_rule_specific_exception_keeps_one_format(full_doc, selection, tmp_path):
    structure = structure_of(full_doc)
    body = next(e for e in structure.elements if e.kind == "parrafo")
    exceptions = ExceptionSet()
    exceptions.add(DocException("elemento", (body.index,), ("par_sangria_primera",)))
    _, _, exported = run(full_doc, selection, exceptions, tmp_path)
    paragraph = next(e for e in exported.elements if e.index == body.index).obj
    assert paragraph.paragraph_format.first_line_indent is None, "se conserva la sangría original"
    assert paragraph.paragraph_format.line_spacing == 2.0, "las demás reglas se aplican"


def test_validation_respects_exceptions(full_doc, selection):
    doc = open_docx(full_doc)
    structure = analyze_document(doc)
    exceptions = ExceptionSet()
    exceptions.add(DocException("tipo", "referencia"))
    report = validate(doc, structure, selection, exceptions)
    hanging = next(r for r in report.reglas if r.rule.id == "ref_sangria_francesa")
    assert hanging.findings == [] and hanging.excluidos == 3


# --------------------------------------------------------------------------- vista previa

def test_apply_selection_is_in_memory(full_doc, selection):
    original = sha256(full_doc)
    doc = open_docx(full_doc)
    result = apply_selection(doc, selection)
    assert result.destino is None and result.cambios
    assert all(c.indice is not None for c in result.cambios if c.regla != "Márgenes" and "Sección" not in c.elemento)
    assert sha256(full_doc) == original


def test_preview_html_shows_changes(full_doc, selection):
    before = open_docx(full_doc)
    after = open_docx(full_doc)
    structure = analyze_document(before)
    intro = find(structure, "Introducción")
    exceptions = ExceptionSet()
    exceptions.add(DocException("elemento", (intro.index,)))
    result = apply_selection(after, selection, exceptions)
    changed = {c.indice for c in result.cambios if c.indice is not None}
    assert intro.index not in changed
    html_before, width_before = render_html(before, structure)
    html_after, width_after = render_html(after, analyze_document(after), changed, {intro.index})
    assert CHANGED_BACKGROUND not in html_before and CHANGED_BACKGROUND in html_after
    assert EXCLUDED_BACKGROUND in html_after
    assert "line-height:200%" in html_after and "line-height:200%" not in html_before
    assert "Times New Roman" in html_after
    assert f'name="e{intro.index}"' in html_after
    assert width_after == round(Cm(21.59 - 2 * 2.54).cm * 37.795 * 0.8)
