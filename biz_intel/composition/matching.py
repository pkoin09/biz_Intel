"""Conservative, evidence-only matching across explicitly selected sources."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Literal

from biz_intel.models.business import Business

MatchDecision = Literal["matched", "ambiguous", "candidate"]


@dataclass(frozen=True, slots=True)
class RecordReference:
    """A safe pointer to one source observation, without raw payload data."""

    source: str
    record_id: str
    evidence_url: str


@dataclass(frozen=True, slots=True)
class CrossSourceMatch:
    """One link or review candidate between a primary and supplemental source."""

    primary: RecordReference
    supplemental: RecordReference
    decision: MatchDecision
    match_method: str
    matched_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Serializable result for an opt-in composition sidecar."""

    primary_source: str
    supplemental_sources: tuple[str, ...]
    matches: tuple[CrossSourceMatch, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "version": 1,
            "primary_source": self.primary_source,
            "supplemental_sources": list(self.supplemental_sources),
            "counts": {
                decision: sum(match.decision == decision for match in self.matches)
                for decision in ("matched", "ambiguous", "candidate")
            },
            "matches": [asdict(match) for match in self.matches],
        }


class CrossSourceMatcher:
    """Produce conservative links; never mutate or merge ``Business`` values.

    Matching runs only when a job explicitly identifies its primary and
    supplemental sources. Shared named source identifiers are strongest. Exact
    normalized phone and website matches are also eligible, but a primary
    observation with multiple supplemental candidates is always ambiguous.
    Exact name/address pairs remain review candidates rather than auto-links.
    """

    def __init__(self, primary_source: str, supplemental_sources: tuple[str, ...]) -> None:
        self.primary_source = primary_source
        self.supplemental_sources = supplemental_sources

    def match(self, businesses: list[Business]) -> MatchResult:
        primary = [item for item in businesses if item.source == self.primary_source]
        outcomes: list[CrossSourceMatch] = []
        for supplemental_source in self.supplemental_sources:
            supplemental = [item for item in businesses if item.source == supplemental_source]
            for primary_item in primary:
                exact = [
                    (item, _strong_fields(primary_item, item))
                    for item in supplemental
                    if _strong_fields(primary_item, item)
                ]
                if len(exact) == 1:
                    item, fields = exact[0]
                    outcomes.append(_match(primary_item, item, "matched", fields))
                    continue
                if len(exact) > 1:
                    outcomes.extend(
                        _match(primary_item, item, "ambiguous", fields)
                        for item, fields in exact
                    )
                    continue

                candidates = [
                    item for item in supplemental
                    if _same_name_and_address(primary_item, item)
                ]
                outcomes.extend(
                    _match(primary_item, item, "candidate", ("name", "address"))
                    for item in candidates
                )

        return MatchResult(
            primary_source=self.primary_source,
            supplemental_sources=self.supplemental_sources,
            matches=tuple(outcomes),
        )


def _match(
    primary: Business,
    supplemental: Business,
    decision: MatchDecision,
    fields: tuple[str, ...],
) -> CrossSourceMatch:
    method = "exact_" + "_and_".join(fields) if decision != "candidate" else "exact_name_address_candidate"
    return CrossSourceMatch(
        primary=_reference(primary),
        supplemental=_reference(supplemental),
        decision=decision,
        match_method=method,
        matched_fields=fields,
    )


def _reference(business: Business) -> RecordReference:
    if business.source_ids:
        record_id = "|".join(
            f"{key}:{value}" for key, value in sorted(business.source_ids.items())
        )
    elif business.source_url:
        record_id = business.source_url
    else:
        stable_input = "\x1f".join(
            (business.source, business.name, business.address, business.city, business.state)
        )
        record_id = "derived:" + sha256(stable_input.encode()).hexdigest()[:16]
    return RecordReference(
        source=business.source,
        record_id=record_id,
        evidence_url=business.source_url,
    )


def _strong_fields(left: Business, right: Business) -> tuple[str, ...]:
    fields: list[str] = []
    if _shared_source_identifier(left, right):
        fields.append("source_id")
    if _phone(left) and _phone(left) == _phone(right):
        fields.append("phone")
    if _website(left) and _website(left) == _website(right):
        fields.append("website")
    return tuple(fields)


def _shared_source_identifier(left: Business, right: Business) -> bool:
    return any(
        left.source_ids.get(key) == value and bool(value)
        for key, value in right.source_ids.items()
    )


def _phone(business: Business) -> str:
    digits = "".join(character for character in business.phone if character.isdigit())
    return digits[1:] if len(digits) == 11 and digits.startswith("1") else digits


def _website(business: Business) -> str:
    value = business.website.casefold().strip().rstrip("/")
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value.removeprefix("www.")


def _same_name_and_address(left: Business, right: Business) -> bool:
    return all((
        _normalized_text(left.name) == _normalized_text(right.name),
        _normalized_text(left.address) == _normalized_text(right.address),
        _normalized_text(left.city) == _normalized_text(right.city),
        _normalized_text(left.state) == _normalized_text(right.state),
        bool(left.name and left.address and left.city and left.state),
    ))


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().replace(".", " ").split())
