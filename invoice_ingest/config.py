from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

# Load .env once for the whole app (real environment variables win over the file).
load_dotenv()

# Logging. Diagnostics go to a logger (stderr); report tables stay on stdout.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


def setup_logging(level: str | None = None) -> None:
    """Configure logging once, for a CLI entry point. Progress → stderr."""
    logging.basicConfig(
        level=(level or LOG_LEVEL).upper(),
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

# LLM: any OpenAI-compatible endpoint (e.g. OpenRouter, OpenAI, a local gateway).
# Default model — haiku-4.5 scored a perfect golden-set eval at ~1/8 the flagship
# cost (see EVAL.md); override with LLM_MODEL or --model.
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"
LLM_API_KEY = os.environ.get("LLM_API_KEY")
LLM_URL = os.environ.get("LLM_URL")
LLM_MODEL = os.environ.get("LLM_MODEL", DEFAULT_MODEL)


def model_slug(model: str) -> str:
    """Filesystem-safe token from a model slug (the '/' becomes '_')."""
    return "".join(c if c.isalnum() or c in "-." else "_" for c in model)

# OCR (Tesseract). Invoices are Danish/German/English, so load all three. The
# render DPI feeds both OCR and the vision agent; 300 is the OCR sweet spot.
TESSDATA_PREFIX = os.environ.get("TESSDATA_PREFIX")  # path to the language data
TESSERACT_CONFIG = f"--tessdata-dir {TESSDATA_PREFIX}" if TESSDATA_PREFIX else ""
OCR_LANGS = os.environ.get("OCR_LANGS", "dan+deu+eng")
OCR_RENDER_DPI = int(os.environ.get("OCR_RENDER_DPI", "300"))
