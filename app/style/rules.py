"""Limpieza de estilo: hallazgos deterministas de redundancia, repetición léxica y registro inflado.

Restricciones de diseño (no negociables):
- No clasifica autoría ni sugiere en ningún texto quién o qué escribió el documento.
- No produce puntuación, porcentaje ni índice global: cada hallazgo trae su valor medido y su umbral.
- No usa modelos de lenguaje ni red. Mismo documento ⇒ mismos hallazgos.
- No modifica nada: las propuestas se aplican solo cuando el autor acepta cada hallazgo.
"""
from __future__ import annotations

import json
import math
import re
import statistics
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.style.text_model import ReviewText

_FOLD = str.maketrans("áàäâéèëêíìïîóòöôúùüûñÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑ",
                      "aaaaeeeeiiiioooouuuunaaaaeeeeiiiioooouuuun")
_WORD = re.compile(r"[^\W\d_]+")  # sobre texto plegado: palabras sin números
_TOKEN = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*")  # para contar palabras de una oración
_TERMINATORS = ".!?…"
RULE_IDS = ("muletilla", "pleonasmo", "adjetivo_vacio", "intensificador", "repeticion", "oracion_larga",
            "prosa_uniforme", "pasiva", "nominalizacion")


def fold(text: str) -> str:
    """Minúsculas sin tildes, sustituyendo cada carácter por exactamente uno.

    No se usa normalize('NFD') + eliminación de diacríticos porque cambia la longitud de la cadena
    y rompería la correspondencia de posiciones con el documento original.
    """
    folded = text.translate(_FOLD)
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in folded)


def approximate_root(word: str) -> str:
    """Raíz APROXIMADA: sin -es/-s final y truncada a 7 caracteres.

    Puede agrupar palabras distintas (falsos positivos). Por eso el umbral de repetición es 3 y el
    hallazgo es una sugerencia revisable, nunca un cambio automático.
    """
    word = fold(word)
    if word.endswith("es") and len(word) > 4:
        word = word[:-2]
    elif word.endswith("s") and len(word) > 3:
        word = word[:-1]
    return word[:7]


@dataclass(frozen=True)
class Hallazgo:
    ruleId: str
    severity: str  # 'info' | 'aviso' | 'revision', derivada de medido y umbral
    ini: int  # posiciones en el texto de revisión del documento ORIGINAL
    fin: int
    excerpt: str  # == texto[ini:fin]
    medido: float
    umbral: float
    explicacion: str  # clave del catálogo de idioma
    propuesta: str | None  # reescritura determinista o None
    aceptable: bool
    elemento: int = 0  # bloque del documento, para navegar hasta el hallazgo
    contexto: tuple = ()  # pares (clave, valor) que completan la explicación; no son agregados

    @property
    def datos(self) -> dict:
        return dict(self.contexto)


@lru_cache(maxsize=None)
def lexicon() -> dict:
    data = json.loads(Path(__file__).with_name("lexicon_es.json").read_text(encoding="utf-8"))
    return {
        "umbrales": data["umbrales"],
        "muletillas": [fold(m) for m in data["muletillas"]],
        "pleonasmos": {fold(k): v for k, v in data["pleonasmos"].items()},
        "vacio": {fold(w) for w in data["vacio"]},
        "intensificadores": {fold(w) for w in data["intensificadores"]},
        "stopwords": {fold(w) for w in data["stopwords_repeticion"]},
        "ser": {fold(w) for w in data["ser"]},
        "irregulares": {fold(w) for w in data["participios_irregulares"]},
        "abreviaturas": {fold(w) for w in data["abreviaturas"]},
        "idioma": {k: {fold(w) for w in v} for k, v in data["idioma"].items()},
    }


def severity(medido: float, umbral: float, lower_is_worse: bool = False) -> str:
    """Severidad a partir de la proporción medido/umbral (o umbral/medido si lo bajo es lo que se señala)."""
    ratio = (umbral / medido if medido else math.inf) if lower_is_worse else medido / umbral
    return "revision" if ratio >= 2 else "aviso" if ratio >= 1 else "info"


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


