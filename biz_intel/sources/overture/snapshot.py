"""Prepare deterministic, local-only Overture Places candidate snapshots.

Preparation is deliberately separate from normal source execution.  It accepts
only explicit local Parquet inputs, selects a reviewed geographic and taxonomy
scope, and emits the frozen snapshot plus the version-1 manifest understood by
``OvertureSnapshotSource``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import glob
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Sequence

import duckdb


_DENTAL_ROOT = "dental_clinic"
_REQUIRED_COLUMNS = frozenset({"id", "names", "taxonomy", "bbox"})


@dataclass(frozen=True, slots=True)
class PreparedSnapshot:
    """Paths and verified size of one prepared snapshot pair."""

    snapshot_path: Path
    manifest_path: Path
    row_count: int
    sha256: str


def prepare_overture_snapshot(
    source: str | Path,
    destination: str | Path,
    *,
    release: str,
    retrieved_at: str | datetime,
    source_reference: str,
    bbox: Sequence[float],
    geography_label: str,
    license: str,
    attribution: str,
    manifest_path: str | Path | None = None,
    taxonomy_root: str = _DENTAL_ROOT,
    localities: Sequence[str] = (),
) -> PreparedSnapshot:
    """Create a deterministic dental candidate snapshot from local Parquet.

    ``source`` may be one explicit local file or a local glob.  URLs, an
    implicit latest release, antimeridian-spanning boxes, and overwrites are
    rejected.  Both output files are first completed beside their destinations
    and then atomically moved into place.
    """

    inputs = _resolve_local_inputs(source)
    output = Path(destination)
    if output.suffix.casefold() not in {".parquet", ".geoparquet"}:
        raise ValueError("Overture snapshot destination must end in .parquet or .geoparquet.")
    manifest = Path(manifest_path) if manifest_path else output.with_suffix(".manifest.json")
    if output == manifest:
        raise ValueError("Snapshot and manifest destinations must be different files.")
    if output.exists() or manifest.exists():
        raise FileExistsError("Overture snapshot preparation never overwrites existing output.")
    if any(_same_path(path, output) or _same_path(path, manifest) for path in inputs):
        raise ValueError("Overture snapshot outputs cannot also be source inputs.")

    release_text = _required_text(release, "release")
    reference_text = _required_text(source_reference, "source_reference")
    label_text = _required_text(geography_label, "geography_label")
    license_text = _required_text(license, "license")
    attribution_text = _required_text(attribution, "attribution")
    if taxonomy_root != _DENTAL_ROOT:
        raise ValueError("Only the reviewed dental_clinic taxonomy root is supported.")
    locality_scope = tuple(
        dict.fromkeys(_required_text(value, "locality").casefold() for value in localities)
    )
    observed = _timestamp(retrieved_at)
    west, south, east, north = _validated_bbox(bbox)

    output.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    parquet_temp = _temporary_path(output)
    manifest_temp = _temporary_path(manifest)
    snapshot_published = False
    try:
        source_argument: str | list[str] = (
            str(inputs[0]) if len(inputs) == 1 else [str(path) for path in inputs]
        )
        with duckdb.connect() as connection:
            columns = {
                item[0]
                for item in connection.execute(
                    "SELECT * FROM read_parquet(?) LIMIT 0", [source_argument]
                ).description
            }
            missing = sorted(_REQUIRED_COLUMNS - columns)
            if missing:
                raise ValueError(
                    "Overture Places schema-v2 input is missing required columns: "
                    + ", ".join(missing)
                )
            locality_clause = (
                " AND lower(addresses[1].locality) = ANY(?)" if locality_scope else ""
            )
            parameters: list[object] = [
                source_argument,
                west,
                east,
                south,
                north,
                taxonomy_root,
                taxonomy_root,
            ]
            if locality_scope:
                parameters.append(list(locality_scope))
            connection.execute(
                f"""
                CREATE TEMP TABLE prepared AS
                SELECT *
                FROM read_parquet(?)
                WHERE bbox.xmax >= ? AND bbox.xmin <= ?
                  AND bbox.ymax >= ? AND bbox.ymin <= ?
                  AND (
                    taxonomy.primary = ?
                    OR coalesce(list_contains(taxonomy.hierarchy, ?), false)
                  )
                  {locality_clause}
                ORDER BY id
                """,
                parameters,
            )
            row_count, blank_ids, distinct_ids = connection.execute(
                """
                SELECT count(*),
                       count(*) FILTER (WHERE id IS NULL OR trim(cast(id AS VARCHAR)) = ''),
                       count(DISTINCT id)
                FROM prepared
                """
            ).fetchone()
            if row_count == 0:
                raise ValueError("Overture snapshot scope selected no dental candidates.")
            if blank_ids:
                raise ValueError("Overture snapshot contains a blank place id.")
            if distinct_ids != row_count:
                raise ValueError("Overture snapshot contains duplicate place ids.")
            license_inventory = []
            if "sources" in columns:
                license_inventory = [
                    {
                        "license": license_name or "unknown",
                        "dataset": dataset or "unknown",
                        "provider": provider or "unknown",
                        "observations": observations,
                    }
                    for license_name, dataset, provider, observations in connection.execute(
                        """
                        SELECT source.license, source.dataset, source.provider, count(*)
                        FROM prepared, UNNEST(sources) AS item(source)
                        GROUP BY ALL
                        ORDER BY count(*) DESC, source.license, source.dataset, source.provider
                        """
                    ).fetchall()
                ]
            connection.execute(
                "COPY prepared TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                [str(parquet_temp)],
            )

        digest = hashlib.sha256(parquet_temp.read_bytes()).hexdigest()
        payload = {
            "schema_version": 1,
            "source": "overture",
            "release": release_text,
            "retrieved_at": observed.isoformat(),
            "source_reference": reference_text,
            "geography": (
                f"{label_text}; bbox=[{west},{south},{east},{north}] "
                "(west,south,east,north; inclusive overlap)"
                + (
                    "; address localities=" + ",".join(locality_scope)
                    if locality_scope
                    else ""
                )
            ),
            "taxonomy_filters": [
                "taxonomy.primary=dental_clinic",
                "taxonomy.hierarchy contains dental_clinic",
            ],
            "license": license_text,
            "license_inventory": license_inventory,
            "attribution": attribution_text,
            "row_count": row_count,
            "sha256": digest,
            "review_status": "reviewed",
            "delivery_approved": False,
        }
        manifest_temp.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(parquet_temp, output)
        snapshot_published = True
        os.replace(manifest_temp, manifest)
    except Exception:
        parquet_temp.unlink(missing_ok=True)
        manifest_temp.unlink(missing_ok=True)
        if snapshot_published:
            output.unlink(missing_ok=True)
        raise

    return PreparedSnapshot(output, manifest, row_count, digest)


def _resolve_local_inputs(source: str | Path) -> tuple[Path, ...]:
    raw = os.fspath(source)
    if not raw.strip() or "\x00" in raw or "://" in raw:
        raise ValueError("Overture snapshot source must be an explicit local Parquet path or glob.")
    matches = sorted(Path(value) for value in glob.glob(raw))
    if not matches:
        raise FileNotFoundError(f"No local Overture Parquet inputs match: {raw}")
    invalid = [
        path
        for path in matches
        if not path.is_file()
        or path.suffix.casefold() not in {".parquet", ".geoparquet"}
    ]
    if invalid:
        raise ValueError(f"Overture source input is not a Parquet file: {invalid[0]}")
    return tuple(path.resolve() for path in matches)


def _validated_bbox(values: Sequence[float]) -> tuple[float, float, float, float]:
    if isinstance(values, (str, bytes)) or len(values) != 4:
        raise ValueError("bbox must contain west, south, east, north.")
    try:
        west, south, east, north = (float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise ValueError("bbox coordinates must be numbers.") from exc
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError(
            "bbox must be valid west, south, east, north coordinates and cannot span the antimeridian."
        )
    return west, south, east, north


def _timestamp(value: str | datetime) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("retrieved_at must be an ISO timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError("retrieved_at must include a timezone.")
    return parsed


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string.")
    return value.strip()


def _temporary_path(destination: Path) -> Path:
    descriptor, value = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
    )
    os.close(descriptor)
    path = Path(value)
    path.unlink()
    return path


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()
