from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import AudioSmithConfig
from .models import BookMetadata


class AudioSmithUnavailable(RuntimeError):
    pass


class AudioSmithClient:
    """Async MCP client for the loopback-only AudioSmith server."""

    def __init__(self, config: AudioSmithConfig):
        self.config = config
        self.mcp_url = f"{config.base_url.rstrip('/')}/mcp"

    async def health(self) -> dict[str, Any]:
        return await self.call_tool("check_health", {})

    async def create_audiobook(
        self,
        path: Path,
        metadata: BookMetadata,
        *,
        voice: str = "",
        model: str = "",
    ) -> dict[str, Any]:
        path = path.expanduser().resolve(strict=True)
        if path.suffix.lower() not in {".epub", ".txt", ".md", ".markdown", ".docx"}:
            raise ValueError("AudioSmith audiobook input must be EPUB, TXT, Markdown, or DOCX")
        arguments: dict[str, Any] = {
            "path": str(path),
            "title": metadata.title or path.stem,
            "language": metadata.language or "auto",
            "format": self.config.format,
        }
        selected_voice = voice or self.config.voice
        selected_model = model or self.config.model
        if selected_voice:
            arguments["voice"] = selected_voice
        if selected_model:
            arguments["model"] = selected_model
        return await self.call_tool("create_audiobook", arguments)

    async def prepare_render(
        self,
        project_id: str,
        metadata: BookMetadata,
        *,
        narrator: str = "",
        cover: Path | None = None,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "project_id": project_id,
            "format": self.config.format,
            "loudness": self.config.loudness,
            "title": metadata.title,
            "author": metadata.author,
            "language": metadata.language or "auto",
            "year": metadata.year,
            "description": metadata.description,
        }
        if narrator:
            arguments["narrator"] = narrator
        if cover:
            cover = cover.expanduser().resolve(strict=True)
            arguments["cover"] = str(cover)
        return await self.call_tool("update_longform", arguments)

    async def render(self, project_id: str, chapters: list[int] | None = None) -> dict[str, Any]:
        arguments: dict[str, Any] = {"project_id": project_id}
        if chapters:
            arguments["chapters"] = chapters
        return await self.call_tool("render_longform", arguments)

    async def job(self, job_id: str, wait_seconds: int = 0) -> dict[str, Any]:
        if not 0 <= wait_seconds <= 60:
            raise ValueError("wait_seconds must be between 0 and 60")
        return await self.call_tool(
            "get_job", {"job_id": job_id, "wait_seconds": wait_seconds}
        )

    async def export(
        self,
        project_id: str,
        directory: Path,
        *,
        render_id: str = "",
        filename: str = "",
    ) -> dict[str, Any]:
        directory = directory.expanduser().resolve()
        arguments: dict[str, Any] = {
            "project_id": project_id,
            "format": self.config.format,
            "directory": str(directory),
        }
        if render_id:
            arguments["render_id"] = render_id.removeprefix("longform:")
        if filename:
            arguments["filename"] = filename
        return await self.call_tool("export_longform", arguments)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as error:
            raise AudioSmithUnavailable(
                "AudioSmith integration requires the 'server' extra"
            ) from error
        headers = {
            "X-AudioSmith-Client": "codex-cli",
            "X-AudioSmith-Request": "1",
        }
        try:
            async with streamable_http_client(self.mcp_url, headers=headers) as streams:
                read_stream, write_stream = streams[0], streams[1]
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments=arguments)
        except Exception as error:
            raise AudioSmithUnavailable(
                "AudioSmith is unavailable. Open AudioSmith and enable Settings → "
                "Integration → Local API on 127.0.0.1:3901."
            ) from error
        payloads: list[Any] = []
        for item in result.content:
            text = getattr(item, "text", None)
            if text is None:
                continue
            try:
                payloads.append(json.loads(text))
            except json.JSONDecodeError:
                payloads.append(text)
        if getattr(result, "isError", False):
            raise RuntimeError(json.dumps(payloads, ensure_ascii=False))
        if len(payloads) == 1 and isinstance(payloads[0], dict):
            return payloads[0]
        return {"ok": True, "content": payloads}

