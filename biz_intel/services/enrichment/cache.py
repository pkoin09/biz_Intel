"""
DuckDB-backed cache for place/business contact details.

Keyed by (source, source_id). Records expire after CACHE_TTL_DAYS days so
stale contact info is eventually re-fetched without manual cache busting.

DuckDB is used instead of SQLite because it is already a project dependency,
supports Parquet export natively (COPY ... TO 'file.parquet'), and makes
analytical queries over the cache (hit rates, age distributions, source
breakdowns) fast without any extra tooling.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections.abc import Mapping
from pathlib import Path

import duckdb

CACHE_TTL_DAYS = 90

_CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS place_details_cache (
        source     VARCHAR NOT NULL,
        source_id  VARCHAR NOT NULL,
        phone      VARCHAR NOT NULL DEFAULT '',
        website    VARCHAR NOT NULL DEFAULT '',
        fetched_at VARCHAR NOT NULL,
        PRIMARY KEY (source, source_id)
    )
"""


class PlaceDetailsCache:

    def __init__(
        self,
        path: Path,
        retention_days_by_source: Mapping[str, int] | None = None,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(path)
        self._retention_days_by_source = dict(retention_days_by_source or {})
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)

    def get(self, source: str, source_id: str) -> tuple[str, str] | None:
        retention_days = self._retention_days(source)
        if retention_days is None or retention_days <= 0:
            self.delete(source, source_id)
            return None
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT phone, website FROM place_details_cache "
                "WHERE source = ? AND source_id = ? AND fetched_at > ?",
                [source, source_id, cutoff],
            ).fetchone()
        if row is None:
            self.delete(source, source_id)
        return (row[0], row[1]) if row else None

    def set(self, source: str, source_id: str, phone: str, website: str) -> None:
        retention_days = self._retention_days(source)
        if retention_days is None or retention_days <= 0:
            self.delete(source, source_id)
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO place_details_cache "
                "(source, source_id, phone, website, fetched_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [source, source_id, phone, website, now],
            )

    def delete(self, source: str, source_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM place_details_cache WHERE source = ? AND source_id = ?",
                [source, source_id],
            )

    def _retention_days(self, source: str) -> int:
        return self._retention_days_by_source.get(source, CACHE_TTL_DAYS)

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self._path)
