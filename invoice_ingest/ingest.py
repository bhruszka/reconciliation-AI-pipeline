#!/usr/bin/env python3
"""Task 1 — turn a PDF into its raw text sources (embedded text layer + OCR).

Library only: the e2e pipeline (`invoice_ingest.application`) and the eval harness
call `process_pdf` directly; there is no standalone CLI.
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from invoice_ingest.parsing.pdf_parsing import extract_text_layer, ocr_pages
from invoice_ingest.parsing.schema import EnrichedInvoice

PAGE_SEP = "\n\n--- page break ---\n\n"


def process_pdf(pdf_path: Path, repo_root: Path) -> EnrichedInvoice:
    """Produce the enriched record for one PDF."""
    with fitz.open(pdf_path) as doc:
        return EnrichedInvoice(
            invoice_path=pdf_path.relative_to(repo_root).as_posix(),
            pdf_text=extract_text_layer(doc),
            ocr_text=PAGE_SEP.join(ocr_pages(doc)).strip(),
        )


def resolve(path_str: str, root: Path) -> Path:
    """Resolve a possibly-relative path against the repo root."""
    path = Path(path_str)
    return path if path.is_absolute() else root / path
