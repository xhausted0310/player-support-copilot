from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from copilot.api.deps import get_page_source_factory, get_session_factory, get_sources
from copilot.api.main import create_app
from copilot.config import Settings, get_settings
from copilot.db.session import get_session
from tests.conftest import SOURCES, FakeWiki, article

pytestmark = pytest.mark.integration


@pytest.fixture
def client(
    session_factory: sessionmaker[Session], wiki: FakeWiki, settings: Settings
) -> Iterator[TestClient]:
    app = create_app()

    def _session() -> Iterator[Session]:
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_sources] = lambda: SOURCES
    app.dependency_overrides[get_page_source_factory] = lambda: lambda: wiki
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as c:
        yield c


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok"}


def test_ingest_runs_in_background_and_reports_stats(client: TestClient, wiki: FakeWiki) -> None:
    wiki.put(1, "Ash", article("Ash"), category="operator")
    wiki.put(2, "P/Patch 2.0", article("Patch"), category="patch")

    r = client.post("/ingest", json={"categories": ["operator"], "limit_per_source": 5})
    assert r.status_code == 202
    run_id = r.json()["id"]
    assert r.json()["params"]["categories"] == ["operator"]

    # TestClient runs background tasks before returning the response
    r = client.get(f"/ingest/runs/{run_id}")
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["stats"]["total"] == {"seen": 1, "new": 1}
    assert body["finished_at"] is not None


def test_ingest_rejects_unknown_category(client: TestClient) -> None:
    r = client.post("/ingest", json={"categories": ["skins"]})
    assert r.status_code == 422
    assert "skins" in r.json()["detail"]


def test_ingest_validates_limit(client: TestClient) -> None:
    assert client.post("/ingest", json={"limit_per_source": 0}).status_code == 422


def test_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/ingest/runs/999").status_code == 404
