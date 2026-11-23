from pathlib import Path


def extract_cover(source: Path, target: Path) -> Path | None:
    """Extract a local cover without contacting external image hosts."""
    if target.exists():
        return target
    content = None
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        import fitz

        with fitz.open(source) as document:
            if document.page_count:
                content = (
                    document[0].get_pixmap(matrix=fitz.Matrix(0.8, 0.8)).tobytes("png")
                )
    elif suffix == ".epub":
        from ebooklib import ITEM_IMAGE, epub
        from ebooklib.exceptions import EpubException

        try:
            book = epub.read_epub(str(source))
        except EpubException:
            return None
        images = list(book.get_items_of_type(ITEM_IMAGE))
        cover = next(
            (item for item in images if "cover" in item.get_name().lower()), None
        )
        if cover is None and images:
            cover = images[0]
        if cover is not None:
            from io import BytesIO

            from PIL import Image

            with Image.open(BytesIO(cover.get_content())) as image:
                output = BytesIO()
                image = image.convert("RGB")
                image.thumbnail((320, 460))
                image.save(output, format="PNG")
                content = output.getvalue()
    if content:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target
    return None
