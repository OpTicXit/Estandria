"""Vistas compartidas por Análisis y Resultados."""
from __future__ import annotations

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QHeaderView, QTreeWidget, QTreeWidgetItem

from app.core.document_validator import ESTADOS, ValidationReport

STATE_COLORS = {
    "cumple": "#4ED37E",
    "requiere_cambios": "#E9B949",
    "indeterminado": "#A8B3C2",
    "sin_elementos": "#5E6B7C",
    "revisar": "#C3A8FF",
}
MAX_CHILDREN = 300  # límite visual por regla; el informe completo sigue en memoria


def make_tree(headers: list[str], min_height: int = 320) -> QTreeWidget:
    tree = QTreeWidget()
    tree.setHeaderLabels(headers)
    tree.setAlternatingRowColors(True)
    tree.setUniformRowHeights(False)
    tree.setMinimumHeight(min_height)
    tree.setWordWrap(True)
    header = tree.header()
    header.setStretchLastSection(True)
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
    tree.setColumnWidth(0, 360)
    tree.setColumnWidth(1, 150)
    for column in range(2, len(headers) - 1):
        tree.setColumnWidth(column, 330)
    return tree


def fill_compliance_tree(tree: QTreeWidget, report: ValidationReport, only_problems: bool = True) -> None:
    """Una fila por regla; debajo, los elementos que no cumplen o no se pudieron determinar."""
    tree.clear()
    for rule_report in report.reglas:
        state = rule_report.estado
        total = len(rule_report.findings)
        if state == "sin_elementos":
            summary = "Todos sus elementos están excluidos" if rule_report.excluidos else "No hay elementos de este tipo"
        else:
            summary = f"{rule_report.cumplen} de {total} cumplen"
            if rule_report.requieren:
                summary += f" · {rule_report.requieren} " + ("para revisar" if rule_report.verificacion else "requieren cambios")
            if rule_report.indeterminados:
                summary += f" · {rule_report.indeterminados} sin determinar"
            if rule_report.excluidos:
                summary += f" · {rule_report.excluidos} excluidos"
        parent = QTreeWidgetItem([rule_report.rule.nombre, ESTADOS[state], summary, ""])
        parent.setForeground(1, QBrush(QColor(STATE_COLORS[state])))
        parent.setToolTip(0, rule_report.rule.descripcion)
        shown = [f for f in rule_report.findings if not (only_problems and f.cumple is True)]
        failed = ("Para revisar", "revisar") if rule_report.verificacion else ("Requiere cambio", "requiere_cambios")
        for finding in shown[:MAX_CHILDREN]:
            status = "Cumple" if finding.cumple is True else failed[0] if finding.cumple is False else "Sin determinar"
            child = QTreeWidgetItem([finding.elemento, status, finding.actual, finding.esperado])
            color = "cumple" if finding.cumple is True else failed[1] if finding.cumple is False else "indeterminado"
            child.setForeground(1, QBrush(QColor(STATE_COLORS[color])))
            for column in range(4):
                child.setToolTip(column, child.text(column))
            parent.addChild(child)
        if len(shown) > MAX_CHILDREN:
            parent.addChild(QTreeWidgetItem([f"… y {len(shown) - MAX_CHILDREN} elementos más", "", "", ""]))
        tree.addTopLevelItem(parent)
