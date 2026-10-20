"""Clean, flat exports derived from a richer research session."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from pathlib import Path

from biz_intel.models import Business

from .session import ResearchSession


RESEARCH_COLUMNS = (
    "name",
    "category",
    "address",
    "city",
    "state",
    "postal_code",
    "phone",
    "phone_status",
    "email",
    "email_status",
    "website",
    "linkedin",
    "instagram",
    "facebook",
    "twitter",
    "medi_cal_dental_enrolled",
    "ownership_assessment",
    "longevity_minimum_years",
    "operational_status",
    "discovery_sources",
    "source_url",
    "evidence_urls",
)


def export_research_session(
    session: ResearchSession,
    destination: str | Path,
    *,
    businesses: Sequence[Business] | None = None,
) -> Path:
    """Write a stable client-facing projection without altering the session."""

    path = Path(destination)
    if path.suffix.casefold() not in {".csv", ".json"}:
        raise ValueError("Research export must use a .csv or .json destination.")
    path.parent.mkdir(parents=True, exist_ok=True)
    selected = session.businesses if businesses is None else businesses
    rows = [_row(business) for business in selected]
    if path.suffix.casefold() == ".json":
        path.write_text(json.dumps(rows, indent=2))
    elif rows:
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=RESEARCH_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
    else:
        path.write_text(",".join(RESEARCH_COLUMNS) + "\n")
    return path


def _row(business: Business) -> dict[str, object]:
    medi_cal = _claim_value(
        business,
        "program.medi_cal_dental_ffs_enrolled",
        default="unknown",
    )
    ownership = _claim_value(
        business,
        "ownership.independence_assessment",
        default="unclear",
    )
    longevity = _claim_value(
        business,
        "business.longevity.minimum_years",
        default="unknown",
    )
    operational_status = _claim_value(
        business,
        "business.operational_status",
        default="unknown",
    )
    evidence_urls = {
        evidence.evidence_url
        for evidence in business.field_provenance.values()
        if evidence.evidence_url
    }
    evidence_urls.update(
        claim.evidence_url for claim in business.claims if claim.evidence_url
    )
    return {
        "name": business.name,
        "category": business.category,
        "address": business.address,
        "city": business.city,
        "state": business.state,
        "postal_code": business.postal_code,
        "phone": business.phone,
        "phone_status": business.phone_status,
        "email": business.email,
        "email_status": business.email_status,
        "website": business.website,
        "linkedin": business.linkedin,
        "instagram": business.instagram,
        "facebook": business.facebook,
        "twitter": business.twitter,
        "medi_cal_dental_enrolled": medi_cal,
        "ownership_assessment": ownership,
        "longevity_minimum_years": longevity,
        "operational_status": operational_status,
        "discovery_sources": " | ".join(
            business.discovery_sources or ((business.source,) if business.source else ())
        ) or "unknown",
        "source_url": business.source_url,
        "evidence_urls": " | ".join(sorted(evidence_urls)),
    }


def _claim_value(business: Business, key: str, *, default: object) -> object:
    return next(
        (claim.value for claim in reversed(business.claims) if claim.key == key),
        default,
    )
