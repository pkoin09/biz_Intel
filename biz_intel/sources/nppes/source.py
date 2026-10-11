"""Bounded CMS NPPES Registry acquisition for healthcare-provider pilots."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import httpx

from biz_intel.core.api_source import BaseApiSource
from biz_intel.models.business import Business
from biz_intel.models.claim import Claim

_API_URL = "https://npiregistry.cms.hhs.gov/api/"
_PROVIDER_URL = "https://npiregistry.cms.hhs.gov/provider-view/{}"


class NppesSource(BaseApiSource):
    """Fetch public NPI records and retain only complete practice contacts."""

    source_name = "nppes"

    def fetch(self) -> Iterator[Business]:
        if self.task.location is None or not self.task.location.state:
            raise ValueError("NPPES requires at least a state location.")
        params = {
            "version": "2.1",
            "state": self.task.location.state,
            "limit": self.task.limit or 100,
            "taxonomy_description": self.task.category or "Dentist",
        }
        if self.task.location.city:
            params["city"] = self.task.location.city
        response = httpx.get(_API_URL, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("NPPES returned an invalid response.")
        for record in payload.get("results", []):
            business = self._to_business(record)
            if business is not None and self._matches_scope(business):
                yield business

    def _matches_scope(self, business: Business) -> bool:
        """Enforce requested geography/taxonomy after the registry search."""

        location = self.task.location
        if location is not None:
            if location.city and business.city.casefold() != location.city.casefold():
                return False
            if location.state and business.state.casefold() != location.state.casefold():
                return False
        category = (self.task.category or "").strip()
        return not category or category.casefold() in business.category.casefold()

    @staticmethod
    def _to_business(record: object) -> Business | None:
        if not isinstance(record, dict):
            return None
        basic = record.get("basic", {})
        number = record.get("number")
        if not isinstance(basic, dict) or not isinstance(number, str):
            return None
        name = str(basic.get("organization_name") or "").strip()
        if not name:
            name = " ".join(
                str(basic.get(key) or "").strip()
                for key in ("first_name", "middle_name", "last_name")
            ).strip()
        location = next(
            (address for address in record.get("addresses", [])
             if isinstance(address, dict) and address.get("address_purpose") == "LOCATION"),
            None,
        )
        if not isinstance(location, dict):
            return None
        phone = str(location.get("telephone_number") or "").strip()
        address = str(location.get("address_1") or "").strip()
        city = str(location.get("city") or "").strip()
        state = str(location.get("state") or "").strip()
        if not all((name, address, city, state, phone)):
            return None
        observed_at = datetime.now(timezone.utc)
        primary = _primary_taxonomy_record(record)
        license_number = _taxonomy_text(primary, "license")
        license_state = _taxonomy_text(primary, "state").upper()
        claims = [
            Claim(
                key="registry.nppes.npi",
                value=number,
                source="nppes",
                source_record_id=number,
                evidence_url=_PROVIDER_URL.format(number),
                observed_at=observed_at,
                authority="official_registry",
            )
        ]
        if license_number:
            claims.append(Claim(
                key="registry.nppes.license_number",
                value=license_number,
                source="nppes",
                source_record_id=number,
                evidence_url=_PROVIDER_URL.format(number),
                observed_at=observed_at,
                authority="source_observation",
            ))
        if license_state:
            claims.append(Claim(
                key="registry.nppes.license_state",
                value=license_state,
                source="nppes",
                source_record_id=number,
                evidence_url=_PROVIDER_URL.format(number),
                observed_at=observed_at,
                authority="source_observation",
            ))
        source_ids = {"npi": number}
        if (
            license_number
            and license_state == "CA"
            and "dentist" in _taxonomy_text(primary, "desc").casefold()
        ):
            source_ids["ca_dental_license"] = license_number
        return Business(
            name=name,
            category=_taxonomy_text(primary, "desc"),
            address=address,
            city=city,
            state=state,
            postal_code=str(location.get("postal_code") or "").strip(),
            country=str(location.get("country_name") or "").strip(),
            phone=phone,
            source="nppes",
            source_url=_PROVIDER_URL.format(number),
            observed_at=observed_at,
            claims=tuple(claims),
            source_ids=source_ids,
            raw_data=record,
        )


def _primary_taxonomy(record: dict) -> str:
    return _taxonomy_text(_primary_taxonomy_record(record), "desc")


def _primary_taxonomy_record(record: dict) -> dict:
    for taxonomy in record.get("taxonomies", []):
        if isinstance(taxonomy, dict) and taxonomy.get("primary"):
            return taxonomy
    return {}


def _taxonomy_text(taxonomy: dict, key: str) -> str:
    return str(taxonomy.get(key) or "").strip()
