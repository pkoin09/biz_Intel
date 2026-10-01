"""
Business domain model.
"""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


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
    scraped_at: datetime | None = None
    observed_at: datetime | None = None

    # Delivery quality. These values describe what is known about a record;
    # they do not replace raw business data or imply outreach permission.
    record_status: str = "needs_review"
    quality_reasons: tuple[str, ...] = ()
    email_status: str = "not_found"
    phone_status: str = "not_found"
    field_provenance: dict[str, FieldProvenance] = field(default_factory=dict)

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
        return cls(**data)
