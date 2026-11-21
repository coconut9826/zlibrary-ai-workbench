from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class BookMetadata:
    title: str
    author: str = ""
    year: str = ""
    language: str = ""
    format: str = ""
    publisher: str = ""
    isbn: str = ""
    id: str = ""
    source: str = "zlibrary"
    categories: list[str] = field(default_factory=list)
    description: str = ""
    cover_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LibraryFile:
    book_id: int
    kind: str
    format: str
    path: Path
    size: int
    sha256: str


@dataclass(slots=True)
class ConversionReport:
    input_path: str
    output_path: str
    mode_requested: str
    mode_used: str
    pages_total: int = 0
    pages_written: int = 0
    characters_extracted: int = 0
    source_images: int = 0
    images_written: int = 0
    blank_pages: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    output_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

