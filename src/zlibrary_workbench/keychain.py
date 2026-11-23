from __future__ import annotations

import subprocess
import sys

SERVICE = "zlibrary-ai-workbench"


def _label(account: str) -> str:
    if not account or not account.replace("_", "").replace("-", "").isalnum():
        raise ValueError("account must contain letters, digits, _ or -")
    return f"zlibrary-password:{account}"


def save_password(account: str, password: str) -> None:
    if sys.platform != "darwin":
        raise RuntimeError("remembering passwords is currently supported on macOS only")
    if not password:
        raise ValueError("password is required")
    subprocess.run(
        [
            "/usr/bin/security",
            "add-generic-password",
            "-U",
            "-s",
            SERVICE,
            "-a",
            _label(account),
            "-w",
            password,
        ],
        capture_output=True,
        text=True,
        check=True,
    )


def load_password(account: str) -> str | None:
    if sys.platform != "darwin":
        return None
    result = subprocess.run(
        [
            "/usr/bin/security",
            "find-generic-password",
            "-s",
            SERVICE,
            "-a",
            _label(account),
            "-w",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.rstrip("\n") if result.returncode == 0 else None


def delete_password(account: str) -> None:
    if sys.platform != "darwin":
        return
    subprocess.run(
        [
            "/usr/bin/security",
            "delete-generic-password",
            "-s",
            SERVICE,
            "-a",
            _label(account),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
