"""
Yelp source backed by an Apify actor.

Returns name, address, phone, website, rating, and category in a single
actor run. The normalizer accepts both the original ``maxcopell`` record
shape and the ``headply`` record shape used by the offline fixtures.

Actor: maxcopell/yelp-scraper
Marketplace: https://apify.com/maxcopell/yelp-scraper
Note: verify actor ID on the Apify marketplace — community actors can change.
"""

from __future__ import annotations

from datetime import datetime, timezone

from biz_intel.core.apify_source import BaseApifySource
from biz_intel.models.business import Business

_APIFY_LIMIT_MAX = 100


class YelpApifySource(BaseApifySource):

    source_name = "yelp-apify"
    actor_id = "maxcopell/yelp-scraper"

    def _build_actor_input(self) -> dict:
        limit = min(self.task.limit or _APIFY_LIMIT_MAX, _APIFY_LIMIT_MAX)
        location = ""
        if self.task.location:
            location = ", ".join(
                p for p in (self.task.location.city, self.task.location.state) if p
            )
        return {
            "term": self.task.category or "",
            "location": location,
            "maxItems": limit,
        }

    def _to_business(self, item: dict) -> Business | None:
        name = _as_text(item.get("name"))
        if not name:
            return None

        location = item.get("location")
        address = item.get("address")
        # The original actor uses ``location``; headply uses ``address``.
        loc = location if isinstance(location, dict) else address
        loc = loc if isinstance(loc, dict) else {}

        return Business(
            name=name,
            category=_first_category(item.get("categories")),
            address=_as_text(loc.get("address1") or loc.get("street")),
            city=_as_text(loc.get("city")),
            state=_as_text(loc.get("state") or loc.get("region")),
            postal_code=_as_text(loc.get("zipCode") or loc.get("postalCode")),
            country=_as_text(loc.get("country")),
            phone=_as_text(item.get("phone")),
            website=_as_text(item.get("website")),
            rating=_as_float(item.get("rating")),
            review_count=_as_int(item.get("reviewCount")),
            source="yelp-apify",
            source_url=_as_text(item.get("url")),
            scraped_at=datetime.now(timezone.utc),
            raw_data=item,
        )


def _as_text(value: object) -> str:
    """Return a safe string for optional actor fields."""
    return value.strip() if isinstance(value, str) else ""


def _first_category(categories: object) -> str:
    """Normalize legacy Yelp category objects and headply category strings."""
    if not isinstance(categories, list) or not categories:
        return ""

    first = categories[0]
    if isinstance(first, str):
        return first.strip()
    if isinstance(first, dict):
        return _as_text(first.get("title"))
    return ""


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
