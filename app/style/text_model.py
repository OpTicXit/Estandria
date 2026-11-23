"""Texto de revisión con posiciones fieles al documento original.

El texto une los bloques del cuerpo en orden, separados por «\\n». Cada párrafo aporta exactamente la
concatenación de sus nodos <w:t>; tablas, imágenes y otros bloques aportan una cadena vacía. Así cada
posición del texto corresponde a un carácter concreto de un nodo <w:t>, y aceptar un hallazgo modifica
justo esos caracteres.
"""
from __future__ import annotations

from dataclasses import dataclass

from docx.text.paragraph import Paragraph

from app.formats.docx_handler import text_nodes

# Solo prosa del autor. No se analizan citas en bloque, referencias, encabezados, tablas ni pies de figura.
ANALYZED_KINDS = frozenset({"parrafo", "lista", "resumen"})
_QUOTES = {"“": "”", "«": "»", '"': '"'}
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def paragraph_text(paragraph: Paragraph) -> str:
    return "".join(node.text or "" for node in text_nodes(paragraph))


@dataclass(frozen=True)
class Tramo:
    elemento: int
    ini: int
    fin: int
    analizable: bool


class ReviewText:
    def __init__(self, structure):
        parts, self.tramos, self._paragraphs = [], [], {}
        position = 0
        for element in structure.elements:
            text = paragraph_text(element.obj) if isinstance(element.obj, Paragraph) else ""
            if isinstance(element.obj, Paragraph):
                self._paragraphs[element.index] = element.obj
            self.tramos.append(Tramo(element.index, position, position + len(text), element.kind in ANALYZED_KINDS))
            parts.append(text)
            position += len(text) + 1
        self.text = "\n".join(parts)
        self.quotes = [span for tramo in self.analyzable() for span in self._quoted_spans(tramo)]

    def analyzable(self) -> list[Tramo]:
        return [t for t in self.tramos if t.analizable and t.fin > t.ini]

    def tramo_at(self, offset: int) -> Tramo:
        return next(t for t in self.tramos if t.ini <= offset <= t.fin)

    def _quoted_spans(self, tramo: Tramo) -> list[tuple[int, int]]:
        """Citas textuales entre comillas (incluidas las comillas). Una comilla sin cierre no excluye nada."""
        spans, i = [], tramo.ini
        while i < tramo.fin:
            closing = _QUOTES.get(self.text[i])
            if closing:
                end = self.text.find(closing, i + 1, tramo.fin)
                if end != -1:
                    spans.append((i, end + 1))
                    i = end + 1
                    continue
            i += 1
        return spans

    def in_quote(self, ini: int, fin: int) -> bool:
        return any(ini < q_fin and fin > q_ini for q_ini, q_fin in self.quotes)

    def paragraph(self, element: int) -> Paragraph:
        return self._paragraphs[element]


def replace_in_paragraph(paragraph: Paragraph, ini: int, fin: int, new: str) -> None:
    """Sustituye los caracteres [ini, fin) del párrafo, repartidos en uno o varios nodos <w:t>.

    El texto nuevo va en el primer nodo afectado (conserva su formato); los demás solo pierden lo
    reemplazado. Lanza ValueError si el resultado no es exactamente el esperado.
    """
    nodes = text_nodes(paragraph)
    before = "".join(node.text or "" for node in nodes)
    expected = before[:ini] + new + before[fin:]
    position, inserted = 0, False
    for node in nodes:
        text = node.text or ""
        start, end = position, position + len(text)
        position = end
        if end <= ini or start >= fin:
            continue
        a, b = max(ini, start) - start, min(fin, end) - start
        node.text = text[:a] + (new if not inserted else "") + text[b:]
        node.set(_XML_SPACE, "preserve")
        inserted = True
    if paragraph_text(paragraph) != expected:
        raise ValueError("El cambio no produjo el texto esperado; no se aplicó.")


def apply_findings(review: ReviewText, findings: list) -> list:
    """Aplica las propuestas aceptadas, de atrás hacia adelante para que las posiciones sigan valiendo.

    Omite las que no tienen propuesta, las que se solapan con otra ya aplicada y las que no coinciden
    con el texto actual. Devuelve las que se aplicaron.
    """
    applied, taken = [], []
    for finding in sorted(findings, key=lambda f: f.ini, reverse=True):
        if finding.propuesta is None or not finding.aceptable:
            continue
        if any(finding.ini < t_fin and finding.fin > t_ini for t_ini, t_fin in taken):
            continue
        if review.text[finding.ini:finding.fin] != finding.excerpt:
            continue
        tramo = review.tramo_at(finding.ini)
        if finding.fin > tramo.fin:
            continue
        replace_in_paragraph(review.paragraph(tramo.elemento), finding.ini - tramo.ini, finding.fin - tramo.ini,
                             finding.propuesta)
        taken.append((finding.ini, finding.fin))
        applied.append(finding)
    return applied
