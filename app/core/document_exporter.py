"""Exportación segura: nunca sobrescribe el original y solo publica archivos verificados."""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Callable

from app.formats.docx_handler import DocxError


class ExportError(Exception):
    """No se pudo exportar; el mensaje es apto para el usuario."""


def _same_file(a: Path, b: Path) -> bool:
    if a == b:
        return True
    try:
        return a.exists() and b.exists() and os.path.samefile(a, b)
    except OSError:
        return False


def save_verified(doc, destination, protected: list, verify: Callable[[Path], None] | None = None) -> Path:
    """Guarda en un temporal, lo verifica y solo entonces lo mueve al destino.

    Si la verificación falla, el destino no se toca y el temporal se elimina.
    """
    dest = Path(destination).expanduser()
    if dest.suffix.lower() != ".docx":
        dest = dest.with_name(dest.name + ".docx")
    dest = dest.resolve()
    for path in protected:
        if _same_file(dest, Path(path).resolve()):
            raise ExportError("El destino coincide con el documento original. Elija otro nombre: el original nunca se sobrescribe.")
    if not dest.parent.is_dir():
        raise ExportError(f"La carpeta «{dest.parent}» no existe.")

    temporary = dest.with_name(f"~{dest.stem}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        doc.save(str(temporary))
        if verify is not None:
            verify(temporary)
        os.replace(temporary, dest)
    except ExportError:
        raise
    except DocxError as exc:
        raise ExportError(f"El archivo generado no superó la validación: {exc}") from exc
    except PermissionError as exc:
        raise ExportError(f"No se puede escribir «{dest.name}». ¿Está abierto en Word? ({exc})") from exc
    except OSError as exc:
        raise ExportError(f"No se pudo guardar «{dest.name}»: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return dest
