from copilot.ingest.filters import apply_filters, detect_language
from copilot.ingest.hashing import content_hash, normalize_text

EN = (
    "Thermite is an attacking operator. His exothermic charge breaches reinforced walls "
    "and hatches, which makes him one of the most picked operators in ranked matches."
)
FR = (
    "Thermite est un agent attaquant. Sa charge exothermique permet de percer les murs "
    "renforcés et les trappes, ce qui en fait l'un des agents les plus choisis en classé."
)


def test_normalize_collapses_whitespace_and_case() -> None:
    assert normalize_text("  Hello\n\n  WORLD\t!  ") == "hello world !"


def test_hash_ignores_formatting_noise() -> None:
    assert content_hash("Patch  Notes\n") == content_hash("patch notes")
    assert content_hash("patch notes") != content_hash("patch note")
    assert len(content_hash("x")) == 64


def test_detect_language() -> None:
    assert detect_language(EN) == "en"
    assert detect_language(FR) == "fr"
    assert detect_language("12345 !!!") is None


def test_filters_keep_english() -> None:
    r = apply_filters(EN, min_chars=50, allowed_languages=("en",))
    assert r.keep and r.lang == "en" and r.reason is None


def test_filters_reject_short() -> None:
    r = apply_filters("too short", min_chars=50, allowed_languages=("en",))
    assert not r.keep and r.reason == "too_short"


def test_filters_reject_other_language() -> None:
    r = apply_filters(FR, min_chars=50, allowed_languages=("en",))
    assert not r.keep and r.reason == "lang:fr"
