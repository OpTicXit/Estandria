"""Motor de reglas: carga y valida catálogos JSON y gestiona la selección del usuario.

No depende del formato del documento. Quien lo usa le entrega las operaciones disponibles
(con su nivel, las propiedades que escriben y los parámetros que requieren) y los alcances
válidos; con eso el motor rechaza catálogos incoherentes antes de que lleguen a un documento.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

CLASIFICACIONES = ("obligatoria", "recomendada", "contextual")
TIPOS_PARAMETRO = ("numero", "opcion", "booleano")
SCOPE_SECTIONS = "secciones"
_REQUIRED_RULE_FIELDS = ("id", "nombre", "descripcion", "categoria", "tipo", "alcance", "clasificacion", "fuente")


class CatalogError(Exception):
    """El catálogo JSON tiene un error; el mensaje indica dónde."""


class RuleError(Exception):
    """Valor de parámetro no válido elegido por el usuario."""


@dataclass(frozen=True)
class Parameter:
    nombre: str
    etiqueta: str
    tipo: str
    valor: Any  # valor predeterminado
    opciones: tuple = ()
    minimo: float | None = None
    maximo: float | None = None
    paso: float = 0.1
    unidad: str = ""
    editable: bool = False  # las opciones admiten texto libre (p. ej. otra fuente)
    conformes: tuple = ()  # valores que cumplen la normativa; vacío = solo el predeterminado

    def coerce(self, value):
        if self.tipo == "numero":
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise RuleError(f"«{self.etiqueta}» debe ser un número.") from None
            if (self.minimo is not None and number < self.minimo) or (self.maximo is not None and number > self.maximo):
                raise RuleError(f"«{self.etiqueta}» debe estar entre {self.minimo:g} y {self.maximo:g}.")
            return number
        if self.tipo == "booleano":
            if not isinstance(value, bool):
                raise RuleError(f"«{self.etiqueta}» debe ser verdadero o falso.")
            return value
        text = str(value).strip()
        if not text:
            raise RuleError(f"«{self.etiqueta}» no puede quedar vacío.")
        if not self.editable and text not in self.opciones:
            raise RuleError(f"«{text}» no es una opción válida para «{self.etiqueta}».")
        return text

    def is_conforming(self, value) -> bool:
        accepted = self.conformes or (self.valor,)
        if self.tipo == "numero":
            return any(abs(float(value) - float(a)) < 1e-9 for a in accepted)
        if self.tipo == "opcion":
            return str(value).casefold() in {str(a).casefold() for a in accepted}
        return value in accepted

    def show(self, value) -> str:
        text = f"{value:g}" if isinstance(value, float) else str(value)
        return f"{text} {self.unidad}" if self.unidad else text

    def expected_text(self) -> str:
        return " o ".join(self.show(a) for a in (self.conformes or (self.valor,)))


@dataclass(frozen=True)
class Rule:
    id: str
    nombre: str
    descripcion: str
    categoria: str
    tipo: str  # nombre de la operación que la aplica
    alcance: tuple[str, ...]  # tipos de elemento a los que afecta
    parametros: dict[str, Parameter]
    activa_por_defecto: bool
    dependencias: tuple[str, ...]
    conflictos: tuple[str, ...]
    clasificacion: str
    edicion: str
    fuente: str


@dataclass(frozen=True)
class Link:
    """Dependencia entre valores: elegir un valor de origen fija el valor de destino.

    Ejemplo APA: la fuente determina el tamaño (Calibri → 11 pt).
    """

    id: str
    descripcion: str
    origen: tuple[str, str]  # (regla, parámetro)
    destino: tuple[str, str]
    valores: dict  # valor de origen en minúsculas → valor de destino
    fuente: str

    def target_for(self, origin_value):
        return self.valores.get(str(origin_value).casefold())


@dataclass(frozen=True)
class Category:
    id: str
    nombre: str
    descripcion: str = ""


@dataclass(frozen=True)
class Standard:
    id: str
    nombre: str
    edicion: str
    descripcion: str
    referencias: tuple[str, ...]
    categorias: tuple[Category, ...]
    reglas: tuple[Rule, ...]
    vinculos: tuple[Link, ...] = ()

    def rule(self, rule_id: str) -> Rule:
        return next(r for r in self.reglas if r.id == rule_id)

    def rules_in(self, category_id: str) -> list[Rule]:
        return [r for r in self.reglas if r.categoria == category_id]

    def links_of(self, rule_id: str) -> list[Link]:
        return [link for link in self.vinculos if rule_id in (link.origen[0], link.destino[0])]


# --------------------------------------------------------------------------- carga y validación

def _parse_parameter(rule_id: str, name: str, raw: dict) -> Parameter:
    where = f"regla «{rule_id}», parámetro «{name}»"
    if raw.get("tipo") not in TIPOS_PARAMETRO:
        raise CatalogError(f"{where}: tipo desconocido «{raw.get('tipo')}».")
    if "valor" not in raw:
        raise CatalogError(f"{where}: falta «valor».")
    param = Parameter(
        nombre=name, etiqueta=raw.get("etiqueta", name), tipo=raw["tipo"], valor=raw["valor"],
        opciones=tuple(raw.get("opciones", ())), minimo=raw.get("minimo"), maximo=raw.get("maximo"),
        paso=raw.get("paso", 0.1), unidad=raw.get("unidad", ""), editable=raw.get("editable", False),
        conformes=tuple(raw.get("conformes", ())),
    )
    if param.tipo == "opcion" and not param.opciones:
        raise CatalogError(f"{where}: un parámetro de opción necesita «opciones».")
    try:
        return replace(param, valor=param.coerce(param.valor), conformes=tuple(param.coerce(c) for c in param.conformes))
    except RuleError as exc:
        raise CatalogError(f"{where}: {exc}") from None


def _check_against_operation(name: str, rule: Rule, operation) -> None:
    """La regla debe usar la operación como esta espera: nivel, parámetros y valores admitidos."""
    nivel = getattr(operation, "nivel", None)
    if nivel == "seccion" and rule.alcance != (SCOPE_SECTIONS,):
        raise CatalogError(f"{name}: «{rule.id}» actúa sobre secciones; su alcance debe ser [\"{SCOPE_SECTIONS}\"].")
    if nivel and nivel != "seccion" and SCOPE_SECTIONS in rule.alcance:
        raise CatalogError(f"{name}: «{rule.id}» actúa sobre párrafos; no puede tener el alcance «{SCOPE_SECTIONS}».")
    if nivel and "tabla" in rule.alcance and not getattr(operation, "tablas", False):
        raise CatalogError(f"{name}: la operación «{rule.tipo}» de «{rule.id}» no puede aplicarse a tablas.")
    required = getattr(operation, "requiere", None)
    if required is None:
        return
    missing = set(required) - set(rule.parametros)
    extra = set(rule.parametros) - set(required)
    if missing or extra:
        detail = "; ".join(filter(None, [f"faltan {', '.join(sorted(missing))}" if missing else "",
                                         f"sobran {', '.join(sorted(extra))}" if extra else ""]))
        raise CatalogError(f"{name}: los parámetros de «{rule.id}» no coinciden con la operación «{rule.tipo}» ({detail}).")
    for pname, (tipo, domain) in required.items():
        param = rule.parametros[pname]
        if param.tipo != tipo:
            raise CatalogError(f"{name}: «{rule.id}», parámetro «{pname}» debe ser de tipo «{tipo}».")
        if domain is not None:
            outside = set(param.opciones) - set(domain)
            if param.editable or outside:
                raise CatalogError(f"{name}: «{rule.id}», parámetro «{pname}» solo admite: {', '.join(sorted(domain))}.")


def _check_overlaps(name: str, rules: list[Rule], operations: Mapping) -> None:
    """Dos reglas que escriben la misma propiedad en el mismo tipo de elemento deben ser incompatibles.

    Así es imposible activar a la vez dos valores contradictorios (p. ej. dos alineaciones para los párrafos).
    """
    for i, first in enumerate(rules):
        for second in rules[i + 1:]:
            shared_props = (getattr(operations.get(first.tipo), "propiedades", frozenset())
                            & getattr(operations.get(second.tipo), "propiedades", frozenset()))
            shared_scope = set(first.alcance) & set(second.alcance)
            declared = second.id in first.conflictos or first.id in second.conflictos
            if shared_props and shared_scope and not declared:
                raise CatalogError(
                    f"{name}: «{first.id}» y «{second.id}» modifican {', '.join(sorted(shared_props))} en "
                    f"{', '.join(sorted(shared_scope))}. Declárelas en «conflictos» o separe sus alcances.")


def _parse_links(name: str, raw_links: list, rules: dict[str, Rule]) -> tuple[Link, ...]:
    links = []
    for raw in raw_links:
        link_id = raw.get("id", "?")
        try:
            origin = (raw["origen"]["regla"], raw["origen"]["parametro"])
            target = (raw["destino"]["regla"], raw["destino"]["parametro"])
            values = raw["valores"]
        except (KeyError, TypeError):
            raise CatalogError(f"{name}: el vínculo «{link_id}» necesita «origen», «destino» y «valores».") from None
        params = {}
        for rule_id, param_name in (origin, target):
            if rule_id not in rules or param_name not in rules[rule_id].parametros:
                raise CatalogError(f"{name}: el vínculo «{link_id}» referencia «{rule_id}.{param_name}», que no existe.")
            params[(rule_id, param_name)] = rules[rule_id].parametros[param_name]
        origin_param, target_param = params[origin], params[target]
        mapped = {}
        for key, value in values.items():
            try:
                origin_param.coerce(key)
                mapped[str(key).casefold()] = target_param.coerce(value)
            except RuleError as exc:
                raise CatalogError(f"{name}: vínculo «{link_id}»: {exc}") from None
        links.append(Link(link_id, raw.get("descripcion", ""), origin, target, mapped, raw.get("fuente", "")))
    return tuple(links)


def load_standard(path, operations: Mapping | None = None, scopes: set[str] | None = None) -> Standard:
    """Carga un catálogo. Con «operations» y «scopes» se valida además contra lo que el programa sabe aplicar."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"{path}: no se pudo leer el catálogo ({exc}).") from exc
    for key in ("id", "nombre", "edicion", "categorias", "reglas"):
        if key not in data:
            raise CatalogError(f"{path.name}: falta el campo «{key}».")

    name = path.name
    categories = tuple(Category(c["id"], c["nombre"], c.get("descripcion", "")) for c in data["categorias"])
    category_ids = {c.id for c in categories}
    rules: list[Rule] = []
    for raw in data["reglas"]:
        missing = [f for f in _REQUIRED_RULE_FIELDS if f not in raw]
        rule_id = raw.get("id", "?")
        if missing:
            raise CatalogError(f"{name}: a la regla «{rule_id}» le faltan: {', '.join(missing)}.")
        if any(r.id == rule_id for r in rules):
            raise CatalogError(f"{name}: identificador repetido «{rule_id}».")
        if raw["categoria"] not in category_ids:
            raise CatalogError(f"{name}: la regla «{rule_id}» usa la categoría inexistente «{raw['categoria']}».")
        if operations is not None and raw["tipo"] not in operations:
            raise CatalogError(f"{name}: la regla «{rule_id}» usa la operación desconocida «{raw['tipo']}».")
        if raw["clasificacion"] not in CLASIFICACIONES:
            raise CatalogError(f"{name}: la regla «{rule_id}» tiene una clasificación no válida «{raw['clasificacion']}».")
        if not isinstance(raw["alcance"], list) or not raw["alcance"]:
            raise CatalogError(f"{name}: la regla «{rule_id}» necesita un «alcance» no vacío.")
        if scopes is not None and set(raw["alcance"]) - scopes:
            unknown = ", ".join(sorted(set(raw["alcance"]) - scopes))
            raise CatalogError(f"{name}: la regla «{rule_id}» tiene un alcance desconocido: {unknown}.")
        rule = Rule(
            id=rule_id, nombre=raw["nombre"], descripcion=raw["descripcion"], categoria=raw["categoria"],
            tipo=raw["tipo"], alcance=tuple(raw["alcance"]),
            parametros={n: _parse_parameter(rule_id, n, p) for n, p in raw.get("parametros", {}).items()},
            activa_por_defecto=bool(raw.get("activa_por_defecto", True)),
            dependencias=tuple(raw.get("dependencias", ())), conflictos=tuple(raw.get("conflictos", ())),
            clasificacion=raw["clasificacion"], edicion=str(raw.get("edicion", data["edicion"])), fuente=raw["fuente"],
        )
        if operations is not None:
            _check_against_operation(name, rule, operations[rule.tipo])
        rules.append(rule)

    by_id = {r.id: r for r in rules}
    for rule in rules:
        for ref in rule.dependencias + rule.conflictos:
            if ref not in by_id or ref == rule.id:
                raise CatalogError(f"{name}: la regla «{rule.id}» referencia «{ref}», que no es válida.")
        if set(rule.dependencias) & set(rule.conflictos):
            raise CatalogError(f"{name}: la regla «{rule.id}» no puede depender de una regla con la que entra en conflicto.")
        if rule.activa_por_defecto and any(by_id[c].activa_por_defecto for c in rule.conflictos):
            raise CatalogError(f"{name}: la regla «{rule.id}» está activa por defecto junto a una regla en conflicto.")
    if operations is not None:
        _check_overlaps(name, rules, operations)

    standard = Standard(data["id"], data["nombre"], str(data["edicion"]), data.get("descripcion", ""),
                        tuple(data.get("referencias", ())), categories, tuple(rules),
                        _parse_links(name, data.get("vinculos", []), by_id))
    for link in standard.vinculos:  # los valores predeterminados deben respetar sus propios vínculos
        origin_rule, origin_param = link.origen
        target_rule, target_param = link.destino
        expected = link.target_for(by_id[origin_rule].parametros[origin_param].valor)
        if expected is not None and expected != by_id[target_rule].parametros[target_param].valor:
            raise CatalogError(f"{name}: los valores predeterminados no respetan el vínculo «{link.id}».")
    return standard


