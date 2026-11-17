from dataclasses import dataclass

from langdetect import DetectorFactory, LangDetectException, detect

DetectorFactory.seed = 0  # langdetect is randomized; make it deterministic


@dataclass(frozen=True)
class FilterResult:
    keep: bool
    lang: str | None
    reason: str | None = None


def detect_language(text: str) -> str | None:
    try:
        return str(detect(text[:5000]))
    except LangDetectException:
        return None


def apply_filters(text: str, *, min_chars: int, allowed_languages: tuple[str, ...]) -> FilterResult:
    if len(text) < min_chars:
        return FilterResult(keep=False, lang=None, reason="too_short")
    lang = detect_language(text)
    if lang not in allowed_languages:
        return FilterResult(keep=False, lang=lang, reason=f"lang:{lang}")
    return FilterResult(keep=True, lang=lang)
