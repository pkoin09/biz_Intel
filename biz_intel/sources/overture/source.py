"""Manifest-gated, offline imports of frozen Overture GeoParquet snapshots.

This module never contacts Overture or any other network service.  A snapshot
is accepted only when the adjacent manifest identifies the exact release,
filters, attribution/licence, retrieval time, record count, and SHA-256 hash.
Real snapshots are local working data; repository fixtures must be synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from numbers import Number
from pathlib import Path
from typing import Any

import duckdb

from biz_intel.core.file_source import FileSource
from biz_intel.models.business import Business
from biz_intel.models.claim import Claim

SOURCE_NAME = "overture"
_MANIFEST_VERSION = 1
_REQUIRED_MANIFEST_FIELDS = frozenset({
    "schema_version",
    "source",
    "release",
    "retrieved_at",
    "source_reference",
    "geography",
    "taxonomy_filters",
    "license",
    "attribution",
    "row_count",
    "sha256",
    "review_status",
})


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    """Verified provenance for one immutable, local snapshot."""

    release: str
    retrieved_at: datetime
    source_reference: str
    geography: str
    taxonomy_filters: tuple[str, ...]
    license: str
    attribution: str
    row_count: int
    sha256: str

    @classmethod
    def load(cls, path: Path) -> "SnapshotManifest":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Overture manifest is not valid JSON: {path}") from exc
        if not isinstance(raw, dict):
            raise ValueError("Overture manifest must be a JSON object.")
        missing = _REQUIRED_MANIFEST_FIELDS - raw.keys()
        if missing:
            raise ValueError(
                "Overture manifest is missing required fields: "
                + ", ".join(sorted(missing))
            )
        if raw["schema_version"] != _MANIFEST_VERSION:
            raise ValueError(
                f"Unsupported Overture manifest schema_version: {raw['schema_version']!r}."
            )
        if raw["source"] != SOURCE_NAME:
            raise ValueError("Overture manifest source must be 'overture'.")
        if raw["review_status"] != "reviewed":
            raise ValueError("Overture manifest review_status must be 'reviewed'.")
        try:
            retrieved_at = datetime.fromisoformat(_required_text(raw, "retrieved_at"))
        except ValueError as exc:
            raise ValueError("Overture manifest retrieved_at must be an ISO timestamp.") from exc
        if retrieved_at.tzinfo is None:
            raise ValueError("Overture manifest retrieved_at must include a timezone.")
        row_count = raw["row_count"]
        if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count < 0:
            raise ValueError("Overture manifest row_count must be a non-negative integer.")
        taxonomy_filters = raw["taxonomy_filters"]
        if not isinstance(taxonomy_filters, list) or not all(
            isinstance(value, str) and value.strip() for value in taxonomy_filters
        ):
            raise ValueError("Overture manifest taxonomy_filters must be a list of non-empty strings.")
        sha256 = _required_text(raw, "sha256").lower()
        if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
            raise ValueError("Overture manifest sha256 must be a lowercase SHA-256 hex digest.")
        return cls(
            release=_required_text(raw, "release"),
            retrieved_at=retrieved_at,
            source_reference=_required_text(raw, "source_reference"),
            geography=_required_text(raw, "geography"),
            taxonomy_filters=tuple(taxonomy_filters),
            license=_required_text(raw, "license"),
            attribution=_required_text(raw, "attribution"),
            row_count=row_count,
            sha256=sha256,
        )


class OvertureSnapshotSource(FileSource):
    """Read one reviewed local GeoParquet snapshot with a checked manifest."""

    source_name = SOURCE_NAME

    def __init__(
        self,
        path: str | Path,
        manifest_path: str | Path | None = None,
    ) -> None:
        super().__init__(path)
        if self.path.suffix.casefold() not in {".parquet", ".geoparquet"}:
            raise ValueError("Overture snapshot path must be a .parquet or .geoparquet file.")
        self.manifest_path = (
            Path(manifest_path)
            if manifest_path is not None
            else self.path.with_suffix(".manifest.json")
        )
        if not self.manifest_path.exists():
            raise FileNotFoundError(
                f"Overture snapshot manifest not found: {self.manifest_path}"
            )

    def extract(self) -> Iterator[Business]:
        manifest = SnapshotManifest.load(self.manifest_path)
        self._verify_integrity(manifest)
        for row_number, row in enumerate(self._rows(), start=1):
            yield self._to_business(row, row_number=row_number, manifest=manifest)

    def _verify_integrity(self, manifest: SnapshotManifest) -> None:
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        if digest != manifest.sha256:
            raise ValueError("Overture snapshot SHA-256 does not match its manifest.")
        with duckdb.connect() as connection:
            count = connection.execute(
                "SELECT count(*) FROM read_parquet(?)", [str(self.path)]
            ).fetchone()[0]
        if count != manifest.row_count:
            raise ValueError(
                "Overture snapshot row count does not match its manifest: "
                f"expected {manifest.row_count}, found {count}."
            )

    def _rows(self) -> Iterator[dict[str, Any]]:
        with duckdb.connect() as connection:
            cursor = connection.execute("SELECT * FROM read_parquet(?)", [str(self.path)])
            columns = [column[0] for column in cursor.description]
            for values in cursor.fetchall():
                yield dict(zip(columns, values, strict=True))

    @staticmethod
    def _to_business(
        row: dict[str, Any], *, row_number: int, manifest: SnapshotManifest
    ) -> Business:
        record_id = _text(row.get("id"))
        name = _text(_nested(row.get("names"), "primary")) or _text(row.get("name"))
        if not record_id or not name:
            missing = "id" if not record_id else "names.primary/name"
            raise ValueError(f"Overture snapshot row {row_number} is missing {missing}.")

        address = _first_mapping(row.get("addresses"))
        category = (
            _text(_nested(row.get("taxonomy"), "primary"))
            or _text(row.get("basic_category"))
            or _text(_nested(row.get("categories"), "primary"))
            or _text(row.get("category"))
        )
        phone = _first_text(row.get("phones")) or _text(row.get("phone"))
        website = _first_text(row.get("websites")) or _text(row.get("website"))
        confidence = row.get("confidence")
        if not isinstance(confidence, Number) or isinstance(confidence, bool):
            confidence = None

        source_url = manifest.source_reference
        claims = [
            Claim(
                key="candidate.overture.id",
                value=record_id,
                source=SOURCE_NAME,
                source_record_id=record_id,
                evidence_url=source_url,
                observed_at=manifest.retrieved_at,
                method="offline_geoparquet_snapshot",
                authority="source_observation",
            ),
            Claim(
                key="candidate.overture.release",
                value=manifest.release,
                source=SOURCE_NAME,
                source_record_id=record_id,
                evidence_url=source_url,
                observed_at=manifest.retrieved_at,
                method="offline_geoparquet_snapshot",
                authority="source_observation",
            ),
        ]
        if confidence is not None:
            claims.append(Claim(
                key="candidate.overture.confidence",
                value=float(confidence),
                source=SOURCE_NAME,
                source_record_id=record_id,
                evidence_url=source_url,
                observed_at=manifest.retrieved_at,
                method="offline_geoparquet_snapshot",
                authority="source_observation",
            ))
        return Business(
            name=name,
            category=category,
            address=_text(address.get("freeform")) or _text(address.get("address")),
            city=_text(address.get("locality")) or _text(address.get("city")),
            state=_text(address.get("region")) or _text(address.get("state")),
            postal_code=_text(address.get("postcode")) or _text(address.get("postal_code")),
            country=_text(address.get("country")),
            phone=phone,
            website=website,
            source=SOURCE_NAME,
            source_url=source_url,
            observed_at=manifest.retrieved_at,
            claims=tuple(claims),
            source_ids={"overture_id": record_id},
            raw_data={
                key: value
                for key, value in {
                    "id": record_id,
                    "name": name,
                    "category": category,
                    "address": _text(address.get("freeform")) or _text(address.get("address")),
                    "city": _text(address.get("locality")) or _text(address.get("city")),
                    "state": _text(address.get("region")) or _text(address.get("state")),
                    "postal_code": _text(address.get("postcode")) or _text(address.get("postal_code")),
                    "country": _text(address.get("country")),
                    "phone": phone,
                    "website": website,
                    "confidence": confidence,
                }.items()
                if value not in (None, "")
            },
        )


def _required_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Overture manifest {key} must be a non-empty string.")
    return value.strip()


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _nested(value: object, key: str) -> object:
    return value.get(key) if isinstance(value, dict) else None


def _first_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        return next((item for item in value if isinstance(item, dict)), {})
    return {}


def _first_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return next((_text(item) for item in value if _text(item)), "")
    return ""
