from sqlalchemy.orm import Session, sessionmaker

from copilot.config import get_settings
from copilot.db.session import get_sessionmaker
from copilot.ingest.pipeline import PageSourceFactory
from copilot.ingest.sources.fandom import SIEGE_SOURCES, FandomClient, SourceSpec


def get_sources() -> tuple[SourceSpec, ...]:
    return SIEGE_SOURCES


def make_fandom_client() -> FandomClient:
    s = get_settings()
    return FandomClient(
        s.fandom_base_url,
        user_agent=s.user_agent,
        timeout_s=s.fandom_timeout_s,
        delay_s=s.fandom_request_delay_s,
    )


def get_page_source_factory() -> PageSourceFactory:
    """Overridden in tests to avoid hitting the real wiki."""
    return make_fandom_client


def get_session_factory() -> sessionmaker[Session]:
    """Used by background tasks, which outlive the request-scoped session."""
    return get_sessionmaker()
