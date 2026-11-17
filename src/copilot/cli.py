import json
import logging
from typing import Annotated

import typer
from sqlalchemy import func, select

from copilot.api.deps import make_fandom_client
from copilot.config import get_settings
from copilot.db.models import Document
from copilot.db.session import get_sessionmaker
from copilot.ingest.pipeline import IngestOptions, run_ingest
from copilot.ingest.sources.fandom import SIEGE_SOURCES

app = typer.Typer(help="Player Support Copilot CLI", no_args_is_help=True)


@app.command()
def ingest(
    limit: Annotated[int | None, typer.Option(help="Max pages per source category")] = None,
    category: Annotated[
        list[str] | None, typer.Option("--category", "-c", help="Only these categories")
    ] = None,
    force: Annotated[bool, typer.Option(help="Re-download even if revision is unchanged")] = False,
) -> None:
    """Fetch Rainbow Six Siege wiki pages into PostgreSQL (incremental)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sources = [s for s in SIEGE_SOURCES if not category or s.category in category]
    if not sources:
        raise typer.BadParameter(f"known categories: {[s.category for s in SIEGE_SOURCES]}")
    with get_sessionmaker()() as session, make_fandom_client() as client:
        run = run_ingest(
            session,
            client,
            sources,
            get_settings(),
            IngestOptions(limit_per_source=limit, force=force),
        )
    typer.echo(json.dumps({"run_id": run.id, "status": run.status, **run.stats}, indent=2))
    if run.status != "succeeded":
        raise typer.Exit(1)


@app.command()
def stats() -> None:
    """Document counts by category and status."""
    with get_sessionmaker()() as session:
        rows = session.execute(
            select(Document.category, Document.status, func.count(), func.avg(Document.char_len))
            .group_by(Document.category, Document.status)
            .order_by(Document.category, Document.status)
        ).all()
    typer.echo(f"{'category':<10} {'status':<10} {'docs':>6} {'avg chars':>10}")
    for cat, status, n, avg in rows:
        typer.echo(f"{cat:<10} {status:<10} {n:>6} {int(avg or 0):>10}")


if __name__ == "__main__":
    app()
