"""Motor de reglas: catálogo, activación, categorías, dependencias, conflictos, vínculos y validación."""
import json

import pytest

from app.core.document_analyzer import known_scopes
from app.core.rule_engine import CLASIFICACIONES, CatalogError, RuleError, RuleSelection, discover_standards, load_standard
from app.formats.docx_operations import OPERATIONS
from app.paths import standards_dir

ALIGN_PARAM = {"alineacion": {"tipo": "opcion", "valor": "izquierda", "opciones": ["izquierda", "centro"]}}
SPACING_PARAM = {"multiplo": {"tipo": "numero", "valor": 2.0, "minimo": 1, "maximo": 3}}


def write_catalog(tmp_path, rules, links=None):
    data = {"id": "prueba", "nombre": "Prueba", "edicion": "1",
            "categorias": [{"id": "c", "nombre": "C"}, {"id": "d", "nombre": "D"}], "reglas": rules}
    if links is not None:
        data["vinculos"] = links
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def rule(rid, **extra):
    base = {"id": rid, "nombre": rid.upper(), "descripcion": "d", "categoria": "c", "tipo": "alineacion",
            "alcance": ["parrafo"], "clasificacion": "obligatoria", "fuente": "f", "parametros": ALIGN_PARAM}
    base.update(extra)
    return base


def load(path):
    return load_standard(path, OPERATIONS, known_scopes())


# --------------------------------------------------------------------------- catálogo APA

def test_apa_catalog_is_complete(apa):
    assert apa.id == "apa7"
    ids = [r.id for r in apa.reglas]
    assert len(ids) == len(set(ids))
    for r in apa.reglas:
        assert r.tipo in OPERATIONS and r.clasificacion in CLASIFICACIONES and r.fuente and r.edicion
    assert [link.id for link in apa.vinculos] == ["fuente_tamano"]


def test_discover_finds_apa_without_errors():
    standards, errors = discover_standards(standards_dir(), OPERATIONS, known_scopes())
    assert errors == []
    assert "apa7" in [s.id for s in standards]


# --------------------------------------------------------------------------- activación

def test_toggle_and_reset(selection):
    assert selection.is_active("par_sangria_primera")
    selection.set_active("par_sangria_primera", False)
    assert not selection.is_active("par_sangria_primera")
    assert all(selection.is_active(r.id) == r.activa_por_defecto
               for r in selection.standard.reglas if r.id != "par_sangria_primera")
    selection.reset()
    assert selection.is_active("par_sangria_primera")


def test_set_all(selection):
    selection.set_all(False)
    assert selection.active_rules() == []
    selection.set_all(True)
    assert len(selection.active_rules()) == len(selection.standard.reglas)


def test_category_toggle_only_affects_its_rules(selection):
    selection.set_category("referencias", False)
    for r in selection.standard.reglas:
        assert selection.is_active(r.id) == (r.activa_por_defecto and r.categoria != "referencias")
    selection.set_category("referencias", True)
    assert all(selection.is_active(r.id) for r in selection.standard.rules_in("referencias"))


def test_dependencies_and_conflicts(tmp_path):
    std = load(write_catalog(tmp_path, [
        rule("a"),
        rule("b", tipo="interlineado", parametros=SPACING_PARAM, dependencias=["a"]),
        rule("c", conflictos=["a"], activa_por_defecto=False),
    ]))
    sel = RuleSelection(std)
    messages = sel.set_active("a", False)
    assert not sel.is_active("b"), "al desactivar «a» se desactiva lo que depende de ella"
    assert any("depende" in m for m in messages)
    sel.set_active("b", True)
    assert sel.is_active("a"), "activar «b» activa su dependencia"
    messages = sel.set_active("c", True)
    assert sel.is_active("c") and not sel.is_active("a") and not sel.is_active("b")
    assert any("incompatible" in m for m in messages)


# --------------------------------------------------------------------------- vínculos y avisos

def test_link_adjusts_size_when_font_changes(selection):
    messages = selection.set_param("tip_familia", "familia", "Calibri")
    assert selection.params("tip_tamano")["tamano"] == 11
    assert any("Tamaño de fuente" in m and "11 pt" in m for m in messages)
    assert selection.compliance_warnings() == []


def test_link_respects_manual_choice_and_warns(selection):
    selection.set_param("tip_familia", "familia", "Calibri")
    selection.set_param("tip_tamano", "tamano", 12)
    assert selection.set_param("tip_familia", "familia", "Calibri") == [], "repetir el mismo valor no reajusta"
    assert selection.params("tip_tamano")["tamano"] == 12
    warnings = [t for level, t in selection.compliance_warnings() if level == "advertencia"]
    assert any("Calibri" in w and "11 pt" in w for w in warnings)


