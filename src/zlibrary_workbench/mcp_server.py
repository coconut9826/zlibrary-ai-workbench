from __future__ import annotations

from pathlib import Path

from .config import AppConfig
from .models import BookMetadata
from .service import WorkbenchService


def build_mcp(config: AppConfig):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:
        raise RuntimeError("MCP server requires the 'server' extra") from error

    service = WorkbenchService(config)
    mcp = FastMCP(
        "Z-Library AI Workbench",
        instructions=(
            "Search and manage books locally. Search first and present exact editions. "
            "Call download_book only after the user selected an edition and set confirmed=true. "
            "Ollama and AudioSmith stay on loopback addresses."
        ),
    )

    @mcp.tool()
    def workbench_status(check_zlibrary: bool = False) -> dict:
        """Check local storage and optionally the Tor/Z-Library connection."""
        result = service.initialize()
        if check_zlibrary:
            result["zlibrary"] = service.zlibrary.doctor()
        return result

    @mcp.tool()
    def search_books(
        query: str,
        page: int = 1,
        limit: int = 10,
        language: str = "",
        extension: str = "",
    ) -> dict:
        """Search Z-Library and return structured editions with id/hash metadata."""
        return service.search(
            query,
            page=page,
            limit=limit,
            language=language,
            extension=extension,
        )

    @mcp.tool()
    def download_book(
        id: str,
        hash: str,
        title: str,
        author: str = "",
        year: str = "",
        language: str = "",
        format: str = "",
        account: str = "auto",
        confirmed: bool = False,
    ) -> dict:
        """Download one user-selected edition, name it, and add it to the local shelf."""
        if not confirmed:
            return {
                "ok": False,
                "status": "confirmation_required",
                "message": "Show the exact edition to the user before setting confirmed=true.",
            }
        return service.download(
            book_id=id,
            book_hash=hash,
            account=account,
            metadata=BookMetadata(
                title=title,
                author=author,
                year=year,
                language=language,
                format=format,
                id=f"{id}:{hash}",
            ),
        )

    @mcp.tool()
    def list_library(query: str = "", limit: int = 100) -> dict:
        """List or search books already indexed in the local shelf."""
        return {"ok": True, "books": service.library.list_books(query, limit)}

    @mcp.tool()
    def list_local_jobs(limit: int = 100) -> dict:
        """List local workbench tasks, including persistent AudioSmith render progress."""
        return {"ok": True, "jobs": service.library.list_jobs(limit=limit)}

    @mcp.tool()
    def convert_pdf_to_epub(
        path: str,
        title: str,
        author: str = "",
        language: str = "",
        mode: str = "auto",
    ) -> dict:
        """Convert PDF to EPUB in auto, reflow, or visual-fidelity mode."""
        return service.convert_pdf(
            Path(path),
            BookMetadata(title=title, author=author, language=language, format="epub"),
            mode=mode,
        )

    @mcp.tool()
    def summarize_book(path: str, title: str = "", author: str = "") -> dict:
        """Use local Ollama to create a Markdown summary and Mermaid mind map."""
        return service.summarize(Path(path), title=title, author=author)

    @mcp.tool()
    async def audiosmith_status() -> dict:
        """Check the local AudioSmith MCP server without starting or changing it."""
        return await service.audiosmith().health()

    @mcp.tool()
    async def create_audiobook(
        path: str,
        title: str,
        author: str = "",
        language: str = "",
        voice: str = "",
        model: str = "",
    ) -> dict:
        """Create an AudioSmith audiobook project from EPUB/TXT/Markdown/DOCX."""
        return await service.create_audiobook(
            Path(path),
            BookMetadata(title=title, author=author, language=language),
            voice=voice,
            model=model,
        )

    @mcp.tool()
    async def render_audiobook(project_id: str) -> dict:
        """Start an AudioSmith background render and return its job id."""
        return await service.render_audiobook(project_id)

    @mcp.tool()
    async def audiobook_job(job_id: str, wait_seconds: int = 0) -> dict:
        """Read AudioSmith audiobook render progress, waiting at most 60 seconds."""
        return await service.audiobook_job(job_id, wait_seconds)

    @mcp.tool()
    async def export_audiobook(
        project_id: str, render_id: str = "", filename: str = ""
    ) -> dict:
        """Export a completed AudioSmith render into the configured audiobook folder."""
        return await service.audiosmith().export(
            project_id,
            service.config.paths.resolved("audiobooks"),
            render_id=render_id,
            filename=filename,
        )

    return mcp


def run_mcp(config: AppConfig) -> None:
    build_mcp(config).run(transport="stdio")
