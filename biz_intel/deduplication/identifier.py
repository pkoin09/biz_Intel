"""
Identifier-based deduplication strategy.
"""

from __future__ import annotations
from biz_intel.models.business import Business


class IdentifierMatchStrategy:
    """
    Deduplicate using strong business identifiers.
    Priority:
        1. website
        2. email
        3. phone + name
        4. name + address
    """

    def key(
        self,
        business: Business,
    ) -> tuple:

        if business.website:
            return (
                "website",
                business.website,
            )

        if business.email:
            return (
                "email",
                business.email,
            )

        if business.phone and business.name:

            return (
                "phone_name",
                business.phone,
                business.name.lower(),
            )

        return (
            "name_address",
            business.name.lower(),
            business.address.lower(),
        )
