from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class ZLibraryCommandError(RuntimeError):
    def __init__(self, message: str, payload: dict | None = None, exit_code: int = 1):
        super().__init__(message)
        self.payload = payload or {}
        self.exit_code = exit_code


class ZLibraryAdapter:
    def __init__(self, script_path: Path | None = None, *, timeout: int = 180):
        self.script_path = script_path or (
            Path(__file__).resolve().parents[2] / "scripts/zlibrary_tor.py"
        )
        self.timeout = timeout

    def doctor(self) -> dict[str, Any]:
        return self._run(["doctor"])

    def search(
        self,
        query: str,
        *,
        page: int = 1,
        limit: int = 10,
        language: str = "",
        extension: str = "",
    ) -> dict[str, Any]:
        args = ["search", query, "--page", str(page), "--limit", str(limit)]
        if language:
            args.extend(["--language", language])
        if extension:
            args.extend(["--extension", extension])
        return self._run(args)

    def download(
        self,
        book_id: str,
        book_hash: str,
        output_dir: Path,
        *,
        account: str = "auto",
        max_mb: int = 80,
    ) -> dict[str, Any]:
        output_dir = output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        args = [
            "download",
            "--id",
            book_id,
            "--hash",
            book_hash,
            "--output-dir",
            str(output_dir),
            "--max-mb",
            str(max_mb),
        ]
        if account:
            args.extend(["--account", account])
        return self._run(args, timeout=max(self.timeout, 1800))

    def accounts(self, *, refresh: bool = False) -> dict[str, Any]:
        args = ["accounts", "list"]
        if refresh:
            args.append("--refresh")
        return self._run(args)

    def _run(
        self, arguments: list[str], *, timeout: int | None = None
    ) -> dict[str, Any]:
        if not self.script_path.exists():
            raise FileNotFoundError(self.script_path)
        process = subprocess.run(
            [sys.executable, str(self.script_path), *arguments],
            capture_output=True,
            text=True,
            timeout=timeout or self.timeout,
            check=False,
        )
        payload: dict[str, Any] = {}
        candidates = [process.stdout.strip(), process.stderr.strip()]
        for candidate in candidates:
            if not candidate:
                continue
            try:
                parsed = json.loads(candidate.splitlines()[-1])
                if isinstance(parsed, dict):
                    payload = parsed
                    break
            except json.JSONDecodeError:
                continue
        if process.returncode != 0:
            message = str(
                payload.get("error") or payload.get("reason") or process.stderr.strip()
            )
            raise ZLibraryCommandError(message, payload, process.returncode)
        if not payload:
            raise ZLibraryCommandError("zlibrary-tor returned no JSON output")
        return payload
