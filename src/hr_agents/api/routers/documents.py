"""Document upload endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status

from hr_agents.api.deps import require_api_key
from hr_agents.api.recruitment_schemas import DocumentUploadResponse
from hr_agents.services.recruiting import (
    DocumentService,
    DocumentTooLargeError,
    RecruitingError,
)

router = APIRouter(
    prefix="/v1/documents", tags=["documents"], dependencies=[Depends(require_api_key)]
)


def get_documents(request: Request) -> DocumentService:
    return request.app.state.recruiting.documents


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentUploadResponse,
    summary="Upload a source document (CV, portfolio, questionnaire)",
)
async def upload_document(
    documents: Annotated[DocumentService, Depends(get_documents)],
    file: Annotated[UploadFile, Form()],
    kind: Annotated[str, Form()] = "other",
    uploaded_by: Annotated[str, Form()] = "api",
) -> DocumentUploadResponse:
    content = await file.read()
    try:
        document = documents.upload(
            filename=file.filename,
            kind=kind,
            content=content,
            uploaded_by=uploaded_by,
        )
    except DocumentTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    except RecruitingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return DocumentUploadResponse(
        document_id=document.id,
        sha256=document.sha256,
        kind=document.kind,
        size_bytes=document.size_bytes,
    )
