import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import fitz
from PIL import Image

from zlibrary_workbench.conversion import convert_pdf_to_epub
from zlibrary_workbench.models import BookMetadata


def make_pdf(path: Path) -> None:
    image = Image.new("RGB", (160, 100), color=(210, 45, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 80), "Chapter One", fontsize=22)
    page.insert_textbox(
        fitz.Rect(72, 110, 520, 310),
        "This is a synthetic PDF used to verify text extraction and image preservation. "
        * 8,
        fontsize=12,
    )
    page.insert_image(fitz.Rect(120, 350, 440, 550), stream=buffer.getvalue())
    document.save(path)
    document.close()


class ConversionIntegrationTests(unittest.TestCase):
    def test_reflow_preserves_text_and_embedded_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdf"
            output = root / "reflow.epub"
            report_file = root / "reflow.json"
            make_pdf(source)
            report = convert_pdf_to_epub(
                source,
                output,
                metadata=BookMetadata(title="Synthetic", author="CI", language="en"),
                mode="reflow",
                report_path=report_file,
            )
            self.assertEqual(report.pages_total, 1)
            self.assertEqual(report.pages_written, 1)
            self.assertGreater(report.characters_extracted, 100)
            self.assertGreaterEqual(report.source_images, 1)
            self.assertGreaterEqual(report.images_written, 1)
            self.assertTrue(report.output_sha256)
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                self.assertTrue(any(name.endswith(".xhtml") for name in names))
                self.assertTrue(any("images/image-" in name for name in names))
                xhtml = b"".join(
                    archive.read(name) for name in names if name.endswith(".xhtml")
                )
                self.assertIn(b"synthetic PDF", xhtml)
            saved = json.loads(report_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["output_sha256"], report.output_sha256)

    def test_visual_mode_writes_one_page_image_per_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdf"
            output = root / "visual.epub"
            make_pdf(source)
            report = convert_pdf_to_epub(source, output, mode="visual")
            self.assertEqual(report.mode_used, "visual")
            self.assertEqual(report.pages_total, report.images_written)
            with zipfile.ZipFile(output) as archive:
                page_images = [
                    name for name in archive.namelist() if "images/page-" in name
                ]
            self.assertEqual(len(page_images), report.pages_total)

    def test_auto_selects_visual_for_scanned_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "scan.pdf"
            output = root / "scan.epub"
            image = Image.new("RGB", (1200, 1600), color="white")
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG")
            document = fitz.open()
            page = document.new_page(width=600, height=800)
            page.insert_image(page.rect, stream=buffer.getvalue())
            document.save(source)
            document.close()
            report = convert_pdf_to_epub(source, output, mode="auto")
            self.assertEqual(report.mode_used, "visual")
            self.assertTrue(any("visual mode" in item for item in report.warnings))


if __name__ == "__main__":
    unittest.main()
