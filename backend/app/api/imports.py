"""Import endpoints.

POST /api/imports/upload  — multipart file upload
POST /api/imports/url     — JSON body with a spec URL
POST /api/imports/curl    — JSON body with one or more curl commands
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_workspace_id, get_db
from app.schemas.api import ImportFromCurlIn, ImportFromUrlIn, SuiteDetailOut
from app.services import SpecImportError
from app.services.import_service import (
    import_from_curl,
    import_from_upload,
    import_from_url,
)

router = APIRouter()

# Guard against accidentally uploading very large files (service-level check
# is also 10 MB, but we short-circuit before even reading into memory).
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post(
    "/imports/upload",
    response_model=SuiteDetailOut,
    status_code=201,
    summary="Import a Swagger spec from an uploaded file",
)
async def import_from_upload_endpoint(
    file: UploadFile,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> SuiteDetailOut:
    """Accept a Swagger 2.0 / OpenAPI 3.x file (JSON or YAML) and create a suite.

    Returns the created suite with its endpoint list.
    """
    content = await file.read()

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large: {len(content):,} bytes "
                f"(limit {_MAX_UPLOAD_BYTES:,})"
            ),
        )

    try:
        suite = await import_from_upload(
            db=db,
            workspace_id=workspace_id,
            content=content,
            filename=file.filename or "spec.json",
        )
    except SpecImportError as exc:
        if "Workspace not found" in str(exc):
            raise HTTPException(status_code=400, detail="Workspace not found") from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return SuiteDetailOut.model_validate(suite)


@router.post(
    "/imports/curl",
    response_model=SuiteDetailOut,
    status_code=201,
    summary="Import one or more cURL commands",
)
async def import_from_curl_endpoint(
    payload: ImportFromCurlIn,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> SuiteDetailOut:
    """Parse one or more pasted ``curl`` commands and create a suite.

    Each ``curl`` command in the input becomes one endpoint. Returns the
    created suite with its endpoint list.
    """
    try:
        suite = await import_from_curl(
            db=db,
            workspace_id=workspace_id,
            curl_text=payload.curl_text,
            suite_name=payload.suite_name,
        )
    except SpecImportError as exc:
        if "Workspace not found" in str(exc):
            raise HTTPException(status_code=400, detail="Workspace not found") from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return SuiteDetailOut.model_validate(suite)


@router.post(
    "/imports/url",
    response_model=SuiteDetailOut,
    status_code=201,
    summary="Import a Swagger spec from a URL",
)
async def import_from_url_endpoint(
    payload: ImportFromUrlIn,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> SuiteDetailOut:
    """Fetch a Swagger 2.0 / OpenAPI 3.x spec from a URL and create a suite.

    The URL must return a valid JSON or YAML spec file (≤ 10 MB).
    Returns the created suite with its endpoint list.
    """
    try:
        suite = await import_from_url(
            db=db,
            workspace_id=workspace_id,
            url=str(payload.url),
        )
    except SpecImportError as exc:
        if "Workspace not found" in str(exc):
            raise HTTPException(status_code=400, detail="Workspace not found") from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return SuiteDetailOut.model_validate(suite)
