import httpx
import pytest
import respx

from copilot.ingest.sources.fandom import FandomClient, SourceSpec
from tests.conftest import load_parse_fixture

BASE = "https://wiki.test"


def make_client(mock: respx.MockRouter) -> FandomClient:
    return FandomClient(
        BASE, user_agent="test-agent", delay_s=0, transport=httpx.MockTransport(mock.handler)
    )


@pytest.fixture
def mock() -> respx.MockRouter:
    return respx.MockRouter(base_url=BASE, assert_all_called=False)


def test_list_pages_follows_continuation_and_skips_redirects(mock: respx.MockRouter) -> None:
    route = mock.get("/api.php")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "continue": {"gcmcontinue": "page|2", "continue": "gcmcontinue||"},
                "query": {
                    "pages": [
                        {"pageid": 2, "title": "B", "lastrevid": 20},
                        {"pageid": 1, "title": "A", "lastrevid": 10},
                        {"pageid": 3, "title": "R", "lastrevid": 30, "redirect": True},
                    ]
                },
            },
        ),
        httpx.Response(
            200, json={"query": {"pages": [{"pageid": 4, "title": "C", "lastrevid": 40}]}}
        ),
    ]
    with make_client(mock) as client:
        refs = list(client.list_pages(SourceSpec("operator", wiki_category="Ops")))

    assert [(r.page_id, r.title, r.revision_id, r.category) for r in refs] == [
        (1, "A", 10, "operator"),
        (2, "B", 20, "operator"),
        (4, "C", 40, "operator"),
    ]
    first, second = (c.request.url.params for c in route.calls)
    assert first["gcmtitle"] == "Category:Ops" and first["formatversion"] == "2"
    assert second["gcmcontinue"] == "page|2"
    assert route.calls[0].request.headers["User-Agent"] == "test-agent"


def test_list_pages_by_prefix(mock: respx.MockRouter) -> None:
    route = mock.get("/api.php").respond(200, json={"query": {"pages": []}})
    with make_client(mock) as client:
        assert list(client.list_pages(SourceSpec("patch", title_prefix="Siege patches/"))) == []
    params = route.calls[0].request.url.params
    assert params["generator"] == "allpages" and params["gapprefix"] == "Siege patches/"


def test_list_pages_requires_category_or_prefix(mock: respx.MockRouter) -> None:
    with make_client(mock) as client, pytest.raises(ValueError):
        list(client.list_pages(SourceSpec("x")))


def test_parse_page_real_fixture(mock: respx.MockRouter) -> None:
    mock.get("/api.php").respond(200, json=load_parse_fixture("parse_patch_5_1_0"))
    with make_client(mock) as client:
        page = client.parse_page(116398)
    assert page.title == "Rainbow Six Siege patches/Patch 5.1.0"
    assert page.revision_id > 0 and "<h2" in page.html
    assert page.categories


def test_retries_server_errors_then_succeeds(
    mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("time.sleep", lambda _s: None)  # tenacity backoff
    route = mock.get("/api.php")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(429),
        httpx.Response(
            200, json={"parse": {"pageid": 1, "title": "A", "revid": 5, "text": "<p>x</p>"}}
        ),
    ]
    with make_client(mock) as client:
        assert client.parse_page(1).revision_id == 5
    assert route.call_count == 3


def test_does_not_retry_client_errors(mock: respx.MockRouter) -> None:
    route = mock.get("/api.php").respond(404)
    with make_client(mock) as client, pytest.raises(httpx.HTTPStatusError):
        client.parse_page(1)
    assert route.call_count == 1


def test_api_error_payload_raises(mock: respx.MockRouter) -> None:
    mock.get("/api.php").respond(200, json={"error": {"code": "missingtitle"}})
    with make_client(mock) as client, pytest.raises(RuntimeError, match="missingtitle"):
        client.parse_page(1)


def test_page_url() -> None:
    client = FandomClient(BASE, user_agent="t")
    assert client.page_url("Ash (Siege)") == "https://wiki.test/wiki/Ash_%28Siege%29"
    client.close()
