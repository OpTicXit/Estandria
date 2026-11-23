"""Limpieza de estilo: reglas, posiciones, plegado, exclusiones, ausencia de agregados, determinismo e idempotencia."""
import dataclasses
import inspect

import pytest
from docx import Document
from docx.shared import Cm

import app.style as style
from app.core.document_analyzer import analyze_document
from app.style import Hallazgo, ReviewText, analyze, apply_findings, detect_language
from app.style.rules import approximate_root, fold

NEUTRAL = "La muestra incluyó estudiantes de varias facultades que respondieron un cuestionario breve. "  # 13 palabras


def review_of(*paragraphs, block_quote=None, references=None):
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    if block_quote:
        doc.add_paragraph(block_quote).paragraph_format.left_indent = Cm(1.27)
    if references:
        doc.add_heading("Referencias", level=1)
        for text in references:
            doc.add_paragraph(text)
    return doc, ReviewText(analyze_document(doc))


def rules_found(*paragraphs, **kwargs):
    return [h.ruleId for h in analyze(review_of(*paragraphs, **kwargs)[1])]


# ---------------------------------------------------------------- 1. positivo y negativo por regla

@pytest.mark.parametrize("rule, positive, negative", [
    ("muletilla", "Cabe destacar que el sueño mejora la memoria.", "El sueño mejora la memoria."),
    ("pleonasmo", "Se midieron variables como por ejemplo la edad.", "Se midieron variables como la edad."),
    ("adjetivo_vacio", "El hallazgo es fundamental y crucial.", NEUTRAL * 30 + "El efecto fue fundamental."),
    ("intensificador", "El efecto fue muy claro.", NEUTRAL * 50 + "El efecto fue muy claro."),
    ("oracion_larga", " ".join(["palabra"] * 40) + ".", " ".join(["palabra"] * 20) + "."),
    ("nominalizacion", "Se llevó a cabo la realización de encuestas.", "Se realizaron encuestas."),
])
def test_rule_positive_and_negative(rule, positive, negative):
    assert rule in rules_found(positive)
    assert rule not in rules_found(negative)


def test_repeticion():
    repeated = ("La memoria cambia con el sueño y la memoria se consolida durante la noche, por eso la memoria "
                "depende de dormir bien según los estudios revisados en esta investigación sobre hábitos de los "
                "estudiantes universitarios de primer año en distintas facultades del país.")
    assert "repeticion" in rules_found(repeated)
    assert "repeticion" not in rules_found("La memoria y la memoria y la memoria.")  # párrafo de menos de 40 palabras
    stopwords = repeated.replace("memoria", "porque")
    assert "repeticion" not in rules_found(stopwords)


def test_prosa_uniforme():
    sentence = " ".join(["palabra"] * 19) + " final."
    assert "prosa_uniforme" in rules_found(" ".join([sentence.capitalize()] * 8))
    varied = " ".join(["Corta.", " ".join(["palabra"] * 34).capitalize() + "."] * 4)
    assert "prosa_uniforme" not in rules_found(varied)


def test_pasiva_with_agent_and_legitimate():
    _, review = review_of("La muestra fue seleccionada por los investigadores. El estudio fue aprobado.")
    passives = [h for h in analyze(review) if h.ruleId == "pasiva"]
    with_agent, without = passives
    assert with_agent.severity != "info" and with_agent.propuesta == "Los investigadores seleccionaron la muestra."
    assert without.severity == "info" and without.propuesta is None
    assert without.explicacion == "regla.pasiva.exp_legitima"
    assert "pasiva" not in rules_found("Los investigadores seleccionaron la muestra. El comité aprobó el estudio.")


def test_irregular_participle():
    assert "pasiva" in rules_found("El informe fue escrito por el equipo.")


def test_english_document_disables_module():
    _, review = review_of("The sample was selected by the researchers and the results of the study are shown in the table.")
    assert detect_language(review) == "en"


# ---------------------------------------------------------------- 2 y 3. posiciones y plegado

FIXTURES = [
    "Cabe destacar que el sueño es muy importante. Hoy en día, la memoria es crucial, pero sin embargo hay dudas.",
    "La muestra fue seleccionada por los investigadores. La evaluación de los datos fue realizada con cuidado.",
    "ÁÉÍÓÚ ñandú Ñuñoa «cita» İstanbul — período de tiempo; como por ejemplo, con el fin de.",
]


@pytest.mark.parametrize("text", FIXTURES)
def test_offsets_point_to_the_original(text):
    _, review = review_of(text, "Segundo párrafo con la utilización de recursos muy variados.")
    for finding in analyze(review):
        assert review.text[finding.ini:finding.fin] == finding.excerpt


@pytest.mark.parametrize("text", FIXTURES)
def test_fold_keeps_length(text):
    assert len(fold(text)) == len(text)


def test_approximate_root():
    assert approximate_root("Memorias") == approximate_root("memoria") == "memoria"
    assert approximate_root("estudiantes") == "estudia"


# ---------------------------------------------------------------- 4. exclusiones

def test_block_quote_references_and_quotes_are_excluded():
    muddled = "Cabe destacar que es muy fundamental, pero sin embargo crucial."
    _, review = review_of(block_quote=muddled, references=[muddled + " (2019)."])
    assert analyze(review) == []
    _, quoted = review_of(f"El autor escribió «{muddled}» en su obra.")
    assert analyze(quoted) == []


# ---------------------------------------------------------------- 5. sin agregados

def test_no_aggregate_anywhere():
    forbidden = ("score", "puntuacion", "porcentaje_global", "indice", "ratio", "veredicto", "total", "global")
    fields = {f.name for f in dataclasses.fields(Hallazgo)}
    assert fields == {"ruleId", "severity", "ini", "fin", "excerpt", "medido", "umbral", "explicacion", "propuesta",
                      "aceptable", "elemento", "contexto"}
    public = set(style.__all__) | {name for name, _ in inspect.getmembers(style.rules, inspect.isfunction)}
    assert not any(word in name.lower() for name in public | fields for word in forbidden)
    assert isinstance(analyze(review_of(FIXTURES[0])[1]), list)


# ---------------------------------------------------------------- 6 y 7. determinismo e idempotencia

def test_deterministic():
    _, review = review_of(*FIXTURES)
    assert analyze(review) == analyze(review)
    assert analyze(review) == analyze(review_of(*FIXTURES)[1])


def test_accepting_does_not_reintroduce_the_finding():
    doc, review = review_of(*FIXTURES[:2], " ".join(["palabra"] * 25) + "; " + " ".join(["otra"] * 25) + ".")
    accepted = [h for h in analyze(review) if h.aceptable]
    applied = apply_findings(review, accepted)
    assert applied
    after = analyze(ReviewText(analyze_document(doc)))
    before_keys = {(h.ruleId, h.propuesta, h.excerpt) for h in applied}
    assert not {(h.ruleId, h.propuesta, h.excerpt) for h in after} & before_keys
    assert not any(h.ruleId in ("muletilla", "pleonasmo", "nominalizacion", "oracion_larga") for h in after)


def test_document_unchanged_until_accepted():
    doc, review = review_of(FIXTURES[0])
    text = review.text
    analyze(review)
    assert ReviewText(analyze_document(doc)).text == text
