"""
Address normalization.
"""

from __future__ import annotations


def normalize_address(address: str) -> str:

    if not address:
        return ""

    return " ".join(address.split())
