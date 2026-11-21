from __future__ import annotations

from pathlib import Path

from .config import AppConfig
from .models import BookMetadata
from .service import WorkbenchService


def create_app(config: AppConfig):
    try:
        from fastapi import FastAPI, HTTPException, Query
        from pydantic import BaseModel, Field
    except ImportError as error:
        raise RuntimeError("REST API requires the 'server' extra") from error

    service = WorkbenchService(config)
    app = FastAPI(
        title="Z-Library AI Workbench",
        version="0.3.0.dev0",
        description="Loopback-only local ebook workbench API",
    )

    class SearchRequest(BaseModel):
        query: str = Field(min_length=1, max_length=500)
        page: int = Field(default=1, ge=1)
        limit: int = Field(default=10, ge=1, le=20)
        language: str = ""
        extension: str = ""

    class MetadataRequest(BaseModel):
        title: str = Field(min_length=1, max_length=500)
        author: str = ""
        year: str = ""
        language: str = ""
        format: str = ""
        publisher: str = ""
        isbn: str = ""
        id: str = ""

        def metadata(self) -> BookMetadata:
            return BookMetadata(**self.model_dump())

    class DownloadRequest(BaseModel):
        id: str
        hash: str
        metadata: MetadataRequest
        account: str = "auto"
        max_mb: int = Field(default=80, ge=1, le=512)
        confirmed: bool = False

    class ConvertRequest(BaseModel):
        path: str
        metadata: MetadataRequest
        mode: str = Field(default="auto", pattern="^(auto|reflow|visual)$")

    class SummarizeRequest(BaseModel):
        path: str
        title: str = ""
        author: str = ""

    class AudioCreateRequest(BaseModel):
        path: str
        metadata: MetadataRequest
        voice: str = ""
        model: str = ""

    @app.get("/health")
    def health():
        return service.initialize()

    @app.post("/v1/books/search")
    def search(request: SearchRequest):
        return service.search(
            request.query,
            page=request.page,
            limit=request.limit,
            language=request.language,
            extension=request.extension,
        )

    @app.post("/v1/books/download")
    def download(request: DownloadRequest):
        if not request.confirmed:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "confirmation_required",
                    "message": "Confirm the exact edition before spending download quota.",
                },
            )
        return service.download(
            book_id=request.id,
            book_hash=request.hash,
            metadata=request.metadata.metadata(),
            account=request.account,
            max_mb=request.max_mb,
        )

    @app.get("/v1/library")
    def library(query: str = "", limit: int = Query(default=100, ge=1, le=500)):
        return {"ok": True, "books": service.library.list_books(query, limit)}

    @app.get("/v1/jobs")
    def jobs(limit: int = Query(default=100, ge=1, le=500)):
        return {"ok": True, "jobs": service.library.list_jobs(limit=limit)}

    @app.get("/v1/jobs/{job_id}")
    def job(job_id: str):
        result = service.library.get_job(job_id)
        if result is None:
            raise HTTPException(status_code=404, detail={"code": "job_not_found"})
        return {"ok": True, "job": result}

    @app.post("/v1/convert/pdf-to-epub")
    def convert(request: ConvertRequest):
        return service.convert_pdf(
            Path(request.path), request.metadata.metadata(), mode=request.mode
        )

    @app.post("/v1/analysis/report")
    def summarize(request: SummarizeRequest):
        return service.summarize(
            Path(request.path), title=request.title, author=request.author
        )

    @app.get("/v1/audiosmith/health")
    async def audiosmith_health():
        return await service.audiosmith().health()

    @app.post("/v1/audiosmith/audiobooks")
    async def audiosmith_create(request: AudioCreateRequest):
        return await service.create_audiobook(
            Path(request.path),
            request.metadata.metadata(),
            voice=request.voice,
            model=request.model,
        )

    @app.post("/v1/audiosmith/audiobooks/{project_id}/render")
    async def audiosmith_render(project_id: str):
        return await service.render_audiobook(project_id)

    @app.get("/v1/audiosmith/jobs/{job_id}")
    async def audiosmith_job(job_id: str, wait: int = Query(default=0, ge=0, le=60)):
        return await service.audiobook_job(job_id, wait)

    @app.post("/v1/audiosmith/audiobooks/{project_id}/export")
    async def audiosmith_export(
        project_id: str, render_id: str = "", filename: str = ""
    ):
        return await service.export_audiobook(
            project_id, render_id=render_id, filename=filename
        )

    return app
