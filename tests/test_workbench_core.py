import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zlibrary_workbench.cli import build_parser, dispatch
from zlibrary_workbench.config import (
    AppConfig,
    AudioSmithConfig,
    NamingConfig,
    OllamaConfig,
    PathsConfig,
    configure_loopback_bypass,
    load_config,
    save_config,
)
from zlibrary_workbench.library import LibraryStore
from zlibrary_workbench.mcp_server import run_mcp
from zlibrary_workbench.models import BookMetadata
from zlibrary_workbench.naming import render_name, resolve_collision, safe_filename
from zlibrary_workbench.ollama import ReportFiles, _batches, _mindmap_report
from zlibrary_workbench.service import WorkbenchService
from zlibrary_workbench.zlibrary import ZLibraryAdapter


class NamingTests(unittest.TestCase):
    def test_missing_fields_do_not_leave_empty_groups(self):
        value = render_name(
            "{title} - {author} ({year}) [{language}] [{format}]",
            {"title": "三体", "author": "刘慈欣", "format": "epub"},
            ".epub",
        )
        self.assertEqual(value, "三体 - 刘慈欣 [epub].epub")

    def test_unsafe_characters_are_removed(self):
        self.assertEqual(safe_filename('A/B: "Book"?'), "A_B_ _Book__")

    def test_collision_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.epub"
            path.write_bytes(b"one")
            self.assertEqual(resolve_collision(path).name, "book (2).epub")


class ConfigTests(unittest.TestCase):
    def test_audiosmith_must_stay_on_loopback(self):
        config = AppConfig(
            audiosmith=AudioSmithConfig(base_url="http://example.com:3901")
        )
        with self.assertRaisesRegex(ValueError, "loopback"):
            config.validate()

    def test_ollama_remote_requires_opt_in(self):
        config = AppConfig(ollama=OllamaConfig(base_url="http://192.0.2.4:11434"))
        with self.assertRaisesRegex(ValueError, "loopback"):
            config.validate()

    def test_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config = AppConfig(
                paths=PathsConfig(library_root=Path(directory) / "book shelf"),
                naming=NamingConfig(template="{author} - {title}"),
            )
            save_config(config, config_path)
            loaded = load_config(config_path)
            self.assertEqual(loaded.paths.library_root, config.paths.library_root)
            self.assertEqual(loaded.naming.template, "{author} - {title}")

    def test_loopback_bypass_is_added_without_losing_existing_entries(self):
        with patch.dict(os.environ, {"NO_PROXY": "example.test"}, clear=True):
            configure_loopback_bypass()
            self.assertEqual(
                os.environ["NO_PROXY"], "example.test,127.0.0.1,localhost,::1"
            )
            self.assertEqual(os.environ["NO_PROXY"], os.environ["no_proxy"])


