"""
Google Maps source backed by the Apify google-maps-scraper actor.

Returns name, address, phone, website, rating, and category in a single
actor run — no separate Place Details call required.

Actor: apify/google-maps-scraper
Marketplace: https://apify.com/apify/google-maps-scraper
"""

from __future__ import annotations

from datetime import datetime, timezone

from biz_intel.core.apify_source import BaseApifySource
from biz_intel.models.business import Business

_APIFY_LIMIT_MAX = 200


class GoogleMapsApifySource(BaseApifySource):

    source_name = "google-apify"
    actor_id = "apify/google-maps-scraper"

    def _build_actor_input(self) -> dict:
        query = self._build_query()
        limit = min(self.task.limit or _APIFY_LIMIT_MAX, _APIFY_LIMIT_MAX)
        return {
            "searchStringsArray": [query],
            "maxCrawledPlacesPerSearch": limit,
            "language": "en",
            "maxImages": 0,
            "maxReviews": 0,
        }

    def _build_query(self) -> str:
        parts = []
        if self.task.category:
            parts.append(self.task.category)
        if self.task.location:
            loc = ", ".join(
                p for p in (self.task.location.city, self.task.location.state) if p
            )
            if loc:
                parts.append(f"in {loc}")
        return " ".join(parts)

    def _to_business(self, item: dict) -> Business | None:
        name = item.get("title", "")
        if not name:
            return None

        rating_raw = item.get("totalScore")
        review_raw = item.get("reviewsCount")

        return Business(
            name=name,
            category=item.get("categoryName", ""),
            address=item.get("street", ""),
            city=item.get("city", ""),
            state=item.get("state", ""),
            postal_code=item.get("postalCode", ""),
            country=item.get("countryCode", ""),
            phone=item.get("phone", ""),
            website=item.get("website", ""),
            rating=float(rating_raw) if rating_raw is not None else None,
            review_count=int(review_raw) if review_raw is not None else None,
            source="google-apify",
            source_url=item.get("url", ""),
            scraped_at=datetime.now(timezone.utc),
            raw_data=item,
        )
