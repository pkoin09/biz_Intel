"""
Enrichment runner — runs post-dedup enrichers over a list of Business records.

Built from a JobSpec via EnrichmentRunner.from_job():
  - ContactEnricher is added for any source where source_options.{source}.enrich_details = true
  - SocialEnricher is added when job.processing.enrich = true
"""

from __future__ import annotations

from biz_intel.config import config
from biz_intel.models.business import Business

from .budget import EnrichmentBudget
from .cache import PlaceDetailsCache
from .contact import ContactEnricher
from .social import SocialEnricher


class EnrichmentRunner:

    def __init__(
        self,
        enrichers: list,
        budget: EnrichmentBudget | None = None,
    ) -> None:
        self._enrichers = enrichers
        self.budget = budget

    def run(self, businesses: list[Business]) -> list[Business]:
        if not self._enrichers:
            return businesses
        result = []
        for business in businesses:
            for enricher in self._enrichers:
                business = enricher.enrich(business)
            result.append(business)
        return result

    @classmethod
    def from_job(
        cls,
        job,
        source_policies: dict[str, object] | None = None,
    ) -> "EnrichmentRunner":
        enrichers: list = []
        budget: EnrichmentBudget | None = None

        sources_to_enrich = {
            source_name
            for source_name in job.sources
            if job.source_options.get(source_name, {}).get("enrich_details", False)
        }
        if sources_to_enrich:
            budget = EnrichmentBudget.from_source_options(
                job.source_options,
                sources_to_enrich,
            )
            retention_days_by_source = {
                name: getattr(policy, "runtime_cache_ttl_days", 0)
                for name, policy in (source_policies or {}).items()
            }
            cache = PlaceDetailsCache(
                config.CACHE_PATH / "place_details.db",
                retention_days_by_source,
            )
            enrichers.append(ContactEnricher(sources_to_enrich, cache, budget))

        if job.processing.enrich:
            enrichers.append(SocialEnricher())

        return cls(enrichers, budget=budget)
