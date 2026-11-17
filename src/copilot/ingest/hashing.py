import hashlib
import re
import unicodedata

_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Canonical form used for hashing: NFKC, lowercase, collapsed whitespace."""
    return _WS.sub(" ", unicodedata.normalize("NFKC", text)).strip().lower()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
