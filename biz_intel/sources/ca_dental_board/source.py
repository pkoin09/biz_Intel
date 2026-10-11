"""Import explicit California Dental Board license-verification evidence.

The California DCA public service exposes individual license profiles, not a
documented bulk API used by this project. This source deliberately accepts a
reviewed CSV snapshot instead of automating those pages.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from biz_intel.core.file_source import FileSource
from biz_intel.models.business import Business
from biz_intel.models.claim import Claim

SOURCE_NAME = "ca-dental-board"
_REQUIRED_COLUMNS = frozenset({
    "license_number",
    "licensee_name",
    "license_status",
    "evidence_url",
    "observed_at",
})
_RAW_COLUMNS = (
    "license_number",
    "licensee_name",
    "license_type",
    "license_status",
    "expiration_date",
    "address",
    "city",
    "state",
    "zip",
    "evidence_url",
    "observed_at",
)


class CaliforniaDentalBoardSource(FileSource):
    """Read a reviewed, headered CSV from the official Board lookup.

    The import has no network behavior. It does not accept or retain bond,
    insurance-policy, disciplinary-document, or unrelated personal fields.
    """

    source_name = SOURCE_NAME

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)

    def extract(self) -> Iterator[Business]:
        with self.path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            columns = set(reader.fieldnames or ())
            missing = _REQUIRED_COLUMNS - columns
            if missing:
                raise ValueError(
                    "California Dental Board evidence is missing required columns: "
                    + ", ".join(sorted(missing))
                )
            for number, row in enumerate(reader, start=2):
                yield self._to_business(row, row_number=number)

    @staticmethod
    def _to_business(row: dict[str, str], *, row_number: int) -> Business:
        values = {key: str(row.get(key) or "").strip() for key in _RAW_COLUMNS}
        missing = [key for key in _REQUIRED_COLUMNS if not values[key]]
        if missing:
            raise ValueError(
                f"California Dental Board evidence row {row_number} is missing: "
                + ", ".join(sorted(missing))
            )
        try:
            observed_at = datetime.fromisoformat(values["observed_at"])
        except ValueError as exc:
            raise ValueError(
                f"California Dental Board evidence row {row_number} has an invalid observed_at."
            ) from exc

        license_number = values["license_number"]
        evidence_url = values["evidence_url"]
        claims = tuple(
            Claim(
                key=key,
                value=value,
                source=SOURCE_NAME,
                source_record_id=license_number,
                evidence_url=evidence_url,
                observed_at=observed_at,
                method="manual_board_evidence_import",
                authority="official_registry",
            )
            for key, value in (
                ("registry.ca_dental_board.license_number", license_number),
                ("registry.ca_dental_board.license_status", values["license_status"]),
                ("registry.ca_dental_board.license_type", values["license_type"]),
                ("registry.ca_dental_board.expiration_date", values["expiration_date"]),
            )
            if value
        )
        return Business(
            name=values["licensee_name"],
            category=values["license_type"] or "Dentist",
            address=values["address"],
            city=values["city"],
            state=values["state"] or "CA",
            postal_code=values["zip"],
            country="US",
            source=SOURCE_NAME,
            source_url=evidence_url,
            observed_at=observed_at,
            claims=claims,
            source_ids={"ca_dental_license": license_number},
            raw_data={key: values[key] for key in _RAW_COLUMNS if values[key]},
        )
