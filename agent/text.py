"""Small text helpers shared by retrieval, guardrails and ingest."""

import re
import unicodedata

_WORD = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*")
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def fold(text: str) -> str:
    """Lowercase and strip accents so 'Ultrasonido' and 'ultrasonido' match."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def tokens(text: str) -> list[str]:
    return _WORD.findall(fold(text))


_STOP = (
    "a al algo con como de del el en es esta este la las lo los mas me mi o para por que se sin su "
    "tiene tienen un una uno y yo ya quiero necesito busco hay "
    "a an and any are at be can do does for from have i in is it me my need of on or some the "
    "to want what which with you your"
)
STOPWORDS = frozenset(_STOP.split())


def terms(text: str) -> list[str]:
    """Tokens for lexical matching: stopwords removed."""
    return [t for t in tokens(text) if t not in STOPWORDS]


def numbers(text: str) -> list[str]:
    """Numbers in a canonical form: '12,500.00' -> '12500', '3.50' -> '3.5'."""
    return [canon_number(m) for m in _NUMBER.findall(text)]


def canon_number(raw: str) -> str:
    value = raw.replace(",", "")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value


def strip_pii(text: str) -> str:
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", text))


def is_email(value: str) -> bool:
    return bool(re.fullmatch(r"[\w.+-]+@[\w-]+\.[\w.-]+", value.strip()))


def is_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return 8 <= len(digits) <= 15 and bool(re.fullmatch(r"\+?[\d\s().-]+", value.strip()))
