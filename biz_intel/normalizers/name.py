"""
Business name normalization.
"""

from __future__ import annotations

from biz_intel.normalizers.helpers.text import normalize_text


def normalize_name(value: str) -> str:
    """
    Normalize business names.
    """

    if not value:
        return ""

    return normalize_text(value)
