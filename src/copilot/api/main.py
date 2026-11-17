import logging

from fastapi import FastAPI

from copilot.api.routes import health, ingest


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    app = FastAPI(
        title="Player Support Copilot",
        version="0.1.0",
        description="AI support assistant for Rainbow Six Siege players (pet project).",
    )
    app.include_router(health.router)
    app.include_router(ingest.router)
    return app


app = create_app()
