"""
Google Places API source.

Uses the Text Search endpoint to find businesses matching a category and
location. Phone and website are not included in Text Search results; use
source_options.google.enrich_details: true in the job YAML to fill them
post-dedup via the ContactEnricher (biz_intel/services/enrichment/contact.py).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import httpx

from biz_intel.config import config
from biz_intel.core.api_source import BaseApiSource
from biz_intel.models.business import Business

_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"

_GENERIC_TYPES = frozenset(
    {
        "point_of_interest",
        "establishment",
        "store",
        "food",
        "health",
        "finance",
        "local_government_office",
        "political",
        "sublocality",
        "sublocality_level_1",
        "geocode",
    }
)


class GooglePlacesSource(BaseApiSource):
    """
    Fetches businesses from the Google Places Text Search API.
    """

    source_name = "google"

    def fetch(self) -> Iterator[Business]:
        api_key = config.GOOGLE_PLACES_API_KEY
        if not api_key:
            raise RuntimeError(
                "GOOGLE_PLACES_API_KEY is not set. Add it to your .env file."
            )

        query = self._build_query()
        limit = self.task.limit or 10

        response = httpx.get(
            _TEXT_SEARCH_URL,
            params={"query": query, "key": api_key},
            timeout=15,
        )
        response.raise_for_status()

        data = response.json()
        status = data.get("status", "UNKNOWN_ERROR")

        if status == "ZERO_RESULTS":
            return

        if status != "OK":
            raise RuntimeError(f"Google Places API returned status: {status}")

        for result in data.get("results", [])[:limit]:
            yield self._to_business(result)

    def _build_query(self) -> str:
        parts = []
        if self.task.category:
            parts.append(self.task.category)
        if self.task.location:
            loc = ", ".join(
                p
                for p in (self.task.location.city, self.task.location.state)
                if p
            )
            if loc:
                parts.append(f"in {loc}")
        return " ".join(parts)

    def _to_business(self, result: dict) -> Business:
        address, city, state, postal_code, country = _parse_address(
            result.get("formatted_address", "")
        )

        types = result.get("types", [])
        category = next(
            (
                t.replace("_", " ").title()
                for t in types
                if t not in _GENERIC_TYPES
            ),
            "",
        )

        rating_raw = result.get("rating")
        review_raw = result.get("user_ratings_total")

        return Business(
            name=result.get("name", ""),
            category=category,
            address=address,
            city=city,
            state=state,
            postal_code=postal_code,
            country=country,
            rating=float(rating_raw) if rating_raw is not None else None,
            review_count=int(review_raw) if review_raw is not None else None,
            source="google",
            source_url=_TEXT_SEARCH_URL,
            scraped_at=datetime.now(timezone.utc),
            raw_data=result,
        )



def _parse_address(formatted: str) -> tuple[str, str, str, str, str]:
    """
    Best-effort parse of a Google formatted_address into components.

    Handles the typical US form: "Street, City, State ZIP, Country".
    Falls back to putting the full string in address if the shape is unexpected.
    """
    parts = [p.strip() for p in formatted.split(",")]

    if len(parts) == 4:
        # "123 Main St, San Jose, CA 95110, USA"
        address = parts[0]
        city = parts[1]
        state_zip = parts[2].split()
        state = state_zip[0] if state_zip else ""
        postal_code = state_zip[1] if len(state_zip) > 1 else ""
        country = parts[3]
    elif len(parts) == 3:
        # "San Jose, CA 95110, USA" — no street-level address
        address = ""
        city = parts[0]
        state_zip = parts[1].split()
        state = state_zip[0] if state_zip else ""
        postal_code = state_zip[1] if len(state_zip) > 1 else ""
        country = parts[2]
    else:
        address = formatted
        city = state = postal_code = country = ""

    return address, city, state, postal_code, country
