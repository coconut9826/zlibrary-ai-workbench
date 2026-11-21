from __future__ import annotations

from pathlib import Path
from typing import Any

from .audiosmith import AudioSmithClient
from .config import AppConfig, load_config
from .conversion import convert_pdf_to_epub
from .library import LibraryStore
from .models import BookMetadata
from .naming import render_name, resolve_collision
from .ollama import OllamaClient
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
        cache_dir = self.library.root / ".workbench/download-cache"
        result = self.zlibrary.download(
            book_id, book_hash, cache_dir, account=account, max_mb=max_mb
        )
        path_value = result.get("path")
        if not path_value:
            raise RuntimeError("download result did not contain a path")
        metadata.id = metadata.id or f"{book_id}:{book_hash}"
        metadata.source = "zlibrary"
        metadata.format = metadata.format or Path(path_value).suffix.lstrip(".")
        ingested = self.library.ingest_file(Path(path_value), metadata, kind="original")
        return {**result, "library": ingested}

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
        return {
            "ok": True,
            "markdown": str(files.markdown),
            "mindmap": str(files.mindmap),
            "metadata": str(files.metadata),
            "model": self.config.ollama.model,
        }

    def audiosmith(self) -> AudioSmithClient:
        return AudioSmithClient(self.config.audiosmith)
