"""Conservative quality classification for client business deliveries."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from biz_intel.models.business import Business, FieldProvenance


STANDARD_PROFILE = "standard"
RECORD_STATUSES = frozenset(
    {
        "accepted",
        "incomplete",
        "closed",
        "out_of_scope",
        "duplicate",
        "needs_review",
    }
)
_TERMINAL_STATUSES = RECORD_STATUSES - {"accepted", "incomplete", "needs_review"}
_OBSERVABLE_FIELDS = (
    "name",
    "category",
    "address",
    "city",
    "state",
    "postal_code",
    "country",
    "phone",
    "email",
    "website",
    "facebook",
    "instagram",
    "linkedin",
    "twitter",
    "rating",
    "review_count",
)


@dataclass(frozen=True, slots=True)
class DeliverySummary:
    """Classified records plus a count suitable for a run manifest."""

    businesses: list[Business]
    status_counts: dict[str, int]


class DeliveryContract:
    """Apply the V1 ``standard`` acceptance rules without dropping records."""

    def __init__(
        self,
        profile: str = STANDARD_PROFILE,
        max_age_days: int | None = None,
    ) -> None:
        if profile != STANDARD_PROFILE:
            raise ValueError(f"Unsupported delivery profile: {profile}.")
        if max_age_days is not None and max_age_days < 1:
            raise ValueError("max_age_days must be a positive integer.")
        self.profile = profile
        self.max_age_days = max_age_days

    def classify(self, businesses: list[Business]) -> DeliverySummary:
        classified = [self.classify_business(business) for business in businesses]
        return DeliverySummary(
            businesses=classified,
            status_counts=dict(sorted(Counter(item.record_status for item in classified).items())),
        )

    def classify_business(self, business: Business) -> Business:
        observed_at = business.observed_at or business.scraped_at
        if observed_at is not None and observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        provenance = dict(business.field_provenance)
        if observed_at:
            business = replace(business, observed_at=observed_at)

        provenance = _fill_source_provenance(business, provenance)
        business = replace(business, field_provenance=provenance)

        if business.record_status in _TERMINAL_STATUSES:
            return business
        if business.record_status not in RECORD_STATUSES:
            return replace(
                business,
                record_status="needs_review",
                quality_reasons=("unknown_record_status",),
            )

        reasons = _standard_missing_requirements(business)
        if self._is_stale(business.observed_at):
            reasons.append("stale_observation")
        return replace(
            business,
            record_status="accepted" if not reasons else "incomplete",
            quality_reasons=tuple(reasons),
        )

    def _is_stale(self, observed_at: datetime | None) -> bool:
        if self.max_age_days is None or observed_at is None:
            return False
        return observed_at < datetime.now(timezone.utc) - timedelta(
            days=self.max_age_days
        )


def _standard_missing_requirements(business: Business) -> list[str]:
    reasons: list[str] = []
    if not business.name:
        reasons.append("missing_name")
    if not _has_location(business):
        reasons.append("missing_location")
    if not (business.phone or business.website):
        reasons.append("missing_phone_or_website")
    if not business.source_url:
        reasons.append("missing_source_url")
    if not business.observed_at:
        reasons.append("missing_observed_at")
    return reasons


def _has_location(business: Business) -> bool:
    return bool(business.address and (business.city or business.state)) or bool(
        business.city and business.state
    )


def _fill_source_provenance(
    business: Business,
    existing: dict[str, FieldProvenance],
) -> dict[str, FieldProvenance]:
    """Record source-level evidence only when the source supplied a URL/time."""

    if not (business.source and business.source_url and business.observed_at):
        return existing

    fallback = FieldProvenance(
        source=business.source,
        evidence_url=business.source_url,
        observed_at=business.observed_at,
        method="source_observation",
    )
    for field in _OBSERVABLE_FIELDS:
        if getattr(business, field) not in (None, ""):
            existing.setdefault(field, fallback)
    return existing


def provenance_payload(business: Business) -> dict[str, object]:
    """Return safe evidence data for a sidecar, excluding raw provider payloads."""

    return {
        "name": business.name,
        "record_status": business.record_status,
        "field_provenance": {
            field: {
                "source": evidence.source,
                "evidence_url": evidence.evidence_url,
                "observed_at": _timestamp(evidence.observed_at),
                "method": evidence.method,
            }
            for field, evidence in sorted(business.field_provenance.items())
        },
    }


def quality_payload(business: Business) -> dict[str, object]:
    return {
        "name": business.name,
        "record_status": business.record_status,
        "quality_reasons": list(business.quality_reasons),
        "email_status": business.email_status,
        "phone_status": business.phone_status,
        "observed_at": _timestamp(business.observed_at),
    }


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
