"""
Deduplication strategies.
"""

from __future__ import annotations

from biz_intel.models.business import Business

from .key import business_key


class ExactMatchStrategy:
    """
    Exact-match deduplication.
    """

    def key(
        self,
        business: Business,
    ):

        return business_key(
            business,
        )
