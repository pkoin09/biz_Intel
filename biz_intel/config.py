"""
Application configuration.

Loads environment variables once and exposes them
through a single Config object.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default

    return value.lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True)
class Config:

    # --------------------------------------------------
    # Google
    # --------------------------------------------------

    GOOGLE_PLACES_API_KEY: str = os.getenv("GOOGLE_PLACES_API_KEY", "")

    # --------------------------------------------------
    # Yelp
    # --------------------------------------------------

    YELP_API_KEY: str = os.getenv("YELP_API_KEY", "")

    # --------------------------------------------------
    # Apify
    # --------------------------------------------------

    APIFY_API_KEY: str = os.getenv("APIFY_API_KEY", "")

    # --------------------------------------------------
    # Cache
    # --------------------------------------------------

    CACHE_PATH: Path = BASE_DIR / os.getenv("CACHE_PATH", ".cache")

    # --------------------------------------------------
    # Supabase
    # --------------------------------------------------

    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")

    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

    # --------------------------------------------------
    # Playwright
    # --------------------------------------------------

    HEADLESS: bool = _to_bool(
        os.getenv("HEADLESS"),
        True,
    )

    # --------------------------------------------------
    # Paths
    # --------------------------------------------------

    EXPORT_PATH: Path = BASE_DIR / os.getenv(
        "EXPORT_PATH",
        "exports",
    )

    SCREENSHOT_PATH: Path = BASE_DIR / os.getenv(
        "SCREENSHOT_PATH",
        "screenshots",
    )

    RUNS_PATH: Path = BASE_DIR / os.getenv(
        "RUNS_PATH",
        "runs",
    )

    # --------------------------------------------------
    # Logging
    # --------------------------------------------------

    LOG_LEVEL: str = os.getenv(
        "LOG_LEVEL",
        "INFO",
    )


config = Config()
