"""MediaWiki (Fandom) HTML -> clean Markdown.

Headings are kept as Markdown `#` lines: stage 2 chunks documents by structure.
"""

import re

from bs4 import BeautifulSoup
from markdownify import markdownify

# Page chrome and non-content blocks that would only add noise to retrieval.
_DROP_SELECTORS = [
    "script",
    "style",
    "noscript",
    "figure",
    ".toc",
    "#toc",
    ".mw-editsection",
    ".navbox",
    ".wikia-gallery",
    ".gallery",
    ".thumb",
    ".reference",
    ".references",
    ".reflist",
    ".mw-references-wrap",
    ".portable-infobox",
    ".noprint",
    ".mw-empty-elt",
    ".redirectMsg",
    "sup.cite-bracket",
]

_PATCH_RE = re.compile(r"\bPatch\s+(\d+(?:\.\d+){1,3})\b", re.IGNORECASE)
_SEASON_RE = re.compile(r"\b(Y\d{1,2}S\d(?:\.\d+)*)\b")
_HATNOTE_RE = re.compile(
    r"^(For (similarly named pages|other uses|the .{1,60} version)|This article is about)",
    re.IGNORECASE,
)
_HATNOTE_MAX_CHARS = 200
_CONTENT_BLOCKS = ["p", "blockquote", "table", "ul", "ol", "h1", "h2", "h3", "h4"]
# "← Patch 5.1 • • • List of Patches • • • Patch 5.3 →" navigation bars
_NAV_LINE_RE = re.compile(r"^\s*←.*→\s*$", re.MULTILINE)
_QUOTE_MARKS = " “”\"'«»"
_MANY_NEWLINES = re.compile(r"\n{3,}")
_TRAILING_WS = re.compile(r"[ \t]+\n")


def _flatten_quote_tables(soup: BeautifulSoup) -> None:
    """Fandom renders quotes as a 3-cell layout table (“ | text | ”): keep only the text."""
    for bq in soup.find_all("blockquote"):
        if bq.find("table") is None:
            continue
        cells = [td.get_text(" ", strip=True) for td in bq.find_all("td")]
        text = " ".join(c for c in cells if c.strip(_QUOTE_MARKS))
        bq.clear()
        p = soup.new_tag("p")
        p.string = text
        bq.append(p)


def _drop_hatnotes(soup: BeautifulSoup) -> None:
    """'For similarly named pages, see X (Disambig).' and similar navigation notes."""
    for node in soup.find_all(["small", "center", "div"]):
        if node.parent is None:  # already removed together with an ancestor
            continue
        text = node.get_text(" ", strip=True)
        # a wrapper whose text merely *starts* with a hatnote holds content: never drop it
        has_content = node.find(_CONTENT_BLOCKS) is not None
        if not has_content and len(text) <= _HATNOTE_MAX_CHARS and _HATNOTE_RE.match(text):
            node.decompose()


def html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for selector in _DROP_SELECTORS:
        for node in soup.select(selector):
            node.decompose()
    for img in soup.find_all(["img", "svg"]):
        img.decompose()
    _drop_hatnotes(soup)
    _flatten_quote_tables(soup)

    md = markdownify(str(soup), heading_style="ATX", strip=["a"], bullets="-")
    md = _NAV_LINE_RE.sub("", md)
    md = _TRAILING_WS.sub("\n", md)
    md = _MANY_NEWLINES.sub("\n\n", md)
    return md.strip()


def extract_patch_version(title: str, text: str = "") -> str | None:
    """`Rainbow Six Siege patches/Patch 5.1.0` -> `5.1.0`; `Y9S3.2` season codes as fallback."""
    if m := _PATCH_RE.search(title):
        return m.group(1)
    if m := _SEASON_RE.search(title) or _SEASON_RE.search(text[:500]):
        return m.group(1)
    return None
