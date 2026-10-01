"""
Executes a validated JobSpec end to end.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from itertools import islice
from time import sleep

from biz_intel.config import config
from biz_intel.core.executor import RetryableSourceError
from biz_intel.core.pipeline import PipelineRunner
from biz_intel.core.registry import SourceRegistry
from biz_intel.core.registry import registry as default_registry
from biz_intel.core.source_health import SourceHealthTracker, SourceTaskOutcome
from biz_intel.core.source_task import SourceTask
from biz_intel.delivery import DeliveryContract, delivery_summary_payload
from biz_intel.metrics import metrics
from biz_intel.models.business import Business
from biz_intel.services.enrichment import EnrichmentRunner
from biz_intel.services.exporter import export_delivery
from biz_intel.services.verification import PhoneVerificationRunner
from biz_intel.storage import RunHistoryStore

from .models import JobSpec
from .planner import Planner
from .run import (
    CostResult,
    HistoryResult,
    OutputResult,
    PreflightResult,
    RunCheckpoint,
    RunResult,
    TaskResult,
    job_fingerprint,
)
from biz_intel.services.enrichment.budget import ESTIMATED_COST_PER_CALL


class JobRunner:
    """
    Runs a JobSpec: plans SourceTasks, executes each against the
    SourceRegistry, runs the collected results through PipelineRunner,
    trims to job.limit, exports, and records a RunResult.

    A single failing SourceTask is recorded and skipped rather than
    aborting the run - multi-task fan-out is the default case, not an
    edge case, so one flaky source/location must not cost every other
    task's results.
    """

    def __init__(
        self,
        planner: Planner | None = None,
        registry: SourceRegistry | None = None,
        sleeper: Callable[[float], None] = sleep,
        history_store: RunHistoryStore | None = None,
        progress_reporter: Callable[[str], None] | None = print,
    ) -> None:
        self.planner = planner or Planner()
        self.registry = registry or default_registry
        self._sleeper = sleeper
        self._history_store = history_store or RunHistoryStore(
            config.RUNS_PATH / "history"
        )
        self._progress_reporter = progress_reporter

    def preflight(self, job: JobSpec) -> PreflightResult:
        """Report execution and known spend ceilings without invoking sources."""

        tasks = self.planner.plan(job)
        live_smoke = job.execution.live_smoke
        max_attempts = live_smoke.max_attempts if live_smoke is not None else 1
        source_cost_models: dict[str, str] = {}
        for source in job.sources:
            try:
                source_cost_models[source] = self.registry.get_policy(source).cost_model
            except KeyError:
                source_cost_models[source] = "unregistered"

        maximum_records = self._maximum_acquisition_records(job, tasks)
        capped_calls = 0
        estimated_spend = 0.0
        unbounded: list[str] = []
        for source in job.sources:
            options = job.source_options.get(source, {})
            if not options.get("enrich_details", False):
                continue
            cap = options.get("max_enrich")
            if cap is None:
                unbounded.append(source)
                continue
            capped_calls += cap
            estimated_spend += cap * ESTIMATED_COST_PER_CALL.get(source, 0.0)

        return PreflightResult(
            job_name=job.name,
            task_count=len(tasks),
            maximum_source_invocations=len(tasks) * max_attempts,
            maximum_acquisition_records=maximum_records,
            maximum_enrichment_calls=capped_calls,
            estimated_max_enrichment_spend=round(estimated_spend, 2),
            unbounded_cost_sources=tuple(sorted(unbounded)),
            source_cost_models=source_cost_models,
        )

    def run(
        self,
        job: JobSpec,
        *,
        resume_from: str | None = None,
    ) -> RunResult:
        # A JobRunner always writes an export, so make this decision before
        # planning or issuing even one source request.
        self.registry.require_delivery_approval(job.sources)
        if getattr(job.execution, "mode", "delivery") == "live_smoke":
            self.registry.require_live_smoke_approval(job.sources)
        preflight = self.preflight(job)
        if preflight.estimated_max_enrichment_spend > job.budget.max_total_usd:
            raise ValueError(
                "Configured paid enrichment exceeds budget.max_total_usd. "
                "Lower max_enrich or raise the client-approved budget."
            )

        checkpoint = self._resume_checkpoint(job, resume_from)
        started_at = checkpoint.started_at if checkpoint else datetime.now(timezone.utc)
        run_id = (
            checkpoint.run_id
            if checkpoint
            else f"{job.name}-{started_at.strftime('%Y%m%dT%H%M%SZ')}"
        )

        execution = getattr(job, "execution", None)
        live_smoke = getattr(execution, "live_smoke", None)
        max_attempts = getattr(live_smoke, "max_attempts", 1)
        failure_threshold = getattr(live_smoke, "failure_threshold", 3)
        retry_backoff = getattr(live_smoke, "retry_backoff_seconds", 0)
        health = SourceHealthTracker(failure_threshold=failure_threshold)
        planned_tasks = self.planner.plan(job)
        self._report(f"Run {run_id}: {len(planned_tasks)} source tasks planned")

        task_results = list(checkpoint.tasks) if checkpoint else []
        collected = list(checkpoint.businesses) if checkpoint else []
        completed_task_indices = {
            task.task_index
            for task in task_results
            if task.task_index is not None and task.outcome in {"success", "empty"}
        }
        retry_task_indices = {
            task.task_index
            for task in task_results
            if task.task_index is not None and task.task_index not in completed_task_indices
        }
        if retry_task_indices:
            task_results = [
                task for task in task_results if task.task_index not in retry_task_indices
            ]
        source_counts, location_counts = self._counts_from_tasks(task_results)
        total_count = sum(task.raw_count for task in task_results)
        active_checkpoint = RunCheckpoint(
            run_id=run_id,
            job_name=job.name,
            job_fingerprint=job_fingerprint(job),
            started_at=started_at,
            tasks=task_results,
            businesses=collected,
        )

        self._report("Acquire: running source tasks")
        self._acquire_tasks(
            job,
            planned_tasks,
            task_results=task_results,
            collected=collected,
            completed_task_indices=completed_task_indices,
            active_checkpoint=active_checkpoint,
            health=health,
            live_smoke=live_smoke,
            max_attempts=max_attempts,
            retry_backoff=retry_backoff,
            source_counts=source_counts,
            location_counts=location_counts,
            total_count=total_count,
        )

        self._report(f"Acquire: {len(collected)} records collected")
        processed = list(
            PipelineRunner(fuzzy_deduplicate=job.processing.fuzzy_deduplicate).run(
                iter(collected),
                on_stage_complete=self._report_pipeline_stage,
            )
        )

        if job.limit is not None:
            processed = processed[: job.limit]

        self._report(f"Enrich: {len(processed)} records")
        enrichment = EnrichmentRunner.from_job(
            job,
            {
                name: self.registry.get_policy(name)
                for name in job.sources
            },
        )
        processed = enrichment.run(processed)

        self._report(f"Verify contacts: {len(processed)} records")
        processed = PhoneVerificationRunner.from_job(job).run(processed)

        self._report(f"Classify: {len(processed)} records")
        delivery = DeliveryContract(
            job.delivery.profile,
            max_age_days=job.delivery.max_age_days,
        ).classify(processed)
        pipeline_metrics = dict(metrics.items())
        delivered_records = sum(
            1
            for business in delivery.businesses
            if job.delivery.include_non_accepted
            or business.record_status == "accepted"
        )
        exported = export_delivery(
            delivery.businesses,
            job.output,
            job.name,
            run_id=run_id,
            include_non_accepted=job.delivery.include_non_accepted,
            include_sidecars=job.delivery.include_sidecars,
            summary_payload=delivery_summary_payload(
                delivery.businesses,
                acquired_records=len(collected),
                delivered_records=delivered_records,
                pipeline_metrics=pipeline_metrics,
            ),
        )
        self._report(
            "Export: "
            f"{exported.record_count} records delivered "
            f"({', '.join(f'{status}={count}' for status, count in sorted(delivery.status_counts.items()))})"
        )
        # History is intentionally limited to delivery-accepted records: they
        # meet the stable identity and evidence requirements of the client
        # contract.  Incomplete research observations remain in the quality
        # sidecar rather than making a completed job fail to persist history.
        history_snapshot = self._history_store.record(
            job.name,
            run_id,
            [
                business
                for business in delivery.businesses
                if business.record_status == "accepted"
            ],
        )

        result = RunResult(
            run_id=run_id,
            job_name=job.name,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            tasks=task_results,
            pipeline_metrics=pipeline_metrics,
            source_health=[report.to_dict() for report in health.reports()],
            output=OutputResult(
                destination=str(exported.destination),
                format=job.output.format,
                record_count=exported.record_count,
                quality_destination=(
                    str(exported.quality_destination)
                    if exported.quality_destination
                    else None
                ),
                evidence_destination=(
                    str(exported.evidence_destination)
                    if exported.evidence_destination
                    else None
                ),
                summary_destination=(
                    str(exported.summary_destination)
                    if exported.summary_destination
                    else None
                ),
                status_counts=delivery.status_counts,
            ),
            cost=(
                CostResult(lines=enrichment.budget.cost_lines())
                if enrichment.budget is not None
                else None
            ),
            history=HistoryResult(
                destination=str(history_snapshot.destination),
                changes=history_snapshot.changes.to_dict(),
            ),
            checkpoint_destination=str(active_checkpoint.destination),
            resumed_from=str(resume_from) if resume_from else None,
        )
        result.write()
        self._report(f"Run complete: {result.run_id}")
        return result

    def _report_pipeline_stage(self, stage: str, record_count: int) -> None:
        self._report(f"{stage.title()}: {record_count} records")

    def _report(self, message: str) -> None:
        """Emit a fixed-size, data-free console progress message when enabled."""

        if self._progress_reporter is not None:
            self._progress_reporter(message)

    def _resume_checkpoint(
        self,
        job: JobSpec,
        resume_from: str | None,
    ) -> RunCheckpoint | None:
        if resume_from is None:
            return None
        checkpoint = RunCheckpoint.load(resume_from)
        if checkpoint.job_name != job.name:
            raise ValueError("Run checkpoint job_name does not match the requested job.")
        if checkpoint.job_fingerprint != job_fingerprint(job):
            raise ValueError("Run checkpoint does not match the requested job definition.")
        return checkpoint

    @staticmethod
    def _with_task_index(result: TaskResult, task_index: int) -> TaskResult:
        result.task_index = task_index
        return result

    @staticmethod
    def _counts_from_tasks(
        task_results: list[TaskResult],
    ) -> tuple[dict[str, int], dict[str, int]]:
        source_counts: dict[str, int] = {}
        location_counts: dict[str, int] = {}
        for task in task_results:
            if task.outcome not in {"success", "empty"}:
                continue
            source_counts[task.source] = source_counts.get(task.source, 0) + task.raw_count
            location_counts[task.location] = (
                location_counts.get(task.location, 0) + task.raw_count
            )
        return source_counts, location_counts

    @staticmethod
    def _maximum_acquisition_records(
        job: JobSpec,
        tasks: list[SourceTask],
    ) -> int | None:
        """Return a safe acquisition ceiling, or ``None`` when it is open-ended."""

        source_counts: dict[str, int] = {}
        location_counts: dict[str, int] = {}
        total_count = 0
        for task in tasks:
            limit, skipped = JobRunner._remaining_task_limit(
                job,
                task,
                source_counts=source_counts,
                location_counts=location_counts,
                total_count=total_count,
            )
            if skipped:
                continue
            if limit is None:
                return None
            source = str(task.source)
            location = _location_label(task)
            source_counts[source] = source_counts.get(source, 0) + limit
            location_counts[location] = location_counts.get(location, 0) + limit
            total_count += limit
        return total_count

    def _run_task(
        self,
        task: SourceTask,
        collected: list[Business],
        *,
        health: SourceHealthTracker,
        max_attempts: int,
        retry_backoff: float,
    ) -> TaskResult:
        result, businesses = self._execute_task(
            task,
            health=health,
            max_attempts=max_attempts,
            retry_backoff=retry_backoff,
        )
        collected.extend(businesses)
        return result

    def _execute_task(
        self,
        task: SourceTask,
        *,
        health: SourceHealthTracker,
        max_attempts: int,
        retry_backoff: float,
    ) -> tuple[TaskResult, list[Business]]:
        """Run one task without mutating shared collected-record state.

        The scheduler permits only one in-flight task for a given source, so
        health mutations remain source-serial even when independent sources
        run concurrently.
        """

        location = _location_label(task)
        source = str(task.source)

        if health.get(source).should_stop:
            return (
                self._skip_task(task, health, "source health failure threshold reached"),
                [],
            )

        for attempt in range(1, max_attempts + 1):
            try:
                businesses = list(islice(self.registry.run(source, task), task.limit))
            except RetryableSourceError as exc:
                health.record(
                    source,
                    SourceTaskOutcome.RETRYABLE_FAILURE,
                    error="retryable_source_failure",
                )
                if attempt < max_attempts and not health.get(source).should_stop:
                    if retry_backoff:
                        self._sleeper(retry_backoff)
                    continue
                return (
                    TaskResult(
                        source=source,
                        location=location,
                        requested_limit=task.limit,
                        raw_count=0,
                        error="retryable_source_failure",
                        attempts=attempt,
                        outcome=SourceTaskOutcome.RETRYABLE_FAILURE.value,
                    ),
                    [],
                )
            except Exception as exc:
                health.record(
                    source,
                    SourceTaskOutcome.FATAL_FAILURE,
                    error="fatal_source_failure",
                )
                return (
                    TaskResult(
                        source=source,
                        location=location,
                        requested_limit=task.limit,
                        raw_count=0,
                        error="fatal_source_failure",
                        attempts=attempt,
                        outcome=SourceTaskOutcome.FATAL_FAILURE.value,
                    ),
                    [],
                )

            outcome = (
                SourceTaskOutcome.SUCCESS if businesses else SourceTaskOutcome.EMPTY
            )
            health.record(source, outcome)
            return (
                TaskResult(
                    source=source,
                    location=location,
                    requested_limit=task.limit,
                    raw_count=len(businesses),
                    attempts=attempt,
                    outcome=outcome.value,
                ),
                businesses,
            )

        raise AssertionError("max_attempts must be at least 1")

    def _acquire_tasks(
        self,
        job: JobSpec,
        planned_tasks: list[SourceTask],
        *,
        task_results: list[TaskResult],
        collected: list[Business],
        completed_task_indices: set[int],
        active_checkpoint: RunCheckpoint,
        health: SourceHealthTracker,
        live_smoke: object | None,
        max_attempts: int,
        retry_backoff: float,
        source_counts: dict[str, int],
        location_counts: dict[str, int],
        total_count: int,
    ) -> None:
        """Acquire deterministically while allowing independent sources to overlap.

        Every source is deliberately serialized.  This preserves source-local
        rate constraints and ensures a failure threshold prevents later work
        from that same source.  Aggregate limits are reserved at dispatch
        time, then reconciled with actual rows as futures finish, so parallel
        locations/sources cannot exceed a job cap.
        """

        max_workers = job.execution.max_parallel_tasks
        pending = {
            index for index in range(len(planned_tasks))
            if index not in completed_task_indices
        }
        running: dict[Future[tuple[TaskResult, list[Business]]], tuple[int, SourceTask]] = {}
        active_sources: set[str] = set()
        reservations: dict[int, int] = {}
        completed: dict[int, tuple[TaskResult, list[Business]]] = {}
        next_checkpoint_index = 0
        while next_checkpoint_index in completed_task_indices:
            next_checkpoint_index += 1

        def reserved_counts() -> tuple[dict[str, int], dict[str, int], int]:
            reserved_source = dict(source_counts)
            reserved_location = dict(location_counts)
            reserved_total = total_count
            for task_index, amount in reservations.items():
                task = planned_tasks[task_index]
                source = str(task.source)
                location = _location_label(task)
                reserved_source[source] = reserved_source.get(source, 0) + amount
                reserved_location[location] = reserved_location.get(location, 0) + amount
                reserved_total += amount
            return reserved_source, reserved_location, reserved_total

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            while pending or running or completed:
                # Fill free worker slots in planned-task order.  A later task
                # may begin before an earlier task only when its source is
                # independent; output/checkpoints still commit in task order.
                for task_index in sorted(tuple(pending)):
                    if len(running) >= max_workers:
                        break
                    task = planned_tasks[task_index]
                    source = str(task.source)
                    if source in active_sources:
                        continue
                    if live_smoke is not None and task_index >= live_smoke.max_tasks:
                        completed[task_index] = (
                            self._skip_task(task, health, "live smoke task cap reached"),
                            [],
                        )
                        pending.remove(task_index)
                        continue
                    # A cap reached by completed work is a permanent skip. A
                    # cap reached only by an in-flight reservation is not: the
                    # earlier source may return fewer rows than requested, in
                    # which case this task must remain eligible to fill the
                    # real delivery ceiling.
                    _, actual_skip_reason = self._remaining_task_limit(
                        job,
                        task,
                        source_counts=source_counts,
                        location_counts=location_counts,
                        total_count=total_count,
                    )
                    if actual_skip_reason:
                        completed[task_index] = (
                            self._skip_task(task, health, actual_skip_reason), []
                        )
                        pending.remove(task_index)
                        continue
                    reserved_source, reserved_location, reserved_total = reserved_counts()
                    limit, reservation_skip_reason = self._remaining_task_limit(
                        job,
                        task,
                        source_counts=reserved_source,
                        location_counts=reserved_location,
                        total_count=reserved_total,
                    )
                    if reservation_skip_reason:
                        # Keep this task pending until an in-flight result
                        # releases enough real capacity to make it eligible.
                        continue
                    task.limit = limit
                    # ``limit`` is always finite when an aggregate cap is in
                    # play.  Reserving it prevents concurrent tasks from
                    # overshooting; an unlimited task needs no reservation.
                    if limit is not None:
                        reservations[task_index] = limit
                    running[executor.submit(
                        self._execute_task,
                        task,
                        health=health,
                        max_attempts=max_attempts,
                        retry_backoff=retry_backoff,
                    )] = (task_index, task)
                    active_sources.add(source)
                    pending.remove(task_index)

                while next_checkpoint_index in completed:
                    result, businesses = completed.pop(next_checkpoint_index)
                    task_results.append(self._with_task_index(result, next_checkpoint_index))
                    collected.extend(businesses)
                    active_checkpoint.write()
                    next_checkpoint_index += 1

                if not running:
                    continue

                done, _ = wait(tuple(running), return_when=FIRST_COMPLETED)
                for future in sorted(done, key=lambda item: running[item][0]):
                    task_index, task = running.pop(future)
                    active_sources.remove(str(task.source))
                    reservations.pop(task_index, None)
                    result, businesses = future.result()
                    completed[task_index] = (result, businesses)
                    if businesses:
                        source = str(task.source)
                        location = _location_label(task)
                        source_counts[source] = source_counts.get(source, 0) + len(businesses)
                        location_counts[location] = location_counts.get(location, 0) + len(businesses)
                        total_count += len(businesses)

    @staticmethod
    def _remaining_task_limit(
        job: JobSpec,
        task: SourceTask,
        *,
        source_counts: dict[str, int],
        location_counts: dict[str, int],
        total_count: int,
    ) -> tuple[int | None, str | None]:
        """Intersect per-task and aggregate acquisition caps before execution."""

        limits = job.limits
        candidates = [limit for limit in (task.limit,) if limit is not None]
        source = str(task.source)
        location = _location_label(task)
        boundaries = (
            (limits.total_records, total_count, "total records cap reached"),
            (
                limits.per_source_records,
                source_counts.get(source, 0),
                "source records cap reached",
            ),
            (
                limits.per_location_records,
                location_counts.get(location, 0),
                "location records cap reached",
            ),
        )
        for cap, used, reason in boundaries:
            if cap is None:
                continue
            remaining = cap - used
            if remaining <= 0:
                return None, reason
            candidates.append(remaining)
        return (min(candidates) if candidates else None), None

    def _skip_task(
        self,
        task: SourceTask,
        health: SourceHealthTracker,
        detail: str,
    ) -> TaskResult:
        """Record withheld work without sending it to a source executor."""

        source = str(task.source)
        health.record(source, SourceTaskOutcome.SKIPPED)
        return TaskResult(
            source=source,
            location=_location_label(task),
            requested_limit=task.limit,
            raw_count=0,
            attempts=0,
            outcome=SourceTaskOutcome.SKIPPED.value,
            detail=detail,
        )


def _location_label(task: SourceTask) -> str:
    if task.location is None:
        return ""

    parts = [
        part
        for part in (task.location.city, task.location.state)
        if part
    ]
    return ", ".join(parts)
