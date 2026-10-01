"""
Text normalization helpers.
"""

from __future__ import annotations

import unicodedata


def normalize_text(value: str) -> str:
    """
    Normalize general text fields.
    """

    if not value:
        return ""

    value = unicodedata.normalize(
        "NFKC",
        value,
    )

    value = value.strip()

    value = " ".join(value.split())

    return value
