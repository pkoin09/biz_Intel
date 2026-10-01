"""
Per-source enrichment cost budget.

``max_enrich`` caps the number of *paid* contact-details API calls a run will
make per source (Google Place Details, Yelp Business Details). It is the only
core cost knob (a free run is always possible: set nothing and no cap, or zero
contact-enrichment sources, and the spend is $0).

Pricing model (decision 18):

- Cache hits are **free** - they never count against the cap and never spend.
- A cap is required for every paid source. An omitted cap permits zero paid
  calls. This prevents a typo or incomplete job definition from silently
  creating an unbounded spend.
- When the cap is hit the business is **returned unenriched**, never dropped -
  the source value is kept even though enrichment stopped. The cap stops
  *spending*, not *data*.

Free-tier auto-clamping (google's monthly credit, yelp's daily quota) is out of
scope here - it arrives with the generic CostModel later. Until then spending
is reported as an **estimate**: paid_calls is exact; estimated_spend treats
every paid call as billable (no free-tier deduction), so it is an upper bound.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Per-call USD estimates for the paid contact-details endpoints. These are
# planning figures, not billing truth - kept here so the cost section can show
# a number without coupling job definitions to source pricing. Free-tier
# accounting (the credit that makes the first chunk of calls free) is a later
# concern; until it lands these over-estimate spend on purpose.
ESTIMATED_COST_PER_CALL = {
    "google": 0.02,  # ~$20 / 1k Place Details calls
    "yelp": 0.02,  # ~$20 / 1k beyond the free tier (verify current)
}


@dataclass(slots=True)
class CostLine:
    """Cost incurred for one source during a run's enrichment."""

    source: str
    paid_calls: int = 0
    capped: bool = False

    @property
    def estimated_unit_cost(self) -> float:
        return ESTIMATED_COST_PER_CALL.get(self.source, 0.0)

    @property
    def estimated_spend(self) -> float:
        return round(self.paid_calls * self.estimated_unit_cost, 2)


@dataclass(slots=True)
class EnrichmentBudget:
    """
    Counts paid contact-details calls per source and clamps at ``max_enrich``.

    Built once per run from ``job.source_options``; consulted on every cache
    *miss* in ContactEnricher.
    """

    _caps: dict[str, int] = field(default_factory=dict)  # source -> max_enrich
    _spent: dict[str, int] = field(default_factory=dict)  # source -> paid calls

    @classmethod
    def from_source_options(
        cls,
        source_options: dict[str, dict],
        sources: set[str],
    ) -> "EnrichmentBudget":
        caps: dict[str, int] = {}
        for source in sources:
            cap = source_options.get(source, {}).get("max_enrich")
            # JobSpec validates this shape before the runner is constructed.
            caps[source] = int(cap) if cap is not None else 0
        return cls(caps)

    def allows(self, source: str) -> bool:
        """Whether another paid call is permitted for ``source``."""
        cap = self._caps.get(source, 0)
        return self._spent.get(source, 0) < cap

    def record_paid_call(self, source: str) -> None:
        self._spent[source] = self._spent.get(source, 0) + 1

    def was_capped(self, source: str) -> bool:
        cap = self._caps.get(source, 0)
        return self._spent.get(source, 0) >= cap

    def cost_line(self, source: str) -> CostLine:
        return CostLine(
            source=source,
            paid_calls=self._spent.get(source, 0),
            capped=self.was_capped(source),
        )

    def cost_lines(self) -> list[CostLine]:
        # Every paid-enrichment source, including a deliberate zero-call cap.
        return [self.cost_line(source) for source in sorted(self._caps)]