class _Analysis:
    """Datos compartidos por las reglas para un mismo texto de revisión."""

    def __init__(self, review: ReviewText):
        self.review = review
        self.text = review.text
        self.folded = fold(review.text)
        self.lex = lexicon()
        self.tramos = review.analyzable()
        self.words = [(t, m.start(), m.end()) for t in self.tramos
                      for m in _WORD.finditer(self.folded, t.ini, t.fin)
                      if not review.in_quote(m.start(), m.end())]
        self.sentences = [(t, s, e) for t in self.tramos for s, e in self._split(t.ini, t.fin)
                          if not review.in_quote(s, e)]

    # ---------------------------------------------------------------- oraciones
    def _split(self, ini: int, fin: int) -> list[tuple[int, int]]:
        text, folded, result, start, i = self.text, self.folded, [], ini, ini
        while i < fin:
            if text[i] in _TERMINATORS:
                j = i
                while j + 1 < fin and text[j + 1] in _TERMINATORS + "»”\")":
                    j += 1
                k = j + 1
                while k < fin and text[k].isspace():
                    k += 1
                previous = re.search(r"([^\W\d_]+)$", folded[start:i])
                abbreviation = text[i] == "." and previous is not None and (
                    previous.group(1) in self.lex["abreviaturas"] or len(previous.group(1)) == 1)
                next_ok = k >= fin or text[k].isupper() or text[k].isdigit() or text[k] in "¿¡«“\"("
                if k > j + 1 and next_ok and not abbreviation or k >= fin:
                    result.append((start, j + 1))
                    start = i = k
                    continue
                i = j + 1
                continue
            i += 1
        if start < fin and text[start:fin].strip():
            result.append((start, fin))
        return [(s, e) for s, e in result if text[s:e].strip()]

    def word_count(self, ini: int, fin: int) -> int:
        return len(_TOKEN.findall(self.text[ini:fin]))

    def sentence_start(self, tramo, ini: int) -> bool:
        j = ini - 1
        while j >= tramo.ini and self.text[j].isspace():
            j -= 1
        return j < tramo.ini or self.text[j] in _TERMINATORS + ":"

    # ---------------------------------------------------------------- utilidades de hallazgo
    def make(self, rule: str, ini: int, fin: int, medido, umbral, key: str, propuesta, tramo,
             level: str | None = None, lower_is_worse: bool = False, **context) -> Hallazgo:
        return Hallazgo(
            ruleId=rule, severity=level or severity(medido, umbral, lower_is_worse), ini=ini, fin=fin,
            excerpt=self.text[ini:fin], medido=medido, umbral=umbral, explicacion=key, propuesta=propuesta,
            aceptable=propuesta is not None, elemento=tramo.elemento,
            contexto=tuple(sorted(context.items())))

    def deletion(self, tramo, ini: int, fin: int) -> tuple[int, int, str]:
        """Borra el fragmento con la coma y los espacios que lo siguen; si abría la oración, la palabra
        siguiente pasa a mayúscula (incluida en el fragmento para que la propuesta lo refleje)."""
        end = fin
        if end < tramo.fin and self.text[end] == ",":
            end += 1
        while end < tramo.fin and self.text[end] == " ":
            end += 1
        if self.sentence_start(tramo, ini) and end < tramo.fin and self.text[end].islower():
            return ini, end + 1, self.text[end].upper()
        if end == tramo.fin or self.text[end] in _TERMINATORS:  # al final: quitar el espacio anterior
            while ini > tramo.ini and self.text[ini - 1] == " ":
                ini -= 1
            return ini, fin, ""
        return ini, end, ""

    def phrase_hits(self, phrase: str):
        pattern = re.compile(r"(?<![^\W\d_])" + r"\s+".join(map(re.escape, phrase.split())) + r"(?![^\W\d_])")
        for tramo in self.tramos:
            for m in pattern.finditer(self.folded, tramo.ini, tramo.fin):
                if not self.review.in_quote(m.start(), m.end()):
                    yield tramo, m.start(), m.end()


# ====================================================================== reglas

def _muletillas(a: _Analysis) -> list[Hallazgo]:
    umbral = a.lex["umbrales"]["muletilla"]
    found = []
    for phrase in a.lex["muletillas"]:
        for tramo, ini, fin in a.phrase_hits(phrase):
            ini, fin, proposal = a.deletion(tramo, ini, fin)
            found.append(a.make("muletilla", ini, fin, 1, umbral, "regla.muletilla.exp", proposal, tramo))
    return found


def _pleonasmos(a: _Analysis) -> list[Hallazgo]:
    umbral = a.lex["umbrales"]["pleonasmo"]
    found = []
    for phrase, short in a.lex["pleonasmos"].items():
        for tramo, ini, fin in a.phrase_hits(phrase):
            proposal = _capitalize(short) if a.text[ini].isupper() else short
            found.append(a.make("pleonasmo", ini, fin, 1, umbral, "regla.pleonasmo.exp", proposal, tramo))
    return found


