from __future__ import annotations

import re
import string
import unicodedata
from pathlib import Path
from typing import Mapping

SUPPORTED_FIELDS = {
    "title",
    "author",
    "year",
    "language",
    "format",
    "publisher",
    "isbn",
    "id",
}
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_EMPTY_GROUPS = re.compile(r"\s*(?:\(\s*\)|\[\s*\]|\{\s*\})")
_SPACE = re.compile(r"\s+")
_DANGLING = re.compile(r"(?:\s*[-–—_|,;·]\s*){2,}")


def validate_template(template: str) -> None:
    fields = {
        field_name
        for _, field_name, _, _ in string.Formatter().parse(template)
        if field_name
    }
    unknown = fields - SUPPORTED_FIELDS
    if unknown:
        raise ValueError(f"unknown naming fields: {', '.join(sorted(unknown))}")


def safe_filename(value: str, *, max_length: int = 180) -> str:
    value = unicodedata.normalize("NFC", value)
    value = _INVALID.sub("_", value)
    value = _SPACE.sub(" ", value).strip(" .")
    if value.upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        value = f"_{value}"
    if not value:
        value = "untitled"
    if len(value) > max_length:
        value = value[:max_length].rstrip(" .")
    return value


def render_name(template: str, metadata: Mapping[str, object], extension: str) -> str:
    validate_template(template)
    values = {field: str(metadata.get(field) or "").strip() for field in SUPPORTED_FIELDS}
    values["format"] = values["format"] or extension.lstrip(".").lower()
    rendered = template.format_map(values)
    rendered = _EMPTY_GROUPS.sub("", rendered)
    rendered = _DANGLING.sub(" - ", rendered)
    rendered = re.sub(r"\s+([)\]}])", r"\1", rendered)
    rendered = _SPACE.sub(" ", rendered).strip(" -–—_|,;·.")
    stem = safe_filename(rendered)
    suffix = extension if extension.startswith(".") else f".{extension}"
    return f"{stem}{suffix.lower()}"


def resolve_collision(path: Path, strategy: str = "suffix") -> Path:
    if not path.exists() or strategy == "reuse":
        return path
    if strategy == "error":
        raise FileExistsError(path)
    if strategy != "suffix":
        raise ValueError("collision strategy must be suffix, error, or reuse")
    for index in range(2, 10000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"too many filename collisions for {path.name}")

