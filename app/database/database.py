"""Conexión SQLite con migraciones versionadas y recuperación ante archivos dañados."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Cada migración lleva la base de la versión i a la i+1. Solo se agregan al final: nunca se editan.
MIGRATIONS = [
    """
    CREATE TABLE perfiles (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre      TEXT NOT NULL UNIQUE COLLATE NOCASE,
        normativa   TEXT NOT NULL,
        descripcion TEXT NOT NULL DEFAULT '',
        datos       TEXT NOT NULL,
        creado      TEXT NOT NULL,
        modificado  TEXT NOT NULL
    );
    CREATE TABLE preferencias (
        clave TEXT PRIMARY KEY,
        valor TEXT NOT NULL
    );
    """,
]


class DatabaseError(Exception):
    """Problema de almacenamiento; el mensaje es apto para el usuario."""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        self.path = path
        self.recovered_from: Path | None = None  # archivo dañado que se apartó, si lo hubo
        try:
            self.conn = self._open()
        except sqlite3.DatabaseError as exc:
            if str(path) == ":memory:":
                raise DatabaseError(f"No se pudo crear la base de datos en memoria: {exc}") from exc
            # Archivo dañado: se aparta (no se borra) y se crea uno nuevo para que la aplicación siga funcionando.
            damaged = Path(path).with_name(f"{Path(path).stem}.danada-{datetime.now():%Y%m%d-%H%M%S}{Path(path).suffix}")
            log.error("Base de datos dañada (%s); se mueve a %s", exc, damaged)
            Path(path).replace(damaged)
            self.recovered_from = damaged
            self.conn = self._open()

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA integrity_check").fetchone()  # falla si el archivo no es una base válida
            self._migrate(conn)
        except Exception:
            conn.close()  # en Windows, una conexión abierta impediría apartar el archivo dañado
            raise
        return conn

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > len(MIGRATIONS):
            raise DatabaseError("La base de datos pertenece a una versión más reciente de Estandria.")
        for index in range(version, len(MIGRATIONS)):
            with conn:
                conn.executescript(MIGRATIONS[index])
                conn.execute(f"PRAGMA user_version = {index + 1}")

    @property
    def version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
