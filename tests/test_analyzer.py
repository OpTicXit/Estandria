"""Análisis: identificación de párrafos, estilos y estructura."""
from collections import Counter

from app.core.document_analyzer import analyze_document
from app.formats.docx_handler import open_docx


def kinds(path):
    return Counter(e.kind for e in analyze_document(open_docx(path)).elements)


def test_full_document_structure(full_doc):
    structure = analyze_document(open_docx(full_doc))
    found = Counter(e.kind for e in structure.elements)
    assert found["titulo"] == 1  # el título conserva su tipo dentro de la portada
    assert found["portada"] == 2  # autor y afiliación antes del salto de página
    assert found["titulo_resumen"] == 1 and found["resumen"] == 1 and found["palabras_clave"] == 1
    assert found["encabezado_1"] == 1 and found["encabezado_2"] == 1 and found["encabezado_3"] == 1
    assert found["titulo_referencias"] == 1
    assert found["referencia"] == 3
    assert found["lista"] == 2
    assert found["cita_bloque"] == 1
    assert found["leyenda"] == 2 and found["titulo_leyenda"] == 2 and found["nota_tabla"] == 1
    assert found["tabla"] == 1
    assert found["imagen"] == 1
    assert found["parrafo"] == 4
    assert structure.resumen["Hipervínculos"] == 1
    assert structure.resumen["Tablas"] == 1
    assert structure.resumen["Citas en el texto"] == 3


def test_combined_caption_is_preserved(tmp_path):
    from docx import Document
    doc = Document()
    doc.add_paragraph("Tabla 2. Resultados del grupo control")
    doc.add_table(rows=1, cols=1)
    path = tmp_path / "rotulo.docx"
    doc.save(path)
    structure = analyze_document(open_docx(path))
    assert structure.elements[0].kind == "leyenda_combinada"
    assert any("misma línea" in note for note in structure.conservados)


def test_styles_are_detected(full_doc):
    elements = analyze_document(open_docx(full_doc)).elements
    by_text = {e.text: e for e in elements}
    assert by_text["Introducción"].style == "Heading 1"
    assert by_text["Primer hallazgo relevante"].style == "List Bullet"
    assert by_text["Efectos del sueño en la memoria"].style == "Title"


def test_plain_document_has_only_paragraphs(plain_doc):
    assert kinds(plain_doc) == Counter({"parrafo": 4})


def test_analysis_does_not_modify_the_file(full_doc):
    data = full_doc.read_bytes()
    analyze_document(open_docx(full_doc))
    assert full_doc.read_bytes() == data


def test_preserved_elements_are_reported(full_doc):
    notes = " ".join(analyze_document(open_docx(full_doc)).conservados)
    assert "tabla" in notes and "imagen" in notes and "portada" in notes
