"""
What JobRunner produces and persists per job run.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from biz_intel.config import config
from biz_intel.models.business import Business, FieldProvenance
from biz_intel.services.enrichment import CostLine


@dataclass(slots=True)
class TaskResult:
    """The outcome of running a single SourceTask."""

    source: str
    location: str
    requested_limit: int | None
    raw_count: int
    error: str | None = None
    attempts: int = 0
    outcome: str = "success"
    detail: str | None = None
    task_index: int | None = None


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """A no-I/O execution ceiling report for a planned job.

    The report deliberately distinguishes a known maximum from an unbounded
    value.  Provider acquisition prices are policy text today, so it never
    invents a dollar estimate for them.  Only capped contact-detail enrichment
    has a local planning estimate.
    """

    job_name: str
    task_count: int
    maximum_source_invocations: int
    maximum_acquisition_records: int | None
    maximum_enrichment_calls: int
    estimated_max_enrichment_spend: float
    unbounded_cost_sources: tuple[str, ...] = ()
    source_cost_models: dict[str, str] = field(default_factory=dict)

    @property
    def has_unbounded_cost(self) -> bool:
        return bool(self.unbounded_cost_sources)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunCheckpoint:
    """Sanitized acquisition state needed to continue an interrupted run.

    Checkpoints intentionally omit ``Business.raw_data``.  They retain only
    canonical records already crossed into the shared pipeline boundary, and
    are stored under the existing ignored ``runs/`` artifact directory.
    """

    run_id: str
    job_name: str
    job_fingerprint: str
    started_at: datetime
    tasks: list[TaskResult] = field(default_factory=list)
    businesses: list[Business] = field(default_factory=list)

    @property
    def destination(self) -> Path:
        return config.RUNS_PATH / f"{self.run_id}.checkpoint.json"

    def write(self) -> Path:
        config.RUNS_PATH.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "run_id": self.run_id,
            "job_name": self.job_name,
            "job_fingerprint": self.job_fingerprint,
            "started_at": self.started_at.isoformat(),
            "tasks": [asdict(task) for task in self.tasks],
            "businesses": [_checkpoint_business(business) for business in self.businesses],
        }
        self.destination.write_text(json.dumps(payload, indent=2))
        return self.destination

    @classmethod
    def load(cls, path: str | Path) -> "RunCheckpoint":
        checkpoint_path = Path(path)
        try:
            payload = json.loads(checkpoint_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to load run checkpoint: {checkpoint_path}") from exc

        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("Run checkpoint must be a version 1 mapping.")
        try:
            tasks = [TaskResult(**item) for item in payload["tasks"]]
            businesses = [_business_from_checkpoint(item) for item in payload["businesses"]]
            return cls(
                run_id=_checkpoint_string(payload, "run_id"),
                job_name=_checkpoint_string(payload, "job_name"),
                job_fingerprint=_checkpoint_string(payload, "job_fingerprint"),
                started_at=datetime.fromisoformat(_checkpoint_string(payload, "started_at")),
                tasks=tasks,
                businesses=businesses,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Run checkpoint has an invalid shape.") from exc


@dataclass(slots=True)
class OutputResult:
    """Where a run's projected Business export landed."""

    destination: str
    format: str
    record_count: int
    quality_destination: str | None = None
    evidence_destination: str | None = None
    summary_destination: str | None = None
    status_counts: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class CostResult:
    """
    A run's enrichment spend, communicated per source.

    ``lines`` holds a ``CostLine`` per source that carries a ``max_enrich``
    cap; total aggregates across them. Numbers are enrichment-estimates
    (see ``budget.ESTIMATED_COST_PER_CALL``) - paid_calls is exact, spend is
    an upper bound until free-tier accounting lands.
    """

    lines: list[CostLine] = field(default_factory=list)

    @property
    def total_paid_calls(self) -> int:
        return sum(line.paid_calls for line in self.lines)

    @property
    def total_estimated_spend(self) -> float:
        return round(sum(line.estimated_spend for line in self.lines), 2)


@dataclass(frozen=True, slots=True)
class HistoryResult:
    """Where a sanitized accepted-record snapshot was stored for this run."""

    destination: str
    changes: dict[str, Any]


