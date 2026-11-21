from __future__ import annotations

import hashlib
import html
import json
import os
import statistics
import tempfile
from pathlib import Path
from typing import Any

from .models import BookMetadata, ConversionReport


class ConversionDependencyError(RuntimeError):
    pass


def _dependencies():
    try:
        import fitz  # type: ignore
        from ebooklib import epub  # type: ignore
    except ImportError as error:
        raise ConversionDependencyError(
            "PDF conversion requires the 'conversion' extra: "
            "pip install 'zlibrary-ai-workbench[conversion]'"
        ) from error
    return fitz, epub


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _choose_mode(document: Any) -> tuple[str, list[str]]:
    text_counts: list[int] = []
    image_ratios: list[float] = []
    block_counts: list[int] = []
    sample_count = min(document.page_count, 12)
    if sample_count == 0:
        return "reflow", ["document contains no pages"]
    indexes = sorted(
        {
            round(index * (document.page_count - 1) / max(sample_count - 1, 1))
            for index in range(sample_count)
        }
    )
    for index in indexes:
        page = document[index]
        text_counts.append(len(page.get_text("text").strip()))
        blocks = page.get_text("dict").get("blocks", [])
        block_counts.append(len(blocks))
        page_area = max(page.rect.width * page.rect.height, 1)
        image_area = sum(
            max(
                0,
                block.get("bbox", [0, 0, 0, 0])[2] - block.get("bbox", [0, 0, 0, 0])[0],
            )
            * max(
                0,
                block.get("bbox", [0, 0, 0, 0])[3] - block.get("bbox", [0, 0, 0, 0])[1],
            )
            for block in blocks
            if block.get("type") == 1
        )
        image_ratios.append(min(image_area / page_area, 1.0))
    median_text = statistics.median(text_counts)
    median_images = statistics.median(image_ratios)
    median_blocks = statistics.median(block_counts)
    warnings: list[str] = []
    if median_text < 80:
        warnings.append("low text density; visual mode selected")
        return "visual", warnings
    if median_images > 0.55 or median_blocks > 90:
        warnings.append("complex/image-heavy layout; visual mode selected")
        return "visual", warnings
    return "reflow", warnings


def _span_html(block: dict) -> tuple[str, int]:
    lines: list[str] = []
    char_count = 0
    sizes: list[float] = []
    for line in block.get("lines", []):
        text_parts: list[str] = []
        for span in line.get("spans", []):
            text = str(span.get("text", ""))
            char_count += len(text)
            sizes.append(float(span.get("size", 0)))
            escaped = html.escape(text)
            if span.get("flags", 0) & 16:
                escaped = f"<strong>{escaped}</strong>"
            if span.get("flags", 0) & 2:
                escaped = f"<em>{escaped}</em>"
            text_parts.append(escaped)
        joined = "".join(text_parts).strip()
        if joined:
            lines.append(joined)
    if not lines:
        return "", char_count
    text_html = "<br/>".join(lines)
    average_size = statistics.mean(sizes) if sizes else 0
    tag = "h2" if average_size >= 17 and char_count < 180 else "p"
    return f"<{tag}>{text_html}</{tag}>", char_count


