"""Etapa 3 — Corrección: aplica solo las reglas activas a los elementos que no las cumplen.

Trabaja sobre la copia, verifica cada cambio en memoria y, al exportar, vuelve a abrir
el archivo generado para comprobar su integridad y su cumplimiento real.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.document_analyzer import analyze_document
from app.core.document_exporter import ExportError, save_verified
from app.core.document_validator import ValidationReport, targets_for, validate
from app.core.exceptions import ExceptionSet
from app.core.rule_engine import RuleSelection
from app.formats.docx_handler import FormatResolver, integrity_snapshot, open_docx
from app.formats.docx_operations import OPERATIONS, SECCION, OpContext

log = logging.getLogger(__name__)

INTEGRITY_LABELS = {
    "caracteres": "Caracteres de texto",
    "texto": "Huella del texto (SHA-256)",
    "parrafos": "Párrafos",
    "tablas": "Tablas",
    "imagenes": "Imágenes",
    "hipervinculos": "Hipervínculos",
    "secciones": "Secciones",
    "notas_al_pie": "Notas al pie",
}


@dataclass
class ChangeRecord:
    regla: str
    elemento: str
    antes: str
    despues: str
    indice: int | None = None  # índice del elemento del cuerpo (None si es una sección)


@dataclass
class IntegrityCheck:
    nombre: str
    antes: Any
    despues: Any

    @property
    def ok(self) -> bool:
        return self.antes == self.despues


@dataclass
class ProcessResult:
    destino: Path | None = None  # None cuando solo se aplicó en memoria (vista previa)
    cambios: list[ChangeRecord] = field(default_factory=list)
    ya_cumplian: int = 0
    omitidos: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    revisiones: list[str] = field(default_factory=list)  # hallazgos de reglas de solo verificación
    integridad: list[IntegrityCheck] = field(default_factory=list)
    cumplimiento: ValidationReport | None = None


def apply_selection(doc, selection: RuleSelection, exceptions: ExceptionSet | None = None) -> ProcessResult:
    """Aplica las reglas activas al documento en memoria. No guarda nada en disco."""
    result = ProcessResult()
    structure = analyze_document(doc)
    ctx = OpContext(doc, FormatResolver(doc), structure)
    for rule in selection.standard.reglas:
        if not selection.is_active(rule.id):
            result.omitidos.append(f"«{rule.nombre}»: desactivada por el usuario.")
            continue
        targets, excluded = targets_for(rule, structure, doc, exceptions)
        if excluded:
            result.omitidos.append(f"«{rule.nombre}»: {excluded} elemento(s) excluido(s) por excepciones.")
        if not targets:
            if not excluded:
                result.omitidos.append(f"«{rule.nombre}»: el documento no tiene elementos de este tipo.")
            continue
        params = selection.params(rule.id)
        operation = OPERATIONS[rule.tipo]
        element_level = operation.nivel != SECCION
        for target in targets:
            try:
                before = operation.check(target, params, ctx)
                if before.cumple is True:
                    result.ya_cumplian += 1
                    continue
                if operation.verificacion:  # nunca modifica: se informa para revisión manual
                    if before.cumple is False:
                        result.revisiones.append(f"«{rule.nombre}» en {target.label}: {before.actual}")
                    continue
                notes = operation.apply(target, params, ctx) or []
                after = operation.check(target, params, ctx)
            except Exception as exc:
                log.exception("Error al aplicar %s en %s", rule.id, target.label)
                result.errores.append(f"«{rule.nombre}» en {target.label}: {exc}")
                continue
            result.advertencias.extend(f"«{rule.nombre}» en {target.label}: {note}" for note in notes)
            if after.cumple is True:
                result.cambios.append(ChangeRecord(rule.nombre, target.label, before.actual, after.actual,
                                                   target.index if element_level else None))
            elif after.cumple is None:
                if not notes:
                    result.advertencias.append(f"«{rule.nombre}» en {target.label}: no se pudo verificar el resultado ({after.actual}).")
            else:
                result.errores.append(f"«{rule.nombre}» en {target.label}: sigue sin cumplirse tras aplicarla ({after.actual}).")
    return result


def process_document(source, original, destination, selection: RuleSelection,
                     exceptions: ExceptionSet | None = None) -> ProcessResult:
    """Aplica la selección a una copia de «source» y la exporta verificada a «destination»."""
    doc = open_docx(source)
    before = integrity_snapshot(doc)
    result = apply_selection(doc, selection, exceptions)

    def verify(temporary: Path) -> None:
        exported = open_docx(temporary)
        after = integrity_snapshot(exported)
        checks = [IntegrityCheck(INTEGRITY_LABELS[key], before[key], after[key]) for key in before]
        failed = [c for c in checks if not c.ok]
        if failed:
            details = "; ".join(f"{c.nombre}: {c.antes} → {c.despues}" for c in failed)
            raise ExportError(f"La verificación de integridad detectó diferencias ({details}). No se guardó el archivo.")
        result.integridad = checks
        # El cumplimiento se mide sobre el archivo realmente guardado, no sobre la memoria.
        result.cumplimiento = validate(exported, analyze_document(exported), selection, exceptions)

    result.destino = save_verified(doc, destination, [original, source], verify)
    return result
