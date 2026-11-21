import tempfile
import unittest
from pathlib import Path

from zlibrary_workbench.audiosmith import AudioSmithClient
from zlibrary_workbench.config import AppConfig, AudioSmithConfig, PathsConfig
from zlibrary_workbench.models import BookMetadata
from zlibrary_workbench.service import WorkbenchService


class FakeAudioSmith(AudioSmithClient):
    def __init__(self):
        super().__init__(AudioSmithConfig())
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "create_audiobook":
            return {"project_id": "book:1", "chapters": 3}
        if name == "render_longform":
            return {"job_id": "longform:render-1"}
        if name == "get_job":
            return {"status": "running", "progress": 0.5}
        if name == "export_longform":
            return {"files": ["/tmp/book.m4b"]}
        return {"ok": True}


class AudioSmithContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_audiobook_flow_uses_documented_tools(self):
        client = FakeAudioSmith()
        metadata = BookMetadata(
            title="Book", author="Author", language="zh-CN", year="2026"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            book = root / "book.epub"
            book.write_bytes(b"epub")
            created = await client.create_audiobook(book, metadata, voice="Serena")
            await client.prepare_render(
                created["project_id"], metadata, narrator="Narrator"
            )
            rendered = await client.render(created["project_id"])
            progress = await client.job(rendered["job_id"], 30)
            exported = await client.export(
                created["project_id"], root / "audio", render_id=rendered["job_id"]
            )
        self.assertEqual(progress["progress"], 0.5)
        self.assertTrue(exported["files"])
        names = [name for name, _ in client.calls]
        self.assertEqual(
            names,
            [
                "create_audiobook",
                "update_longform",
                "render_longform",
                "get_job",
                "export_longform",
            ],
        )
        create_args = client.calls[0][1]
        self.assertEqual(create_args["format"], "m4b")
        self.assertEqual(create_args["voice"], "Serena")
        update_args = client.calls[1][1]
        self.assertEqual(update_args["loudness"], "acx")
        self.assertEqual(update_args["author"], "Author")
        export_args = client.calls[-1][1]
        self.assertEqual(export_args["render_id"], "render-1")

    async def test_service_configures_project_before_render(self):
        metadata = BookMetadata(title="Book", author="Author", language="zh-CN")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            book = root / "book.epub"
            book.write_bytes(b"epub")
            service = WorkbenchService(
                AppConfig(paths=PathsConfig(library_root=root / "library"))
            )
            ingested = service.ingest(
                book,
                BookMetadata(title="Book", author="Author", format="epub", id="b-1"),
            )
            fake = FakeAudioSmith()
            service.audiosmith = lambda: fake
            result = await service.create_audiobook(
                Path(ingested["path"]), metadata, voice="Serena"
            )
            rendered = await service.render_audiobook(result["project_id"])
            progress = await service.audiobook_job(rendered["job_id"], 30)
        self.assertEqual(result["project_id"], "book:1")
        self.assertIn("next_action", result)
        self.assertEqual(
            [name for name, _ in fake.calls],
            ["create_audiobook", "update_longform", "render_longform", "get_job"],
        )
        self.assertEqual(fake.calls[1][1]["narrator"], "Serena")
        self.assertEqual(result["tracking"]["status"], "prepared")
        self.assertEqual(rendered["tracking"]["status"], "queued")
        self.assertEqual(progress["tracking"]["progress"], 0.5)


if __name__ == "__main__":
    unittest.main()
