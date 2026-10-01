"""
Website normalization.
"""

from __future__ import annotations

from urllib.parse import urlparse


def normalize_website(url: str) -> str:
    """
    Normalize website URLs into a canonical domain.
    """

    if not url:
        return ""

    url = url.strip().lower()

    # Remove common bad imports
    url = url.replace("[", "")
    url = url.replace("]", "")

    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)

    domain = parsed.netloc

    # Remove www.
    if domain.startswith("www."):
        domain = domain[4:]

    return domain.rstrip("/")
