import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import zlibrary_tor
from fastapi.testclient import TestClient

from zlibrary_workbench.api import create_app
from zlibrary_workbench.config import AppConfig, PathsConfig
from zlibrary_workbench.covers import extract_cover
from zlibrary_workbench.library import LibraryStore
from zlibrary_workbench.models import BookMetadata
from zlibrary_workbench.service import WorkbenchService


class CoverTests(unittest.TestCase):
    def test_pdf_first_page_becomes_cover(self):
        import fitz

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "book.pdf"
            target = Path(directory) / "cover.png"
            with fitz.open() as document:
                document.new_page().insert_text((72, 72), "Cover")
                document.save(source)
            self.assertEqual(extract_cover(source, target), target)
            self.assertTrue(target.read_bytes().startswith(b"\x89PNG"))


class DownloadQueueTests(unittest.TestCase):
    def test_confirmation_and_format_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            config = AppConfig(
                paths=PathsConfig(library_root=Path(directory) / "library")
            )
            client = TestClient(
                create_app(config, config_path=Path(directory) / "config.toml")
            )
            payload = {
                "id": "123",
                "hash": "abc",
                "metadata": {"title": "Example", "format": "pdf"},
                "target_format": "epub",
            }
            self.assertEqual(
                client.post("/v1/books/downloads", json=payload).status_code, 409
            )
            payload["confirmed"] = True
            with patch(
                "zlibrary_workbench.service.WorkbenchService.download"
            ) as download:
                response = client.post("/v1/books/downloads", json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["job_id"].startswith("download:"))
            download.assert_called_once()
            self.assertEqual(download.call_args.kwargs["target_format"], "epub")
            payload["target_format"] = "mobi"
            self.assertEqual(
                client.post("/v1/books/downloads", json=payload).status_code, 400
            )

    def test_jobs_include_live_transfer_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            config = AppConfig(
                paths=PathsConfig(library_root=Path(directory) / "library")
            )
            job_id = "download:sample"
            LibraryStore(config).record_job(job_id, kind="download", status="running")
            progress = WorkbenchService(config).download_progress_path(job_id)
            zlibrary_tor._write_download_progress(progress, 512, 1024)
            client = TestClient(
                create_app(config, config_path=Path(directory) / "config.toml")
            )
            jobs = client.get("/v1/jobs").json()["jobs"]
            self.assertEqual(
                jobs[0]["transfer"], {"bytes_done": 512, "bytes_total": 1024}
            )

    def test_pdf_download_keeps_original_and_registers_epub(self):
        import fitz

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            with fitz.open() as document:
                document.new_page().insert_text((72, 72), "Chapter One")
                document.save(source)
            service = WorkbenchService(
                AppConfig(paths=PathsConfig(library_root=Path(directory) / "library"))
            )
            service.zlibrary.download = lambda *args, **kwargs: {"path": str(source)}
            result = service.download(
                book_id="123",
                book_hash="abc",
                metadata=BookMetadata(title="Example", format="pdf"),
                target_format="epub",
            )
            self.assertEqual(Path(result["library"]["path"]).suffix, ".epub")
            files = service.library.list_books()[0]["files"]
            self.assertEqual({file["format"] for file in files}, {"pdf", "epub"})