@dataclass(slots=True)
class RunResult:
    """
    A job run's manifest: identity, per-task outcomes, pipeline metrics,
    and where the output landed. Rendered two ways - written as JSON to
    config.RUNS_PATH, and as a human-readable console summary.
    """

    run_id: str
    job_name: str
    started_at: datetime
    finished_at: datetime
    tasks: list[TaskResult] = field(default_factory=list)
    pipeline_metrics: dict[str, int] = field(default_factory=dict)
    source_health: list[dict[str, object]] = field(default_factory=list)
    output: OutputResult | None = None
    cost: CostResult | None = None
    history: HistoryResult | None = None
    checkpoint_destination: str | None = None
    resumed_from: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        data["finished_at"] = self.finished_at.isoformat()
        return data

    def write(self) -> Path:
        config.RUNS_PATH.mkdir(parents=True, exist_ok=True)
        destination = config.RUNS_PATH / f"{self.run_id}.json"
        destination.write_text(json.dumps(self.to_dict(), indent=2))
        return destination

    def summary(self) -> str:
        lines = [f"Job: {self.job_name} ({self.run_id})"]

        for task in self.tasks:
            location = task.location or "any"
            if task.outcome == "skipped":
                status = f"SKIPPED: {task.detail or 'source health threshold reached'}"
            elif task.error:
                status = f"ERROR: {task.error}"
            else:
                status = f"{task.raw_count} raw"
            lines.append(f"  - {task.source} / {location}: {status}")

        if self.pipeline_metrics:
            lines.append("Pipeline metrics:")
            for key, value in sorted(self.pipeline_metrics.items()):
                lines.append(f"  {key}: {value}")

        if self.source_health:
            lines.append("Source health:")
            for health in self.source_health:
                lines.append(
                    "  "
                    f"{health['source']}: {health['status']} "
                    f"({health['attempts']} attempts)"
                )

        if self.output:
            lines.append(
                f"Output: {self.output.record_count} records -> "
                f"{self.output.destination}"
            )
            if self.output.status_counts:
                counts = ", ".join(
                    f"{status}={count}"
                    for status, count in sorted(self.output.status_counts.items())
                )
                lines.append(f"Quality: {counts}")
            if self.output.summary_destination:
                lines.append(f"Quality summary: {self.output.summary_destination}")

        if self.cost and self.cost.lines:
            lines.append("Enrichment cost (estimated):")
            for line in self.cost.lines:
                status = "capped" if line.capped else ""
                lines.append(
                    f"  {line.source}: {line.paid_calls} paid calls "
                    f"(~${line.estimated_spend}) {status}".rstrip()
                )
            lines.append(
                f"  total: {self.cost.total_paid_calls} paid calls "
                f"(~${self.cost.total_estimated_spend})"
            )

        return "\n".join(lines)


def job_fingerprint(job: object) -> str:
    """Return a stable identity for the parsed job definition."""

    payload = asdict(job)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode()).hexdigest()


def _checkpoint_string(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"Run checkpoint {key} must be a non-empty string.")
    return value


def _checkpoint_business(business: Business) -> dict[str, Any]:
    """Serialize canonical state without retaining source-private raw payloads."""

    data = business.to_dict()
    data.pop("raw_data", None)
    for key in ("scraped_at", "observed_at"):
        value = data.get(key)
        if value is not None:
            data[key] = value.isoformat()
    for value in data["field_provenance"].values():
        observed_at = value.get("observed_at")
        if observed_at is not None:
            value["observed_at"] = observed_at.isoformat()
    return data


def _business_from_checkpoint(data: object) -> Business:
    if not isinstance(data, dict):
        raise ValueError("Run checkpoint business must be a mapping.")
    restored = dict(data)
    restored["raw_data"] = None
    restored["quality_reasons"] = tuple(restored.get("quality_reasons", ()))
    for key in ("scraped_at", "observed_at"):
        value = restored.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"Run checkpoint {key} must be an ISO timestamp.")
            restored[key] = datetime.fromisoformat(value)
    provenance: dict[str, FieldProvenance] = {}
    raw_provenance = restored.get("field_provenance", {})
    if not isinstance(raw_provenance, dict):
        raise ValueError("Run checkpoint field_provenance must be a mapping.")
    for field_name, value in raw_provenance.items():
        if not isinstance(value, dict):
            raise ValueError("Run checkpoint provenance entry must be a mapping.")
        evidence = dict(value)
        observed_at = evidence.get("observed_at")
        if observed_at is not None:
            if not isinstance(observed_at, str):
                raise ValueError("Run checkpoint provenance timestamp is invalid.")
            evidence["observed_at"] = datetime.fromisoformat(observed_at)
        provenance[field_name] = FieldProvenance(**evidence)
    restored["field_provenance"] = provenance
    return Business.from_dict(restored)
