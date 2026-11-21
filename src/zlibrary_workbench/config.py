from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse


def default_config_path() -> Path:
    override = os.environ.get("ZLIBRARY_WORKBENCH_CONFIG")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library/Application Support/zlibrary-ai-workbench/config.toml"
        )
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "zlibrary-ai-workbench/config.toml"


@dataclass(slots=True)
class PathsConfig:
    library_root: Path = field(
        default_factory=lambda: Path.home() / "Books/ZLibraryWorkbench"
    )
    downloads: str = "originals"
    converted: str = "converted"
    audiobooks: str = "audiobooks"
    reports: str = "reports"

    def resolved(self, name: str) -> Path:
        value = Path(getattr(self, name)).expanduser()
        if value.is_absolute():
            return value.resolve()
        return (self.library_root.expanduser() / value).resolve()


@dataclass(slots=True)
class NamingConfig:
    template: str = "{title} - {author} ({year}) [{language}] [{format}]"
    collision: str = "suffix"


@dataclass(slots=True)
class OllamaConfig:
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3.5:9b"
    context_chars: int = 18000
    allow_remote: bool = False


@dataclass(slots=True)
class AudioSmithConfig:
    base_url: str = "http://127.0.0.1:3901"
    voice: str = ""
    model: str = ""
    format: str = "m4b"
    loudness: str = "acx"


@dataclass(slots=True)
class AppConfig:
    paths: PathsConfig = field(default_factory=PathsConfig)
    naming: NamingConfig = field(default_factory=NamingConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    audiosmith: AudioSmithConfig = field(default_factory=AudioSmithConfig)

    def validate(self) -> None:
        if self.naming.collision not in {"suffix", "error", "reuse"}:
            raise ValueError("naming.collision must be suffix, error, or reuse")
        if self.audiosmith.format not in {"m4b", "wav"}:
            raise ValueError("audiosmith.format must be m4b or wav")
        if self.audiosmith.loudness not in {"acx", "podcast", "off"}:
            raise ValueError("audiosmith.loudness must be acx, podcast, or off")
        _validate_local_url(self.audiosmith.base_url, "AudioSmith", allow_remote=False)
        _validate_local_url(
            self.ollama.base_url, "Ollama", allow_remote=self.ollama.allow_remote
        )
        root = self.paths.library_root.expanduser().resolve()
        for name in ("downloads", "converted", "audiobooks", "reports"):
            target = self.paths.resolved(name)
            if (
                not target.is_relative_to(root)
                and not Path(getattr(self.paths, name)).expanduser().is_absolute()
            ):
                raise ValueError(f"paths.{name} escapes library_root")

    def ensure_directories(self) -> None:
        self.validate()
        root = self.paths.library_root.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        for name in ("downloads", "converted", "audiobooks", "reports"):
            self.paths.resolved(name).mkdir(parents=True, exist_ok=True)
        (root / ".workbench/jobs").mkdir(parents=True, exist_ok=True)
        (root / ".workbench/conversion-reports").mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["paths"]["library_root"] = str(self.paths.library_root)
        return data


def _validate_local_url(url: str, label: str, *, allow_remote: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{label} base_url must be an HTTP(S) origin")
    if (
        parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
    ):
        raise ValueError(
            f"{label} base_url must not include path, credentials, or query"
        )
    if not allow_remote and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"{label} must use a loopback address")


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or default_config_path()
    if not config_path.exists():
        config = AppConfig()
        config.validate()
        return config
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    path_data = raw.get("paths", {})
    if "library_root" in path_data:
        path_data = {**path_data, "library_root": Path(path_data["library_root"])}
    config = AppConfig(
        paths=PathsConfig(**path_data),
        naming=NamingConfig(**raw.get("naming", {})),
        ollama=OllamaConfig(**raw.get("ollama", {})),
        audiosmith=AudioSmithConfig(**raw.get("audiosmith", {})),
    )
    config.validate()
    return config


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    """Persist the user-owned settings without storing credentials in this file."""
    config.validate()
    config_path = (path or default_config_path()).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    values = config.to_dict()
    lines: list[str] = []
    for section in ("paths", "naming", "ollama", "audiosmith"):
        lines.append(f"[{section}]")
        for key, value in values[section].items():
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            elif isinstance(value, int):
                rendered = str(value)
            else:
                rendered = (
                    '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'
                )
            lines.append(f"{key} = {rendered}")
        lines.append("")
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return config_path


def default_config_text() -> str:
    return """[paths]
library_root = "~/Books/ZLibraryWorkbench"
downloads = "originals"
converted = "converted"
audiobooks = "audiobooks"
reports = "reports"

[naming]
template = "{title} - {author} ({year}) [{language}] [{format}]"
collision = "suffix"

[ollama]
base_url = "http://127.0.0.1:11434"
model = "qwen3.5:9b"
context_chars = 18000
allow_remote = false

[audiosmith]
base_url = "http://127.0.0.1:3901"
voice = ""
model = ""
format = "m4b"
loudness = "acx"
"""
