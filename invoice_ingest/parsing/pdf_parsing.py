from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

from invoice_ingest import config


def extract_text_layer(doc: fitz.Document) -> str:
    """Concatenate the embedded text layer across all pages.

    Returns an empty string for image-only (scanned) PDFs, which have no layer.
    """
    return "\n".join(page.get_text("text") for page in doc).strip()


def ocr_pages(doc: fitz.Document) -> list[str]:
    """OCR each page (rendered to an image) and return one string per page."""
    parts = []
    for page in doc:
        pix = page.get_pixmap(dpi=config.OCR_RENDER_DPI)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        text = pytesseract.image_to_string(
            img, lang=config.OCR_LANGS, config=config.TESSERACT_CONFIG
        )
        parts.append(text.strip())
    return parts


def render_page_pngs(pdf_path: Path | str) -> list[bytes]:
    """Render each page to PNG bytes — the input for the vision agent."""
    with fitz.open(pdf_path) as doc:
        return [page.get_pixmap(dpi=config.OCR_RENDER_DPI).tobytes("png") for page in doc]
