"""
Email normalization.
"""

from __future__ import annotations


def normalize_email(email: str) -> str:
    if not email:
        return ""
    return email.strip().lower()
