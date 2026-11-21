from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import default_config_path, default_config_text, load_config
from .models import BookMetadata
from .service import WorkbenchService


def _metadata(args: argparse.Namespace) -> BookMetadata:
    return BookMetadata(
        title=args.title or Path(getattr(args, "path", "book")).stem,
        author=args.author,
        year=args.year,
        language=args.language,
        format=getattr(args, "format", ""),
        publisher=args.publisher,
        isbn=args.isbn,
        id=getattr(args, "source_id", ""),
    )


def _metadata_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--title", default="")
    parser.add_argument("--author", default="")
    parser.add_argument("--year", default="")
    parser.add_argument("--language", default="")
    parser.add_argument("--publisher", default="")
    parser.add_argument("--isbn", default="")
    parser.add_argument("--source-id", default="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zlibrary-workbench")
    parser.add_argument("--config", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    config = sub.add_parser("config")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("show")
    config_sub.add_parser("init")

    sub.add_parser("init")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--zlibrary", action="store_true")

    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--page", type=int, default=1)
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--language", default="")
    search.add_argument("--extension", default="")

    download = sub.add_parser("download")
    download.add_argument("--id", required=True)
    download.add_argument("--hash", required=True)
    download.add_argument("--account", default="auto")
    download.add_argument("--max-mb", type=int, default=80)
    download.add_argument("--format", default="")
    _metadata_arguments(download)

    library = sub.add_parser("library")
    library_sub = library.add_subparsers(dest="library_command", required=True)
    library_list = library_sub.add_parser("list")
    library_list.add_argument("--query", default="")
    library_list.add_argument("--limit", type=int, default=100)
    library_jobs = library_sub.add_parser("jobs")
    library_jobs.add_argument("--limit", type=int, default=100)
    ingest = library_sub.add_parser("ingest")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--kind", default="original")
    ingest.add_argument("--format", default="")
    _metadata_arguments(ingest)

    convert = sub.add_parser("convert")
    convert.add_argument("path", type=Path)
    convert.add_argument("--mode", choices=["auto", "reflow", "visual"], default="auto")
    convert.add_argument("--format", default="epub")
    _metadata_arguments(convert)

    summarize = sub.add_parser("summarize")
    summarize.add_argument("path", type=Path)
    summarize.add_argument("--title", default="")
    summarize.add_argument("--author", default="")

    audio = sub.add_parser("audiosmith")
    audio_sub = audio.add_subparsers(dest="audio_command", required=True)
    audio_sub.add_parser("health")
    audio_create = audio_sub.add_parser("create")
    audio_create.add_argument("path", type=Path)
    audio_create.add_argument("--voice", default="")
    audio_create.add_argument("--model", default="")
    audio_create.add_argument("--format", default="")
    _metadata_arguments(audio_create)
    audio_render = audio_sub.add_parser("render")
    audio_render.add_argument("project_id")
    audio_job = audio_sub.add_parser("job")
    audio_job.add_argument("job_id")
    audio_job.add_argument("--wait", type=int, default=0)
    audio_export = audio_sub.add_parser("export")
    audio_export.add_argument("project_id")
    audio_export.add_argument("--render-id", default="")
    audio_export.add_argument("--filename", default="")

    api = sub.add_parser("serve-api")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8765)
    sub.add_parser("serve-mcp")
    return parser


async def _audio_command(service: WorkbenchService, args: argparse.Namespace) -> dict:
    client = service.audiosmith()
    if args.audio_command == "health":
        return await client.health()
    if args.audio_command == "create":
        return await client.create_audiobook(
            args.path, _metadata(args), voice=args.voice, model=args.model
        )
    if args.audio_command == "render":
        return await client.render(args.project_id)
    if args.audio_command == "job":
        return await client.job(args.job_id, args.wait)
    if args.audio_command == "export":
        return await client.export(
            args.project_id,
            service.config.paths.resolved("audiobooks"),
            render_id=args.render_id,
            filename=args.filename,
        )
    raise ValueError("unknown AudioSmith command")


def dispatch(args: argparse.Namespace) -> dict:
    config_path = args.config or default_config_path()
    if args.command == "config" and args.config_command == "init":
        if config_path.exists():
            raise FileExistsError(config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(default_config_text(), encoding="utf-8")
        return {"ok": True, "path": str(config_path)}
    config = load_config(config_path)
    if args.command == "config":
        return {"ok": True, "path": str(config_path), "config": config.to_dict()}
    service = WorkbenchService(config)
    if args.command == "init":
        return service.initialize()
    if args.command == "doctor":
        result = service.initialize()
        if args.zlibrary:
            result["zlibrary"] = service.zlibrary.doctor()
        return result
    if args.command == "search":
        return service.search(
            args.query,
            page=args.page,
            limit=args.limit,
            language=args.language,
            extension=args.extension,
        )
    if args.command == "download":
        return service.download(
            book_id=args.id,
            book_hash=args.hash,
            metadata=_metadata(args),
            account=args.account,
            max_mb=args.max_mb,
        )
    if args.command == "library":
        if args.library_command == "list":
            return {
                "ok": True,
                "books": service.library.list_books(args.query, args.limit),
            }
        if args.library_command == "jobs":
            return {"ok": True, "jobs": service.library.list_jobs(limit=args.limit)}
        return service.ingest(args.path, _metadata(args), kind=args.kind)
    if args.command == "convert":
        return service.convert_pdf(args.path, _metadata(args), mode=args.mode)
    if args.command == "summarize":
        return service.summarize(args.path, title=args.title, author=args.author)
    if args.command == "audiosmith":
        return asyncio.run(_audio_command(service, args))
    if args.command == "serve-api":
        if args.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(
                "REST API defaults to loopback; remote binding is not enabled"
            )
        try:
            import uvicorn
        except ImportError as error:
            raise RuntimeError("serve-api requires the 'server' extra") from error
        from .api import create_app

        uvicorn.run(create_app(config), host=args.host, port=args.port)
        return {"ok": True}
    if args.command == "serve-mcp":
        from .mcp_server import run_mcp

        run_mcp(config)
        return {"ok": True}
    raise ValueError("unknown command")


def main() -> int:
    parser = build_parser()
    try:
        result = dispatch(parser.parse_args())
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as error:
        print(
            json.dumps(
                {"ok": False, "error": str(error), "type": type(error).__name__},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
