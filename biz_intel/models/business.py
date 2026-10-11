"""
Business domain model.
"""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .claim import Claim


@dataclass(frozen=True, slots=True)
class FieldProvenance:
    """Evidence for one observed field value; never a verification claim."""

    source: str
    evidence_url: str
    observed_at: datetime | None
    method: str


@dataclass(slots=True)
class Business:

    # Identity
    name: str = ""
    category: str = ""

    # Location
    address: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""

    # Contact
    phone: str = ""
    email: str = ""
    website: str = ""

    # Socials
    facebook: str = ""
    instagram: str = ""
    linkedin: str = ""
    twitter: str = ""

    # Metrics
    rating: float | None = None
    review_count: int | None = None

    # Metadata
    source: str = ""
    source_url: str = ""
    discovery_sources: tuple[str, ...] = ()
    scraped_at: datetime | None = None
    observed_at: datetime | None = None

    # Delivery quality. These values describe what is known about a record;
    # they do not replace raw business data or imply outreach permission.
    record_status: str = "needs_review"
    quality_reasons: tuple[str, ...] = ()
    email_status: str = "not_found"
    phone_status: str = "not_found"
    field_provenance: dict[str, FieldProvenance] = field(default_factory=dict)

    # Additive source facts. Claims are deliberately distinct from canonical
    # fields so a registry or catalog source cannot silently overwrite an
    # observed business value during optional cross-source composition.
    claims: tuple[Claim, ...] = ()
    source_ids: dict[str, str] = field(default_factory=dict)

    # Original payload
    raw_data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the model as a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "Business":
        """Create a Business from a dictionary."""
        restored = dict(data)
        restored["quality_reasons"] = tuple(restored.get("quality_reasons", ()))
        restored["discovery_sources"] = tuple(restored.get("discovery_sources", ()))
        for key in ("scraped_at", "observed_at"):
            value = restored.get(key)
            if isinstance(value, str):
                restored[key] = datetime.fromisoformat(value)

        raw_provenance = restored.get("field_provenance", {})
        if not isinstance(raw_provenance, dict):
            raise ValueError("Business field_provenance must be a mapping.")
        restored["field_provenance"] = {
            key: value
            if isinstance(value, FieldProvenance)
            else FieldProvenance(
                source=value["source"],
                evidence_url=value["evidence_url"],
                observed_at=(
                    datetime.fromisoformat(value["observed_at"])
                    if isinstance(value.get("observed_at"), str)
                    else value.get("observed_at")
                ),
                method=value["method"],
            )
            for key, value in raw_provenance.items()
        }
        raw_claims = restored.get("claims", ())
        if not isinstance(raw_claims, (list, tuple)):
            raise ValueError("Business claims must be a sequence.")
        restored["claims"] = tuple(
            item if isinstance(item, Claim) else Claim.from_dict(item)
            for item in raw_claims
        )
        return cls(**restored)
