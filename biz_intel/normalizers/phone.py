"""
Phone normalization.
"""

from __future__ import annotations


def normalize_phone(phone: str) -> str:
    """
    Normalize phone numbers to digits only.
    """

    if not phone:
        return ""

    digits = "".join(
        c for c in phone
        if c.isdigit()
    )

    # Reject obviously invalid values
    if len(digits) < 7:
        return ""

    return digits
