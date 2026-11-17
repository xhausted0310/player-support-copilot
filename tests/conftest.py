import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from copilot.config import Settings, get_settings
from copilot.db.models import Base
from copilot.ingest.sources.fandom import PageRef, ParsedPage, SourceSpec

FIXTURES = Path(__file__).parent / "fixtures"


def load_parse_fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, min_text_chars=50)


# ---------- PostgreSQL (integration) ----------


@pytest.fixture(scope="session")
def pg_engine() -> Iterator[Engine]:
    """Each test session gets its own throwaway schema in the configured database,
    so tests never touch real data and need no extra database to be created."""
    url = get_settings().database_url
    schema = f"test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(url)
    try:
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL not available: {exc.orig}")
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def session_factory(pg_engine: Engine) -> Iterator[sessionmaker[Session]]:
    yield sessionmaker(bind=pg_engine, expire_on_commit=False)
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE documents, ingest_runs RESTART IDENTITY CASCADE"))


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session


# ---------- fake wiki ----------


class FakeWiki:
    """In-memory PageSource: pages keyed by id, each with (title, revid, html, category)."""

    base_url = "https://wiki.test"

    def __init__(self) -> None:
        self.pages: dict[int, dict[str, Any]] = {}
        self.parse_calls: list[int] = []
        self.fail_on: set[int] = set()

    def put(self, page_id: int, title: str, html: str, *, category: str, revid: int = 1) -> None:
        self.pages[page_id] = {"title": title, "html": html, "category": category, "revid": revid}

    def list_pages(self, spec: SourceSpec) -> Iterator[PageRef]:
        for pid, p in sorted(self.pages.items()):
            if p["category"] == spec.category:
                yield PageRef(pid, p["title"], p["revid"], spec.category)

    def parse_page(self, page_id: int) -> ParsedPage:
        self.parse_calls.append(page_id)
        if page_id in self.fail_on:
            raise RuntimeError("boom")
        p = self.pages[page_id]
        return ParsedPage(page_id, p["title"], p["revid"], p["html"], ["Cat"])

    def page_url(self, title: str) -> str:
        return f"{self.base_url}/wiki/{title}"

    def __enter__(self) -> "FakeWiki":
        return self

    def __exit__(self, *_: object) -> None:
        pass


@pytest.fixture
def wiki() -> FakeWiki:
    return FakeWiki()


SOURCES = (SourceSpec("patch", title_prefix="P/"), SourceSpec("operator", wiki_category="Ops"))


def article(topic: str, extra: str = "") -> str:
    """A realistic English paragraph long enough to pass filters; `topic` makes it unique."""
    body = (
        f"{topic} is an attacking operator who uses breaching charges to open reinforced walls. "
        f"Players usually pick {topic} when the defenders reinforce many walls on the objective. "
        f"The charge can be destroyed by electronic gadgets, so teammates should clear them first. "
        f"In ranked matches {topic} often enters the round early and coordinates with the team "
        f"to open a line of sight onto the bomb site before the final push. {extra}"
    )
    return f"<h2>Overview of {topic}</h2><p>{body}</p>"