def test_custom_font_has_no_link(selection):
    selection.set_param("tip_familia", "familia", "Garamond")
    assert selection.params("tip_tamano")["tamano"] == 12
    assert any("Garamond" in t for _, t in selection.compliance_warnings())


def test_link_warning_needs_both_rules_active(selection):
    selection.set_param("tip_familia", "familia", "Arial")
    selection.set_param("tip_tamano", "tamano", 12)
    selection.set_active("tip_tamano", False)
    assert not any("no corresponde" in t for _, t in selection.compliance_warnings())


def test_compliance_warnings(selection):
    assert selection.compliance_warnings() == []
    selection.set_active("par_sangria_primera", False)
    selection.set_param("tip_tamano", "tamano", 14)
    warnings = [text for level, text in selection.compliance_warnings() if level == "advertencia"]
    assert any("Sangría de primera línea" in w for w in warnings)
    assert any("Tamaño" in w and "14" in w for w in warnings)


def test_contextual_change_does_not_warn(selection):
    selection.set_param("pag_tamano_papel", "papel", "A4")
    assert selection.compliance_warnings() == []


def test_invalid_parameter_values(selection):
    with pytest.raises(RuleError):
        selection.set_param("pag_margenes", "superior_cm", 50)
    with pytest.raises(RuleError):
        selection.set_param("par_alineacion", "alineacion", "diagonal")


# --------------------------------------------------------------------------- validación de catálogos

FONT_RULE = rule("f", tipo="familia_fuente", parametros={"familia": {"tipo": "opcion", "valor": "Arial", "opciones": ["Arial"], "editable": True}})
SIZE_RULE = rule("s", tipo="tamano_fuente", parametros={"tamano": {"tipo": "numero", "valor": 11, "minimo": 6, "maximo": 72}})


@pytest.mark.parametrize("rules, links, message", [
    ([rule("a"), rule("a")], None, "repetido"),
    ([rule("a", dependencias=["x"])], None, "no es válida"),
    ([rule("a", tipo="inventada")], None, "desconocida"),
    ([rule("a", clasificacion="opcional")], None, "clasificación"),
    ([rule("a", categoria="otra")], None, "categoría"),
    ([rule("a"), rule("b", conflictos=["a"])], None, "conflicto"),
    ([rule("a"), rule("b", alcance=["parrafo", "lista"])], None, "modifican alineacion"),
    ([rule("a", alcance=["parrafos"])], None, "alcance desconocido"),
    ([rule("a", alcance=["secciones"])], None, "actúa sobre párrafos"),
    ([rule("a", alcance=["tabla"])], None, "no puede aplicarse a tablas"),
    ([rule("a", tipo="interlineado")], None, "no coinciden"),
    ([rule("a", parametros={"alineacion": {"tipo": "opcion", "valor": "diagonal", "opciones": ["diagonal"]}})], None, "solo admite"),
    ([FONT_RULE, SIZE_RULE], [{"id": "v", "origen": {"regla": "f", "parametro": "familia"},
                               "destino": {"regla": "s", "parametro": "x"}, "valores": {}}], "no existe"),
    ([FONT_RULE, SIZE_RULE], [{"id": "v", "origen": {"regla": "f", "parametro": "familia"},
                               "destino": {"regla": "s", "parametro": "tamano"}, "valores": {"Arial": 500}}], "entre"),
    ([FONT_RULE, SIZE_RULE], [{"id": "v", "origen": {"regla": "f", "parametro": "familia"},
                               "destino": {"regla": "s", "parametro": "tamano"}, "valores": {"Arial": 12}}], "predeterminados"),
])
def test_invalid_catalogs_are_rejected(tmp_path, rules, links, message):
    with pytest.raises(CatalogError, match=message):
        load(write_catalog(tmp_path, rules, links))


def test_overlap_is_allowed_when_declared_as_conflict(tmp_path):
    std = load(write_catalog(tmp_path, [rule("a"), rule("b", conflictos=["a"], activa_por_defecto=False)]))
    assert len(std.reglas) == 2


def test_rules_in_different_scopes_do_not_overlap(tmp_path):
    std = load(write_catalog(tmp_path, [rule("a"), rule("b", alcance=["referencia"])]))
    assert len(std.reglas) == 2
