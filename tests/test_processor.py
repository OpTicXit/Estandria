"""Aplicación de reglas y exportación, comprobadas sobre el archivo DOCX exportado."""
import pytest
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Length

from app.core.document_analyzer import analyze_document
from app.core.document_exporter import ExportError
from app.core.document_loader import create_working_copy, inspect_file
from app.core.document_processor import process_document
from app.formats.docx_handler import FormatResolver, integrity_snapshot, open_docx, text_runs
from tests.conftest import sha256


def run(path, selection, tmp_path, name="salida.docx"):
    info = inspect_file(path)
    copy = create_working_copy(info)
    result = process_document(copy, info.ruta, tmp_path / name, selection)
    doc = open_docx(result.destino)
    return result, doc, analyze_document(doc)


def of_kind(structure, kind):
    return [e.obj for e in structure.elements if e.kind == kind]


def only(selection, *rule_ids):
    selection.set_all(False)
    for rule_id in rule_ids:
        selection.set_active(rule_id, True)
    return selection


def close(a, b):
    return abs(int(a or 0) - int(b)) <= Cm(0.01)


def test_full_apa_export(full_doc, selection, tmp_path):
    original_hash = sha256(full_doc)
    result, doc, structure = run(full_doc, selection, tmp_path)
    resolver = FormatResolver(doc)

    assert result.errores == []
    assert all(c.ok for c in result.integridad)
    for report in result.cumplimiento.reglas:
        allowed = ("cumple", "sin_elementos", "revisar") if report.verificacion else ("cumple", "sin_elementos")
        assert report.estado in allowed, report.rule.id
    assert sha256(full_doc) == original_hash, "el original no debe cambiar"

    for p in of_kind(structure, "parrafo"):
        assert p.paragraph_format.line_spacing == 2.0
        assert close(p.paragraph_format.first_line_indent, Cm(1.27))
        # Los que ya estaban a la izquierda por herencia no se tocan: se comprueba el valor efectivo.
        assert resolver.paragraph_value(p, "alignment") in (None, WD_ALIGN_PARAGRAPH.LEFT)
        for r in text_runs(p):
            assert resolver.run_font(r, p) == "Times New Roman" and resolver.run_size(r, p) == 12
    for p in of_kind(structure, "referencia"):
        assert close(p.paragraph_format.left_indent, Cm(1.27))
        assert close(p.paragraph_format.first_line_indent, -Cm(1.27))
    heading = of_kind(structure, "encabezado_1")[0]
    assert heading.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert all(r.font.bold for r in text_runs(heading))
    assert of_kind(structure, "titulo_referencias")[0].paragraph_format.page_break_before
    section = doc.sections[0]
    assert close(section.top_margin, Cm(2.54)) and close(section.left_margin, Cm(2.54))
    assert section.header._element.xpath(".//w:fldSimple")


def italic_label(paragraph, resolver):
    """(cursiva de la etiqueta, cursiva del resto) en el archivo exportado."""
    runs = text_runs(paragraph)
    label_end = paragraph.text.index(":") + 1 if ":" in paragraph.text[:30] else paragraph.text.index(".") + 1
    flags, position = [], 0
    for run in runs:
        flags.append((position < label_end, resolver.run_flag(run, paragraph, "w:i")))
        position += len(run.text)
    return {f for inside, f in flags if inside}, {f for inside, f in flags if not inside}


