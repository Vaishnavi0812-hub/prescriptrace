"""FastAPI application entry point."""

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.limiter import limiter
from app.api.v1 import router as v1_router
from app.config import get_settings
from app.db import get_session
from app.models import Dataset
from app.services.check_service import DISCLAIMER
from app.services.offline_service import get_pack
from app.services.state import get_state, load_state


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    state = load_state()  # vocabulary for normalisation; a no-op warning if data is not loaded yet
    if state.vocabulary is not None and get_settings().offline_pack_prebuild:
        # The offline pack takes ~10 s to build: do it now, in the background.
        threading.Thread(target=get_pack, args=(state.vocabulary,), daemon=True).start()
    yield


app = FastAPI(
    title="PrescripTrace API",
    version="0.1.0",
    description=DISCLAIMER,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
# Results carry evidence quotes (~70 KB); compression matters on slow mobile connections.
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.include_router(v1_router)


@app.get("/api/v1/health", tags=["meta"])
def health(session: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    """Liveness, database reachability, datasets loaded, and whether drug search is ready."""
    try:
        session.execute(text("SELECT 1"))
        datasets = session.scalar(select(func.count()).select_from(Dataset)) or 0
        db_ok = True
    except SQLAlchemyError:
        datasets, db_ok = 0, False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "datasets_loaded": datasets,
        "search_ready": get_state().ready,
    }
