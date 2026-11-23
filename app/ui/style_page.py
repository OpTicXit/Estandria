"""Limpieza de estilo: hallazgos agrupados por regla, con detalle, diferencias y aceptación individual.

Sin puntuación global ni barras de progreso: solo contadores por regla. La severidad se indica con
símbolo y texto (no solo color) y el cambio propuesto se marca con símbolos, legible sin color.
"""
from __future__ import annotations

import csv
import html
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QLabel, QPushButton, QScrollArea, QSplitter, QTextBrowser, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from app.i18n import t
from app.style import Hallazgo
from app.style.rules import RULE_IDS
from app.ui.widgets import Banner, hbox, label, page_header

SEVERITY_SYMBOL = {"info": "ⓘ", "aviso": "▲", "revision": "✎"}


def severity_text(finding: Hallazgo) -> str:
    return f"{SEVERITY_SYMBOL[finding.severity]} {t('severidad.' + finding.severity)}"


def explanation(finding: Hallazgo) -> str:
    values = {k: (f"{v:g}" if isinstance(v, float) else v) for k, v in finding.datos.items()}
    return t(finding.explicacion, excerpt=finding.excerpt.strip(), medido=f"{finding.medido:g}",
             umbral=f"{finding.umbral:g}", **values)


def finding_key(finding: Hallazgo) -> tuple:
    """Identidad estable de un hallazgo entre análisis (las posiciones cambian al aceptar otros)."""
    return finding.ruleId, finding.elemento, finding.excerpt


