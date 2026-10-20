"""Discovery and selection of saved research sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

from biz_intel.models import Business

from .session import RefinementStep, ResearchSession


@dataclass(frozen=True, slots=True)
class SavedResearchSession:
    """A valid saved session and the metadata needed by the CLI."""

    path: Path
    session: ResearchSession
    modified_at: datetime


def list_research_sessions(directory: str | Path) -> list[SavedResearchSession]:
    """Return valid session JSON files, most recently modified first."""

    root = Path(directory)
    if not root.is_dir():
        return []

    saved: list[SavedResearchSession] = []
    for path in root.glob("*.json"):
        try:
            session = ResearchSession.load(path)
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except (OSError, ValueError):
            continue
        saved.append(SavedResearchSession(path, session, modified_at))

    return sorted(saved, key=lambda item: (item.modified_at, item.path.name), reverse=True)


def select_latest_research_session(
    directory: str | Path,
    position: int = 1,
) -> SavedResearchSession:
    """Select a one-based entry from the same ordering shown by ``sessions``."""

    if position < 1:
        raise ValueError("--latest must be 1 or greater.")
    sessions = list_research_sessions(directory)
    if position > len(sessions):
        raise ValueError(
            f"Requested session {position}, but only {len(sessions)} saved session(s) exist."
        )
    return sessions[position - 1]


def latest_refinement_records(session: ResearchSession) -> list[Business]:
    """Return records satisfying every plugin from the latest instruction."""

    steps = latest_refinement_steps(session)
    if not steps:
        return session.businesses
    return [
        business
        for business in session.businesses
        if all(_matches_refinement(business, step.plugin, step.instruction) for step in steps)
    ]


def latest_refinement_steps(session: ResearchSession) -> list[RefinementStep]:
    """Return the distinct plugin steps from the latest CLI invocation."""

    if not session.refinements:
        return []
    latest_instruction = session.refinements[-1].instruction
    steps = []
    seen_plugins: set[str] = set()
    for step in reversed(session.refinements):
        if step.instruction != latest_instruction or step.plugin in seen_plugins:
            break
        seen_plugins.add(step.plugin)
        steps.append(step)
    steps.reverse()
    return steps


def research_session_summary(session: ResearchSession) -> dict[str, int]:
    """Return compact, evidence-aware coverage counts for one session."""

    return {
        "total_records": len(session.businesses),
        "latest_matches": len(latest_refinement_records(session)),
        "with_phone": sum(bool(business.phone) for business in session.businesses),
        "with_website": sum(bool(business.website) for business in session.businesses),
        "with_email": sum(bool(business.email) for business in session.businesses),
        "with_social": sum(
            any((business.linkedin, business.instagram, business.facebook, business.twitter))
            for business in session.businesses
        ),
        "medi_cal_dental_enrolled": _claim_count(
            session, "program.medi_cal_dental_ffs_enrolled", True
        ),
        "likely_independent": _claim_count(
            session, "ownership.independence_assessment", "likely_independent"
        ),
        "likely_corporate": _claim_count(
            session, "ownership.independence_assessment", "likely_corporate"
        ),
        "with_longevity_evidence": sum(
            any(claim.key == "business.longevity.minimum_years" for claim in business.claims)
            for business in session.businesses
        ),
        "explicitly_closed": _claim_count(
            session, "business.operational_status", "closed"
        ),
    }


def _claim_count(session: ResearchSession, key: str, value: object) -> int:
    return sum(
        any(claim.key == key and claim.value == value for claim in business.claims)
        for business in session.businesses
    )


def _matches_refinement(business: Business, plugin: str, instruction: str) -> bool:
    """Interpret only the small, explicit criteria understood by each plugin."""

    if plugin == "medi-cal-dental-enrollment":
        return any(
            claim.key == "program.medi_cal_dental_ffs_enrolled" and claim.value is True
            for claim in business.claims
        )
    if plugin == "ownership-evidence":
        lowered = instruction.casefold()
        expected = (
            "likely_independent"
            if any(
                phrase in lowered
                for phrase in (
                    "family owned",
                    "family-owned",
                    "independent",
                    "locally owned",
                    "locally-owned",
                    "not corporate",
                    "not a corporation",
                    "not corporation",
                )
            )
            else "likely_corporate"
        )
        return any(
            claim.key == "ownership.independence_assessment" and claim.value == expected
            for claim in business.claims
        )
    if plugin == "longevity-evidence":
        threshold_match = re.search(r"\b(\d{1,3})\s*\+?\s*years?\b", instruction)
        threshold = int(threshold_match.group(1)) if threshold_match else 10
        return any(
            claim.key == "business.longevity.minimum_years"
            and isinstance(claim.value, (int, float))
            and claim.value >= threshold
            for claim in business.claims
        )
    if plugin == "public-email":
        return bool(business.email)
    if plugin == "operational-status-evidence":
        return any(
            claim.key == "business.operational_status" and claim.value == "closed"
            for claim in business.claims
        )
    if plugin == "public-socials":
        return any((business.linkedin, business.instagram, business.facebook, business.twitter))
    return True
