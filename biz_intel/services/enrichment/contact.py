"""
Post-dedup contact enricher.

Fills phone and website for businesses whose source is in the configured set.
Checks a local SQLite cache before making any API call — a known place_id is
never fetched twice within CACHE_TTL_DAYS days.

Supported sources:
  google  — calls Google Place Details API (formatted_phone_number + website)
  yelp    — calls Yelp Business Details API (phone only; Yelp does not expose
             the business website in its public API)
"""

from __future__ import annotations

from dataclasses import replace

import httpx

from biz_intel.config import config
from biz_intel.models.business import Business

from .budget import EnrichmentBudget
from .cache import PlaceDetailsCache

_GOOGLE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
_YELP_DETAILS_URL = "https://api.yelp.com/v3/businesses"


class ContactEnricher:
    """
    The only enricher that spends money. A paid call happens exclusively on a
    cache miss in ``_fetch``; cache hits are free and never count against
    ``max_enrich``. When the budget cap is reached the business is returned
    unenriched (its source value is kept - the cap stops spending, not data).
    """

    def __init__(
        self,
        sources: set[str],
        cache: PlaceDetailsCache,
        budget: EnrichmentBudget | None = None,
    ) -> None:
        self._sources = sources
        self._cache = cache
        self._budget = budget

    def enrich(self, business: Business) -> Business:
        if business.source not in self._sources:
            return business

        if business.phone and business.website:
            return business

        source_id = self._source_id(business)
        if not source_id:
            return business

        cached = self._cache.get(business.source, source_id)
        if cached is not None:
            # Free path: a known place_id never costs twice within the TTL.
            phone, website = cached
        elif self._budget is not None and not self._budget.allows(
            business.source
        ):
            # Budget exhausted: keep the business's source value rather than
            # spending on another details call.
            return business
        else:
            phone, website = self._fetch(business.source, source_id)
            self._cache.set(business.source, source_id, phone, website)
            if self._budget is not None:
                self._budget.record_paid_call(business.source)

        updates = {}
        if phone and not business.phone:
            updates["phone"] = phone
        if website and not business.website:
            updates["website"] = website

        return replace(business, **updates) if updates else business

    def _source_id(self, business: Business) -> str:
        if not business.raw_data:
            return ""
        if business.source == "google":
            return business.raw_data.get("place_id", "")
        if business.source == "yelp":
            return business.raw_data.get("id", "")
        return ""

    def _fetch(self, source: str, source_id: str) -> tuple[str, str]:
        if source == "google":
            return self._fetch_google(source_id)
        if source == "yelp":
            return self._fetch_yelp(source_id)
        return "", ""

    def _fetch_google(self, place_id: str) -> tuple[str, str]:
        resp = httpx.get(
            _GOOGLE_DETAILS_URL,
            params={
                "place_id": place_id,
                "fields": "formatted_phone_number,website",
                "key": config.GOOGLE_PLACES_API_KEY,
            },
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json().get("result", {})
        return (
            result.get("formatted_phone_number", ""),
            result.get("website", ""),
        )

    def _fetch_yelp(self, business_id: str) -> tuple[str, str]:
        resp = httpx.get(
            f"{_YELP_DETAILS_URL}/{business_id}",
            headers={"Authorization": f"Bearer {config.YELP_API_KEY}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return (data.get("display_phone", ""), "")
