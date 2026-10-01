"""Aggregate, client-safe quality reporting for a classified delivery."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping

from biz_intel.models.business import Business


# These are useful delivery fields, not an export projection.  A client can
# request a smaller projection without losing an honest view of source coverage.
COMPLETENESS_FIELDS = (
    "name",
    "address",
    "city",
    "state",
    "postal_code",
    "phone",
    "email",
    "website",
    "facebook",
    "instagram",
    "linkedin",
    "twitter",
)


def delivery_summary_payload(
    businesses: Iterable[Business],
    *,
    acquired_records: int,
    delivered_records: int,
    pipeline_metrics: Mapping[str, int],
) -> dict[str, object]:
    """Create a compact, raw-payload-free summary for one job output.

    ``acquired_records`` is the count retained from source tasks before the
    shared pipeline. ``classified_records`` is after validation, normalization,
    deduplication, and any permitted enrichment.
    """

    classified = list(businesses)
    status_counts = Counter(item.record_status for item in classified)
    non_accepted_reasons = Counter(
        reason
        for item in classified
        if item.record_status != "accepted"
        for reason in item.quality_reasons
    )
    for item in classified:
        if item.record_status != "accepted" and not item.quality_reasons:
            non_accepted_reasons[f"status:{item.record_status}"] += 1

    total = len(classified)
    return {
        "schema_version": 1,
        "records": {
            "acquired": acquired_records,
            "classified": total,
            "delivered": delivered_records,
        },
        "duplicates_removed": pipeline_metrics.get("duplicates_removed", 0),
        "pipeline_metrics": dict(sorted(pipeline_metrics.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "non_accepted_reason_counts": dict(sorted(non_accepted_reasons.items())),
        "field_completeness": {
            field: _field_completeness(classified, field, total)
            for field in COMPLETENESS_FIELDS
        },
    }


def _field_completeness(
    businesses: list[Business],
    field: str,
    total: int,
) -> dict[str, int | float]:
    present = sum(bool(getattr(item, field)) for item in businesses)
    return {
        "present": present,
        "total": total,
        "percent": round((present / total * 100) if total else 0, 2),
    }
