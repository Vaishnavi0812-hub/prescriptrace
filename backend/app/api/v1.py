"""/api/v1 routes. Thin: validation and serialisation only; logic lives in core/services."""

from __future__ import annotations

import gzip
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.limiter import limiter
from app.config import get_settings
from app.core.normalise import Normaliser
from app.core.ocr import ImageError, scan
from app.core.ocr.vision_llm import VisionUnavailableError
from app.db import get_session
from app.models import Dataset, IngestRun
from app.schemas import api
from app.services.check_service import ABSENCE_NOTE, DISCLAIMER, SelectionError, run_check
from app.services.ocr_service import OcrUnavailableError, get_engine
from app.services.offline_service import get_pack
from app.services.state import get_state

router = APIRouter(prefix="/api/v1")
settings = get_settings()
SessionDep = Annotated[Session, Depends(get_session)]


def get_normaliser() -> Normaliser:
    """Called inside handlers (not as a dependency) so that invalid input is always reported as
    422, even before the data has been loaded (FastAPI resolves dependencies before it reports
    body validation errors)."""
    state = get_state()
    if state.normaliser is None:
        raise HTTPException(503, "Drug data is not loaded yet. Run the data ingestion first.")
    return state.normaliser


@router.get("/drugs/search", response_model=api.SearchResponse, tags=["drugs"])
@limiter.limit(lambda: settings.rate_limit_search)
def search_drugs(
    request: Request,
    q: Annotated[str, Query(min_length=1, max_length=60)],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> api.SearchResponse:
    """Autocomplete: brand and generic names, typo-tolerant."""
    hits = [api.SearchHit.model_validate(c) for c in get_normaliser().suggest(q, limit)]
    return api.SearchResponse(query=q, hits=hits)


@router.post("/normalise", response_model=api.NormaliseResponse, tags=["drugs"])
@limiter.limit(lambda: settings.rate_limit_normalise)
def normalise_lines(request: Request, body: api.NormaliseRequest) -> api.NormaliseResponse:
    """Resolve typed or OCR'd lines to ingredients, with a confidence and candidates."""
    normaliser = get_normaliser()
    results = [api.NormalisedLine.model_validate(normaliser.normalise(x)) for x in body.lines]
    return api.NormaliseResponse(results=results)


@router.post("/check", response_model=api.CheckResponse, tags=["check"])
@limiter.limit(lambda: settings.rate_limit_check)
def check_medicines(
    request: Request, body: api.CheckRequest, session: SessionDep
) -> api.CheckResponse:
    """One prioritised safety summary: interactions, duplicates, rules, context, recalls."""
    normaliser = get_normaliser()
    try:
        out = run_check(session, normaliser, body)
    except SelectionError as exc:
        raise HTTPException(422, str(exc)) from exc
    names = normaliser.vocab.ingredient_names
    result, recalls = out.result, out.recalls
    versions = _dataset_versions(session)
    return api.CheckResponse(
        summary=api.Summary.model_validate(out.summary),
        medicines=[
            api.CheckedMedicine(
                id=r.item.id,
                text=r.item.text,
                label=r.label,
                ingredients=[
                    api.Ingredient(rxcui=rx, name=names.get(rx, rx)) for rx in r.ingredients
                ],
                how=r.how,
                confidence=r.confidence,
                batch=r.item.batch,
            )
            for r in out.medicines
        ],
        unresolved=[
            api.UnresolvedMedicine(
                id=item.id,
                text=item.text,
                status=line.status,
                candidates=[api.Candidate.model_validate(c) for c in line.candidates],
            )
            for item, line in out.unresolved
        ],
        findings=[api.Finding.model_validate(f) for f in (result.findings if result else ())],
        notes=[api.CheckNote.model_validate(n) for n in (result.notes if result else ())],
        recalls=(
            api.Recalls.model_validate(recalls)
            if recalls
            else api.Recalls(flags=[], ingredient_summaries=[], checklist=[], coverage_notes=[])
        ),
        no_known_issue_pairs=[list(p) for p in (result.no_known_issue_pairs if result else ())],
        disclaimer=DISCLAIMER,
        absence_note=ABSENCE_NOTE,
        data_versions=versions,
    )


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


@router.post("/ocr", response_model=api.ScanResponse, tags=["ocr"])
@limiter.limit(lambda: settings.rate_limit_ocr)
def scan_prescription(
    request: Request, file: Annotated[UploadFile, File(description="Photo of a prescription")]
) -> api.ScanResponse:
    """Read a prescription photo. Lines are suggestions only: nothing is added automatically.

    The image is processed in memory and never stored or logged.
    """
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(415, "Please upload a JPEG, PNG or WebP photo.")
    data = file.file.read(settings.ocr_max_bytes + 1)
    if len(data) > settings.ocr_max_bytes:
        raise HTTPException(413, "The photo is too large (maximum 8 MB).")
    normaliser = get_normaliser()
    try:
        engine = get_engine()
        result = scan(data, engine, normaliser)
    except ImageError as exc:
        raise HTTPException(422, "This file could not be read as an image.") from exc
    except (OcrUnavailableError, VisionUnavailableError) as exc:
        raise HTTPException(503, f"Prescription reading is unavailable: {exc}") from exc
    finally:
        del data  # do not keep the image around longer than needed
    return api.ScanResponse.model_validate(result)


@router.get("/offline-pack/meta", response_model=api.OfflinePackMeta, tags=["offline"])
def offline_pack_meta() -> api.OfflinePackMeta:
    """Version and size of the offline pack, so the app can tell whether its copy is current."""
    pack = get_pack(get_normaliser().vocab)
    return api.OfflinePackMeta(
        version=pack.version,
        generated_at=pack.generated_at,
        download_bytes=len(pack.gzipped),
        raw_bytes=pack.raw_size,
    )


@router.get("/offline-pack", tags=["offline"], response_class=Response)
@limiter.limit(lambda: settings.rate_limit_offline_pack)
def offline_pack(request: Request) -> Response:
    """Data for offline typed checks: names, serious/moderate pairs with their source records,
    rule groups and wording. No recalls, label quotes or patient-context data (ADR-018)."""
    pack = get_pack(get_normaliser().vocab)
    headers = {"ETag": f'"{pack.version}"', "Cache-Control": "no-cache"}
    if request.headers.get("if-none-match") == headers["ETag"]:
        return Response(status_code=304, headers=headers)
    if "gzip" in request.headers.get("accept-encoding", ""):
        headers["Content-Encoding"] = "gzip"
        return Response(pack.gzipped, media_type="application/json", headers=headers)
    return Response(gzip.decompress(pack.gzipped), media_type="application/json", headers=headers)


@router.get("/datasets", response_model=api.DatasetsResponse, tags=["meta"])
def datasets(session: SessionDep) -> api.DatasetsResponse:
    """Every dataset: version, download date, record count, licence, known limitations."""
    out = []
    for d in session.scalars(select(Dataset).order_by(Dataset.id)):
        last = session.scalars(
            select(IngestRun).where(IngestRun.dataset_id == d.id).order_by(IngestRun.id.desc())
        ).first()
        out.append(
            api.DatasetInfo(
                code=d.code,
                name=d.name,
                version=d.version,
                source_url=d.source_url,
                licence=d.licence,
                licence_url=d.licence_url,
                region=d.region,
                downloaded_at=d.downloaded_at,
                record_count=d.record_count,
                limitations=d.limitations,
                last_ingest_status=last.status if last else None,
                last_ingest_at=last.finished_at if last else None,
            )
        )
    return api.DatasetsResponse(
        datasets=out,
        non_commercial_notice=(
            "Interaction data from DDInter 2.0 is licensed CC BY-NC-SA 4.0: non-commercial use "
            "only, and derived data must be shared under the same licence."
        ),
    )


def _dataset_versions(session: Session) -> list[api.DatasetVersion]:
    return [
        api.DatasetVersion(code=d.code, name=d.name, version=d.version, licence=d.licence)
        for d in session.scalars(select(Dataset).order_by(Dataset.id))
    ]
