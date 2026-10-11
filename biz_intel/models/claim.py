"""Additive, evidence-backed source claims for canonical business records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TypeAlias


ClaimValue: TypeAlias = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class Claim:
    """One source observation that does not overwrite a canonical field.

    Claims keep source-specific facts such as a registry status or license
    expiration separate from ``Business`` identity/contact fields. Multiple
    sources may make competing claims about the same key; later composition
    decides whether any claim is a match or is eligible for promotion.
    """

    key: str
    value: ClaimValue
    source: str
    source_record_id: str
    evidence_url: str
    observed_at: datetime | None = None
    method: str = "source_observation"
    authority: str = "supplemental"

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("Claim key is required.")
        if not self.source:
            raise ValueError("Claim source is required.")
        if not self.source_record_id:
            raise ValueError("Claim source_record_id is required.")
        if not self.evidence_url:
            raise ValueError("Claim evidence_url is required.")
        if not self.method:
            raise ValueError("Claim method is required.")
        if not self.authority:
            raise ValueError("Claim authority is required.")

    @classmethod
    def from_dict(cls, data: object) -> "Claim":
        """Restore a checkpoint-safe claim mapping without accepting raw data."""

        if not isinstance(data, dict):
            raise ValueError("Claim must be a mapping.")
        restored = dict(data)
        observed_at = restored.get("observed_at")
        if observed_at is not None:
            if isinstance(observed_at, datetime):
                pass
            elif not isinstance(observed_at, str):
                raise ValueError("Claim observed_at must be an ISO timestamp.")
            else:
                restored["observed_at"] = datetime.fromisoformat(observed_at)
        return cls(**restored)
