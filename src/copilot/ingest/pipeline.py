"""fetch -> clean -> filter -> dedup -> upsert, incrementally.

A page is re-downloaded only when its wiki revision changed; a re-downloaded page is marked
`changed` only when its cleaned text hash changed. Stage 2 re-chunks documents whose
`content_hash` differs from the hash stored on their chunks.
"""

import logging
from collections import Counter
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from copilot.config import Settings
from copilot.db.models import DocStatus, Document, IngestRun, RunStatus, utcnow
from copilot.ingest.clean import extract_patch_version, html_to_markdown
from copilot.ingest.dedup import NearDuplicateIndex
from copilot.ingest.filters import apply_filters
from copilot.ingest.hashing import content_hash
from copilot.ingest.sources.fandom import LICENSE, PageRef, ParsedPage, SourceSpec

log = logging.getLogger(__name__)

SOURCE = "fandom"
_KEPT = (DocStatus.NEW, DocStatus.CHANGED, DocStatus.UNCHANGED)


class PageSource(Protocol):
    base_url: str

    def list_pages(self, spec: SourceSpec) -> Iterable[PageRef]: ...
    def parse_page(self, page_id: int) -> ParsedPage: ...
    def page_url(self, title: str) -> str: ...


class ClosablePageSource(PageSource, AbstractContextManager["ClosablePageSource"], Protocol): ...


PageSourceFactory = Callable[[], ClosablePageSource]


@dataclass
class IngestOptions:
    limit_per_source: int | None = None
    force: bool = False  # re-download even if the revision did not change


def _build_dedup_index(session: Session, settings: Settings) -> NearDuplicateIndex:
    index = NearDuplicateIndex(
        threshold=settings.dedup_threshold,
        num_perm=settings.dedup_num_perm,
        shingle_words=settings.dedup_shingle_words,
    )
    rows = session.execute(select(Document.id, Document.text_md).where(Document.status.in_(_KEPT)))
    for doc_id, text in rows:
        index.add(str(doc_id), text)
    return index


def _process_page(
    session: Session,
    client: PageSource,
    ref: PageRef,
    index: NearDuplicateIndex,
    settings: Settings,
    options: IngestOptions,
    now: datetime,
) -> DocStatus:
    doc = session.scalar(
        select(Document).where(Document.source == SOURCE, Document.external_id == str(ref.page_id))
    )
    if doc is not None and not options.force and doc.revision_id == ref.revision_id:
        return DocStatus.UNCHANGED  # nothing touched, not even downloaded

    page = client.parse_page(ref.page_id)
    text = html_to_markdown(page.html)
    digest = content_hash(text)

    if doc is not None and doc.content_hash == digest:
        doc.revision_id = page.revision_id
        doc.fetched_at = now
        doc.status = DocStatus.UNCHANGED if doc.status in _KEPT else doc.status
        return DocStatus.UNCHANGED

    is_new = doc is None
    if doc is None:
        doc = Document(source=SOURCE, external_id=str(ref.page_id))
        session.add(doc)

    doc.url = client.page_url(page.title)
    doc.title = page.title
    doc.category = ref.category
    doc.revision_id = page.revision_id
    doc.raw_html = page.html
    doc.text_md = text
    doc.content_hash = digest
    doc.char_len = len(text)
    doc.patch_version = extract_patch_version(page.title, text)
    doc.fetched_at = now
    doc.duplicate_of = None
    doc.filter_reason = None
    doc.meta = {
        "license": LICENSE,
        "attribution": f"{page.title} — {client.base_url} contributors",
        "wiki_categories": page.categories,
    }

    verdict = apply_filters(
        text, min_chars=settings.min_text_chars, allowed_languages=settings.allowed_languages
    )
    doc.lang = verdict.lang
    doc.status = DocStatus.NEW if is_new else DocStatus.CHANGED
    session.flush()  # assigns doc.id
    key = str(doc.id)

    if not verdict.keep:
        doc.status = DocStatus.FILTERED
        doc.filter_reason = verdict.reason
        return DocStatus.FILTERED

    if dup_key := index.find_duplicate(text, exclude=key):
        doc.status = DocStatus.DUPLICATE
        doc.duplicate_of = int(dup_key)
        return DocStatus.DUPLICATE

    index.add(key, text)
    return DocStatus(doc.status)


def run_ingest(
    session: Session,
    client: PageSource,
    sources: Iterable[SourceSpec],
    settings: Settings,
    options: IngestOptions | None = None,
    run: IngestRun | None = None,
) -> IngestRun:
    options = options or IngestOptions()
    if run is None:
        run = IngestRun(
            params={"limit_per_source": options.limit_per_source, "force": options.force}
        )
        session.add(run)
        session.commit()

    stats: Counter[str] = Counter()
    by_category: dict[str, Counter[str]] = {}
    try:
        index = _build_dedup_index(session, settings)
        for spec in sources:
            cat_stats = by_category.setdefault(spec.category, Counter())
            for i, ref in enumerate(client.list_pages(spec)):
                if options.limit_per_source is not None and i >= options.limit_per_source:
                    break
                stats["seen"] += 1
                try:
                    status = _process_page(session, client, ref, index, settings, options, utcnow())
                    session.commit()
                except Exception:
                    session.rollback()
                    log.exception("failed to ingest page %s (%s)", ref.page_id, ref.title)
                    status_key = "errors"
                else:
                    status_key = status.value
                stats[status_key] += 1
                cat_stats[status_key] += 1
            log.info("source %s: %s", spec.category, dict(cat_stats))
        run.status = RunStatus.SUCCEEDED
    except Exception as exc:
        session.rollback()
        run.status = RunStatus.FAILED
        run.error = repr(exc)
        log.exception("ingest run failed")
    finally:
        run.stats = {
            "total": dict(stats),
            "by_category": {k: dict(v) for k, v in by_category.items()},
        }
        run.finished_at = utcnow()
        session.add(run)
        session.commit()
    return run
