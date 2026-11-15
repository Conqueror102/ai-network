"""Output guardrails (06 §8): groundedness, PII leak, length."""

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+?\d[\s-]?){9,15}")
_HANDLE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{2,}")
_URL = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:com|ng|io|co|me|ly)\b", re.I)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]*|\d[\d,.]*")


def contains_contact_details(text: str) -> bool:
    return bool(
        _EMAIL.search(text) or _PHONE.search(text) or _HANDLE.search(text) or _URL.search(text)
    )


def _norm(word: str) -> str:
    return word.lower().strip(".,-").rstrip("s")


def ungrounded_terms(output: str, source: str) -> list[str]:
    """Named facts in `output` that do not appear in `source`.

    A named fact is a number or a capitalised word that is not the first word of a
    sentence. Everything else is treated as connective prose.
    """
    source_words = {_norm(w) for w in _WORD.findall(source)}
    bad: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", output):
        for i, word in enumerate(_WORD.findall(sentence)):
            is_number = word[0].isdigit()
            is_name = (
                word[0].isupper()
                and i > 0
                and word not in ("I", "You", "She", "He", "They", "Your", "Their")
            )
            if (is_number or is_name) and _norm(word) not in source_words:
                bad.append(word.rstrip(".,-"))
    return bad


def clamp(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
