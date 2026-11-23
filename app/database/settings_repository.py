"""Preferencias de la aplicación, guardadas como JSON en la tabla «preferencias»."""
from __future__ import annotations

import json

from app.database.database import Database

DEFAULTS = {
    "carpeta_exportacion": "",  # vacío = la carpeta del documento original
    "carpeta_respaldos": "",  # vacío = %LOCALAPPDATA%\Estandria\respaldos
    "conservar_respaldos": 0,  # 0 = conservar todas las copias
    "sufijo_exportacion": "_{normativa}",
    "abrir_al_exportar": False,
    "perfil_inicial": None,  # id del perfil que se carga al iniciar
    "escala_interfaz": 100,
    "animaciones": True,
    "idioma": "es-419",  # idioma de los textos con catálogo (por ahora, la limpieza de estilo)
    "recientes": [],
}


class SettingsRepository:
    def __init__(self, db: Database):
        self.conn = db.conn

    def get(self, key: str):
        if key not in DEFAULTS:
            raise KeyError(key)
        row = self.conn.execute("SELECT valor FROM preferencias WHERE clave = ?", (key,)).fetchone()
        if row is None:
            return DEFAULTS[key]
        try:
            value = json.loads(row["valor"])
        except json.JSONDecodeError:
            return DEFAULTS[key]
        # Un valor de tipo inesperado (archivo editado a mano, versión anterior) vuelve al predeterminado.
        default = DEFAULTS[key]
        if default is not None and not isinstance(value, type(default)):
            return default
        return value

    def set(self, key: str, value) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        with self.conn:
            self.conn.execute("INSERT INTO preferencias (clave, valor) VALUES (?, ?) "
                              "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                              (key, json.dumps(value, ensure_ascii=False)))
