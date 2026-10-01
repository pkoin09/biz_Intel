"""
Yelp Fusion API source.

Uses the Business Search endpoint to find businesses matching a category and
location. Phone is returned directly by the search response; website requires
a separate Business Details call (deferred — see roadmap item 2).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import httpx

from biz_intel.config import config
from biz_intel.core.api_source import BaseApiSource
from biz_intel.models.business import Business

_SEARCH_URL = "https://api.yelp.com/v3/businesses/search"

_YELP_LIMIT_MAX = 50


class YelpSource(BaseApiSource):

    source_name = "yelp"

    def fetch(self) -> Iterator[Business]:
        api_key = config.YELP_API_KEY
        if not api_key:
            raise RuntimeError(
                "YELP_API_KEY is not set. Add it to your .env file."
            )

        headers = {"Authorization": f"Bearer {api_key}"}
        params = self._build_params()

        response = httpx.get(
            _SEARCH_URL,
            headers=headers,
            params=params,
            timeout=15,
        )
        response.raise_for_status()

        for result in response.json().get("businesses", []):
            yield self._to_business(result)

    def _build_params(self) -> dict:
        params: dict = {}
        if self.task.category:
            params["term"] = self.task.category
        if self.task.location:
            loc = ", ".join(
                p for p in (self.task.location.city, self.task.location.state) if p
            )
            if loc:
                params["location"] = loc
        limit = self.task.limit or _YELP_LIMIT_MAX
        params["limit"] = min(limit, _YELP_LIMIT_MAX)
        return params

    def _to_business(self, result: dict) -> Business:
        loc = result.get("location", {})
        categories = result.get("categories", [])
        category = categories[0]["title"] if categories else ""
        rating_raw = result.get("rating")
        review_raw = result.get("review_count")

        return Business(
            name=result.get("name", ""),
            category=category,
            address=loc.get("address1", ""),
            city=loc.get("city", ""),
            state=loc.get("state", ""),
            postal_code=loc.get("zip_code", ""),
            country=loc.get("country", ""),
            phone=result.get("display_phone", ""),
            source="yelp",
            source_url=result.get("url", ""),
            rating=float(rating_raw) if rating_raw is not None else None,
            review_count=int(review_raw) if review_raw is not None else None,
            scraped_at=datetime.now(timezone.utc),
            raw_data=result,
        )
