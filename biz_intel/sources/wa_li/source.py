"""Bounded Washington L&I contractor-registration acquisition."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
import re
from typing import Any

import httpx

from biz_intel.core.api_source import BaseApiSource
from biz_intel.models.business import Business
from biz_intel.models.claim import Claim

SOURCE_NAME = "wa-li"
_GENERAL_API_URL = "https://data.wa.gov/resource/m8qx-ubtq.json"
_VERIFY_URL = "https://secure.lni.wa.gov/verify/Detail.aspx?LIC={}&SAW=false"
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 250
_DEFAULT_LICENSE_TYPES = ("CC",)
_DEFAULT_STATUSES = ("ACTIVE",)
_SAFE_CODE = re.compile(r"^[A-Z0-9 -]+$")


class WaLiSource(BaseApiSource):
    """Fetch a capped, city-filtered set of Washington contractor records.

    This is a standalone registry source.  It intentionally reads only the
    public General dataset, not the separate insurance or principal datasets.
    The current task must target Washington because registration authority is
    state-specific, even though a registrant's mailing address can be outside
    Washington.
    """

    source_name = SOURCE_NAME

    def fetch(self) -> Iterator[Business]:
        location = self.task.location
        if location is None or (location.state or "").casefold() != "wa":
            raise ValueError("WA L&I requires a Washington (WA) location.")

        limit = self._limit()
        response = httpx.get(
            _GENERAL_API_URL,
            params={
                "$where": self._where_clause(),
                "$limit": limit,
                "$order": "contractorlicensenumber",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("WA L&I returned an invalid response.")

        observed_at = datetime.now(timezone.utc)
        for record in payload[:limit]:
            business = self._to_business(record, observed_at=observed_at)
            if business is not None:
                yield business

    def _limit(self) -> int:
        limit = self.task.limit or _DEFAULT_LIMIT
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("WA L&I limit must be a positive integer.")
        if limit > _MAX_LIMIT:
            raise ValueError(f"WA L&I limit cannot exceed {_MAX_LIMIT} records per task.")
        return limit

    def _where_clause(self) -> str:
        clauses = [
            _in_clause("contractorlicensetypecode", self._codes("license_types", _DEFAULT_LICENSE_TYPES)),
            _in_clause("upper(contractorlicensestatus)", self._codes("license_statuses", _DEFAULT_STATUSES)),
        ]
        city = (self.task.location.city if self.task.location else None)
        if city:
            clauses.append(f"upper(city) = '{_escape(city.upper())}'")
        return " AND ".join(clauses)

    def _codes(self, option: str, default: tuple[str, ...]) -> tuple[str, ...]:
        raw = self.task.options.get(option, default)
        if isinstance(raw, str):
            values = (raw,)
        elif isinstance(raw, (list, tuple)) and all(isinstance(value, str) for value in raw):
            values = tuple(raw)
        else:
            raise ValueError(f"WA L&I option '{option}' must be a string or list of strings.")
        normalized = tuple(value.strip().upper() for value in values if value.strip())
        if not normalized or any(not _SAFE_CODE.fullmatch(value) for value in normalized):
            raise ValueError(f"WA L&I option '{option}' contains an invalid code.")
        return normalized

    @staticmethod
    def _to_business(record: object, *, observed_at: datetime) -> Business | None:
        if not isinstance(record, dict):
            return None
        name = _text(record, "businessname")
        address = " ".join(filter(None, (_text(record, "address1"), _text(record, "address2"))))
        city = _text(record, "city")
        state = _text(record, "state")
        license_number = _text(record, "contractorlicensenumber")
        if not all((name, address, city, state, license_number)):
            return None

        source_url = _VERIFY_URL.format(license_number)
        claims = tuple(
            Claim(
                key=key,
                value=value,
                source=SOURCE_NAME,
                source_record_id=license_number,
                evidence_url=source_url,
                observed_at=observed_at,
                authority="official_registry",
            )
            for key, value in (
                ("registry.wa_li.license_number", license_number),
                ("registry.wa_li.license_status", _text(record, "contractorlicensestatus")),
                ("registry.wa_li.license_type", _text(record, "contractorlicensetypecodedesc")),
                ("registry.wa_li.license_effective_date", _text(record, "licenseeffectivedate")),
                ("registry.wa_li.license_expiration_date", _text(record, "licenseexpirationdate")),
            )
            if value
        )
        return Business(
            name=name,
            category=_text(record, "contractorlicensetypecodedesc"),
            address=address,
            city=city,
            state=state,
            postal_code=_text(record, "zip"),
            country="US",
            phone=_text(record, "phonenumber"),
            source=SOURCE_NAME,
            source_url=source_url,
            observed_at=observed_at,
            claims=claims,
            source_ids={"wa_li_contractor_license": license_number},
            raw_data={
                key: record[key]
                for key in (
                    "businessname", "contractorlicensenumber", "contractorlicensetypecode",
                    "contractorlicensetypecodedesc", "contractorlicensestatus", "address1",
                    "address2", "city", "state", "zip", "phonenumber", "licenseeffectivedate",
                    "licenseexpirationdate",
                )
                if key in record
            },
        )


def _text(record: dict[str, Any], key: str) -> str:
    return str(record.get(key) or "").strip()


def _escape(value: str) -> str:
    return value.replace("'", "''")


def _in_clause(field: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{_escape(value)}'" for value in values)
    return f"{field} IN ({quoted})"
