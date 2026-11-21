from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from .config import AppConfig
from .models import BookMetadata
from .naming import render_name, resolve_collision

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    year TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',
    publisher TEXT NOT NULL DEFAULT '',
    isbn TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    cover_path TEXT NOT NULL DEFAULT '',
    categories_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source, source_id)
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    format TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    book_id INTEGER REFERENCES books(id) ON DELETE SET NULL,
    progress REAL NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_books_title ON books(title);
CREATE INDEX IF NOT EXISTS idx_books_author ON books(author);
CREATE INDEX IF NOT EXISTS idx_files_book ON files(book_id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class LibraryStore:
    def __init__(self, config: AppConfig):
        self.config = config
        self.root = config.paths.library_root.expanduser().resolve()
        self.db_path = self.root / ".workbench/library.sqlite3"

    def initialize(self) -> None:
        self.config.ensure_directories()
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def upsert_book(self, metadata: BookMetadata) -> int:
        self.initialize()
        now = _now()
        source_id = metadata.id or self._fallback_source_id(metadata)
        values = (
            metadata.source,
            source_id,
            metadata.title,
            metadata.author,
            metadata.year,
            metadata.language,
            metadata.publisher,
            metadata.isbn,
            metadata.description,
            metadata.cover_path,
            json.dumps(metadata.categories, ensure_ascii=False),
            now,
            now,
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO books (
                    source, source_id, title, author, year, language, publisher,
                    isbn, description, cover_path, categories_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, source_id) DO UPDATE SET
                    title=excluded.title, author=excluded.author, year=excluded.year,
                    language=excluded.language, publisher=excluded.publisher,
                    isbn=excluded.isbn, description=excluded.description,
                    cover_path=excluded.cover_path,
                    categories_json=excluded.categories_json, updated_at=excluded.updated_at
                """,
                values,
            )
            row = connection.execute(
                "SELECT id FROM books WHERE source=? AND source_id=?",
                (metadata.source, source_id),
            ).fetchone()
        return int(row["id"])

    def ingest_file(
        self,
        source_path: Path,
        metadata: BookMetadata,
        *,
        kind: str = "original",
        move: bool = False,
    ) -> dict:
        source_path = source_path.expanduser().resolve(strict=True)
        if not source_path.is_file():
            raise ValueError("source_path must be a file")
        book_id = self.upsert_book(metadata)
        extension = source_path.suffix or f".{metadata.format or 'bin'}"
        metadata.format = metadata.format or extension.lstrip(".").lower()
        directory_name = {
            "original": "downloads",
            "converted": "converted",
            "audiobook": "audiobooks",
            "report": "reports",
        }.get(kind, "downloads")
        destination_dir = self.config.paths.resolved(directory_name)
        destination_dir.mkdir(parents=True, exist_ok=True)
        filename = render_name(
            self.config.naming.template, metadata.to_dict(), extension
        )
        destination = resolve_collision(
            destination_dir / filename, self.config.naming.collision
        )
        if destination != source_path:
            if move:
                shutil.move(str(source_path), destination)
            else:
                shutil.copy2(source_path, destination)
        return self.register_file(destination, metadata, kind=kind, book_id=book_id)

    def register_file(
        self,
        path: Path,
        metadata: BookMetadata,
        *,
        kind: str,
        book_id: int | None = None,
    ) -> dict:
        path = path.expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError("path must be a file")
        if book_id is None:
            book_id = self.upsert_book(metadata)
        metadata.format = metadata.format or path.suffix.lstrip(".").lower()
        size = path.stat().st_size
        digest = sha256_file(path)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO files (book_id, kind, format, path, size, sha256, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    book_id=excluded.book_id, kind=excluded.kind,
                    format=excluded.format, size=excluded.size, sha256=excluded.sha256
                """,
                (
                    book_id,
                    kind,
                    metadata.format,
                    str(path),
                    size,
                    digest,
                    _now(),
                ),
            )
        return {
            "book_id": book_id,
            "path": str(path),
            "size": size,
            "sha256": digest,
            "kind": kind,
            "format": metadata.format,
        }

    def list_books(self, query: str = "", limit: int = 100) -> list[dict]:
        self.initialize()
        limit = max(1, min(limit, 500))
        sql = "SELECT * FROM books"
        parameters: list[object] = []
        if query:
            sql += " WHERE title LIKE ? OR author LIKE ? OR isbn LIKE ?"
            needle = f"%{query}%"
            parameters.extend([needle, needle, needle])
        sql += " ORDER BY updated_at DESC LIMIT ?"
        parameters.append(limit)
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["categories"] = json.loads(item.pop("categories_json"))
                item["files"] = [
                    dict(file_row)
                    for file_row in connection.execute(
                        "SELECT kind, format, path, size, sha256 FROM files WHERE book_id=?",
                        (item["id"],),
                    ).fetchall()
                ]
                result.append(item)
        return result

    def apply_analysis(
        self,
        source_path: Path,
        *,
        categories: list[str],
        reports: list[tuple[str, Path]],
        model: str,
        prompt_version: str,
    ) -> dict:
        """Attach locally generated analysis to the book owning ``source_path``.

        A report is always useful even for a file that has not yet been ingested.
        In that case we return ``attached: False`` instead of creating an ambiguous
        book row from a path alone.
        """
        self.initialize()
        source = str(source_path.expanduser().resolve(strict=True))
        cleaned_categories = _clean_categories(categories)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT book_id FROM files WHERE path=?", (source,)
            ).fetchone()
            if row is None:
                return {"attached": False, "categories": cleaned_categories}
            book_id = int(row["book_id"])
            connection.execute(
                "UPDATE books SET categories_json=?, updated_at=? WHERE id=?",
                (json.dumps(cleaned_categories, ensure_ascii=False), _now(), book_id),
            )
            for kind, report_path in reports:
                report_path = report_path.expanduser().resolve(strict=True)
                connection.execute(
                    """
                    INSERT INTO reports (book_id, kind, path, model, prompt_version, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        book_id,
                        kind,
                        str(report_path),
                        model,
                        prompt_version,
                        _now(),
                    ),
                )
        return {
            "attached": True,
            "book_id": book_id,
            "categories": cleaned_categories,
            "reports": [str(path) for _, path in reports],
        }

    def record_job(
        self,
        job_id: str,
        *,
        kind: str,
        status: str,
        book_id: int | None = None,
        progress: float = 0,
        payload: dict | None = None,
        result: dict | None = None,
        error: str = "",
    ) -> dict:
        self.initialize()
        progress = min(1.0, max(0.0, float(progress)))
        now = _now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, kind, status, book_id, progress, payload_json, result_json,
                    error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    book_id=COALESCE(excluded.book_id, jobs.book_id),
                    progress=excluded.progress,
                    payload_json=excluded.payload_json,
                    result_json=excluded.result_json,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    job_id,
                    kind,
                    status,
                    book_id,
                    progress,
                    json.dumps(payload or {}, ensure_ascii=False),
                    json.dumps(result or {}, ensure_ascii=False),
                    error,
                    now,
                    now,
                ),
            )
        return self.get_job(job_id) or {}

    def get_job(self, job_id: str) -> dict | None:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        result["result"] = json.loads(result.pop("result_json"))
        return result

    def book_id_for_file(self, path: Path) -> int | None:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT book_id FROM files WHERE path=?",
                (str(path.expanduser().resolve()),),
            ).fetchone()
        return int(row["book_id"]) if row else None

    @staticmethod
    def _fallback_source_id(metadata: BookMetadata) -> str:
        raw = "\n".join([metadata.title, metadata.author, metadata.year, metadata.isbn])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _clean_categories(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        category = " ".join(str(value).split()).strip()[:80]
        if category and category not in result:
            result.append(category)
    return result[:12]
