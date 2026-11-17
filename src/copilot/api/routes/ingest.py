from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from copilot.api.deps import get_page_source_factory, get_session_factory, get_sources
from copilot.config import get_settings
from copilot.db.models import IngestRun
from copilot.db.session import get_session
from copilot.ingest.pipeline import IngestOptions, PageSourceFactory, run_ingest
from copilot.ingest.sources.fandom import SourceSpec

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestIn(BaseModel):
    limit_per_source: int | None = Field(default=None, ge=1)
    force: bool = False
    categories: list[str] | None = Field(
        default=None, description="Subset of source categories, e.g. ['patch', 'operator']"
    )


class IngestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    params: dict[str, Any]
    stats: dict[str, Any]
    error: str | None


def _run_in_background(
    run_id: int,
    sources: list[SourceSpec],
    options: IngestOptions,
    factory: PageSourceFactory,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session, factory() as client:
        run = session.get(IngestRun, run_id)
        run_ingest(session, client, sources, get_settings(), options, run=run)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def start_ingest(
    body: IngestIn,
    background: BackgroundTasks,
    session: Annotated[Session, Depends(get_session)],
    all_sources: Annotated[tuple[SourceSpec, ...], Depends(get_sources)],
    factory: Annotated[PageSourceFactory, Depends(get_page_source_factory)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> IngestRunOut:
    sources = list(all_sources)
    if body.categories is not None:
        known = {s.category for s in all_sources}
        if unknown := set(body.categories) - known:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"unknown categories: {sorted(unknown)}; known: {sorted(known)}",
            )
        sources = [s for s in all_sources if s.category in body.categories]

    run = IngestRun(params=body.model_dump())
    session.add(run)
    session.commit()
    options = IngestOptions(limit_per_source=body.limit_per_source, force=body.force)
    background.add_task(_run_in_background, run.id, sources, options, factory, session_factory)
    return IngestRunOut.model_validate(run)


@router.get("/runs/{run_id}")
def get_run(run_id: int, session: Annotated[Session, Depends(get_session)]) -> IngestRunOut:
    run = session.get(IngestRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    return IngestRunOut.model_validate(run)
