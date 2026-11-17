from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from copilot.db.session import get_session

router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: str
    database: str


@router.get("/health")
def health(response: Response, session: Annotated[Session, Depends(get_session)]) -> HealthOut:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthOut(status="degraded", database="unavailable")
    return HealthOut(status="ok", database="ok")
