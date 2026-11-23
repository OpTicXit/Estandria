"""Registro de formatos de documento y detección por firma binaria.

Solo los formatos con ``soportado=True`` tienen un procesador implementado.
Los demás se identifican para informar al usuario, sin tocar el archivo.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FormatSpec:
    extension: str
    nombre: str
    firma: str  # firma binaria esperada, ver detect_signature()
    soportado: bool
    alternativa: str = ""


_CONVERT_HINT = (
    "Ábralo en Microsoft Word o LibreOffice Writer, use «Guardar como» → "
    "Documento de Word (.docx) e importe el archivo nuevo. "
    "La conversión automática se incorporará en una fase posterior."
)

FORMATS: dict[str, FormatSpec] = {
    ".docx": FormatSpec(".docx", "Documento de Word (DOCX)", "docx", True),
    ".doc": FormatSpec(".doc", "Documento de Word 97-2003 (DOC)", "ole", False, _CONVERT_HINT),
    ".odt": FormatSpec(".odt", "Documento OpenDocument (ODT)", "odt", False, _CONVERT_HINT),
    ".rtf": FormatSpec(".rtf", "Texto enriquecido (RTF)", "rtf", False, _CONVERT_HINT),
}

SIGNATURE_NAMES = {
    "docx": "un documento DOCX",
    "odt": "un documento ODT",
    "ole": "un documento Word 97-2003 (DOC)",
    "rtf": "un documento RTF",
    "zip": "un archivo ZIP que no es un documento de Word",
    "danado": "un archivo ZIP dañado",
    "desconocido": "un formato no reconocido",
}


def detect_signature(path: Path) -> str:
    """Identifica el formato real por su contenido, no por la extensión."""
    with open(path, "rb") as handle:
        head = handle.read(8)
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as package:
                names = set(package.namelist())
                if "word/document.xml" in names:
                    return "docx"
                if "mimetype" in names and b"opendocument.text" in package.read("mimetype"):
                    return "odt"
        except zipfile.BadZipFile:
            return "danado"
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole"
    if head.startswith(b"{\\rtf"):
        return "rtf"
    return "desconocido"