def _density_rule(a: _Analysis, rule: str, words: set[str], delete: bool) -> list[Hallazgo]:
    umbral = a.lex["umbrales"][rule]
    hits = [(t, s, e) for t, s, e in a.words if a.folded[s:e] in words]
    total = len(a.words)
    if not hits or not total:
        return []
    density = round(len(hits) * 1000 / total, 1)
    if density < umbral:
        return []
    found = []
    for tramo, ini, fin in hits:
        if delete:
            ini, fin, proposal = a.deletion(tramo, ini, fin)
        else:
            proposal = None  # quitar un adjetivo puede romper la frase: se pide un dato, no se borra
        found.append(a.make(rule, ini, fin, density, umbral, f"regla.{rule}.exp", proposal, tramo,
                            ocurrencias=len(hits), palabras=total))
    return found


def _repeticion(a: _Analysis) -> list[Hallazgo]:
    umbral = a.lex["umbrales"]["repeticion"]
    minimum = a.lex["umbrales"]["repeticion_min_palabras_parrafo"]
    found = []
    for tramo in a.tramos:
        words = [(s, e) for t, s, e in a.words if t is tramo]
        if len(words) < minimum:
            continue
        groups: dict[str, list[tuple[int, int]]] = {}
        for s, e in words:
            word = a.folded[s:e]
            if len(word) >= 5 and word not in a.lex["stopwords"]:
                groups.setdefault(approximate_root(word), []).append((s, e))
        for root, spans in sorted(groups.items()):
            if len(spans) >= umbral:
                forms = ", ".join(dict.fromkeys(a.text[s:e] for s, e in spans))
                s, e = spans[0]
                found.append(a.make("repeticion", s, e, len(spans), umbral, "regla.repeticion.exp", None, tramo,
                                    raiz=root, palabras=len(words), formas=forms))
    return found


_SPLITS = [("; ", ". ", True), (", pero ", ". Pero ", False), (", aunque ", ". Aunque ", False),
           (", sin embargo, ", ". Sin embargo, ", False), (", y ", ". ", True)]


def _split_proposal(sentence: str) -> str | None:
    """Corte en el conector más cercano al centro (entre el 30 % y el 70 % de la oración)."""
    best = None
    for connector, replacement, capitalize_next in _SPLITS:
        for m in re.finditer(re.escape(connector), sentence):
            if not 0.3 <= m.start() / len(sentence) <= 0.7:
                continue
            distance = abs(m.start() - len(sentence) / 2)
            if best is None or distance < best[0]:
                best = (distance, m.start(), m.end(), replacement, capitalize_next)
    if best is None:
        return None
    _, start, end, replacement, capitalize_next = best
    rest = sentence[end:]
    return sentence[:start] + replacement + (_capitalize(rest) if capitalize_next else rest)


def _oracion_larga(a: _Analysis) -> list[Hallazgo]:
    umbral = a.lex["umbrales"]["oracion_larga"]
    found = []
    for tramo, ini, fin in a.sentences:
        count = a.word_count(ini, fin)
        if count > umbral:
            found.append(a.make("oracion_larga", ini, fin, count, umbral, "regla.oracion_larga.exp",
                                _split_proposal(a.text[ini:fin]), tramo))
    return found


def _prosa_uniforme(a: _Analysis) -> list[Hallazgo]:
    u = a.lex["umbrales"]
    lengths = [a.word_count(s, e) for _, s, e in a.sentences]
    if len(lengths) < u["prosa_uniforme_min_oraciones"]:
        return []
    mean = statistics.fmean(lengths)
    sigma = round(statistics.pstdev(lengths), 2)
    if not (u["prosa_uniforme_media_min"] <= mean <= u["prosa_uniforme_media_max"]) or sigma >= u["prosa_uniforme_sigma"]:
        return []
    tramo, ini, fin = a.sentences[0]
    return [a.make("prosa_uniforme", ini, fin, sigma, u["prosa_uniforme_sigma"], "regla.prosa_uniforme.exp", None,
                   tramo, lower_is_worse=True, oraciones=len(lengths), media=round(mean, 1))]


_PARTICIPLE = re.compile(r"(?:ado|ada|ados|adas|ido|ida|idos|idas)$")
_PASSIVE_ACTIVE = re.compile(r"^(?P<suj>.+?) (?P<aux>fue|fueron) (?P<part>[^\W\d_]+?(?P<suf>ado|ada|ados|adas|ido|ida|idos|idas)) "
                             r"por (?P<ag>[^,;:]+?)(?P<punct>[.!?…])$", re.IGNORECASE)
_DETERMINERS = ("el ", "la ", "los ", "las ", "un ", "una ", "unos ", "unas ", "este ", "esta ", "estos ", "estas ")


