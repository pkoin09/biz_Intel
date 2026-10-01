"""
Minimal output export writer.

CSV/JSON only, projected to output.fields if given. Full "export
projection and output formats" work is a later roadmap item; this covers
the minimal reproducible job run path.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from biz_intel.config import BASE_DIR, config
from biz_intel.delivery.contract import provenance_payload, quality_payload
from biz_intel.jobs.models import JobOutput
from biz_intel.models.business import Business


@dataclass(frozen=True, slots=True)
class DeliveryExportResult:
    destination: Path
    record_count: int
    quality_destination: Path | None
    evidence_destination: Path | None
    summary_destination: Path | None = None


def export(
    businesses: Iterable[Business],
    output: JobOutput,
    job_name: str,
    run_id: str | None = None,
) -> tuple[Path, int]:
    """
    Write businesses to output.destination (or a config.EXPORT_PATH
    default) in output.format. Returns (destination, records written).
    """

    destination = _resolve_destination(output, job_name, run_id)
    destination.parent.mkdir(parents=True, exist_ok=True)

    rows = [_project(business, output.fields) for business in businesses]

    if output.format == "json":
        destination.write_text(json.dumps(rows, indent=2, default=str))
    else:
        _write_csv(destination, rows)

    return destination, len(rows)


def export_delivery(
    businesses: list[Business],
    output: JobOutput,
    job_name: str,
    *,
    run_id: str | None = None,
    include_non_accepted: bool,
    include_sidecars: bool,
    summary_payload: dict[str, object] | None = None,
) -> DeliveryExportResult:
    """Write a client main file and optional quality/evidence sidecars.

    The main file contains accepted records by default. Sidecars retain the
    classification and field evidence for every record without exporting raw
    provider payloads.
    """

    selected = (
        businesses
        if include_non_accepted
        else [business for business in businesses if business.record_status == "accepted"]
    )
    destination, record_count = export(selected, output, job_name, run_id)
    summary_destination = None
    if summary_payload is not None:
        summary_destination = _sidecar_destination(destination, "summary")
        summary_destination.write_text(json.dumps(summary_payload, indent=2))

    if not include_sidecars:
        return DeliveryExportResult(
            destination,
            record_count,
            None,
            None,
            summary_destination,
        )

    quality_destination = _sidecar_destination(destination, "quality")
    evidence_destination = _sidecar_destination(destination, "evidence")
    quality_destination.write_text(
        json.dumps([quality_payload(item) for item in businesses], indent=2)
    )
    evidence_destination.write_text(
        json.dumps([provenance_payload(item) for item in businesses], indent=2)
    )
    return DeliveryExportResult(
        destination,
        record_count,
        quality_destination,
        evidence_destination,
        summary_destination,
    )


def _resolve_destination(
    output: JobOutput,
    job_name: str,
    run_id: str | None,
) -> Path:
    if not output.destination:
        path = config.EXPORT_PATH / f"{job_name}.{output.format}"
    else:
        path = Path(output.destination)
        path = path if path.is_absolute() else BASE_DIR / path

    if run_id and path.parent == config.EXPORT_PATH:
        return path.parent / job_name / run_id / path.name
    return path


def _project(
    business: Business,
    fields: tuple[str, ...],
) -> dict:
    data = business.to_dict()
    return {field: data.get(field) for field in fields} if fields else data


def _write_csv(
    destination: Path,
    rows: list[dict],
) -> None:
    if not rows:
        destination.write_text("")
        return

    with destination.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _sidecar_destination(destination: Path, kind: str) -> Path:
    return destination.with_name(f"{destination.stem}.{kind}.json")
