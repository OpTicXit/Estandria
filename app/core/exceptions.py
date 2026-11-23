"""Excepciones del usuario: elementos que no se deben modificar, con todas las reglas o solo con algunas.

Tienen prioridad sobre las reglas. Se aplican a reglas de párrafo; las de página (márgenes, papel,
número de página) actúan por sección y no admiten excepciones por elemento.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.core.document_analyzer import DocumentStructure, Element, kind_label
from app.core.rule_engine import RuleSelection

TIPOS = {
    "elemento": "Elementos concretos",
    "tipo": "Todos los elementos de un tipo",
    "seccion": "Sección completa bajo un encabezado",
    "pagina": "Página",
}


@dataclass(frozen=True)
class DocException:
    tipo: str  # clave de TIPOS
    valor: Any  # índices de elementos, tipo de elemento, índice del encabezado o número de página
    reglas: tuple[str, ...] = ()  # vacío = todas las reglas
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def applies_to(self, rule_id: str) -> bool:
        return not self.reglas or rule_id in self.reglas


def section_under(structure: DocumentStructure, heading_index: int) -> list[Element]:
    """El encabezado y todo lo que sigue hasta otro encabezado de su nivel o superior."""
    elements = structure.elements
    start = next((i for i, e in enumerate(elements) if e.index == heading_index), None)
    if start is None:
        return []
    level = elements[start].level or 1
    end = start + 1
    while end < len(elements):
        current = elements[end]
        if current.is_heading and (current.level or 1) <= level:
            break
        end += 1
    return elements[start:end]


class ExceptionSet:
    def __init__(self):
        self.items: list[DocException] = []

    def add(self, exception: DocException) -> None:
        self.items.append(exception)

    def remove(self, exception_id: str) -> None:
        self.items = [e for e in self.items if e.id != exception_id]

    def clear(self) -> None:
        self.items = []

    def elements_of(self, exception: DocException, structure: DocumentStructure) -> list[Element]:
        if exception.tipo == "elemento":
            wanted = set(exception.valor)
            return [e for e in structure.elements if e.index in wanted]
        if exception.tipo == "tipo":
            return [e for e in structure.elements if e.kind == exception.valor]
        if exception.tipo == "seccion":
            return section_under(structure, exception.valor)
        if exception.tipo == "pagina":
            return [e for e in structure.elements if e.paginas[0] <= exception.valor <= e.paginas[1]]
        raise ValueError(f"Tipo de excepción desconocido: {exception.tipo}")

    def excluded(self, structure: DocumentStructure, rule_id: str) -> set[int]:
        """Índices de los elementos que la regla no debe tocar."""
        return {e.index for exc in self.items if exc.applies_to(rule_id) for e in self.elements_of(exc, structure)}

    def describe(self, exception: DocException, structure: DocumentStructure) -> str:
        if exception.tipo == "elemento":
            affected = self.elements_of(exception, structure)
            what = affected[0].label if len(affected) == 1 else f"{len(affected)} elementos (" + ", ".join(
                f"#{e.index}" for e in affected[:6]) + ("…" if len(affected) > 6 else "") + ")"
        elif exception.tipo == "tipo":
            what = f"Todos los elementos de tipo «{kind_label(exception.valor)}»"
        elif exception.tipo == "seccion":
            heading = next((e for e in structure.elements if e.index == exception.valor), None)
            what = f"Sección bajo {heading.label if heading else f'#{exception.valor}'}"
        else:
            what = f"Página {exception.valor}"
        return what

    def rules_text(self, exception: DocException, selection: RuleSelection) -> str:
        if not exception.reglas:
            return "todas las reglas"
        known = {r.id: r.nombre for r in selection.standard.reglas}
        return ", ".join(f"«{known[r]}»" for r in exception.reglas if r in known) or "reglas de otra normativa"

    def warnings(self, structure: DocumentStructure, selection: RuleSelection) -> list[tuple[str, str]]:
        """Avisos: excepciones que impiden reglas obligatorias, que no afectan a nada o con reglas ajenas."""
        result = []
        known = {r.id for r in selection.standard.reglas}
        for exception in self.items:
            label = self.describe(exception, structure)
            affected = self.elements_of(exception, structure)
            if not affected:
                result.append(("info", f"La excepción «{label}» no afecta a ningún elemento del documento."))
                continue
            if exception.reglas and not set(exception.reglas) & known:
                result.append(("info", f"La excepción «{label}» se refiere a reglas de otra normativa y no tiene efecto."))
                continue
            kinds = {e.kind for e in affected}
            blocked = [r for r in selection.active_rules()
                       if r.clasificacion == "obligatoria" and exception.applies_to(r.id) and kinds & set(r.alcance)]
            if blocked:
                names = ", ".join(f"«{r.nombre}»" for r in blocked[:4]) + ("…" if len(blocked) > 4 else "")
                result.append(("advertencia", f"La excepción «{label}» impide aplicar {len(blocked)} regla(s) obligatoria(s) "
                                              f"en {len(affected)} elemento(s): {names}."))
        return result
