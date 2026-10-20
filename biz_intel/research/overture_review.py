"""Read-only comparison of a verified Overture snapshot with a research session."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from biz_intel.composition import CrossSourceMatcher
from biz_intel.models import Business
from biz_intel.sources.overture import OvertureSnapshotSource

from .composition import _record_id
from .session import ResearchSession


def review_overture_snapshot(
    session: ResearchSession,
    snapshot: str | Path,
    *,
    limit: int = 20,
    offset: int = 0,
    decision: str | None = None,
) -> dict[str, object]:
    """Return a bounded match preview without changing either input."""

    if limit < 1:
        raise ValueError("Overture review limit must be 1 or greater.")
    if offset < 0:
        raise ValueError("Overture review offset cannot be negative.")
    if decision not in {None, "matched", "candidate", "ambiguous"}:
        raise ValueError("Overture review decision must be matched, candidate, or ambiguous.")
    primary_sources = {business.source for business in session.businesses if business.source}
    if len(primary_sources) != 1:
        raise ValueError("A research session must have one primary source for review.")
    candidates = list(OvertureSnapshotSource(snapshot).extract())
    result = CrossSourceMatcher(next(iter(primary_sources)), ("overture",)).match(
        [*session.businesses, *candidates]
    )
    primary_by_id = {_record_id(business): business for business in session.businesses}
    candidate_by_id = {_record_id(business): business for business in candidates}
    counts = Counter(match.decision for match in result.matches)
    order = {"matched": 0, "candidate": 1, "ambiguous": 2}
    matches = sorted(
        result.matches,
        key=lambda match: (
            order[match.decision],
            match.primary.record_id,
            match.supplemental.record_id,
        ),
    )
    selected_matches = [
        match for match in matches if decision is None or match.decision == decision
    ]
    return {
        "snapshot": str(Path(snapshot)),
        "delivery_approved": False,
        "candidate_records": len(candidates),
        "counts": {
            decision: counts[decision]
            for decision in ("matched", "candidate", "ambiguous")
        },
        "selection": {
            "decision": decision or "all",
            "offset": offset,
            "limit": limit,
            "available": len(selected_matches),
        },
        "preview": [
            _preview_row(
                primary_by_id[match.primary.record_id],
                candidate_by_id[match.supplemental.record_id],
                match.decision,
                match.match_method,
            )
            for match in selected_matches[offset : offset + limit]
        ],
    }


def _preview_row(
    primary: Business,
    candidate: Business,
    decision: str,
    method: str,
) -> dict[str, object]:
    return {
        "decision": decision,
        "method": method,
        "primary": {
            "name": primary.name,
            "address": primary.address,
            "phone": primary.phone,
            "website": primary.website or None,
            "source_ids": dict(primary.source_ids),
        },
        "overture": {
            "name": candidate.name,
            "address": candidate.address,
            "phone": candidate.phone,
            "website": candidate.website or None,
            "overture_id": candidate.source_ids.get("overture_id"),
        },
    }
