"""
Business deduplication keys.
"""

from __future__ import annotations

from biz_intel.models.business import Business


def business_key(
    business: Business,
) -> tuple[str, str, str]:
    """
    Return the canonical deduplication key.

    Version 1:
        name + address + phone
    """

    return (
        business.name.lower(),
        business.address.lower(),
        business.phone,
    )
