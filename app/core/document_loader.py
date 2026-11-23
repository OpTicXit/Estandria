"""Identificación de formatos y carga segura de documentos.

El original nunca se abre para escribir: se copia a la carpeta de respaldos y todo
el procesamiento trabaja sobre esa copia.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.formats import FORMATS, SIGNATURE_NAMES, detect_signature
from app.formats.docx_handler import DocxError, open_docx
from app.paths import backups_dir


class LoadError(Exception):
    """El documento no se puede importar; el mensaje es apto para el usuario."""


@dataclass
class FileInfo:
    ruta: Path
    extension: str
    formato: str
    firma: str
    tamano_bytes: int
    soportado: bool
    mensaje: str

    @property
    def nombre(self) -> str:
        return self.ruta.name

    @property
    def carpeta(self) -> Path:
        return self.ruta.parent

    @property
    def tamano_legible(self) -> str:
        size = float(self.tamano_bytes)
        for unit in ("bytes", "KB", "MB"):
            if size < 1024:
                return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"


def inspect_file(path) -> FileInfo:
    """Describe el archivo y decide si se puede procesar, sin modificarlo."""
    ruta = Path(path).expanduser().resolve()
    if not ruta.is_file():
        raise LoadError(f"No se encontró el archivo «{ruta}».")
    try:
        size = ruta.stat().st_size
        firma = detect_signature(ruta) if size else "desconocido"
    except OSError as exc:
        raise LoadError(f"No se puede leer «{ruta.name}»: {exc}") from exc

    ext = ruta.suffix.lower()
    spec = FORMATS.get(ext)
    if spec is None:
        admitidos = ", ".join(FORMATS)
        return FileInfo(ruta, ext or "(sin extensión)", "No reconocido", firma, size, False,
                        f"La extensión «{ext or 'sin extensión'}» no es compatible. Formatos reconocidos: {admitidos}.")
    if size == 0:
        return FileInfo(ruta, ext, spec.nombre, firma, size, False, "El archivo está vacío.")
    if firma != spec.firma:
        return FileInfo(ruta, ext, spec.nombre, firma, size, False,
                        f"La extensión indica {spec.nombre}, pero el contenido es {SIGNATURE_NAMES.get(firma, firma)}. "
                        "No se procesará para no dañarlo: guárdelo de nuevo con el formato correcto desde su procesador de textos.")
    if not spec.soportado:
        return FileInfo(ruta, ext, spec.nombre, firma, size, False,
                        f"{spec.nombre} todavía no tiene un procesador implementado. {spec.alternativa}")
    return FileInfo(ruta, ext, spec.nombre, firma, size, True,
                    "Compatible. Se trabajará sobre una copia: el original no se modificará.")


_BACKUP_NAME = re.compile(r"^\d{8}-\d{6}-\d{6}_.+")  # solo las copias que crea Estandria


def list_backups(folder: Path) -> list[Path]:
    """Copias creadas por Estandria en la carpeta, de la más reciente a la más antigua."""
    if not folder.is_dir():
        return []
    # El nombre empieza con la fecha y hora, así que el orden alfabético es el cronológico.
    return sorted((p for p in folder.iterdir() if p.is_file() and _BACKUP_NAME.match(p.name)),
                  key=lambda p: p.name, reverse=True)


def prune_backups(folder: Path, keep: int, protect: tuple[Path, ...] = ()) -> int:
    """Elimina las copias más antiguas y conserva las «keep» más recientes; nunca toca otros archivos."""
    if keep <= 0:
        return 0
    protected = {p.resolve() for p in protect if p}
    removed = 0
    for backup in list_backups(folder)[keep:]:
        if backup.resolve() in protected:
            continue
        try:
            backup.unlink()
            removed += 1
        except OSError:  # abierta por otro programa: se intentará la próxima vez
            pass
    return removed


def create_working_copy(info: FileInfo, folder: Path | None = None, keep: int = 0) -> Path:
    """Copia el original a la carpeta de respaldos y comprueba que la copia se puede abrir."""
    if not info.soportado:
        raise LoadError(info.mensaje)
    folder = Path(folder) if folder else backups_dir()
    if not folder.is_dir():
        raise LoadError(f"La carpeta de copias de seguridad «{folder}» no existe. Revísela en Configuración.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    copy = folder / f"{stamp}_{info.nombre}"
    try:
        shutil.copy2(info.ruta, copy)
    except OSError as exc:
        raise LoadError(f"No se pudo crear la copia de trabajo: {exc}") from exc
    try:
        open_docx(copy)
    except DocxError as exc:
        copy.unlink(missing_ok=True)
        raise LoadError(str(exc)) from exc
    prune_backups(folder, keep, protect=(copy,))
    return copy