class StylePage(QWidget):
    analyzeRequested = Signal()
    acceptRequested = Signal(list)
    rejected = Signal(tuple)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.findings: list[Hallazgo] = []
        self.review_text = ""
        self.current: Hallazgo | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 20)
        layout.setSpacing(12)
        self.header_holder = QVBoxLayout()
        layout.addLayout(self.header_holder)
        self.banner = Banner()
        layout.addWidget(self.banner)
        self.excluded_note = label("", "muted", wrap=True)
        layout.addWidget(self.excluded_note)
        self.analyze_button = QPushButton()
        self.analyze_button.setProperty("variant", "primary")
        self.analyze_button.clicked.connect(self.analyzeRequested)
        self.export_button = QPushButton()
        self.export_button.clicked.connect(self._export)
        layout.addLayout(hbox(self.analyze_button, self.export_button, stretch_end=True))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(380)
        self.tree.currentItemChanged.connect(lambda item, _: self._select(item))
        splitter.addWidget(self.tree)

        detail = QWidget()
        detail.setObjectName("scrollContent")
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(18, 4, 4, 4)
        dl.setSpacing(8)
        self.severity = label("", "sectionTitle")
        self.original_title, self.original = label("", "fieldLabel"), label("", "", wrap=True)
        self.proposal_title, self.proposal = label("", "fieldLabel"), label("", "", wrap=True)
        self.diff_title, self.diff = label("", "fieldLabel"), QLabel()
        self.diff.setWordWrap(True)
        self.diff.setTextFormat(Qt.TextFormat.RichText)
        for widget in (self.original, self.proposal, self.diff):
            widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.explain_button = QPushButton()
        self.explain_button.setCheckable(True)
        self.explain_button.setProperty("variant", "ghost")
        self.explanation = label("", "muted", wrap=True)
        self.explanation.hide()
        self.explain_button.toggled.connect(self.explanation.setVisible)
        self.context_title = label("", "fieldLabel")
        self.context = QTextBrowser()
        self.context.setObjectName("paper")
        self.context.setMinimumHeight(140)
        self.accept_button = QPushButton()
        self.accept_button.setProperty("variant", "primary")
        self.accept_button.clicked.connect(lambda: self.current and self.acceptRequested.emit([self.current]))
        self.reject_button = QPushButton()
        self.reject_button.clicked.connect(self._reject)
        self.accept_rule_button = QPushButton()
        self.accept_rule_button.clicked.connect(self._accept_rule)
        self.placeholder = label("", "muted", wrap=True)
        for widget in (self.placeholder, self.severity, self.original_title, self.original, self.proposal_title,
                       self.proposal, self.diff_title, self.diff, self.explain_button, self.explanation,
                       self.context_title, self.context):
            dl.addWidget(widget)
        dl.addLayout(hbox(self.accept_button, self.reject_button, None, self.accept_rule_button))
        dl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(detail)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        self.retranslate()
        self._show_detail(None)

    # ------------------------------------------------------------------ textos
    def retranslate(self) -> None:
        while self.header_holder.count():
            item = self.header_holder.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.header_holder.addWidget(page_header(t("estilo.titulo"), t("estilo.subtitulo")))
        self.excluded_note.setText(t("estilo.excluidos"))
        self.analyze_button.setText(t("estilo.analizar"))
        self.export_button.setText(t("estilo.exportar"))
        self.original_title.setText(t("estilo.original"))
        self.proposal_title.setText(t("estilo.propuesta"))
        self.diff_title.setText(t("estilo.diff"))
        self.explain_button.setText(t("estilo.explicacion"))
        self.context_title.setText(t("estilo.contexto"))
        self.accept_button.setText(t("estilo.aceptar"))
        self.reject_button.setText(t("estilo.rechazar"))
        self.accept_rule_button.setText(t("estilo.aceptar_regla"))
        self.placeholder.setText(t("estilo.seleccione"))
        if self.findings or self.tree.topLevelItemCount():
            self._fill_tree()

    def set_document(self, loaded: bool) -> None:
        self.analyze_button.setEnabled(loaded)
        if not loaded:
            self.banner.show_message(t("estilo.sin_documento"), "info")

    # ------------------------------------------------------------------ resultados
    def show_findings(self, language: str, review_text: str, findings: list[Hallazgo], message: str = "") -> None:
        self.review_text = review_text
        self.findings = findings if language == "es" else []
        if language == "en":
            self.banner.show_message(t("estilo.desactivado_en"), "warning")
        elif language != "es":
            self.banner.show_message(t("estilo.desactivado_indeterminado"), "info")
        elif message:
            self.banner.show_message(message, "success")
        elif not findings:
            self.banner.show_message(t("estilo.ninguno"), "success")
        else:
            self.banner.hide()
        self.export_button.setEnabled(bool(self.findings))
        self._fill_tree()

    def _fill_tree(self) -> None:
        self.tree.clear()
        for rule in RULE_IDS:
            items = [f for f in self.findings if f.ruleId == rule]
            if not items:
                continue
            group = QTreeWidgetItem([f"{t(f'regla.{rule}.nombre')}  ({len(items)})"])
            group.setData(0, Qt.ItemDataRole.UserRole, rule)
            for finding in items:
                excerpt = " ".join(finding.excerpt.split())
                excerpt = excerpt[:60] + ("…" if len(excerpt) > 60 else "")
                child = QTreeWidgetItem([f"{severity_text(finding)} — «{excerpt}»"])
                child.setData(0, Qt.ItemDataRole.UserRole, self.findings.index(finding))
                child.setToolTip(0, explanation(finding))
                group.addChild(child)
            self.tree.addTopLevelItem(group)
            group.setExpanded(True)
        self._show_detail(None)

    def _select(self, item: QTreeWidgetItem | None) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        self._show_detail(self.findings[data] if isinstance(data, int) else None)

    def _show_detail(self, finding: Hallazgo | None) -> None:
        self.current = finding
        has = finding is not None
        self.placeholder.setVisible(not has)
        for widget in (self.severity, self.original_title, self.original, self.proposal_title, self.proposal,
                       self.diff_title, self.diff, self.explain_button, self.context_title, self.context,
                       self.accept_button, self.reject_button, self.accept_rule_button):
            widget.setVisible(has)
        self.explanation.setVisible(has and self.explain_button.isChecked())
        if not has:
            return
        self.severity.setText(severity_text(finding))
        self.original.setText(finding.excerpt)
        self.proposal.setText(finding.propuesta if finding.propuesta is not None else t("estilo.sin_propuesta"))
        if finding.propuesta is None:
            self.diff.setText("—")
        else:  # legible sin color: [−…−] lo que sale, {+…+} lo que entra
            removed = f"<s>[−{html.escape(finding.excerpt)}−]</s>"
            added = f"<u>{{+{html.escape(finding.propuesta)}+}}</u>" if finding.propuesta else ""
            self.diff.setText(f"{removed} {added}")
        self.explanation.setText(explanation(finding) + "\n" +
                                 t("estilo.medido_umbral", medido=f"{finding.medido:g}", umbral=f"{finding.umbral:g}"))
        tramo_start = self.review_text.rfind("\n", 0, finding.ini) + 1
        tramo_end = self.review_text.find("\n", finding.fin)
        tramo_end = len(self.review_text) if tramo_end == -1 else tramo_end
        before = html.escape(self.review_text[tramo_start:finding.ini])
        marked = html.escape(self.review_text[finding.ini:finding.fin])
        after = html.escape(self.review_text[finding.fin:tramo_end])
        self.context.setHtml(f'<p style="color:#6b7280">{html.escape(t("estilo.elemento", elemento=finding.elemento))}</p>'
                             f"<p>{before}<b>⟦{marked}⟧</b>{after}</p>")
        self.accept_button.setEnabled(finding.aceptable)
        same_rule = [f for f in self.findings if f.ruleId == finding.ruleId and f.aceptable]
        self.accept_rule_button.setEnabled(len(same_rule) > 1)

    def _reject(self) -> None:
        if self.current:
            self.rejected.emit(finding_key(self.current))

    def _accept_rule(self) -> None:
        if self.current:  # «Aceptar todo» solo dentro de una misma regla
            self.acceptRequested.emit([f for f in self.findings if f.ruleId == self.current.ruleId and f.aceptable])

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, t("estilo.exportar"), str(Path.home() / "revision_estilo.csv"),
                                              "CSV (*.csv)")
        if not path:
            return
        fields = ["ruleId", "severity", "ini", "fin", "excerpt", "medido", "umbral", "explicacion", "propuesta",
                  "aceptable", "elemento"]
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(fields + ["explicacion_texto"])
            for f in self.findings:
                writer.writerow([getattr(f, name) for name in fields] + [explanation(f)])
        self.banner.show_message(t("estilo.exportado", ruta=path), "success")
