"""Attach a supplemental result set to a durable research session."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from biz_intel.composition import CrossSourceMatcher
from biz_intel.models import Business, FieldProvenance

from .importer import load_business_records
from .session import CompositionStep, ResearchSession


def compose_research_session(
    session: ResearchSession,
    source_file: str | Path,
    *,
    source: str | None = None,
) -> CompositionStep:
    """Match supplemental records and promote only safe, missing websites."""

    path = Path(source_file)
    supplemental = load_business_records(path)
    source_name = (source or _single_source(supplemental) or path.stem).strip()
    if not source_name:
        raise ValueError("A supplemental source name is required.")
    for business in supplemental:
        if not business.source:
            business.source = source_name
        elif business.source != source_name:
            raise ValueError(
                "Supplemental records must use one source; pass --source only for "
                "rows without a source."
            )

    primary_source = _primary_source(session.businesses)
    result = CrossSourceMatcher(primary_source, (source_name,)).match(
        [*session.businesses, *supplemental]
    )
    supplemental_by_id = {_record_id(item): item for item in supplemental}
    primary_by_id = {_record_id(item): item for item in session.businesses}
    website_count = 0
    contact_count = 0
    for match in result.matches:
        if match.decision != "matched":
            continue
        primary = primary_by_id.get(match.primary.record_id)
        addition = supplemental_by_id.get(match.supplemental.record_id)
        if (
            primary is None
            or addition is None
            or not _safe_field_promotion(primary, addition, match.matched_fields)
        ):
            continue
        promoted = False
        if not primary.website and addition.website:
            primary.website = addition.website
            primary.field_provenance["website"] = _composition_evidence(
                addition, source_name, addition.website
            )
            website_count += 1
            promoted = True
        if source_name == "manual_first_party_review":
            for field in ("email", "linkedin", "instagram", "facebook", "twitter"):
                value = getattr(addition, field)
                if getattr(primary, field) or not value:
                    continue
                setattr(primary, field, value)
                primary.field_provenance[field] = _composition_evidence(
                    addition, source_name, addition.website
                )
                if field == "email":
                    primary.email_status = "not_checked"
                contact_count += 1
                promoted = True
        if promoted:
            primary.discovery_sources = tuple(
                dict.fromkeys((*primary.discovery_sources, primary.source, source_name))
            )

    counts = {
        decision: sum(match.decision == decision for match in result.matches)
        for decision in ("matched", "ambiguous", "candidate")
    }
    step = CompositionStep(
        source=source_name,
        source_file=str(path),
        record_count=len(supplemental),
        matched_count=counts["matched"],
        ambiguous_count=counts["ambiguous"],
        candidate_count=counts["candidate"],
        website_count=website_count,
        applied_at=datetime.now(timezone.utc),
        contact_count=contact_count,
        matches=tuple(asdict(match) for match in result.matches),
    )
    session.compositions.append(step)
    return step


def _single_source(businesses: list[Business]) -> str:
    sources = {business.source for business in businesses if business.source}
    if len(sources) > 1:
        raise ValueError("Supplemental records must use one source.")
    return next(iter(sources), "")


def _primary_source(businesses: list[Business]) -> str:
    sources = {business.source for business in businesses if business.source}
    if len(sources) != 1:
        raise ValueError("A research session must have one primary source for composition.")
    return next(iter(sources))


def _record_id(business: Business) -> str:
    if business.source_ids:
        return "|".join(
            f"{key}:{value}" for key, value in sorted(business.source_ids.items())
        )
    if business.source_url:
        return business.source_url
    stable_input = "\x1f".join(
        (business.source, business.name, business.address, business.city, business.state)
    )
    return "derived:" + sha256(stable_input.encode()).hexdigest()[:16]


def _safe_field_promotion(
    primary: Business,
    supplemental: Business,
    matched_fields: tuple[str, ...],
) -> bool:
    """Require identity corroboration before changing a canonical contact field."""

    if "source_id" in matched_fields:
        return True
    return "phone" in matched_fields and all(
        (
            _text(primary.name) == _text(supplemental.name),
            _text(primary.address) == _text(supplemental.address),
            _text(primary.city) == _text(supplemental.city),
            _text(primary.state) == _text(supplemental.state),
            bool(primary.name and primary.address and primary.city and primary.state),
        )
    )


def _composition_evidence(
    addition: Business,
    source_name: str,
    fallback_url: str,
) -> FieldProvenance:
    return FieldProvenance(
        source=source_name,
        evidence_url=addition.source_url or fallback_url,
        observed_at=addition.observed_at or addition.scraped_at,
        method="cross_source_exact_match",
    )


def _text(value: str) -> str:
    return " ".join(value.casefold().replace(".", " ").split())
