"""Checks around the model: scope pre-filter and post-answer grounding checks.

Post-answer:
- citations: only ids that exist in this session; unknown ids are removed;
- prices: every currency amount must appear in a tool result (else the answer is replaced);
- role leak: a public answer may not contain any internal-only price (else replaced);
- other numbers that no tool returned are counted (metric), not blocked.
"""

import re
from dataclasses import dataclass, field

from agent.text import canon_number, fold, numbers

# Conservative pre-filter (accent-folded): only clearly clinical requests. Equipment specs such as
# "radiation dose" or "drug infusion pump" must pass; the system prompt covers the rest.
_CLINICAL = re.compile(
    r"\b((what|which|how much) (dose|dosage|medication|medicine|drug)s?\b|"
    r"(que|cual|cuanta) (dosis|medicamento|medicina)|"
    r"(should|can) (i|he|she|they|we) take|(debo|debe|puedo) tomar|"
    r"prescri\w*|recet(ar|ame|eme)\w*|symptoms?|sintomas?|"
    r"(medication|medicine|drug|medicamento|medicina|tratamiento|treatment) (for|para)|"
    r"diagnos\w* (me|my|mi)|am i sick|estoy enfermo)"
)
_CITE = re.compile(r"\[(S\d+(?:\s*,\s*S\d+)*)\]")
_CURRENCY = r"(?:USD|EUR|GBP|MXN|CAD|BRL|COP|CLP|ARS|PEN|US\$|\$|€|£)"
_PRICE = re.compile(rf"{_CURRENCY}\s?(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s?{_CURRENCY}(?![A-Za-z])")
_ES_HINT = re.compile(r"[áéíóúñ¿¡]|\b(el|la|los|las|que|para|tienen|precio|cita|equipo|hola)\b")

MESSAGES = {
    "clinical": {
        "en": "I can only help with medical equipment: finding devices, specs, availability, prices and "
        "appointments. For questions about medicines, doses, diagnosis or treatment, please ask a "
        "health professional.",
        "es": "Solo puedo ayudar con equipo médico: búsqueda de equipos, especificaciones, disponibilidad, "
        "precios y citas. Para preguntas sobre medicamentos, dosis, diagnóstico o tratamiento, "
        "consulta a un profesional de la salud.",
    },
    "price": {
        "en": "I could not verify that price in our documents. Our sales team can confirm it: I can book a "
        "sales call or hand you over to staff.",
        "es": "No pude verificar ese precio en nuestros documentos. El equipo de ventas puede confirmarlo: "
        "puedo agendar una llamada de ventas o pasarte con una persona del equipo.",
    },
    "empty": {
        "en": "I could not find an answer in our catalog. I can hand you over to staff.",
        "es": "No encontré una respuesta en nuestro catálogo. Puedo pasarte con una persona del equipo.",
    },
    "llm_unavailable": {
        "en": "The assistant is not available right now. Please try again in a few minutes or ask for a "
        "handoff to staff.",
        "es": "El asistente no está disponible en este momento. Intenta de nuevo en unos minutos o pide que "
        "te atienda una persona del equipo.",
    },
}


def lang_of(text: str) -> str:
    return "es" if _ES_HINT.search(fold(text)) or re.search(r"[áéíóúñ¿¡]", text.lower()) else "en"


def message(kind: str, lang: str) -> str:
    return MESSAGES[kind].get(lang, MESSAGES[kind]["en"])


def out_of_scope(text: str) -> str | None:
    return "clinical" if _CLINICAL.search(fold(text)) else None


@dataclass
class Checked:
    text: str
    citations: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    replaced: bool = False


def check_answer(
    text: str,
    *,
    known_sources: set[str],
    evidence: list[str],
    role: str,
    internal_prices: set[float],
    lang: str,
) -> Checked:
    out = Checked(text)
    evidence_numbers = {n for chunk in evidence for n in numbers(chunk)}

    # citations
    def keep(match: re.Match) -> str:
        ids = [i.strip() for i in match.group(1).split(",")]
        good = [i for i in ids if i in known_sources]
        if len(good) < len(ids):
            out.violations.append("unknown_citation")
        for i in good:
            if i not in out.citations:
                out.citations.append(i)
        return f"[{', '.join(good)}]" if good else ""

    out.text = _CITE.sub(keep, out.text)

    # role leak: internal prices never reach a public answer
    if role != "internal":
        leaked = {canon_number(f"{p:.2f}") for p in internal_prices} & set(numbers(out.text))
        if leaked:
            out.violations.append("price_leak")
            return _replace(out, "price", lang)

    # prices must be grounded
    for m in _PRICE.finditer(out.text):
        value = canon_number(m.group(1) or m.group(2))
        if value not in evidence_numbers:
            out.violations.append("unverified_price")
            return _replace(out, "price", lang)

    # other numbers: counted only
    body = _CITE.sub("", out.text)
    if any(n not in evidence_numbers and len(n.replace(".", "")) > 1 for n in numbers(body)):
        out.violations.append("unverified_number")
    return out


def _replace(out: Checked, kind: str, lang: str) -> Checked:
    out.text = message(kind, lang)
    out.citations = []
    out.replaced = True
    return out
