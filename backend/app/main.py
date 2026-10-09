"""FastAPI application entry point."""

from typing import Annotated, Any

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import Dataset

DISCLAIMER = (
    "PrescripTrace is decision support, not a diagnostic or prescribing tool. "
    "Absence of a warning is not proof of safety. Consider confirming with the prescriber."
)

app = FastAPI(
    title="PrescripTrace API",
    version="0.1.0",
    description=DISCLAIMER,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/v1/health", tags=["meta"])
def health(session: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    """Liveness plus database reachability and how many datasets are loaded."""
    try:
        session.execute(text("SELECT 1"))
        datasets = session.scalar(select(func.count()).select_from(Dataset)) or 0
        db_ok = True
    except SQLAlchemyError:
        datasets, db_ok = 0, False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "datasets_loaded": datasets}
