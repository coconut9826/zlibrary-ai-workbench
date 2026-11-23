from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .audiosmith import AudioSmithClient
from .config import AppConfig, load_config
from .conversion import convert_pdf_to_epub
from .keychain import delete_password, load_password, save_password
from .library import LibraryStore
from .models import BookMetadata
from .naming import render_name, resolve_collision
from .ollama import PROMPT_VERSION, OllamaClient
from .zlibrary import ZLibraryAdapter


class WorkbenchService:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or load_config()
        self.library = LibraryStore(self.config)
        self.zlibrary = ZLibraryAdapter()

    def initialize(self) -> dict:
        self.library.initialize()
        return {
            "ok": True,
            "library_root": str(self.library.root),
            "database": str(self.library.db_path),
        }

    def search(self, query: str, **filters: Any) -> dict:
        return self.zlibrary.search(query, **filters)

    def zlibrary_status(self, *, refresh: bool = False) -> dict:
        accounts = self.zlibrary.accounts(refresh=refresh)
        for item in accounts.get("accounts", []):
            if isinstance(item, dict) and item.get("name"):
                item["has_saved_password"] = bool(load_password(str(item["name"])))
        return {
            "ok": True,
            "accounts": accounts,
            "account": self.config.zlibrary.account,
            "email": self.config.zlibrary.email,
            "remember_password": self.config.zlibrary.remember_password,
            "has_saved_password": bool(load_password(self.config.zlibrary.account)),
        }

    def zlibrary_login(
        self,
        *,
        email: str,
        password: str = "",
        account: str = "default",
        remember_password: bool = False,
    ) -> dict:
        selected_password = password or load_password(account)
        if not selected_password:
            raise ValueError("password is required or must be saved in macOS Keychain")
        result = self.zlibrary.login(
            email=email, password=selected_password, account=account
        )
        if remember_password:
            save_password(account, selected_password)
        else:
            delete_password(account)
        self.config.zlibrary.account = account
        self.config.zlibrary.email = email
        self.config.zlibrary.remember_password = remember_password
        return result

    def zlibrary_select_account(self, account: str) -> dict:
        result = self.zlibrary.use_account(account)
        self.config.zlibrary.account = account
        self.config.zlibrary.email = ""
        self.config.zlibrary.remember_password = bool(load_password(account))
        return result

    def download(
        self,
        *,
        book_id: str,
        book_hash: str,
        metadata: BookMetadata,
        account: str = "auto",
        max_mb: int = 80,
    ) -> dict:
        self.initialize()
        job_id = f"download:{uuid.uuid4().hex}"
        self.library.record_job(
            job_id,
            kind="download",
            status="running",
            progress=0.1,
            payload={"id": book_id, "title": metadata.title, "account": account},
        )
        cache_dir = self.library.root / ".workbench/download-cache"
        try:
            result = self.zlibrary.download(
                book_id, book_hash, cache_dir, account=account, max_mb=max_mb
            )
            path_value = result.get("path")
            if not path_value:
                raise RuntimeError("download result did not contain a path")
            metadata.id = metadata.id or f"{book_id}:{book_hash}"
            metadata.source = "zlibrary"
            metadata.format = metadata.format or Path(path_value).suffix.lstrip(".")
            ingested = self.library.ingest_file(
                Path(path_value), metadata, kind="original"
            )
        except Exception as error:
            self.library.record_job(
                job_id, kind="download", status="failed", error=str(error)
            )
            raise
        tracked = self.library.record_job(
            job_id,
            kind="download",
            status="completed",
            progress=1,
            book_id=ingested["book_id"],
            result={"path": ingested["path"]},
        )
        return {**result, "library": ingested, "tracking": tracked}

    def ingest(
        self, path: Path, metadata: BookMetadata, *, kind: str = "original"
    ) -> dict:
        return self.library.ingest_file(path, metadata, kind=kind)

    def convert_pdf(
        self,
        path: Path,
        metadata: BookMetadata,
        *,
        mode: str = "auto",
    ) -> dict:
        self.initialize()
        metadata.format = "epub"
        filename = render_name(self.config.naming.template, metadata.to_dict(), ".epub")
        output = resolve_collision(
            self.config.paths.resolved("converted") / filename,
            self.config.naming.collision,
        )
        report_path = (
            self.library.root / ".workbench/conversion-reports" / f"{output.stem}.json"
        )
        report = convert_pdf_to_epub(
            path, output, metadata=metadata, mode=mode, report_path=report_path
        )
        library_entry = self.library.register_file(output, metadata, kind="converted")
        return {
            "ok": True,
            "conversion": report.to_dict(),
            "quality_report": str(report_path),
            "library": library_entry,
        }

    def summarize(self, path: Path, *, title: str = "", author: str = "") -> dict:
        self.initialize()
        client = OllamaClient(self.config.ollama)
        try:
            files = client.summarize_document(
                path,
                self.config.paths.resolved("reports"),
                title=title,
                author=author,
            )
        finally:
            client.close()
        result = json.loads(files.metadata.read_text(encoding="utf-8"))["result"]
        categories = result.get("categories", [])
        if not isinstance(categories, list):
            categories = []
        analysis = self.library.apply_analysis(
            path,
            categories=categories,
            reports=[
                ("summary", files.markdown),
                ("mindmap", files.mindmap),
                ("analysis_metadata", files.metadata),
            ],
            model=self.config.ollama.model,
            prompt_version=PROMPT_VERSION,
        )
        return {
            "ok": True,
            "markdown": str(files.markdown),
            "mindmap": str(files.mindmap),
            "metadata": str(files.metadata),
            "model": self.config.ollama.model,
            "library": analysis,
        }

    def audiosmith(self) -> AudioSmithClient:
        return AudioSmithClient(self.config.audiosmith)

    async def create_audiobook(
        self,
        path: Path,
        metadata: BookMetadata,
        *,
        voice: str = "",
        model: str = "",
    ) -> dict:
        """Create and configure an AudioSmith project without starting a render."""
        client = self.audiosmith()
        created = await client.create_audiobook(
            path, metadata, voice=voice, model=model
        )
        project_id = str(created.get("project_id", ""))
        if not project_id:
            raise RuntimeError("AudioSmith did not return an audiobook project_id")
        narrator = voice or self.config.audiosmith.voice
        cover = Path(metadata.cover_path) if metadata.cover_path else None
        prepared = await client.prepare_render(
            project_id, metadata, narrator=narrator, cover=cover
        )
        source_path = path.expanduser().resolve(strict=True)
        project_job = f"audiosmith-project:{project_id}"
        tracked = self.library.record_job(
            project_job,
            kind="audiobook_project",
            status="prepared",
            book_id=self.library.book_id_for_file(source_path),
            payload={"project_id": project_id, "source_path": str(source_path)},
            result={"create": created, "prepare": prepared},
        )
        return {
            **created,
            "project_id": project_id,
            "prepared": prepared,
            "tracking": tracked,
            "next_action": "Call render_audiobook to start the background render.",
        }

    async def render_audiobook(self, project_id: str) -> dict:
        rendered = await self.audiosmith().render(project_id)
        job_id = str(rendered.get("job_id", ""))
        if not job_id:
            raise RuntimeError("AudioSmith did not return a render job_id")
        project = self.library.get_job(f"audiosmith-project:{project_id}") or {}
        tracked = self.library.record_job(
            job_id,
            kind="audiobook_render",
            status=str(rendered.get("status", "queued")),
            book_id=project.get("book_id"),
            payload={"project_id": project_id},
            result=rendered,
        )
        return {**rendered, "tracking": tracked}

    async def audiobook_job(self, job_id: str, wait_seconds: int = 0) -> dict:
        status = await self.audiosmith().job(job_id, wait_seconds)
        previous = self.library.get_job(job_id) or {}
        tracked = self.library.record_job(
            job_id,
            kind=previous.get("kind", "audiobook_render"),
            status=str(status.get("status", "unknown")),
            book_id=previous.get("book_id"),
            progress=float(status.get("progress", previous.get("progress", 0))),
            payload=previous.get("payload", {}),
            result=status,
            error=str(status.get("error", "")),
        )
        return {**status, "tracking": tracked}

    async def export_audiobook(
        self, project_id: str, *, render_id: str = "", filename: str = ""
    ) -> dict:
        exported = await self.audiosmith().export(
            project_id,
            self.config.paths.resolved("audiobooks"),
            render_id=render_id,
            filename=filename,
        )
        project = self.library.get_job(f"audiosmith-project:{project_id}") or {}
        book_id = project.get("book_id")
        metadata = self.library.get_book_metadata(int(book_id)) if book_id else None
        library_files = []
        if metadata:
            for value in exported.get("files", []):
                path = Path(value)
                if path.is_file():
                    metadata.format = path.suffix.lstrip(".").lower()
                    library_files.append(
                        self.library.register_file(path, metadata, kind="audiobook")
                    )
        return {**exported, "library": library_files}
