"""
CSV extractor.
"""

from __future__ import annotations

from datetime import datetime

from biz_intel.models.business import Business
from . import SOURCE_NAME

class CSVExtractor:
    """
    Convert CSV rows into Business models.
    """

    def extract(
        self,
        row: dict[str, str],
    ) -> Business:

        return Business(
            #
            # Identity
            #

            # name=row.get("business_name", ""),
            name=row.get("business_name", row.get("name", "")),
            category=row.get("category", ""),

            #
            # Address
            #
            address=row.get("address", ""),
            city=row.get("city", ""),
            state=row.get("state", ""),
            postal_code=row.get("zip", ""),
            country=row.get("country", ""),

            #
            # Contact
            #
            phone=row.get("phone", ""),
            email=row.get("email", ""),
            website=row.get("website", ""),

            #
            # Social
            #
            facebook="",
            instagram="",
            linkedin="",
            twitter="",

            #
            # Metrics
            #
            rating=row.get("rating", ""),
            review_count=row.get("reviews", ""),

            #
            # Metadata
            #
            # source="csv",
            source=SOURCE_NAME,
            source_url=row.get("source_url", ""),
            observed_at=_parse_observed_at(row.get("observed_at", "")),
            raw_data=row,
        )


def _parse_observed_at(value: str) -> datetime | None:
    """Keep a client-supplied ISO observation time when it is well formed."""

    try:
        return datetime.fromisoformat(value) if value.strip() else None
    except ValueError:
        return None
