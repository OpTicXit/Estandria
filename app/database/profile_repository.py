"""Perfiles: configuraciones de reglas guardadas con nombre (p. ej. «APA 7 Profesor»)."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from app.database.database import Database, now

MAX_NAME = 80


class ProfileError(Exception):
    """Operación de perfil no válida; el mensaje es apto para el usuario."""


@dataclass(frozen=True)
class Profile:
    id: int
    nombre: str
    normativa: str
    descripcion: str
    datos: dict  # RuleSelection.to_dict()
    creado: str
    modificado: str


def _row(row: sqlite3.Row) -> Profile:
    return Profile(row["id"], row["nombre"], row["normativa"], row["descripcion"], json.loads(row["datos"]),
                   row["creado"], row["modificado"])


def _clean_name(nombre: str) -> str:
    nombre = " ".join(str(nombre).split())
    if not nombre:
        raise ProfileError("El nombre del perfil no puede quedar vacío.")
    if len(nombre) > MAX_NAME:
        raise ProfileError(f"El nombre del perfil admite como máximo {MAX_NAME} caracteres.")
    return nombre


class ProfileRepository:
    def __init__(self, db: Database):
        self.conn = db.conn

    def list(self, normativa: str | None = None) -> list[Profile]:
        if normativa:
            rows = self.conn.execute("SELECT * FROM perfiles WHERE normativa = ? ORDER BY nombre COLLATE NOCASE", (normativa,))
        else:
            rows = self.conn.execute("SELECT * FROM perfiles ORDER BY nombre COLLATE NOCASE")
        return [_row(r) for r in rows]

    def get(self, profile_id: int) -> Profile | None:
        row = self.conn.execute("SELECT * FROM perfiles WHERE id = ?", (profile_id,)).fetchone()
        return _row(row) if row else None

    def exists(self, nombre: str, exclude_id: int | None = None) -> bool:
        row = self.conn.execute("SELECT id FROM perfiles WHERE nombre = ? COLLATE NOCASE AND id IS NOT ?",
                                (" ".join(nombre.split()), exclude_id)).fetchone()
        return row is not None

    def create(self, nombre: str, normativa: str, datos: dict, descripcion: str = "") -> Profile:
        nombre = _clean_name(nombre)
        if self.exists(nombre):
            raise ProfileError(f"Ya existe un perfil llamado «{nombre}».")
        stamp = now()
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO perfiles (nombre, normativa, descripcion, datos, creado, modificado) VALUES (?, ?, ?, ?, ?, ?)",
                (nombre, normativa, descripcion.strip(), json.dumps(datos, ensure_ascii=False), stamp, stamp))
        return self.get(cursor.lastrowid)

    def update(self, profile_id: int, *, nombre: str | None = None, descripcion: str | None = None,
               datos: dict | None = None) -> Profile:
        current = self.get(profile_id)
        if current is None:
            raise ProfileError("El perfil ya no existe.")
        nombre = _clean_name(nombre) if nombre is not None else current.nombre
        if self.exists(nombre, exclude_id=profile_id):
            raise ProfileError(f"Ya existe un perfil llamado «{nombre}».")
        with self.conn:
            self.conn.execute(
                "UPDATE perfiles SET nombre = ?, descripcion = ?, datos = ?, modificado = ? WHERE id = ?",
                (nombre, (descripcion if descripcion is not None else current.descripcion).strip(),
                 json.dumps(datos if datos is not None else current.datos, ensure_ascii=False), now(), profile_id))
        return self.get(profile_id)

    def duplicate(self, profile_id: int) -> Profile:
        source = self.get(profile_id)
        if source is None:
            raise ProfileError("El perfil ya no existe.")
        base = f"Copia de {source.nombre}"[:MAX_NAME - 4]
        nombre, counter = base, 2
        while self.exists(nombre):
            nombre, counter = f"{base} ({counter})", counter + 1
        return self.create(nombre, source.normativa, source.datos, source.descripcion)

    def delete(self, profile_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM perfiles WHERE id = ?", (profile_id,))
