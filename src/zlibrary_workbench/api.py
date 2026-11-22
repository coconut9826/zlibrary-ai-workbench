import uuid
from pathlib import Path

from .api_models import (
    AudioCreateRequest,
    ConvertRequest,
    DownloadRequest,
    SearchRequest,
    SettingsRequest,
    SummarizeRequest,
    ZLibraryLoginRequest,
)
from .config import AppConfig, default_config_path, save_config
from .service import WorkbenchService
from .zlibrary import ZLibraryCommandError


def create_app(config: AppConfig, *, config_path: Path | None = None):
    try:
        from fastapi import FastAPI, File, HTTPException, Query, UploadFile
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as error:
        raise RuntimeError("REST API requires the 'server' extra") from error

    service = WorkbenchService(config)
    settings_path = config_path or default_config_path()
    app = FastAPI(
        title="Z-Library AI Workbench",
        version="0.3.0.dev0",
        description="Loopback-only local ebook workbench API",
    )

    @app.get("/health")
    def health():
        return service.initialize()

    @app.get("/v1/settings")
    def settings():
        return {"ok": True, "config": config.to_dict(), "path": str(settings_path)}

    @app.put("/v1/settings")
    def update_settings(request: SettingsRequest):
        config.paths.library_root = Path(request.library_root).expanduser()
        config.paths.downloads = request.downloads
        config.paths.converted = request.converted
        config.paths.audiobooks = request.audiobooks
        config.paths.reports = request.reports
        config.naming.template = request.naming_template
        config.naming.collision = request.collision
        config.ollama.model = request.ollama_model
        config.audiosmith.voice = request.audiosmith_voice
        config.audiosmith.model = request.audiosmith_model
        config.ensure_directories()
        saved = save_config(config, settings_path)
        return {"ok": True, "config": config.to_dict(), "path": str(saved)}

    @app.post("/v1/files/upload")
    async def upload_file(file: UploadFile = File(...)):
        filename = Path(file.filename or "upload.bin").name
        inbox = service.library.root / ".workbench/inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        target = inbox / f"{uuid.uuid4().hex}-{filename}"
        size = 0
        try:
            with target.open("wb") as handle:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 512 * 1024 * 1024:
                        raise HTTPException(
                            status_code=413,
                            detail={
                                "code": "file_too_large",
                                "message": "Maximum upload is 512 MiB.",
                            },
                        )
                    handle.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return {"ok": True, "path": str(target), "filename": filename}

    @app.post("/v1/books/search")
    def search(request: SearchRequest):
        return service.search(
            request.query,
            page=request.page,
            limit=request.limit,
            language=request.language,
            extension=request.extension,
        )

    @app.get("/v1/zlibrary/status")
    def zlibrary_status(refresh: bool = False):
        return service.zlibrary_status(refresh=refresh)

    @app.post("/v1/zlibrary/login")
    def zlibrary_login(request: ZLibraryLoginRequest):
        try:
            result = service.zlibrary_login(
                email=request.email,
                password=request.password,
                account=request.account,
                remember_password=request.remember_password,
            )
        except (ValueError, ZLibraryCommandError) as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "login_failed", "message": str(error)},
            ) from error
        save_config(config, settings_path)
        return {"ok": True, "login": result, "account": request.account}

    @app.post("/v1/zlibrary/accounts/{account}/select")
    def zlibrary_select_account(account: str):
        try:
            result = service.zlibrary_select_account(account)
        except (ValueError, ZLibraryCommandError) as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "account_select_failed", "message": str(error)},
            ) from error
        save_config(config, settings_path)
        return {"ok": True, "account": account, "selection": result}

    @app.post("/v1/zlibrary/doctor")
    def zlibrary_doctor():
        try:
            return service.zlibrary.doctor()
        except ZLibraryCommandError as error:
            raise HTTPException(
                status_code=503,
                detail={"code": "tor_check_failed", "message": str(error)},
            ) from error

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

    static = Path(__file__).with_name("static")
    app.mount("/assets", StaticFiles(directory=static), name="assets")

    @app.get("/", include_in_schema=False)
    def gui():
        return FileResponse(static / "index.html")

    return app