def test_phase3_structure_tables_and_citations(full_doc, selection, tmp_path):
    result, doc, structure = run(full_doc, selection, tmp_path)
    resolver = FormatResolver(doc)

    title = of_kind(structure, "titulo")[0]
    assert title.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER and all(r.font.bold for r in text_runs(title))
    for p in of_kind(structure, "portada"):
        assert p.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER
    abstract_title = of_kind(structure, "titulo_resumen")[0]
    assert abstract_title.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert close(of_kind(structure, "resumen")[0].paragraph_format.first_line_indent, 0)

    keywords = of_kind(structure, "palabras_clave")[0]
    assert italic_label(keywords, resolver) == ({True}, {False}), "solo la etiqueta va en cursiva"
    assert keywords.text == "Palabras clave: sueño, memoria, aprendizaje", "el texto no cambia"
    assert close(keywords.paragraph_format.first_line_indent, Cm(1.27))

    numbers = of_kind(structure, "leyenda")
    titles = of_kind(structure, "titulo_leyenda")
    assert all(r.font.bold for p in numbers for r in text_runs(p))
    assert all(r.font.italic and not r.font.bold for p in titles for r in text_runs(p))
    note = of_kind(structure, "nota_tabla")[0]
    assert italic_label(note, resolver)[0] == {True}
    quote = of_kind(structure, "cita_bloque")[0]
    assert close(quote.paragraph_format.left_indent, Cm(1.27)) and close(quote.paragraph_format.first_line_indent, 0)

    table = doc.tables[0]
    for paragraph in (p for row in table.rows for cell in row.cells for p in cell.paragraphs):
        for r in text_runs(paragraph):
            assert resolver.run_font(r, paragraph) == "Times New Roman" and resolver.run_size(r, paragraph) == 12

    review = " | ".join(result.revisiones)
    missing = next(r for r in result.revisiones if "sin referencia" in r).split("sin referencia:")[1]
    assert missing.strip() == "(Pérez, 2018)", "solo falta la referencia de Pérez"
    assert "Walker" in review and "no se cita" in review
    assert "doi:" in review
    assert not any("Orden alfabético" in r for r in result.revisiones)


def test_verification_rules_never_modify(full_doc, selection, tmp_path):
    only(selection, "cit_con_referencia", "ref_citada", "ref_orden", "ref_doi", "ref_anio")
    result, doc, _ = run(full_doc, selection, tmp_path)
    assert result.cambios == [] and result.revisiones
    original = open_docx(full_doc)
    assert [p.text for p in doc.paragraphs] == [p.text for p in original.paragraphs]


def test_numbering_restart_is_removed(sections_doc, selection, tmp_path):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    source = open_docx(sections_doc)
    numbering = OxmlElement("w:pgNumType")
    numbering.set(qn("w:start"), "5")
    source.sections[1]._sectPr.append(numbering)
    source.save(sections_doc)
    _, doc, _ = run(sections_doc, only(selection, "num_inicio"), tmp_path)
    assert doc.sections[1]._sectPr.find(qn("w:pgNumType")).get(qn("w:start")) is None


def test_orientation_rule_is_off_by_default_and_keeps_landscape(sections_doc, selection, tmp_path):
    assert not selection.is_active("pag_orientacion")
    _, doc, _ = run(sections_doc, selection, tmp_path)
    assert doc.sections[1].page_width > doc.sections[1].page_height


def test_disabled_rule_is_not_applied(full_doc, selection, tmp_path):
    selection.set_active("par_sangria_primera", False)
    result, doc, structure = run(full_doc, selection, tmp_path)
    assert any("Sangría de primera línea" in o for o in result.omitidos)
    for p in of_kind(structure, "parrafo"):
        assert p.paragraph_format.first_line_indent is None, "la sangría desactivada no se toca"
        assert p.paragraph_format.line_spacing == 2.0, "las demás reglas sí se aplican"


def test_single_rule_changes_only_its_property(full_doc, selection, tmp_path):
    before = analyze_document(open_docx(full_doc))
    before_body = [(p.paragraph_format.first_line_indent, p.paragraph_format.alignment)
                   for p in of_kind(before, "parrafo")]
    _, doc, structure = run(full_doc, only(selection, "par_interlineado"), tmp_path)
    after = of_kind(structure, "parrafo")
    assert [p.paragraph_format.line_spacing for p in after] == [2.0] * len(after)
    assert [(p.paragraph_format.first_line_indent, p.paragraph_format.alignment) for p in after] == before_body
    assert doc.sections[0].top_margin == open_docx(full_doc).sections[0].top_margin