def discover_standards(directory, operations: Mapping | None = None,
                       scopes: set[str] | None = None) -> tuple[list[Standard], list[str]]:
    """Carga todos los catálogos <directorio>/<normativa>/rules.json; los defectuosos se informan."""
    standards, errors = [], []
    directory = Path(directory)
    if not directory.is_dir():
        return standards, [f"No se encontró la carpeta de normativas «{directory}»."]
    for folder in sorted(p for p in directory.iterdir() if p.is_dir()):
        catalog = folder / "rules.json"
        if catalog.is_file():
            try:
                standards.append(load_standard(catalog, operations, scopes))
            except CatalogError as exc:
                errors.append(str(exc))
    return standards, errors


# --------------------------------------------------------------------------- selección del usuario

class RuleSelection:
    """Qué reglas aplicar y con qué valores. Resuelve dependencias, conflictos y vínculos."""

    def __init__(self, standard: Standard):
        self.standard = standard
        self._rules = {r.id: r for r in standard.reglas}
        self.reset()

    def reset(self) -> None:
        self._active = {r.id: r.activa_por_defecto for r in self.standard.reglas}
        self._params = {r.id: {n: p.valor for n, p in r.parametros.items()} for r in self.standard.reglas}

    def to_dict(self) -> dict:
        """Estado serializable (para perfiles)."""
        return {"normativa": self.standard.id, "edicion": self.standard.edicion,
                "activas": dict(self._active), "parametros": {k: dict(v) for k, v in self._params.items()}}

    def apply_dict(self, data: dict) -> list[str]:
        """Carga un estado guardado. Lo que ya no encaja con el catálogo se ignora y se explica."""
        self.reset()
        problems = []
        if data.get("edicion") and data["edicion"] != self.standard.edicion:
            problems.append(f"El perfil se guardó con la edición {data['edicion']} del catálogo; la actual es "
                            f"{self.standard.edicion}. Revise las reglas.")
        for rule_id, active in (data.get("activas") or {}).items():
            if rule_id not in self._rules:
                problems.append(f"La regla «{rule_id}» ya no existe en el catálogo; se ignoró.")
                continue
            self._active[rule_id] = bool(active)
        for rule_id, values in (data.get("parametros") or {}).items():
            rule = self._rules.get(rule_id)
            if rule is None:
                continue
            for name, value in values.items():
                if name not in rule.parametros:
                    continue
                try:
                    self._params[rule_id][name] = rule.parametros[name].coerce(value)
                except RuleError as exc:
                    problems.append(f"«{rule.nombre}»: {exc} Se usa el valor predeterminado.")
        problems += self._repair()
        return problems

    def _repair(self) -> list[str]:
        """Tras cargar un estado guardado: resuelve conflictos y dependencias que el catálogo actual exija."""
        messages: list[str] = []
        for rule in self.standard.reglas:
            if not self._active[rule.id]:
                continue
            for other in sorted(self._conflicts_of(rule.id)):
                if self._active[other]:
                    self._active[other] = False
                    messages.append(f"Se desactivó «{self._rules[other].nombre}» porque es incompatible con «{rule.nombre}».")
            for dependency in rule.dependencias:
                self._activate(dependency, messages, rule.nombre)
        return messages

    def is_active(self, rule_id: str) -> bool:
        return self._active[rule_id]

    def active_rules(self) -> list[Rule]:
        return [r for r in self.standard.reglas if self._active[r.id]]

    def params(self, rule_id: str) -> dict:
        return dict(self._params[rule_id])

    def set_param(self, rule_id: str, name: str, value) -> list[str]:
        """Cambia un valor; si es origen de un vínculo, ajusta el valor vinculado y lo explica."""
        new = self._rules[rule_id].parametros[name].coerce(value)
        if new == self._params[rule_id][name]:
            return []  # sin cambio real: no se reajusta lo que el usuario haya elegido a mano
        self._params[rule_id][name] = new
        messages = []
        for link in self.standard.vinculos:
            if link.origen != (rule_id, name):
                continue
            target = link.target_for(new)
            target_rule, target_param = link.destino
            if target is not None and self._params[target_rule][target_param] != target:
                self._params[target_rule][target_param] = target
                param = self._rules[target_rule].parametros[target_param]
                messages.append(f"Se ajustó «{self._rules[target_rule].nombre}» a {param.show(target)}: "
                                f"{self.standard.nombre} asocia «{new}» con ese valor. Puede cambiarlo si lo necesita.")
        return messages

    def set_active(self, rule_id: str, active: bool) -> list[str]:
        """Activa o desactiva una regla; devuelve los cambios automáticos que provocó."""
        messages: list[str] = []
        (self._activate if active else self._deactivate)(rule_id, messages, None)
        return messages

    def set_all(self, active: bool) -> list[str]:
        return self._set_many(self.standard.reglas, active)

    def set_category(self, category_id: str, active: bool) -> list[str]:
        return self._set_many(self.standard.rules_in(category_id), active)

    def _set_many(self, rules, active: bool) -> list[str]:
        messages: list[str] = []
        for rule in rules:
            (self._activate if active else self._deactivate)(rule.id, messages, None)
        return messages

    def _conflicts_of(self, rule_id: str) -> set[str]:
        own = set(self._rules[rule_id].conflictos)
        return own | {r.id for r in self.standard.reglas if rule_id in r.conflictos}

    def _activate(self, rule_id: str, messages: list[str], required_by: str | None) -> None:
        if self._active[rule_id]:
            return
        rule = self._rules[rule_id]
        self._active[rule_id] = True
        if required_by:
            messages.append(f"Se activó «{rule.nombre}» porque «{required_by}» depende de ella.")
        for other in sorted(self._conflicts_of(rule_id)):
            if self._active[other]:
                self._deactivate(other, messages, None)
                messages.append(f"Se desactivó «{self._rules[other].nombre}» porque es incompatible con «{rule.nombre}».")
        for dependency in rule.dependencias:
            self._activate(dependency, messages, rule.nombre)

    def _deactivate(self, rule_id: str, messages: list[str], because_of: str | None) -> None:
        if not self._active[rule_id]:
            return
        rule = self._rules[rule_id]
        self._active[rule_id] = False
        if because_of:
            messages.append(f"Se desactivó «{rule.nombre}» porque depende de «{because_of}».")
        for other in self.standard.reglas:
            if rule_id in other.dependencias and self._active[other.id]:
                self._deactivate(other.id, messages, rule.nombre)

    def compliance_warnings(self) -> list[tuple[str, str]]:
        """Avisos de personalización: («advertencia» | «info», texto)."""
        name = self.standard.nombre
        warnings = []
        for rule in self.standard.reglas:
            if not self._active[rule.id]:
                if rule.clasificacion == "obligatoria":
                    warnings.append(("advertencia", f"«{rule.nombre}» está desactivada: el documento no cumplirá completamente {name}."))
                elif rule.clasificacion == "recomendada":
                    warnings.append(("info", f"«{rule.nombre}» es una recomendación de {name} y está desactivada."))
                continue
            for pname, param in rule.parametros.items():
                value = self._params[rule.id][pname]
                if not param.is_conforming(value):
                    level = "advertencia" if rule.clasificacion == "obligatoria" else "info"
                    warnings.append((level, f"«{rule.nombre}»: {param.etiqueta} = {param.show(value)} no coincide con {name} "
                                            f"({param.expected_text()})."))
        warnings += self._link_warnings()
        return warnings

    def _link_warnings(self) -> list[tuple[str, str]]:
        warnings = []
        for link in self.standard.vinculos:
            (origin_rule, origin_param), (target_rule, target_param) = link.origen, link.destino
            if not (self._active[origin_rule] and self._active[target_rule]):
                continue
            origin_value = self._params[origin_rule][origin_param]
            expected = link.target_for(origin_value)
            actual = self._params[target_rule][target_param]
            param = self._rules[target_rule].parametros[target_param]
            # Si el valor ya incumple por sí solo, ese aviso basta; aquí solo la combinación.
            if expected is None or actual == expected or not param.is_conforming(actual):
                continue
            level = "advertencia" if self._rules[target_rule].clasificacion == "obligatoria" else "info"
            warnings.append((level, f"«{self._rules[target_rule].nombre}» = {param.show(actual)} no corresponde a "
                                    f"«{origin_value}»: {self.standard.nombre} indica {param.show(expected)}."))
        return warnings
