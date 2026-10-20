"""Minimal contract for a plugin that refines an existing result set."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import re
from typing import Protocol
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from biz_intel.models.business import Business
from biz_intel.models.claim import Claim
from biz_intel.services.enrichment.social import FirstPartyWebsiteCrawler, SocialEnricher


_MEDI_CAL_DENTAL_LAYER = (
    "https://services7.arcgis.com/7MUwsS9z05YumJRZ/arcgis/rest/services/"
    "MediCal_Dental_FFS_Provider_Listing/FeatureServer/0"
)
_MEDI_CAL_DENTAL_DATASET = (
    "https://data.ca.gov/dataset/medical-dental-ffs-provider-listing"
)

_INDEPENDENT_PHRASES = {
    "family owned": "family_owned",
    "family-owned": "family_owned",
    "independently owned": "independently_owned",
    "independent practice": "independent_practice",
    "locally owned": "locally_owned",
}
_CORPORATE_PHRASES = {
    "dental support organization": "dental_support_organization",
    "corporate office": "corporate_office",
    "nationwide network": "nationwide_network",
    "locations nationwide": "locations_nationwide",
}
_FOUNDED_YEAR = re.compile(r"\b(?:founded|established|since)\s+(?:in\s+)?((?:18|19|20)\d{2})\b", re.I)
_OPENED_YEAR = re.compile(
    r"\bopened\b.{0,80}?\b(?:office|practice|business)\b.{0,30}?"
    r"\b(?:in\s+)?((?:18|19|20)\d{2})\b",
    re.I,
)
_YEARS_SERVING = re.compile(
    r"\b(?:serving|served)\b.{0,80}?\b(?:for\s+)?(?:over|more than)?\s*(\d{1,3})\+?\s+years\b",
    re.I,
)
_CLOSED_STATUS = re.compile(
    r"\b(?:office|practice|business)\b.{0,40}?\b(?:officially|permanently)\s+closed\b"
    r"|\bretired\b.{0,120}?\b(?:office|practice|business)\b.{0,40}?\bclosed\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class RefinementResult:
    businesses: list[Business]
    note: str = ""
    details: tuple[dict[str, object], ...] = ()


class RefinementPlugin(Protocol):
    name: str

    def apply(
        self,
        businesses: list[Business],
        instruction: str,
    ) -> RefinementResult:
        """Return the updated result set without owning session persistence."""


class ClaimFilterPlugin:
    """Keep records supported by an already gathered claim.

    This deliberately does not guess facts. A separate acquisition plugin can
    add the claim; this plugin only makes a decision from existing evidence.
    """

    name = "claim-filter"

    def __init__(self, key: str, expected_value: object) -> None:
        self.key = key
        self.expected_value = expected_value

    def apply(
        self,
        businesses: list[Business],
        instruction: str,
    ) -> RefinementResult:
        selected = [
            business
            for business in businesses
            if any(
                claim.key == self.key and claim.value == self.expected_value
                for claim in business.claims
            )
        ]
        return RefinementResult(
            selected,
            note=f"Kept records with evidence for {self.key}={self.expected_value!r}.",
        )


class MediCalDentalEnrollmentPlugin:
    """Add official Medi-Cal Dental FFS enrollment evidence by exact NPI.

    Enrollment is narrower than "accepting new patients". The plugin records
    only what the public DHCS dataset establishes and leaves unmatched records
    unchanged rather than treating absence as a negative claim.
    """

    name = "medi-cal-dental-enrollment"
    claim_key = "program.medi_cal_dental_ffs_enrolled"

    def __init__(self, client: object | None = None, *, max_records: int = 100) -> None:
        if max_records < 1:
            raise ValueError("max_records must be positive.")
        self._client = client or httpx
        self.max_records = max_records

    def apply(
        self,
        businesses: list[Business],
        instruction: str,
    ) -> RefinementResult:
        npi_businesses = {
            npi: business
            for business in businesses
            if (npi := business.source_ids.get("npi", "")).isdigit()
            and len(npi) == 10
        }
        if len(npi_businesses) > self.max_records:
            raise ValueError(
                f"Medi-Cal refinement is capped at {self.max_records} NPI records."
            )
        if not npi_businesses:
            return RefinementResult(
                businesses,
                note="No exact NPI identifiers were available for Medi-Cal matching.",
            )

        quoted_npis = ",".join(f"'{npi}'" for npi in sorted(npi_businesses))
        response = self._client.post(
            f"{_MEDI_CAL_DENTAL_LAYER}/query",
            data={
                "where": f"Provider_NPI IN ({quoted_npis})",
                "outFields": "Provider_NPI",
                "returnGeometry": "false",
                "f": "json",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or "error" in payload:
            raise ValueError("DHCS Medi-Cal Dental directory returned an invalid response.")
        features = payload.get("features", [])
        if not isinstance(features, list):
            raise ValueError("DHCS Medi-Cal Dental directory returned invalid features.")

        matched_npis = {
            str(feature.get("attributes", {}).get("Provider_NPI", "")).strip()
            for feature in features
            if isinstance(feature, dict)
            and isinstance(feature.get("attributes"), dict)
        }
        observed_at = datetime.now(timezone.utc)
        updated = 0
        for npi in matched_npis & npi_businesses.keys():
            business = npi_businesses[npi]
            if any(claim.key == self.claim_key for claim in business.claims):
                continue
            business.claims += (
                Claim(
                    key=self.claim_key,
                    value=True,
                    source="ca-dhcs-medi-cal-dental-ffs",
                    source_record_id=npi,
                    evidence_url=_MEDI_CAL_DENTAL_DATASET,
                    observed_at=observed_at,
                    method="official_dataset_exact_npi_match",
                    authority="official_program_directory",
                ),
            )
            updated += 1

        return RefinementResult(
            businesses,
            note=(
                f"Added official Medi-Cal Dental FFS enrollment evidence to {updated} "
                "records. Enrollment does not guarantee that a provider accepts new patients."
            ),
        )


class OwnershipEvidencePlugin:
    """Assess ownership shape from explicit wording on first-party pages.

    This is intentionally an evidence collector, not a legal ownership check.
    It does not infer independence from a business name, a single location, or
    the absence of corporate language.
    """

    name = "ownership-evidence"
    claim_key = "ownership.independence_assessment"

    def __init__(self, crawler: object | None = None) -> None:
        self._crawler = crawler or FirstPartyWebsiteCrawler()

    def apply(
        self,
        businesses: list[Business],
        instruction: str,
    ) -> RefinementResult:
        details: list[dict[str, object]] = []
        read_without_signal = 0
        for business in businesses:
            if not business.website or any(
                claim.key == self.claim_key for claim in business.claims
            ):
                continue
            if hasattr(self._crawler, "crawl_with_outcome"):
                crawl = self._crawler.crawl_with_outcome(business.website)
                pages = list(crawl.pages)
                details.append(_crawl_detail(business, crawl))
            else:
                pages = self._crawler.crawl(business.website)
            match = self._classify(pages)
            if match is None:
                if pages:
                    read_without_signal += 1
                continue
            value, signal, evidence_url = match
            business.claims += (
                Claim(
                    key=self.claim_key,
                    value=value,
                    source="first-party-website",
                    source_record_id=urlparse(evidence_url).netloc,
                    evidence_url=evidence_url,
                    observed_at=datetime.now(timezone.utc),
                    method=f"explicit_first_party_phrase:{signal}",
                    authority="business_self_description",
                ),
            )
        assessments = [
            claim.value
            for business in businesses
            for claim in business.claims
            if claim.key == self.claim_key
        ]
        independent = assessments.count("likely_independent")
        corporate = assessments.count("likely_corporate")
        assessed = independent + corporate
        inaccessible = sum(detail["status"] != "success" for detail in details)
        without_website = sum(not business.website for business in businesses)
        return RefinementResult(
            businesses,
            note=(
                f"Found explicit first-party ownership signals for {assessed} records: "
                f"{independent} likely independent and {corporate} likely corporate. "
                f"This pass had {_counted(read_without_signal, 'readable site')} with no "
                f"clear signal, {_counted(inaccessible, 'inaccessible site')}, and "
                f"{_counted(without_website, 'record')} without "
                "a website. Unclear records were retained."
                f"{_outcome_note(details)}"
            ),
            details=tuple(details),
        )

    @staticmethod
    def _classify(
        pages: list[tuple[str, str]],
    ) -> tuple[str, str, str] | None:
        matches: list[tuple[str, str, str]] = []
        for page_url, html in pages:
            text = " ".join(BeautifulSoup(html, "html.parser").stripped_strings).casefold()
            for phrase, signal in _INDEPENDENT_PHRASES.items():
                if phrase in text:
                    matches.append(("likely_independent", signal, page_url))
            for phrase, signal in _CORPORATE_PHRASES.items():
                if phrase in text:
                    matches.append(("likely_corporate", signal, page_url))
        values = {match[0] for match in matches}
        return matches[0] if len(values) == 1 else None


class LongevityEvidencePlugin:
    """Record only explicit first-party evidence of business longevity."""

    name = "longevity-evidence"
    claim_key = "business.longevity.minimum_years"

    def __init__(self, crawler: object | None = None) -> None:
        self._crawler = crawler or FirstPartyWebsiteCrawler()

    def apply(
        self,
        businesses: list[Business],
        instruction: str,
    ) -> RefinementResult:
        details: list[dict[str, object]] = []
        added = 0
        threshold_match = re.search(r"\b(\d{1,3})\s*\+?\s*years?\b", instruction)
        threshold = int(threshold_match.group(1)) if threshold_match else 10
        for business in businesses:
            if not business.website or any(
                claim.key == self.claim_key for claim in business.claims
            ):
                continue
            if hasattr(self._crawler, "crawl_with_outcome"):
                crawl = self._crawler.crawl_with_outcome(business.website)
                pages = list(crawl.pages)
                details.append(_crawl_detail(business, crawl))
            else:
                pages = self._crawler.crawl(business.website)
            evidence = self._find_evidence(pages)
            if evidence is None:
                continue
            minimum_years, signal, evidence_url = evidence
            business.claims += (
                Claim(
                    key=self.claim_key,
                    value=minimum_years,
                    source="first-party-website",
                    source_record_id=urlparse(evidence_url).netloc,
                    evidence_url=evidence_url,
                    observed_at=datetime.now(timezone.utc),
                    method=f"explicit_first_party_phrase:{signal}",
                    authority="business_self_description",
                ),
            )
            added += 1
        qualifying = sum(
            any(
                claim.key == self.claim_key
                and isinstance(claim.value, (int, float))
                and claim.value >= threshold
                for claim in business.claims
            )
            for business in businesses
        )
        return RefinementResult(
            businesses,
            note=(
                f"Added explicit first-party longevity evidence to {added} records; "
                f"{qualifying} have evidence for at least {threshold} years. NPI age was "
                f"not treated as business age.{_outcome_note(details)}"
            ),
            details=tuple(details),
        )

    @staticmethod
    def _find_evidence(
        pages: list[tuple[str, str]],
    ) -> tuple[int, str, str] | None:
        current_year = datetime.now(timezone.utc).year
        matches: list[tuple[int, str, str]] = []
        for page_url, html in pages:
            text = " ".join(BeautifulSoup(html, "html.parser").stripped_strings)
            for match in _FOUNDED_YEAR.finditer(text):
                year = int(match.group(1))
                if 1800 <= year <= current_year:
                    matches.append((current_year - year, f"founded_year:{year}", page_url))
            for match in _OPENED_YEAR.finditer(text):
                year = int(match.group(1))
                if 1800 <= year <= current_year:
                    matches.append((current_year - year, f"opened_year:{year}", page_url))
            for match in _YEARS_SERVING.finditer(text):
                years = int(match.group(1))
                if 1 <= years <= 200:
                    matches.append((years, f"years_serving:{years}", page_url))
        return max(matches, default=None, key=lambda item: item[0])


class PublicEmailPlugin:
    """Find explicitly published email addresses on first-party websites."""

    name = "public-email"

    def __init__(self, enricher: object | None = None) -> None:
        self._enricher = enricher or SocialEnricher()

    def apply(
        self,
        businesses: list[Business],
        instruction: str,
    ) -> RefinementResult:
        updated: list[Business] = []
        discovered = 0
        details: list[dict[str, object]] = []
        for business in businesses:
            if business.email or not business.website:
                updated.append(business)
                continue
            if hasattr(self._enricher, "enrich_with_outcome"):
                result = self._enricher.enrich_with_outcome(business)
                enriched = result.business
                if result.crawl is not None:
                    details.append(_crawl_detail(business, result.crawl))
            else:
                enriched = self._enricher.enrich(business)
            if not enriched.email:
                updated.append(business)
                continue
            discovered += 1
            updated.append(
                replace(
                    business,
                    email=enriched.email,
                    email_status="not_checked",
                    field_provenance={
                        **business.field_provenance,
                        "email": enriched.field_provenance["email"],
                    },
                )
            )
        total = sum(bool(business.email) for business in updated)
        return RefinementResult(
            updated,
            note=(
                f"Found {discovered} new first-party public emails; {total} records "
                f"now have an email. Deliverability was not checked.{_outcome_note(details)}"
            ),
            details=tuple(details),
        )


class OperationalStatusEvidencePlugin:
    """Record explicit first-party closure evidence without inferring activity."""

    name = "operational-status-evidence"
    claim_key = "business.operational_status"

    def __init__(self, crawler: object | None = None) -> None:
        self._crawler = crawler or FirstPartyWebsiteCrawler()

    def apply(
        self,
        businesses: list[Business],
        instruction: str,
    ) -> RefinementResult:
        details: list[dict[str, object]] = []
        added = 0
        for business in businesses:
            if not business.website or any(
                claim.key == self.claim_key for claim in business.claims
            ):
                continue
            if hasattr(self._crawler, "crawl_with_outcome"):
                crawl = self._crawler.crawl_with_outcome(business.website)
                pages = list(crawl.pages)
                details.append(_crawl_detail(business, crawl))
            else:
                pages = self._crawler.crawl(business.website)
            evidence = self._find_closure(pages)
            if evidence is None:
                continue
            signal, evidence_url = evidence
            business.claims += (
                Claim(
                    key=self.claim_key,
                    value="closed",
                    source="first-party-website",
                    source_record_id=urlparse(evidence_url).netloc,
                    evidence_url=evidence_url,
                    observed_at=datetime.now(timezone.utc),
                    method=f"explicit_first_party_phrase:{signal}",
                    authority="business_self_description",
                ),
            )
            added += 1
        return RefinementResult(
            businesses,
            note=(
                f"Added explicit first-party closure evidence to {added} records. "
                "A live site or lack of closure wording was not treated as proof that a "
                f"business is open.{_outcome_note(details)}"
            ),
            details=tuple(details),
        )

    @staticmethod
    def _find_closure(pages: list[tuple[str, str]]) -> tuple[str, str] | None:
        for page_url, html in pages:
            text = " ".join(BeautifulSoup(html, "html.parser").stripped_strings)
            if match := _CLOSED_STATUS.search(text):
                return ("closure_statement", page_url)
        return None


class PublicSocialPlugin:
    """Find explicitly linked public social profiles on first-party websites."""

    name = "public-socials"
    fields = ("linkedin", "instagram", "facebook", "twitter")

    def __init__(self, enricher: object | None = None) -> None:
        self._enricher = enricher or SocialEnricher()

    def apply(
        self,
        businesses: list[Business],
        instruction: str,
    ) -> RefinementResult:
        updated: list[Business] = []
        discovered = 0
        details: list[dict[str, object]] = []
        for business in businesses:
            if not business.website or all(
                getattr(business, field) for field in self.fields
            ):
                updated.append(business)
                continue
            if hasattr(self._enricher, "enrich_with_outcome"):
                result = self._enricher.enrich_with_outcome(business)
                enriched = result.business
                if result.crawl is not None:
                    details.append(_crawl_detail(business, result.crawl))
            else:
                enriched = self._enricher.enrich(business)
            field_updates = {
                field: getattr(enriched, field)
                for field in self.fields
                if not getattr(business, field) and getattr(enriched, field)
            }
            if not field_updates:
                updated.append(business)
                continue
            discovered += len(field_updates)
            evidence = {
                field: enriched.field_provenance[field]
                for field in field_updates
            }
            updated.append(
                replace(
                    business,
                    **field_updates,
                    field_provenance={**business.field_provenance, **evidence},
                )
            )
        businesses_with_socials = sum(
            any(getattr(business, field) for field in self.fields)
            for business in updated
        )
        return RefinementResult(
            updated,
            note=(
                f"Found {discovered} new first-party social links; "
                f"{businesses_with_socials} records now have at least one."
                f"{_outcome_note(details)}"
            ),
            details=tuple(details),
        )


def _crawl_detail(business: Business, crawl: object) -> dict[str, object]:
    return {
        "business": business.name,
        "website": business.website,
        "status": getattr(crawl, "status"),
        "pages_read": len(getattr(crawl, "pages")),
    }


def _outcome_note(details: list[dict[str, object]]) -> str:
    if not details:
        return ""
    counts: dict[str, int] = {}
    for detail in details:
        status = str(detail["status"])
        counts[status] = counts.get(status, 0) + 1
    summary = ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
    return f" Crawl outcomes: {summary}."


def _counted(count: int, label: str) -> str:
    return f"{count} {label if count == 1 else label + 's'}"