def test_hanging_indent_only_on_references(full_doc, selection, tmp_path):
    _, _, structure = run(full_doc, only(selection, "ref_sangria_francesa"), tmp_path)
    for e in structure.elements:
        if hasattr(e.obj, "paragraph_format") and e.kind != "referencia":
            indent = e.obj.paragraph_format.first_line_indent
            assert indent is None or int(indent) >= 0, f"{e.label} no debería tener sangría francesa"
    assert all(int(p.paragraph_format.first_line_indent) < 0 for p in of_kind(structure, "referencia"))


def test_cover_and_block_quote_are_preserved(full_doc, selection, tmp_path):
    _, _, structure = run(full_doc, selection, tmp_path)
    for p in of_kind(structure, "portada")[1:]:
        assert p.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER
        assert p.paragraph_format.first_line_indent is None
    quote = of_kind(structure, "cita_bloque")[0]
    assert close(quote.paragraph_format.left_indent, Cm(1.27))


def test_tables_images_and_links_are_preserved(full_doc, selection, tmp_path):
    original = integrity_snapshot(open_docx(full_doc))
    _, doc, _ = run(full_doc, selection, tmp_path)
    exported = integrity_snapshot(doc)
    assert exported == original
    assert doc.tables[0].cell(1, 1).text == "7.5"


def test_existing_header_is_kept_and_sections_keep_orientation(sections_doc, selection, tmp_path):
    result, doc, _ = run(sections_doc, selection, tmp_path)
    header = doc.sections[0].header
    assert header.paragraphs[0].text == "Informe interno"
    assert header._element.xpath(".//w:fldSimple")
    assert doc.sections[0].first_page_header._element.xpath(".//w:fldSimple")
    landscape = doc.sections[1]
    assert landscape.page_width > landscape.page_height
    assert any("tenía contenido" in a for a in result.advertencias)


def test_custom_parameter_value_is_applied(plain_doc, selection, tmp_path):
    selection.set_param("tip_familia", "familia", "Arial")
    selection.set_param("tip_tamano", "tamano", 11)
    _, doc, structure = run(plain_doc, selection, tmp_path)
    resolver = FormatResolver(doc)
    for p in of_kind(structure, "parrafo"):
        assert {resolver.run_font(r, p) for r in text_runs(p)} == {"Arial"}
        assert {resolver.run_size(r, p) for r in text_runs(p)} == {11}


def test_export_never_overwrites_original(full_doc, selection, tmp_path):
    original_hash = sha256(full_doc)
    info = inspect_file(full_doc)
    copy = create_working_copy(info)
    with pytest.raises(ExportError, match="original"):
        process_document(copy, info.ruta, full_doc, selection)
    assert sha256(full_doc) == original_hash


def test_export_to_missing_folder_fails_cleanly(full_doc, selection, tmp_path):
    info = inspect_file(full_doc)
    copy = create_working_copy(info)
    with pytest.raises(ExportError, match="no existe"):
        process_document(copy, info.ruta, tmp_path / "no" / "salida.docx", selection)


def test_export_adds_docx_extension(plain_doc, selection, tmp_path):
    info = inspect_file(plain_doc)
    result = process_document(create_working_copy(info), info.ruta, tmp_path / "sin_extension", selection)
    assert result.destino.suffix == ".docx" and result.destino.is_file()
    assert not list(tmp_path.glob("~*.tmp")), "no deben quedar temporales"


def test_reprocessing_the_export_finds_nothing_to_change(full_doc, selection, tmp_path):
    first, _, _ = run(full_doc, selection, tmp_path, "primera.docx")
    second, _, _ = run(first.destino, selection, tmp_path, "segunda.docx")
    assert second.cambios == [] and second.errores == []


def test_length_helper_sanity():
    assert int(Cm(1.27)) == int(Length(457200))
