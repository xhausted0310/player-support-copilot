import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from copilot.config import Settings
from copilot.db.models import Document, IngestRun
from copilot.ingest.pipeline import IngestOptions, run_ingest
from tests.conftest import SOURCES, FakeWiki, article

pytestmark = pytest.mark.integration


def docs(db: Session) -> dict[str, Document]:
    db.expire_all()
    return {d.external_id: d for d in db.scalars(select(Document))}


def ingest(db: Session, wiki: FakeWiki, settings: Settings, **opts: object) -> IngestRun:
    return run_ingest(db, wiki, SOURCES, settings, IngestOptions(**opts))  # type: ignore[arg-type]


def test_first_run_stores_clean_documents(db: Session, wiki: FakeWiki, settings: Settings) -> None:
    wiki.put(1, "P/Patch 5.1.0", article("Patch notes for Thermite"), category="patch")
    wiki.put(2, "Ash (Siege)", article("Ash"), category="operator")

    run = ingest(db, wiki, settings)

    assert run.status == "succeeded"
    assert run.stats["total"] == {"seen": 2, "new": 2}
    assert run.stats["by_category"]["operator"] == {"new": 1}
    d = docs(db)
    assert d["1"].patch_version == "5.1.0" and d["1"].category == "patch"
    assert d["2"].status == "new" and d["2"].lang == "en"
    assert d["2"].text_md.startswith("## Overview of Ash")
    assert d["2"].url == "https://wiki.test/wiki/Ash (Siege)"
    assert d["2"].meta["license"] == "CC BY-SA 3.0"
    assert run.finished_at is not None


def test_second_run_is_incremental(db: Session, wiki: FakeWiki, settings: Settings) -> None:
    wiki.put(1, "Ash", article("Ash"), category="operator", revid=1)
    wiki.put(2, "Sledge", article("Sledge"), category="operator", revid=1)
    wiki.put(3, "Thatcher", article("Thatcher"), category="operator", revid=1)
    ingest(db, wiki, settings)
    wiki.parse_calls.clear()

    # page 2: new revision, same text (e.g. category edit) -> fetched but unchanged
    wiki.put(2, "Sledge", article("Sledge"), category="operator", revid=2)
    # page 3: new revision with new text -> changed
    wiki.put(3, "Thatcher", article("Thatcher", "Updated in Y9S3."), category="operator", revid=2)
    run = ingest(db, wiki, settings)

    assert wiki.parse_calls == [2, 3]  # page 1 was not downloaded at all
    assert run.stats["total"] == {"seen": 3, "unchanged": 2, "changed": 1}
    d = docs(db)
    assert d["2"].revision_id == 2 and d["2"].status == "unchanged"
    assert d["3"].status == "changed" and "Updated in Y9S3." in d["3"].text_md


def test_force_redownloads(db: Session, wiki: FakeWiki, settings: Settings) -> None:
    wiki.put(1, "Ash", article("Ash"), category="operator")
    ingest(db, wiki, settings)
    wiki.parse_calls.clear()
    run = ingest(db, wiki, settings, force=True)
    assert wiki.parse_calls == [1]
    assert run.stats["total"] == {"seen": 1, "unchanged": 1}


def test_filters_and_duplicates(db: Session, wiki: FakeWiki, settings: Settings) -> None:
    wiki.put(1, "Ash", article("Ash"), category="operator")
    wiki.put(2, "Ash copy", article("Ash", "Minor."), category="operator")
    wiki.put(3, "Stub", "<p>Stub page.</p>", category="operator")
    fr = "<p>" + "Thermite est un agent attaquant qui perce les murs renforcés. " * 5 + "</p>"
    wiki.put(4, "Thermite FR", fr, category="operator")

    run = ingest(db, wiki, settings)

    assert run.stats["total"] == {"seen": 4, "new": 1, "duplicate": 1, "filtered": 2}
    d = docs(db)
    assert d["2"].status == "duplicate" and d["2"].duplicate_of == d["1"].id
    assert d["3"].filter_reason == "too_short"
    assert d["4"].filter_reason == "lang:fr"


def test_changed_doc_is_not_duplicate_of_itself(
    db: Session, wiki: FakeWiki, settings: Settings
) -> None:
    wiki.put(1, "Ash", article("Ash"), category="operator", revid=1)
    ingest(db, wiki, settings)
    wiki.put(1, "Ash", article("Ash", "Small tweak."), category="operator", revid=2)
    run = ingest(db, wiki, settings)
    assert run.stats["total"] == {"seen": 1, "changed": 1}


def test_page_errors_are_counted_not_fatal(db: Session, wiki: FakeWiki, settings: Settings) -> None:
    wiki.put(1, "Ash", article("Ash"), category="operator")
    wiki.put(2, "Broken", article("Broken"), category="operator")
    wiki.fail_on.add(2)
    run = ingest(db, wiki, settings)
    assert run.status == "succeeded"
    assert run.stats["total"] == {"seen": 2, "new": 1, "errors": 1}


def test_limit_per_source(db: Session, wiki: FakeWiki, settings: Settings) -> None:
    for i in range(1, 4):
        wiki.put(i, f"Op {i}", article(f"Operator{i}"), category="operator")
    wiki.put(10, "P/Patch 1.1", article("Patch"), category="patch")
    run = ingest(db, wiki, settings, limit_per_source=2)
    assert run.stats["by_category"] == {"patch": {"new": 1}, "operator": {"new": 2}}


def test_listing_failure_marks_run_failed(db: Session, wiki: FakeWiki, settings: Settings) -> None:
    def broken(_spec: object) -> None:
        raise ConnectionError("wiki down")

    wiki.list_pages = broken  # type: ignore[assignment,method-assign]
    run = ingest(db, wiki, settings)
    assert run.status == "failed" and "wiki down" in (run.error or "")
