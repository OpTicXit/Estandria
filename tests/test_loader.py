"""Importación: detección de formato, compatibilidad, copia de trabajo y manejo de errores."""
import pytest

from app.core.document_loader import LoadError, create_working_copy, inspect_file
from tests.conftest import sha256


def test_docx_is_supported_and_described(full_doc):
    info = inspect_file(full_doc)
    assert info.soportado
    assert info.firma == "docx"
    assert info.nombre == "trabajo.docx"
    assert info.tamano_bytes > 0 and "KB" in info.tamano_legible


def test_working_copy_is_separate_and_original_untouched(full_doc):
    before = sha256(full_doc)
    copy = create_working_copy(inspect_file(full_doc))
    assert copy != full_doc and copy.is_file()
    assert sha256(copy) == before
    assert sha256(full_doc) == before


@pytest.mark.parametrize("name, content, expected", [
    ("viejo.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100, "todavía no tiene un procesador"),
    ("texto.odt", b"PK\x03\x04" + b"\x00" * 50, "contenido es"),
    ("nota.rtf", b"{\\rtf1 hola}", "todavía no tiene un procesador"),
    ("datos.txt", b"hola", "no es compatible"),
    ("falso.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100, "Word 97-2003"),
    ("vacio.docx", b"", "vacío"),
])
def test_unsupported_files_are_reported_not_modified(tmp_path, name, content, expected):
    path = tmp_path / name
    path.write_bytes(content)
    info = inspect_file(path)
    assert not info.soportado
    assert expected in info.mensaje
    with pytest.raises(LoadError):
        create_working_copy(info)
    assert path.read_bytes() == content


def test_damaged_docx_is_rejected(full_doc):
    data = full_doc.read_bytes()
    full_doc.write_bytes(data[: len(data) // 2])  # ZIP truncado
    info = inspect_file(full_doc)
    with pytest.raises(LoadError):
        create_working_copy(info)


def test_missing_file_raises(tmp_path):
    with pytest.raises(LoadError):
        inspect_file(tmp_path / "no_existe.docx")