class LibraryTests(unittest.TestCase):
    def test_ingest_and_list(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "library"
            incoming = Path(directory) / "incoming.pdf"
            incoming.write_bytes(b"%PDF-test")
            config = AppConfig(
                paths=PathsConfig(library_root=root),
                naming=NamingConfig(template="{title} - {author} [{format}]"),
            )
            store = LibraryStore(config)
            metadata = BookMetadata(
                title="测试书", author="作者", format="pdf", id="123:abc"
            )
            result = store.ingest_file(incoming, metadata)
            self.assertTrue(Path(result["path"]).exists())
            books = store.list_books("测试")
            self.assertEqual(len(books), 1)
            self.assertEqual(books[0]["title"], "测试书")
            self.assertEqual(books[0]["files"][0]["sha256"], result["sha256"])

    def test_analysis_updates_categories_and_registers_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "library"
            incoming = Path(directory) / "incoming.epub"
            incoming.write_bytes(b"EPUB-test")
            report = root / "reports" / "report.md"
            report.parent.mkdir(parents=True)
            report.write_text("summary", encoding="utf-8")
            store = LibraryStore(AppConfig(paths=PathsConfig(library_root=root)))
            result = store.ingest_file(
                incoming, BookMetadata(title="分析书", format="epub", id="book-1")
            )
            attached = store.apply_analysis(
                Path(result["path"]),
                categories=[" 科技 ", "科技", "", "社会"],
                reports=[("summary", report)],
                model="qwen3.5:9b",
                prompt_version="test-v1",
            )
            self.assertTrue(attached["attached"])
            self.assertEqual(attached["categories"], ["科技", "社会"])
            books = store.list_books("分析")
            self.assertEqual(books[0]["categories"], ["科技", "社会"])

    def test_jobs_are_persisted_and_listed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LibraryStore(
                AppConfig(paths=PathsConfig(library_root=Path(directory) / "library"))
            )
            saved = store.record_job(
                "longform:1",
                kind="audiobook_render",
                status="running",
                progress=0.25,
                payload={"project_id": "book:1"},
            )
            self.assertEqual(saved["progress"], 0.25)
            listed = store.list_jobs()
            self.assertEqual(listed[0]["id"], "longform:1")
            self.assertEqual(listed[0]["payload"]["project_id"], "book:1")


class OllamaReportTests(unittest.TestCase):
    def test_batches_preserve_all_text(self):
        source = [{"source": "p1", "text": "x" * 5000}]
        batches = _batches(source, 2000)
        joined = "".join(item["text"] for batch in batches for item in batch)
        self.assertEqual(joined, source[0]["text"])

    def test_mindmap_is_mermaid(self):
        report = _mindmap_report(
            {
                "concepts": [{"name": "主题", "children": ["子项"]}],
                "key_points": ["重点"],
            },
            "书名",
        )
        self.assertIn("```mermaid", report)
        self.assertIn("mindmap", report)
        self.assertIn("子项", report)

    def test_service_attaches_analysis_to_ingested_book(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "library"
            incoming = Path(directory) / "incoming.epub"
            incoming.write_bytes(b"EPUB-test")
            config = AppConfig(paths=PathsConfig(library_root=root))
            service = WorkbenchService(config)
            ingested = service.ingest(
                incoming, BookMetadata(title="本地分析", format="epub", id="book-1")
            )
            reports = config.paths.resolved("reports")
            markdown = reports / "summary.md"
            mindmap = reports / "mindmap.md"
            metadata = reports / "metadata.json"
            reports.mkdir(parents=True, exist_ok=True)
            markdown.write_text("summary", encoding="utf-8")
            mindmap.write_text("mindmap", encoding="utf-8")
            metadata.write_text(
                '{"result": {"categories": ["历史", " 科技 ", "历史"]}}',
                encoding="utf-8",
            )

            class FakeOllama:
                def __init__(self, *args, **kwargs):
                    pass

                def summarize_document(self, *args, **kwargs):
                    return ReportFiles(markdown, mindmap, metadata)

                def close(self):
                    pass

            with patch("zlibrary_workbench.service.OllamaClient", FakeOllama):
                result = service.summarize(Path(ingested["path"]))
            self.assertTrue(result["library"]["attached"])
            self.assertEqual(result["library"]["categories"], ["历史", "科技"])


class McpServerTests(unittest.TestCase):
    def test_closed_stdio_is_a_clean_mcp_exit(self):
        config = AppConfig()

        class FakeMcp:
            def run(self, **kwargs):
                raise ValueError("I/O operation on closed file.")

        with patch("zlibrary_workbench.mcp_server.build_mcp", return_value=FakeMcp()):
            run_mcp(config)

    def test_other_mcp_errors_are_not_hidden(self):
        config = AppConfig()

        class FakeMcp:
            def run(self, **kwargs):
                raise ValueError("unexpected")

        with patch("zlibrary_workbench.mcp_server.build_mcp", return_value=FakeMcp()):
            with self.assertRaisesRegex(ValueError, "unexpected"):
                run_mcp(config)


class ZLibraryLoginTests(unittest.TestCase):
    def test_adapter_accepts_pretty_printed_json(self):
        adapter = ZLibraryAdapter(script_path=Path(__file__))
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{\n  "ok": true,\n  "accounts": []\n}\n',
            stderr="",
        )
        with patch(
            "zlibrary_workbench.zlibrary.subprocess.run", return_value=completed
        ):
            result = adapter.accounts()
        self.assertTrue(result["ok"])
        self.assertEqual(result["accounts"], [])

    def test_adapter_sends_password_only_on_stdin(self):
        adapter = ZLibraryAdapter(script_path=Path(__file__))
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"ok": true, "account": "work"}\n', stderr=""
        )
        with patch(
            "zlibrary_workbench.zlibrary.subprocess.run", return_value=completed
        ) as run:
            result = adapter.login(
                email="reader@example.test", password="secret", account="work"
            )
        self.assertTrue(result["ok"])
        command = run.call_args.args[0]
        self.assertNotIn("secret", command)
        self.assertEqual(run.call_args.kwargs["input"], "secret\n")

    def test_service_remembers_password_only_after_successful_login(self):
        service = WorkbenchService(AppConfig())
        service.zlibrary = type(
            "Adapter", (), {"login": lambda self, **kwargs: {"ok": True}}
        )()
        with (
            patch("zlibrary_workbench.service.save_password") as save,
            patch("zlibrary_workbench.service.delete_password") as delete,
        ):
            result = service.zlibrary_login(
                email="reader@example.test",
                password="secret",
                account="work",
                remember_password=True,
            )
        self.assertTrue(result["ok"])
        save.assert_called_once_with("work", "secret")
        delete.assert_not_called()
        self.assertEqual(service.config.zlibrary.email, "reader@example.test")

    def test_mcp_cli_does_not_emit_a_json_envelope(self):
        args = build_parser().parse_args(["serve-mcp"])
        with patch("zlibrary_workbench.mcp_server.run_mcp") as server:
            self.assertIsNone(dispatch(args))
        server.assert_called_once()


if __name__ == "__main__":
    unittest.main()