def _passive_info(a: _Analysis, ini: int, fin: int) -> tuple[bool, bool]:
    """(es pasiva, tiene agente explícito «por …»)."""
    tokens = [(m.group(), m.start()) for m in _WORD.finditer(a.folded, ini, fin)]
    for i, (token, _) in enumerate(tokens):
        if token not in a.lex["ser"]:
            continue
        j = i + 1
        if j < len(tokens) and tokens[j][0].endswith("mente"):
            j += 1
        if j < len(tokens) and (tokens[j][0] in a.lex["irregulares"] or
                                (len(tokens[j][0]) >= 5 and _PARTICIPLE.search(tokens[j][0]))):
            return True, any(t == "por" for t, _ in tokens[j + 1:])
    return False, False


def _active_proposal(sentence: str) -> str | None:
    """Solo para «sujeto fue/fueron participio regular por agente.»; en otro caso, None."""
    m = _PASSIVE_ACTIVE.match(sentence.strip())
    if not m:
        return None
    agent = m.group("ag").strip()
    plural = agent.lower().startswith(("los ", "las ", "unos ", "unas ")) or " y " in agent
    stem = m.group("part")[:-len(m.group("suf"))]
    if m.group("suf").lower().startswith("a"):
        verb = stem + ("aron" if plural else "ó")
    else:
        verb = stem + ("ieron" if plural else "ió")
    subject = m.group("suj")
    if subject.lower().startswith(_DETERMINERS):
        subject = subject[0].lower() + subject[1:]
    return f"{_capitalize(agent)} {verb} {subject}{m.group('punct')}"


def _pasiva(a: _Analysis) -> list[Hallazgo]:
    umbral = a.lex["umbrales"]["pasiva_porcentaje"]
    passives = [(t, s, e, agent) for t, s, e in a.sentences for is_passive, agent in [_passive_info(a, s, e)] if is_passive]
    if not a.sentences or not passives:
        return []
    percentage = round(len(passives) * 100 / len(a.sentences), 1)
    if percentage < umbral:
        return []
    found = []
    for tramo, ini, fin, agent in passives:
        context = dict(pasivas=len(passives), oraciones=len(a.sentences))
        if agent:
            found.append(a.make("pasiva", ini, fin, percentage, umbral, "regla.pasiva.exp",
                                _active_proposal(a.text[ini:fin]), tramo, **context))
        else:  # sin agente la pasiva es legítima en APA: solo se informa
            found.append(a.make("pasiva", ini, fin, percentage, umbral, "regla.pasiva.exp_legitima", None, tramo,
                                level="info", **context))
    return found


_NOMINAL = re.compile(r"(?<![^\W\d_])(?:la|el) ([^\W\d_]+(?:cion|miento)) de(?![^\W\d_])")


def _nominalizacion(a: _Analysis) -> list[Hallazgo]:
    umbral = a.lex["umbrales"]["nominalizacion"]
    found = []
    for tramo in a.tramos:
        for m in _NOMINAL.finditer(a.folded, tramo.ini, tramo.fin):
            if a.review.in_quote(m.start(), m.end()):
                continue
            noun_folded, noun = m.group(1), a.text[m.start(1):m.end(1)]
            verb = None  # solo derivaciones regulares: -ación → -ar, -amiento → -ar
            for suffix in ("acion", "amiento"):
                if noun_folded.endswith(suffix) and len(noun_folded) > len(suffix) + 2:
                    verb = noun[:-len(suffix)] + "ar"
            if verb and a.text[m.start()].isupper():
                verb = _capitalize(verb)
            found.append(a.make("nominalizacion", m.start(), m.end(), 1, umbral, "regla.nominalizacion.exp", verb, tramo))
    return found


_RULES = (_muletillas, _pleonasmos, lambda a: _density_rule(a, "adjetivo_vacio", a.lex["vacio"], False),
          lambda a: _density_rule(a, "intensificador", a.lex["intensificadores"], True),
          _repeticion, _oracion_larga, _prosa_uniforme, _pasiva, _nominalizacion)


def detect_language(review: ReviewText) -> str:
    """'es', 'en' o 'indeterminado', contando palabras funcionales de cada idioma en la prosa analizable."""
    lex = lexicon()["idioma"]
    words = [fold(m.group()) for t in review.analyzable() for m in _WORD.finditer(review.text, t.ini, t.fin)]
    spanish = sum(w in lex["es"] for w in words)
    english = sum(w in lex["en"] for w in words)
    if spanish + english < 5:
        return "indeterminado"
    return "es" if spanish >= english else "en"


def analyze(review: ReviewText) -> list[Hallazgo]:
    """Hallazgos de estilo del documento, ordenados por posición. Sin puntuaciones ni agregados."""
    analysis = _Analysis(review)
    found = [h for rule in _RULES for h in rule(analysis)]
    return sorted(found, key=lambda h: (h.ini, h.fin, h.ruleId))
