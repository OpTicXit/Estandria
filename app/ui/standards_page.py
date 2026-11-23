"""Normativa: categorías y reglas individuales con interruptores y valores ajustables."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from app.core.document_analyzer import kind_label
from app.core.rule_engine import Parameter, Rule, RuleError, RuleSelection, Standard
from app.formats.docx_operations import OPERATIONS
from app.ui.widgets import (
    Badge, Banner, NoWheelComboBox, NoWheelSpinBox, ToggleSwitch, card, clear_layout, divider, hbox, label,
    page_header, scroll_page,
)

CLASSIFICATION_LABELS = {"obligatoria": "Obligatoria", "recomendada": "Recomendada", "contextual": "Contextual"}


def _decimals(step: float) -> int:
    return max(0, -Decimal(str(step)).normalize().as_tuple().exponent)


class RuleRow(QFrame):
    """Una regla: interruptor, nombre, clasificación, valores y detalles desplegables."""

    def __init__(self, rule: Rule, selection: RuleSelection, on_toggle, on_param, parent=None):
        super().__init__(parent)
        self.setObjectName("ruleRow")
        self.rule = rule
        self.selection = selection
        self.editors: dict[str, QWidget] = {}

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 10, 8, 10)
        row.setSpacing(14)
        self.switch = ToggleSwitch()
        self.switch.setAccessibleName(rule.nombre)
        self.switch.setChecked(selection.is_active(rule.id))
        self.switch.toggled.connect(lambda checked: on_toggle(rule.id, checked))
        row.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(6)
        details_button = QPushButton("Detalles")
        details_button.setProperty("variant", "ghost")
        details_button.setCheckable(True)
        badge = Badge(CLASSIFICATION_LABELS[rule.clasificacion], rule.clasificacion)
        verify = Badge("Solo verificación", "neutral") if OPERATIONS[rule.tipo].verificacion else None
        body.addLayout(hbox(*filter(None, [label(rule.nombre, "ruleName"), badge, verify]), None, details_button))
        summary = label(rule.descripcion, "muted", wrap=True)
        body.addWidget(summary)

        scope = ", ".join(kind_label(k) for k in rule.alcance)
        extra = [f"Se aplica a: {scope}.", f"Fuente: {rule.fuente} · Edición {rule.edicion}."]
        if rule.dependencias:
            names = ", ".join(f"«{selection.standard.rule(d).nombre}»" for d in rule.dependencias)
            extra.append(f"Depende de {names}: al activarla se activarán también.")
        if rule.conflictos:
            names = ", ".join(f"«{selection.standard.rule(c).nombre}»" for c in rule.conflictos)
            extra.append(f"Incompatible con {names}: no pueden estar activas a la vez.")
        for link in selection.standard.links_of(rule.id):
            origin, target = (selection.standard.rule(link.origen[0]), selection.standard.rule(link.destino[0]))
            extra.append(f"Vinculada: «{origin.nombre}» determina «{target.nombre}». {link.descripcion} ({link.fuente})")
        details = label("\n".join(extra), "muted", wrap=True)
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details.hide()
        details_button.toggled.connect(details.setVisible)
        body.addWidget(details)

        if rule.parametros:
            params_row = QHBoxLayout()
            params_row.setSpacing(10)
            for name, param in rule.parametros.items():
                editor = self._make_editor(param, selection.params(rule.id)[name],
                                           lambda value, n=name: on_param(rule.id, n, value))
                editor.setAccessibleName(f"{rule.nombre}: {param.etiqueta}")
                self.editors[name] = editor
                params_row.addWidget(label(param.etiqueta, "fieldLabel"))
                params_row.addWidget(editor)
                params_row.addSpacing(8)
            params_row.addStretch(1)
            body.addLayout(params_row)
        row.addLayout(body, 1)
        self.sync()

    @staticmethod
    def _make_editor(param: Parameter, value, on_change) -> QWidget:
        if param.tipo == "numero":
            editor = NoWheelSpinBox()
            editor.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            editor.setDecimals(_decimals(param.paso))
            editor.setSingleStep(param.paso)
            editor.setRange(param.minimo if param.minimo is not None else -1e6,
                            param.maximo if param.maximo is not None else 1e6)
            editor.setValue(float(value))
            if param.unidad:
                editor.setSuffix(f" {param.unidad}")
            editor.setMinimumWidth(110)
            editor.valueChanged.connect(on_change)
            return editor
        if param.tipo == "booleano":
            editor = QCheckBox()
            editor.setChecked(bool(value))
            editor.toggled.connect(on_change)
            return editor
        editor = NoWheelComboBox()
        editor.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        editor.setMinimumWidth(150)
        if param.editable:
            editor.setEditable(True)
            editor.addItems([str(o) for o in param.opciones])
            editor.setCurrentText(str(value))
            editor.activated.connect(lambda _i: on_change(editor.currentText()))
            editor.lineEdit().editingFinished.connect(lambda: on_change(editor.currentText()))
        else:
            for option in param.opciones:
                editor.addItem(str(option).capitalize(), option)
            editor.setCurrentIndex(max(0, editor.findData(value)))
            editor.currentIndexChanged.connect(lambda _i: on_change(editor.currentData()))
        return editor

    def sync(self) -> None:
        """Refleja el estado de la selección (puede haber cambiado por dependencias o vínculos)."""
        active = self.selection.is_active(self.rule.id)
        self.switch.blockSignals(True)
        self.switch.setChecked(active)
        self.switch.blockSignals(False)
        values = self.selection.params(self.rule.id)
        for name, editor in self.editors.items():
            editor.blockSignals(True)
            value = values[name]
            if isinstance(editor, NoWheelSpinBox):
                editor.setValue(float(value))
            elif isinstance(editor, QCheckBox):
                editor.setChecked(bool(value))
            elif editor.isEditable():
                editor.setCurrentText(str(value))
            else:
                editor.setCurrentIndex(max(0, editor.findData(value)))
            editor.blockSignals(False)
            editor.setEnabled(active)


class StandardsPage(QWidget):
    analyzeRequested = Signal()
    standardChanged = Signal(str)
    profileSelected = Signal(object)  # id del perfil o None
    saveProfileRequested = Signal()
    saveAsProfileRequested = Signal()
    selectionEdited = Signal()

    def __init__(self, standards: list[Standard], parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.selection: RuleSelection | None = None
        self.rows: list[RuleRow] = []
        self.category_controls: dict[str, tuple] = {}
        layout = scroll_page(self)
        layout.addWidget(page_header(
            "Normativa y reglas",
            "Active o desactive cada regla y ajuste sus valores. Solo se aplicará lo que usted seleccione."))

        top_card, top_layout = card()
        self.combo = NoWheelComboBox()
        for standard in standards:
            self.combo.addItem(standard.nombre, standard.id)
        self.combo.currentIndexChanged.connect(lambda _i: self.standardChanged.emit(self.combo.currentData()))
        self.combo.setMinimumWidth(240)
        self.count_label = label("", "muted")
        top_layout.addLayout(hbox(label("Normativa", "fieldLabel"), self.combo, None, self.count_label))
        self.profile_combo = NoWheelComboBox()
        self.profile_combo.setMinimumWidth(240)
        self.profile_combo.setAccessibleName("Perfil")
        self.profile_combo.activated.connect(lambda _i: self.profileSelected.emit(self.profile_combo.currentData()))
        self.save_profile = QPushButton("Guardar perfil")
        self.save_profile.clicked.connect(self.saveProfileRequested)
        self.save_as_profile = QPushButton("Guardar como perfil…")
        self.save_as_profile.clicked.connect(self.saveAsProfileRequested)
        self.dirty_label = label("", "muted")
        top_layout.addLayout(hbox(label("Perfil", "fieldLabel"), self.profile_combo, self.save_profile,
                                  self.save_as_profile, self.dirty_label, None))
        self.description = label("", "muted", wrap=True)
        top_layout.addWidget(self.description)
        self.enable_all = QPushButton("Activar todo")
        self.disable_all = QPushButton("Desactivar todo")
        self.restore = QPushButton("Restaurar valores predeterminados")
        self.enable_all.clicked.connect(lambda: self._bulk(lambda s: s.set_all(True)))
        self.disable_all.clicked.connect(lambda: self._bulk(lambda s: s.set_all(False)))
        self.restore.clicked.connect(self._restore)
        top_layout.addLayout(hbox(self.enable_all, self.disable_all, self.restore, stretch_end=True))
        layout.addWidget(top_card)

        self.message = Banner()
        self.warnings = Banner()
        layout.addWidget(self.message)
        layout.addWidget(self.warnings)

        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(12)
        layout.addLayout(self.rules_layout)

        self.doc_label = label("Importe un documento para analizarlo con estas reglas.", "muted")
        self.analyze_button = QPushButton("Analizar cumplimiento  →")
        self.analyze_button.setProperty("variant", "primary")
        self.analyze_button.setEnabled(False)
        self.analyze_button.clicked.connect(self.analyzeRequested)
        layout.addLayout(hbox(self.doc_label, None, self.analyze_button))
        layout.addStretch(1)

    def set_profiles(self, profiles, active_id: int | None) -> None:
        """Perfiles de la normativa visible; «active_id» es el cargado (None = valores de la normativa)."""
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("Valores de la normativa (sin perfil)", None)
        for profile in profiles:
            self.profile_combo.addItem(profile.nombre, profile.id)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(active_id)))
        self.profile_combo.blockSignals(False)

    def set_dirty(self, has_profile: bool, dirty: bool) -> None:
        self.save_profile.setEnabled(has_profile and dirty)
        self.dirty_label.setText("● cambios sin guardar en el perfil" if has_profile and dirty else "")

    def set_document(self, name: str | None) -> None:
        self.analyze_button.setEnabled(bool(name))
        self.doc_label.setText(f"Documento: {name}" if name else "Importe un documento para analizarlo con estas reglas.")

    def set_selection(self, selection: RuleSelection) -> None:
        self.selection = selection
        index = self.combo.findData(selection.standard.id)
        if index != self.combo.currentIndex():
            self.combo.blockSignals(True)
            self.combo.setCurrentIndex(index)
            self.combo.blockSignals(False)
        standard = selection.standard
        self.description.setText(f"{standard.descripcion}\n\nReferencias: " + " · ".join(standard.referencias))
        clear_layout(self.rules_layout)
        self.rows = []
        self.category_controls = {}
        for category in standard.categorias:
            rules = standard.rules_in(category.id)
            if not rules:
                continue
            switch = ToggleSwitch()
            switch.setAccessibleName(f"Categoría {category.nombre}")
            switch.setToolTip("Activar o desactivar todas las reglas de esta categoría")
            switch.toggled.connect(lambda checked, cid=category.id: self._bulk(lambda s: s.set_category(cid, checked)))
            counter = label("", "muted")
            self.category_controls[category.id] = (switch, counter)
            self.rules_layout.addLayout(hbox(label(category.nombre, "sectionTitle"), None, counter, switch))
            frame, frame_layout = card()
            frame_layout.setSpacing(2)
            if category.descripcion:
                frame_layout.addWidget(label(category.descripcion, "muted", wrap=True))
            for i, rule in enumerate(rules):
                frame_layout.addWidget(divider())
                row = RuleRow(rule, selection, self._toggle, self._set_param)
                self.rows.append(row)
                frame_layout.addWidget(row)
            self.rules_layout.addWidget(frame)
        self.message.hide()
        self._refresh()

    def _toggle(self, rule_id: str, active: bool) -> None:
        messages = self.selection.set_active(rule_id, active)
        self.message.show_message("\n".join(messages), "info")
        self._refresh()

    def _set_param(self, rule_id: str, name: str, value) -> None:
        try:
            messages = self.selection.set_param(rule_id, name, value)
            self.message.show_message("\n".join(messages), "info")
        except RuleError as exc:
            self.message.show_message(str(exc), "error")
        self._refresh()

    def _bulk(self, action) -> None:
        messages = action(self.selection)
        self.message.show_message("\n".join(messages), "info")
        self._refresh()

    def _restore(self) -> None:
        self.selection.reset()
        self.set_selection(self.selection)  # reconstruye para mostrar los valores originales
        self.message.show_message("Se restauraron las reglas y valores predeterminados de la normativa.", "info")

    def _refresh(self) -> None:
        for row in self.rows:
            row.sync()
        for category_id, (switch, counter) in self.category_controls.items():
            rules = self.selection.standard.rules_in(category_id)
            on = sum(self.selection.is_active(r.id) for r in rules)
            counter.setText(f"{on} de {len(rules)} activas")
            switch.blockSignals(True)
            switch.setChecked(on == len(rules))
            switch.blockSignals(False)
        active = len(self.selection.active_rules())
        self.count_label.setText(f"{active} de {len(self.selection.standard.reglas)} reglas activas")
        warnings = self.selection.compliance_warnings()
        if warnings:
            severe = any(level == "advertencia" for level, _ in warnings)
            self.warnings.show_message("\n".join(f"• {text}" for _, text in warnings), "warning" if severe else "info")
        else:
            self.warnings.show_message(f"La configuración cumple {self.selection.standard.nombre} en todas sus reglas.", "success")
        self.selectionEdited.emit()
