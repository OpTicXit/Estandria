"""Detección de citas autor-fecha y cruce con referencias."""
import pytest

from app.core.citations import abbreviation_map, extract_citations, matches, reference_key


def authors(text):
    return [(c.autor, c.anio) for c in extract_citations(text)]


@pytest.mark.parametrize("text, expected", [
    ("(García, 2019)", [("garcia", "2019")]),
    ("García (2019) afirma", [("garcia", "2019")]),
    ("Martínez y Soto (2021)", [("martinez", "2021")]),
    ("(Pérez et al., 2018a, p. 4)", [("perez", "2018a")]),
    ("(Walker, 2017; véase García, 2019)", [("walker", "2017"), ("garcia", "2019")]),
    ("De la Cruz (s. f.)", [("cruz", "sf")]),
    ("(Ruiz, n.d.)", [("ruiz", "sf")]),
    ("durante la pandemia (2020) aumentó", []),
    ("(J. Ruiz, comunicación personal, 3 de mayo de 2020)", []),
    ("(p. 45)", []),
])
def test_extract(text, expected):
    assert authors(text) == expected


def test_reference_keys():
    assert reference_key("García, L. (2019). Título. Editorial.") == ("garcia", "2019")
    assert reference_key("García, L. (Ed.). (2019). Libro.") == ("garcia", "2019")
    assert reference_key("Organización Mundial de la Salud. (2020). Informe.") == ("organizacion mundial de la salud", "2020")
    assert reference_key("De la Cruz, A. (s. f.). Página web.") == ("de la cruz", "sf")
    assert reference_key("Entrada sin año. Editorial.") is None


def test_matching_with_abbreviation_and_compound_surname():
    found = extract_citations("La Organización Mundial de la Salud [OMS] (2020) informa (OMS, 2020). De la Cruz (s. f.)")
    abbreviations = abbreviation_map(found)
    who = reference_key("Organización Mundial de la Salud. (2020). Informe.")
    cruz = reference_key("De la Cruz, A. (s. f.). Web.")
    assert [matches(c, who, abbreviations) for c in found[:2]] == [True, True]
    assert matches(found[2], cruz, abbreviations)


def test_year_must_match():
    citation = extract_citations("(García, 2018)")[0]
    assert not matches(citation, ("garcia", "2019"), {})
