"""Sanitized, file-backed history for canonical business records.

This module deliberately does not introduce a database or make provider calls.
It gives jobs a stable record identity and an auditable comparison with the
previous completed run.  Snapshots omit provider raw payloads and volatile
observation/provenance timestamps so ordinary re-observation does not look
like a business-record change.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from biz_intel.models.business import Business


SNAPSHOT_VERSION = 1
_VOLATILE_FIELDS = frozenset({"raw_data", "scraped_at", "observed_at", "field_provenance"})
_IDENTITY_CANDIDATES = (
    ("name", "address", "phone"),
    ("name", "address", "website"),
    ("name", "city", "state", "phone"),
    ("name", "city", "state", "website"),
    ("name", "source_url"),
)


@dataclass(frozen=True, slots=True)
class ChangeSet:
    """Change counts and field-level differences from the preceding snapshot."""

    new: tuple[str, ...] = ()
    updated: dict[str, tuple[str, ...]] | None = None
    unchanged: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.updated is None:
            object.__setattr__(self, "updated", {})

    @property
    def counts(self) -> dict[str, int]:
        return {
            "new": len(self.new),
            "updated": len(self.updated or {}),
            "unchanged": len(self.unchanged),
            "missing": len(self.missing),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": self.counts,
            "new": list(self.new),
            "updated": {
                record_id: list(fields)
                for record_id, fields in sorted((self.updated or {}).items())
            },
            "unchanged": list(self.unchanged),
            "missing": list(self.missing),
        }


@dataclass(frozen=True, slots=True)
class HistorySnapshot:
    """The persisted, sanitized state for one completed run."""

    job_name: str
    run_id: str
    recorded_at: datetime
    destination: Path
    changes: ChangeSet


class RunHistoryStore:
    """Store and compare per-job snapshots under a caller-selected directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def record(
        self,
        job_name: str,
        run_id: str,
        businesses: list[Business],
    ) -> HistorySnapshot:
        """Persist a run and compare it to the last persisted snapshot.

        A record without a sufficiently stable identity is rejected rather than
        receiving a run-local identifier: run-local IDs would make change
        tracking silently misleading. Call this after deduplication.
        """

        safe_job_name = _safe_path_component(job_name)
        safe_run_id = _safe_path_component(run_id)
        records = _snapshot_records(businesses)
        previous = self._load_latest(safe_job_name)
        changes = compare_records(previous, records)
        recorded_at = datetime.now(timezone.utc)
        payload = {
            "version": SNAPSHOT_VERSION,
            "job_name": job_name,
            "run_id": run_id,
            "recorded_at": recorded_at.isoformat(),
            "records": records,
            "changes": changes.to_dict(),
        }
        job_directory = self.root / safe_job_name
        job_directory.mkdir(parents=True, exist_ok=True)
        destination = job_directory / f"{safe_run_id}.json"
        _write_json(destination, payload)
        _write_json(job_directory / "latest.json", payload)
        return HistorySnapshot(job_name, run_id, recorded_at, destination, changes)

    def _load_latest(self, safe_job_name: str) -> list[dict[str, Any]]:
        path = self.root / safe_job_name / "latest.json"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to read history snapshot: {path}") from exc
        if not isinstance(payload, dict) or payload.get("version") != SNAPSHOT_VERSION:
            raise ValueError("History snapshot must be a version 1 mapping.")
        records = payload.get("records")
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise ValueError("History snapshot records must be a list of mappings.")
        return records


def stable_record_id(business: Business) -> str | None:
    """Return a deterministic identifier from durable, normalized identity fields.

    The source is intentionally excluded: the same business observed through
    an approved different source should remain the same stored record.
    """

    values = _identity_values(business)
    if values is None:
        return None
    encoded = "\x1f".join(values).encode("utf-8")
    return f"biz_{sha256(encoded).hexdigest()[:24]}"


def compare_records(
    previous: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> ChangeSet:
    """Compare sanitized snapshot records by ID and return deterministic changes."""

    before = _index_records(previous)
    after = _index_records(current)
    new = tuple(sorted(set(after) - set(before)))
    missing = tuple(sorted(set(before) - set(after)))
    unchanged: list[str] = []
    updated: dict[str, tuple[str, ...]] = {}
    for record_id in sorted(set(before) & set(after)):
        changed_fields = tuple(
            field
            for field in sorted(set(before[record_id]["business"]) | set(after[record_id]["business"]))
            if before[record_id]["business"].get(field)
            != after[record_id]["business"].get(field)
        )
        if changed_fields:
            updated[record_id] = changed_fields
        else:
            unchanged.append(record_id)
    return ChangeSet(new, updated, tuple(unchanged), missing)


def _snapshot_records(businesses: list[Business]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for business in businesses:
        record_id = stable_record_id(business)
        if record_id is None:
            raise ValueError("Business lacks sufficient stable identity for history tracking.")
        data = _sanitized_business(business)
        records.append(
            {
                "record_id": record_id,
                "content_hash": _content_hash(data),
                "business": data,
            }
        )
    _index_records(records)
    return sorted(records, key=lambda record: record["record_id"])


def _sanitized_business(business: Business) -> dict[str, Any]:
    data = asdict(business)
    for field in _VOLATILE_FIELDS:
        data.pop(field, None)
    # Keep the in-memory comparison representation identical to the JSON
    # snapshot representation (for example, tuples become JSON lists).
    return json.loads(json.dumps(data, default=str, sort_keys=True))


def _identity_values(business: Business) -> tuple[str, ...] | None:
    for fields in _IDENTITY_CANDIDATES:
        values = tuple(_normalised_identity_value(getattr(business, field)) for field in fields)
        if all(values):
            return values
    return None


def _normalised_identity_value(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip().casefold())


def _content_hash(data: dict[str, Any]) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _index_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = record.get("record_id")
        business = record.get("business")
        if not isinstance(record_id, str) or not record_id or not isinstance(business, dict):
            raise ValueError("History records require record_id and business mappings.")
        if record_id in indexed:
            raise ValueError(f"Duplicate stable record ID in history: {record_id}")
        indexed[record_id] = record
    return indexed


def _safe_path_component(value: str) -> str:
    component = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    if not component:
        raise ValueError("Job name and run ID must contain a safe path character.")
    return component


def _write_json(destination: Path, payload: dict[str, Any]) -> None:
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
    temporary.replace(destination)
