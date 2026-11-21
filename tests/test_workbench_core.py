import tempfile
import unittest
from pathlib import Path

from zlibrary_workbench.config import (
    AppConfig,
    AudioSmithConfig,
    NamingConfig,
    OllamaConfig,
    PathsConfig,
)
from zlibrary_workbench.library import LibraryStore
from zlibrary_workbench.models import BookMetadata
from zlibrary_workbench.naming import render_name, resolve_collision, safe_filename
from zlibrary_workbench.ollama import _batches, _mindmap_report


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
        config = AppConfig(audiosmith=AudioSmithConfig(base_url="http://example.com:3901"))
        with self.assertRaisesRegex(ValueError, "loopback"):
            config.validate()

    def test_ollama_remote_requires_opt_in(self):
        config = AppConfig(ollama=OllamaConfig(base_url="http://192.0.2.4:11434"))
        with self.assertRaisesRegex(ValueError, "loopback"):
            config.validate()


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


class OllamaReportTests(unittest.TestCase):
    def test_batches_preserve_all_text(self):
        source = [{"source": "p1", "text": "x" * 5000}]
        batches = _batches(source, 2000)
        joined = "".join(item["text"] for batch in batches for item in batch)
        self.assertEqual(joined, source[0]["text"])

    def test_mindmap_is_mermaid(self):
        report = _mindmap_report(
            {"concepts": [{"name": "主题", "children": ["子项"]}], "key_points": ["重点"]},
            "书名",
        )
        self.assertIn("```mermaid", report)
        self.assertIn("mindmap", report)
        self.assertIn("子项", report)


if __name__ == "__main__":
    unittest.main()
