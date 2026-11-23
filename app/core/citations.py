"""Detección de citas en el texto y cruce con la lista de referencias (estilo autor-fecha).

Solo lee texto: nunca lo modifica. Es una detección aproximada, por eso sus resultados
se presentan como «para revisar» y no como errores.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_YEAR = r"(?:1[5-9]\d{2}|20\d{2})[a-z]?|s\.\s?f\.|n\.\s?d\."
_YEAR_RE = re.compile(rf"(?<!\d)({_YEAR})(?![\d])", re.IGNORECASE)
_PAREN = re.compile(r"\(([^()]*)\)")
_UPPER = "A-ZÁÉÍÓÚÑÜ"
# Autor de una cita narrativa: la palabra con mayúscula justo antes de «(2019)».
_NARRATIVE = re.compile(rf"([{_UPPER}][\w'’\-]*)(?:\s(?:y|&)\s[{_UPPER}][\w'’\-]*)?(?:\set al\.)?(?:\s\[[^\]]+\])?\s*$")
_PREFIX = re.compile(r"^(?:v[ée]ase(?:\s+tambi[ée]n)?|ver|cf\.|p\.\s?ej\.,?|e\.\s?g\.,?)\s+", re.IGNORECASE)
_ABBREVIATION = re.compile(r"\[([^\]]+)\]")
_REFERENCE_YEAR = re.compile(rf"\(\s*({_YEAR})", re.IGNORECASE)


@dataclass(frozen=True)
class Citation:
    texto: str  # cómo aparece en el documento
    autor: str  # primer autor normalizado
    anio: str  # año normalizado
    abreviatura: str | None = None  # p. ej. «OMS» en «(Organización Mundial de la Salud [OMS], 2020)»


def normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in plain if not unicodedata.combining(c)).casefold()
    plain = re.sub(r"[^\w\s]", " ", plain)
    return " ".join(plain.split())


def _normalize_year(year: str) -> str:
    value = re.sub(r"[\s.]", "", year.casefold())
    return "sf" if value in ("sf", "nd") else value


def _first_author(authors: str) -> str:
    return re.split(r",|\s(?:y|&)\s|\set al\.", authors)[0].strip()


def extract_citations(text: str) -> list[Citation]:
    found = []
    for match in _PAREN.finditer(text):
        inner = match.group(1)
        if "comunicación personal" in inner.casefold() or "personal communication" in inner.casefold():
            continue  # APA no las incluye en la lista de referencias
        for part in inner.split(";"):
            year = _YEAR_RE.search(part)
            if not year:
                continue
            authors = _PREFIX.sub("", part[:year.start()].strip(" ,"))
            if authors:
                snippet = f"({part.strip()})"  # solo esta obra, aunque el paréntesis cite varias
            else:  # cita narrativa: el autor está antes del paréntesis
                narrative = _NARRATIVE.search(text[:match.start()])
                if not narrative or len(inner.split(";")) > 1:
                    continue
                authors = narrative.group(0).strip()
                snippet = f"{narrative.group(0).strip()} ({inner.strip()})"
            abbreviation = _ABBREVIATION.search(authors)
            first = normalize(_first_author(_ABBREVIATION.sub("", authors)))
            if first:
                found.append(Citation(snippet, first, _normalize_year(year.group(1)),
                                      normalize(abbreviation.group(1)) if abbreviation else None))
    return found


def reference_key(text: str) -> tuple[str, str] | None:
    """(primer autor, año) de una entrada de la lista de referencias; None si no se reconocen."""
    year = _REFERENCE_YEAR.search(text)
    if not year:
        return None
    first = normalize(text[:year.start()].strip(" .,").split(",")[0])
    return (first, _normalize_year(year.group(1))) if first else None


def has_reference_year(text: str) -> bool:
    return _REFERENCE_YEAR.search(text) is not None


def matches(citation: Citation, key: tuple[str, str], abbreviations: dict[str, str]) -> bool:
    author = abbreviations.get(citation.autor, citation.autor)
    surname, year = key
    if citation.anio != year:
        return False
    return surname == author or surname.startswith(author + " ") or surname.endswith(" " + author)


def abbreviation_map(citations: list[Citation]) -> dict[str, str]:
    return {c.abreviatura: c.autor for c in citations if c.abreviatura}


def sort_key(text: str) -> str:
    return normalize(text)
