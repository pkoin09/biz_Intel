"""Opt-in SQLite-backed history for accepted delivery records.

The file-based :class:`RunHistoryStore` remains the default for a job.  This
store has the same ``record`` entry point but keeps immutable per-run versions
and a materialized latest record, so callers can ask for a record's history
without reading every JSON snapshot.  It stores the sanitized representation
from ``history.py`` only; raw provider payloads and volatile observation data
never cross this boundary.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from biz_intel.models.business import Business

from .history import ChangeSet, HistorySnapshot, _snapshot_records, compare_records


_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class StoredRun:
    """A completed, immutable database-backed run summary."""

    job_name: str
    run_id: str
    recorded_at: datetime
    changes: ChangeSet


@dataclass(frozen=True, slots=True)
class StoredRecord:
    """The latest accepted, sanitized representation of one business."""

    job_name: str
    record_id: str
    first_seen_run_id: str
    last_seen_run_id: str
    content_hash: str
    business: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RecordVersion:
    """One immutable accepted-record observation within a completed run."""

    job_name: str
    record_id: str
    run_id: str
    recorded_at: datetime
    content_hash: str
    business: dict[str, Any]


class SQLiteHistoryStore:
    """Persist accepted business history in one local SQLite database.

    This is intentionally opt-in: construct it and pass it as ``history_store``
    to ``JobRunner``.  The schema uses only the Python standard library and is
    safe for normal sequential job execution.  A run ID is immutable: recording
    it a second time raises rather than silently overwriting audit history.
    """

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)

    def record(
        self,
        job_name: str,
        run_id: str,
        businesses: list[Business],
    ) -> HistorySnapshot:
        """Store accepted records, their versions, and deterministic changes.

        Non-accepted records are deliberately ignored.  The normal JobRunner
        already supplies accepted records, but the guard makes direct callers
        unable to accidentally persist incomplete research observations.
        """

        accepted = [business for business in businesses if business.record_status == "accepted"]
        records = _snapshot_records(accepted)
        recorded_at = datetime.now(timezone.utc)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._ensure_schema(connection)
            if connection.execute(
                "SELECT 1 FROM runs WHERE job_name = ? AND run_id = ?", (job_name, run_id)
            ).fetchone():
                raise ValueError(f"History run already exists: {job_name}/{run_id}")
            previous = self._current_records(connection, job_name)
            changes = compare_records(previous, records)
            connection.execute(
                "INSERT INTO runs (job_name, run_id, recorded_at, changes_json) VALUES (?, ?, ?, ?)",
                (job_name, run_id, recorded_at.isoformat(), _changes_json(changes)),
            )
            self._insert_changes(connection, job_name, run_id, changes)
            current_ids = {record["record_id"] for record in records}
            for record in records:
                business_json = _json(record["business"])
                connection.execute(
                    """
                    INSERT INTO record_versions
                        (job_name, record_id, run_id, recorded_at, content_hash, business_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (job_name, record["record_id"], run_id, recorded_at.isoformat(), record["content_hash"], business_json),
                )
                connection.execute(
                    """
                    INSERT INTO current_records
                        (job_name, record_id, first_seen_run_id, last_seen_run_id, content_hash, business_json, is_present)
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(job_name, record_id) DO UPDATE SET
                        last_seen_run_id = excluded.last_seen_run_id,
                        content_hash = excluded.content_hash,
                        business_json = excluded.business_json,
                        is_present = 1
                    """,
                    (job_name, record["record_id"], run_id, run_id, record["content_hash"], business_json),
                )
            if current_ids:
                placeholders = ", ".join("?" for _ in current_ids)
                connection.execute(
                    f"UPDATE current_records SET is_present = 0 WHERE job_name = ? AND record_id NOT IN ({placeholders})",
                    (job_name, *sorted(current_ids)),
                )
            else:
                connection.execute(
                    "UPDATE current_records SET is_present = 0 WHERE job_name = ?", (job_name,)
                )
        return HistorySnapshot(job_name, run_id, recorded_at, self.database, changes)

    def list_runs(self, job_name: str, *, limit: int | None = None) -> tuple[StoredRun, ...]:
        """Return newest completed runs for a job, optionally bounded."""

        query = "SELECT run_id, recorded_at, changes_json FROM runs WHERE job_name = ? ORDER BY recorded_at DESC, run_id DESC"
        parameters: tuple[object, ...] = (job_name,)
        if limit is not None:
            if limit < 1:
                raise ValueError("limit must be positive when supplied")
            query += " LIMIT ?"
            parameters += (limit,)
        with self._connect() as connection:
            self._ensure_schema(connection)
            rows = connection.execute(query, parameters).fetchall()
        return tuple(
            StoredRun(job_name, row["run_id"], _parse_datetime(row["recorded_at"]), _changes_from_json(row["changes_json"]))
            for row in rows
        )

    def get_record(self, job_name: str, record_id: str) -> StoredRecord | None:
        """Return the latest currently-present accepted record by stable ID."""

        with self._connect() as connection:
            self._ensure_schema(connection)
            row = connection.execute(
                """SELECT first_seen_run_id, last_seen_run_id, content_hash, business_json
                   FROM current_records WHERE job_name = ? AND record_id = ? AND is_present = 1""",
                (job_name, record_id),
            ).fetchone()
        if row is None:
            return None
        return StoredRecord(job_name, record_id, row["first_seen_run_id"], row["last_seen_run_id"], row["content_hash"], _mapping(row["business_json"]))

    def get_record_versions(self, job_name: str, record_id: str) -> tuple[RecordVersion, ...]:
        """Return oldest-first immutable versions for one stable record ID."""

        with self._connect() as connection:
            self._ensure_schema(connection)
            rows = connection.execute(
                """SELECT run_id, recorded_at, content_hash, business_json FROM record_versions
                   WHERE job_name = ? AND record_id = ? ORDER BY recorded_at, run_id""",
                (job_name, record_id),
            ).fetchall()
        return tuple(
            RecordVersion(job_name, record_id, row["run_id"], _parse_datetime(row["recorded_at"]), row["content_hash"], _mapping(row["business_json"]))
            for row in rows
        )

    def get_run_changes(self, job_name: str, run_id: str) -> ChangeSet | None:
        """Return the persisted change set for one run, if it exists."""

        with self._connect() as connection:
            self._ensure_schema(connection)
            row = connection.execute(
                "SELECT changes_json FROM runs WHERE job_name = ? AND run_id = ?", (job_name, run_id)
            ).fetchone()
        return _changes_from_json(row["changes_json"]) if row else None

    def _connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS history_schema (version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                job_name TEXT NOT NULL,
                run_id TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                changes_json TEXT NOT NULL,
                PRIMARY KEY (job_name, run_id)
            );
            CREATE TABLE IF NOT EXISTS current_records (
                job_name TEXT NOT NULL,
                record_id TEXT NOT NULL,
                first_seen_run_id TEXT NOT NULL,
                last_seen_run_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                business_json TEXT NOT NULL,
                is_present INTEGER NOT NULL CHECK (is_present IN (0, 1)),
                PRIMARY KEY (job_name, record_id)
            );
            CREATE TABLE IF NOT EXISTS record_versions (
                job_name TEXT NOT NULL,
                record_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                business_json TEXT NOT NULL,
                PRIMARY KEY (job_name, record_id, run_id),
                FOREIGN KEY (job_name, run_id) REFERENCES runs(job_name, run_id)
            );
            CREATE TABLE IF NOT EXISTS run_changes (
                job_name TEXT NOT NULL,
                run_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                change_kind TEXT NOT NULL CHECK (change_kind IN ('new', 'updated', 'unchanged', 'missing')),
                fields_json TEXT NOT NULL,
                PRIMARY KEY (job_name, run_id, record_id),
                FOREIGN KEY (job_name, run_id) REFERENCES runs(job_name, run_id)
            );
            CREATE INDEX IF NOT EXISTS idx_record_versions_lookup
                ON record_versions(job_name, record_id, recorded_at);
            CREATE INDEX IF NOT EXISTS idx_runs_lookup ON runs(job_name, recorded_at DESC);
            """
        )
        version = connection.execute("SELECT version FROM history_schema LIMIT 1").fetchone()
        if version is None:
            connection.execute("INSERT INTO history_schema (version) VALUES (?)", (_SCHEMA_VERSION,))
        elif version["version"] != _SCHEMA_VERSION:
            raise ValueError("Unsupported SQLite history schema version.")

    @staticmethod
    def _current_records(connection: sqlite3.Connection, job_name: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            """SELECT record_id, content_hash, business_json FROM current_records
               WHERE job_name = ? AND is_present = 1 ORDER BY record_id""",
            (job_name,),
        ).fetchall()
        return [
            {"record_id": row["record_id"], "content_hash": row["content_hash"], "business": _mapping(row["business_json"])}
            for row in rows
        ]

    @staticmethod
    def _insert_changes(connection: sqlite3.Connection, job_name: str, run_id: str, changes: ChangeSet) -> None:
        rows = [
            *( (job_name, run_id, record_id, "new", "[]") for record_id in changes.new ),
            *( (job_name, run_id, record_id, "updated", _json(list(fields))) for record_id, fields in (changes.updated or {}).items() ),
            *( (job_name, run_id, record_id, "unchanged", "[]") for record_id in changes.unchanged ),
            *( (job_name, run_id, record_id, "missing", "[]") for record_id in changes.missing ),
        ]
        connection.executemany(
            """INSERT INTO run_changes (job_name, run_id, record_id, change_kind, fields_json)
               VALUES (?, ?, ?, ?, ?)""",
            rows,
        )


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _mapping(value: str) -> dict[str, Any]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("Stored history business must be a JSON mapping.")
    return decoded


def _changes_json(changes: ChangeSet) -> str:
    return _json(changes.to_dict())


def _changes_from_json(value: str) -> ChangeSet:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("Stored history changes must be a JSON mapping.")
    updated = decoded.get("updated", {})
    if not isinstance(updated, dict):
        raise ValueError("Stored history updated changes must be a mapping.")
    return ChangeSet(
        new=tuple(decoded.get("new", [])),
        updated={record_id: tuple(fields) for record_id, fields in updated.items()},
        unchanged=tuple(decoded.get("unchanged", [])),
        missing=tuple(decoded.get("missing", [])),
    )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Stored history timestamps must include a timezone.")
    return parsed
