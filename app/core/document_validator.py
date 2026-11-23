"""Etapa 2 — Validación: compara cada elemento con las reglas activas, sin modificar nada."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.document_analyzer import DocumentStructure
from app.core.exceptions import ExceptionSet
from app.core.rule_engine import Rule, RuleSelection
from app.formats.docx_handler import FormatResolver
from app.formats.docx_operations import OPERATIONS, SECCION, CheckResult, OpContext, Target

log = logging.getLogger(__name__)

ESTADOS = {
    "cumple": "Cumple",
    "requiere_cambios": "Requiere cambios",
    "indeterminado": "Sin determinar",
    "sin_elementos": "Sin elementos",
    "revisar": "Para revisar",
}


@dataclass
class Finding:
    elemento: str
    cumple: bool | None
    actual: str
    esperado: str


@dataclass
class RuleReport:
    rule: Rule
    findings: list[Finding] = field(default_factory=list)
    verificacion: bool = False  # la regla solo comprueba: sus incumplimientos se revisan a mano
    excluidos: int = 0  # elementos de su alcance que el usuario excluyó con excepciones

    @property
    def cumplen(self) -> int:
        return sum(f.cumple is True for f in self.findings)

    @property
    def requieren(self) -> int:
        return sum(f.cumple is False for f in self.findings)

    @property
    def indeterminados(self) -> int:
        return sum(f.cumple is None for f in self.findings)

    @property
    def estado(self) -> str:
        if not self.findings:
            return "sin_elementos"
        if self.requieren:
            return "revisar" if self.verificacion else "requiere_cambios"
        if self.indeterminados:
            return "indeterminado"
        return "cumple"


@dataclass
class ValidationReport:
    reglas: list[RuleReport]
    inactivas: list[Rule]

    def count(self, estado: str) -> int:
        return sum(r.estado == estado for r in self.reglas)

    @property
    def elementos_a_modificar(self) -> int:
        return sum(r.requieren + r.indeterminados for r in self.reglas if not r.verificacion)

    @property
    def elementos_a_revisar(self) -> int:
        return sum(r.requieren for r in self.reglas if r.verificacion)


def targets_for(rule: Rule, structure: DocumentStructure, doc,
                exceptions: ExceptionSet | None = None) -> tuple[list[Target], int]:
    """Elementos a los que se aplica la regla y cuántos quedaron fuera por excepciones."""
    if OPERATIONS[rule.tipo].nivel == SECCION:  # las excepciones no actúan sobre secciones
        return [Target(f"Sección {i + 1}", section, i) for i, section in enumerate(doc.sections)], 0
    excluded = exceptions.excluded(structure, rule.id) if exceptions else set()
    in_scope = structure.of_kinds(rule.alcance)
    targets = [Target(e.label, e.obj, e.index) for e in in_scope if e.index not in excluded]
    return targets, len(in_scope) - len(targets)


def validate(doc, structure: DocumentStructure, selection: RuleSelection,
             exceptions: ExceptionSet | None = None) -> ValidationReport:
    ctx = OpContext(doc, FormatResolver(doc), structure)
    reports = []
    for rule in selection.active_rules():
        operation = OPERATIONS[rule.tipo]
        targets, excluded = targets_for(rule, structure, doc, exceptions)
        report = RuleReport(rule, verificacion=operation.verificacion, excluidos=excluded)
        params = selection.params(rule.id)
        for target in targets:
            try:
                result = operation.check(target, params, ctx)
            except Exception as exc:  # un elemento extraño no debe impedir analizar el resto
                log.exception("Error al comprobar %s en %s", rule.id, target.label)
                result = CheckResult(None, f"error al analizar: {exc}", "")
            report.findings.append(Finding(target.label, result.cumple, result.actual, result.esperado))
        reports.append(report)
    inactive = [r for r in selection.standard.reglas if not selection.is_active(r.id)]
    return ValidationReport(reports, inactive)