def convert_pdf_to_epub(
    input_path: Path,
    output_path: Path,
    *,
    metadata: BookMetadata | None = None,
    mode: str = "auto",
    visual_dpi: int = 144,
    max_pages: int = 5000,
    max_input_mb: int = 512,
    report_path: Path | None = None,
) -> ConversionReport:
    if mode not in {"auto", "reflow", "visual"}:
        raise ValueError("mode must be auto, reflow, or visual")
    if not 96 <= visual_dpi <= 240:
        raise ValueError("visual_dpi must be between 96 and 240")
    input_path = input_path.expanduser().resolve(strict=True)
    output_path = output_path.expanduser().resolve()
    if input_path.suffix.lower() != ".pdf":
        raise ValueError("input file must be PDF")
    if output_path.suffix.lower() != ".epub":
        raise ValueError("output file must use .epub")
    if input_path == output_path:
        raise ValueError("output must not replace the original PDF")
    if input_path.stat().st_size > max_input_mb * 1024 * 1024:
        raise ValueError(f"input exceeds {max_input_mb} MiB limit")

    fitz, epub = _dependencies()
    document = fitz.open(input_path)
    try:
        if document.page_count > max_pages:
            raise ValueError(f"PDF exceeds {max_pages} page limit")
        selected_mode, warnings = (
            _choose_mode(document) if mode == "auto" else (mode, [])
        )
        report = ConversionReport(
            input_path=str(input_path),
            output_path=str(output_path),
            mode_requested=mode,
            mode_used=selected_mode,
            pages_total=document.page_count,
            warnings=warnings,
        )
        meta = metadata or BookMetadata(title=input_path.stem, format="epub")
        book = epub.EpubBook()
        book.set_identifier(
            meta.isbn
            or meta.id
            or hashlib.sha256(str(input_path).encode()).hexdigest()[:24]
        )
        book.set_title(meta.title or input_path.stem)
        book.set_language(meta.language or "und")
        if meta.author:
            book.add_author(meta.author)
        css = epub.EpubItem(
            uid="workbench-style",
            file_name="styles/workbench.css",
            media_type="text/css",
            content=(
                "body{font-family:serif;line-height:1.55;margin:5%;}"
                "img{max-width:100%;height:auto;display:block;margin:1em auto;}"
                ".visual-page{margin:0;padding:0;text-align:center;}"
                ".visual-page img{width:100%;max-width:none;margin:0;}"
                "p{margin:.65em 0;}h2{margin:1.4em 0 .7em;}"
            ),
        )
        book.add_item(css)
        chapters = []
        image_counter = 0
        for page_index in range(document.page_count):
            page = document[page_index]
            parts: list[str] = []
            if selected_mode == "visual":
                scale = visual_dpi / 72
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                image_bytes = pixmap.tobytes("png")
                image_name = f"images/page-{page_index + 1:05d}.png"
                image_item = epub.EpubItem(
                    uid=f"page-image-{page_index + 1}",
                    file_name=image_name,
                    media_type="image/png",
                    content=image_bytes,
                )
                book.add_item(image_item)
                parts.append(
                    f'<div class="visual-page"><img src="../{image_name}" alt="Page {page_index + 1}"/></div>'
                )
                report.source_images += len(page.get_images(full=True))
                report.images_written += 1
            else:
                blocks = page.get_text("dict").get("blocks", [])
                blocks.sort(
                    key=lambda item: (
                        item.get("bbox", [0, 0])[1],
                        item.get("bbox", [0, 0])[0],
                    )
                )
                for block in blocks:
                    if block.get("type") == 0:
                        fragment, count = _span_html(block)
                        report.characters_extracted += count
                        if fragment:
                            parts.append(fragment)
                    elif block.get("type") == 1 and block.get("image"):
                        report.source_images += 1
                        extension = str(block.get("ext") or "png").lower()
                        if extension not in {"png", "jpg", "jpeg", "gif", "webp"}:
                            extension = "png"
                        media = (
                            "image/jpeg"
                            if extension in {"jpg", "jpeg"}
                            else f"image/{extension}"
                        )
                        image_counter += 1
                        image_name = f"images/image-{image_counter:05d}.{extension}"
                        image_item = epub.EpubItem(
                            uid=f"image-{image_counter}",
                            file_name=image_name,
                            media_type=media,
                            content=block["image"],
                        )
                        book.add_item(image_item)
                        parts.append(
                            f'<img src="../{image_name}" alt="Image from page {page_index + 1}"/>'
                        )
                        report.images_written += 1
            if not parts:
                report.blank_pages.append(page_index + 1)
                parts.append(f"<p>[Blank page {page_index + 1}]</p>")
            chapter = epub.EpubHtml(
                title=f"Page {page_index + 1}",
                file_name=f"pages/page-{page_index + 1:05d}.xhtml",
                lang=meta.language or "und",
            )
            chapter.content = "\n".join(parts)
            chapter.add_item(css)
            book.add_item(chapter)
            chapters.append(chapter)
            report.pages_written += 1
        book.toc = tuple(chapters)
        book.spine = ["nav", *chapters]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{output_path.stem}-", suffix=".part.epub", dir=output_path.parent
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            epub.write_epub(str(temporary), book, {})
            if temporary.stat().st_size == 0:
                raise RuntimeError("converter produced an empty EPUB")
            os.replace(temporary, output_path)
        finally:
            temporary.unlink(missing_ok=True)
        report.output_sha256 = _sha256(output_path)
        if report_path:
            report_path = report_path.expanduser().resolve()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_report = report_path.with_suffix(report_path.suffix + ".tmp")
            temporary_report.write_text(
                json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary_report, report_path)
        return report
    finally:
        document.close()


def extract_document_text(path: Path, max_chars: int = 4_000_000) -> list[dict]:
    path = path.expanduser().resolve(strict=True)
    fitz, epub = _dependencies()
    chunks: list[dict] = []
    total = 0
    if path.suffix.lower() == ".pdf":
        document = fitz.open(path)
        try:
            for index, page in enumerate(document):
                text = page.get_text("text").strip()
                if text:
                    chunks.append({"source": f"page {index + 1}", "text": text})
                    total += len(text)
                if total >= max_chars:
                    break
        finally:
            document.close()
        return chunks
    if path.suffix.lower() == ".epub":
        book = epub.read_epub(str(path))
        import re

        for item in book.get_items():
            if item.get_type() != 9:
                continue
            raw = item.get_content().decode("utf-8", errors="replace")
            text = re.sub(r"<[^>]+>", " ", raw)
            text = html.unescape(" ".join(text.split()))
            if text:
                chunks.append({"source": item.get_name(), "text": text})
                total += len(text)
            if total >= max_chars:
                break
        return chunks
    if path.suffix.lower() in {".txt", ".md", ".markdown"}:
        text = path.read_text(encoding="utf-8", errors="replace")[:max_chars]
        return [{"source": path.name, "text": text}]
    raise ValueError("supported text extraction formats: PDF, EPUB, TXT, Markdown")
