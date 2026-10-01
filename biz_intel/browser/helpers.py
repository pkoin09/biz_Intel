"""
General browser helper functions.
"""

from __future__ import annotations

import random
import re
from datetime import datetime


def random_delay(
    minimum: int = 750,
    maximum: int = 2000,
) -> int:
    """
    Returns a random delay in milliseconds.
    """

    return random.randint(
        minimum,
        maximum,
    )


def slugify(text: str) -> str:
    """
    Convert text into a filesystem-safe slug.
    """

    text = text.lower()

    text = re.sub(
        r"[^a-z0-9]+",
        "-",
        text,
    )

    return text.strip("-")


def timestamp() -> str:
    """
    Current timestamp.
    """

    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def screenshot_name(
    business_name: str,
) -> str:
    """
    Example:

    abc-coffee_20260703_181500.png
    """

    return f"{slugify(business_name)}" f"_{timestamp()}.png"
