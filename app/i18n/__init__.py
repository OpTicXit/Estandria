"""Catálogos de textos por idioma. Las cadenas se piden por clave: t("estilo.titulo")."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

IDIOMAS = ("es-419", "es-ES", "en")
_DEFAULT = "es-419"
_current = _DEFAULT


@lru_cache(maxsize=None)
def _catalog(language: str) -> dict:
    from app.paths import resource_dir  # importación tardía: evita ciclos al arrancar
    path = resource_dir() / "app" / "i18n" / f"{language}.json"
    if not path.is_file():
        path = Path(__file__).with_name(f"{language}.json")
    return json.loads(path.read_text(encoding="utf-8"))


def language_name(language: str) -> str:
    return _catalog(language).get("idioma.nombre", language)


def set_language(language: str) -> None:
    global _current
    _current = language if language in IDIOMAS else _DEFAULT


def current_language() -> str:
    return _current


def t(key: str, **values) -> str:
    """Texto del catálogo activo; si falta la clave, se usa el español y, en último caso, la clave misma."""
    text = _catalog(_current).get(key) or _catalog(_DEFAULT).get(key) or key
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError):
        return text
