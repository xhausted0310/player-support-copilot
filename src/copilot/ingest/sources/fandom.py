"""Client for the Rainbow Six Fandom wiki (MediaWiki API). Content is CC BY-SA 3.0."""

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

LICENSE = "CC BY-SA 3.0"


@dataclass(frozen=True)
class SourceSpec:
    """Where to list pages from: a wiki category or a title prefix."""

    category: str  # our label, stored in documents.category
    wiki_category: str | None = None
    title_prefix: str | None = None


SIEGE_SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec("patch", title_prefix="Rainbow Six Siege patches/"),
    SourceSpec("operator", wiki_category="Characters of Tom Clancy's Rainbow Six Siege"),
    SourceSpec("map", wiki_category="Siege Maps"),
    SourceSpec("weapon", wiki_category="Weapons of Tom Clancy's Rainbow Six Siege"),
    SourceSpec("gadget", wiki_category="Gadgets of Tom Clancy's Rainbow Six Siege"),
    SourceSpec("playlist", wiki_category="Siege Playlists"),
    SourceSpec("guide", wiki_category="Siege Guides"),
)


@dataclass(frozen=True)
class PageRef:
    page_id: int
    title: str
    revision_id: int
    category: str


@dataclass(frozen=True)
class ParsedPage:
    page_id: int
    title: str
    revision_id: int
    html: str
    categories: list[str] = field(default_factory=list)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


class FandomClient:
    def __init__(
        self,
        base_url: str,
        *,
        user_agent: str,
        timeout_s: float = 30.0,
        delay_s: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._delay_s = delay_s
        self._last_request = 0.0
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"User-Agent": user_agent},
            timeout=timeout_s,
            transport=transport,
        )

    def __enter__(self) -> "FandomClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def page_url(self, title: str) -> str:
        return f"{self.base_url}/wiki/{quote(title.replace(' ', '_'))}"

    def _throttle(self) -> None:
        wait = self._delay_s - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        self._throttle()
        resp = self._http.get("/api.php", params={**params, "format": "json", "formatversion": 2})
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        if "error" in data:
            raise RuntimeError(f"MediaWiki API error: {data['error']}")
        return data

    def list_pages(self, spec: SourceSpec) -> Iterator[PageRef]:
        """All main-namespace pages of a source, with their latest revision id (one cheap call
        per 500 pages) — enough to skip unchanged pages without downloading their HTML."""
        params: dict[str, Any] = {"action": "query", "prop": "info"}
        if spec.wiki_category:
            params |= {
                "generator": "categorymembers",
                "gcmtitle": f"Category:{spec.wiki_category}",
                "gcmnamespace": 0,
                "gcmlimit": "max",
            }
        elif spec.title_prefix:
            params |= {
                "generator": "allpages",
                "gapprefix": spec.title_prefix,
                "gapnamespace": 0,
                "gaplimit": "max",
                "gapfilterredir": "nonredirects",
            }
        else:
            raise ValueError(f"SourceSpec {spec.category!r} has neither category nor prefix")

        cont: dict[str, Any] = {}
        while True:
            data = self._get(params | cont)
            pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p["pageid"])
            for p in pages:
                if p.get("redirect") or "missing" in p:
                    continue
                yield PageRef(p["pageid"], p["title"], p["lastrevid"], spec.category)
            if "continue" not in data:
                break
            cont = data["continue"]

    def parse_page(self, page_id: int) -> ParsedPage:
        data = self._get(
            {
                "action": "parse",
                "pageid": page_id,
                "prop": "text|revid|categories",
                "redirects": 1,
                "disableeditsection": 1,
                "disabletoc": 1,
            }
        )["parse"]
        return ParsedPage(
            page_id=data["pageid"],
            title=data["title"],
            revision_id=data["revid"],
            html=data["text"],
            categories=[c["category"] for c in data.get("categories", [])],
        )
