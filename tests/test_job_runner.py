"""Tests for JobRunner."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from time import sleep
import unittest
from unittest.mock import patch

from biz_intel.config import config
from biz_intel.core.executor import RetryableSourceError
from biz_intel.core.registry import SourceRegistry
from biz_intel.core.source_health import SourceHealthTracker
from biz_intel.core.source_kind import SourceKind
from biz_intel.core.source_policy import CLIENT_INPUT_POLICY
from biz_intel.core.source_policy import EXPERIMENTAL_OR_DISALLOWED_POLICY
from biz_intel.core.source_policy import SourcePolicyError
from biz_intel.jobs.models import JobSpec
from biz_intel.jobs.runner import JobRunner
from biz_intel.models.business import Business, FieldProvenance


class _FixedExecutor:
    """Returns the same fixed Business records for any task."""

    def __init__(self, businesses: list[Business]) -> None:
        self._businesses = businesses
        self.calls = 0

    def run(self, source_class, task):
        self.calls += 1
        return iter(self._businesses)


class _FailingExecutor:
    def run(self, source_class, task):
        raise RuntimeError("https://secret.example.test/?token=leaked")


class _FlakyExecutor:
    def __init__(self, failures: int, businesses: list[Business]) -> None:
        self.failures = failures
        self.businesses = businesses
        self.calls = 0

    def run(self, source_class, task):
        self.calls += 1
        if self.calls <= self.failures:
            raise RetryableSourceError("temporary timeout")
        return iter(self.businesses)


class _ConcurrentTrackingExecutor:
    """Records source-task overlap without exposing business data in progress."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.active = 0
        self.maximum_active = 0
        self.active_by_source: dict[str, int] = {}
        self.maximum_by_source: dict[str, int] = {}

    def run(self, source_class, task):
        source = str(task.source)
        with self._lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            self.active_by_source[source] = self.active_by_source.get(source, 0) + 1
            self.maximum_by_source[source] = max(
                self.maximum_by_source.get(source, 0),
                self.active_by_source[source],
            )
        try:
            sleep(0.03)
            return iter([Business(name=f"{source}-{task.location.city}")])
        finally:
            with self._lock:
                self.active -= 1
                self.active_by_source[source] -= 1


def _job(name: str, destination: str) -> JobSpec:
    return JobSpec.from_dict(
        {
            "version": 1,
            "name": name,
            "search": {"query": "dentist", "cities": ["San Jose, CA"]},
            "sources": ["yellowpages"],
            "limit": 100,
            "processing": {},
            "output": {
                "format": "csv",
                "fields": ["name", "phone", "website"],
                "destination": destination,
            },
        }
    )


class JobRunnerTests(unittest.TestCase):
    """Protect JobRunner's public contract."""

    def setUp(self) -> None:
        self.written_files: list[Path] = []

    def tearDown(self) -> None:
        for path in self.written_files:
            path.unlink(missing_ok=True)

    def _track_run_files(self, result) -> None:
        self.written_files.append(config.RUNS_PATH / f"{result.run_id}.json")
        if result.output and result.output.quality_destination:
            self.written_files.append(Path(result.output.quality_destination))
        if result.output and result.output.evidence_destination:
            self.written_files.append(Path(result.output.evidence_destination))
        if result.output and result.output.summary_destination:
            self.written_files.append(Path(result.output.summary_destination))
        if result.history:
            self.written_files.append(Path(result.history.destination))

    def test_runs_a_job_end_to_end(self) -> None:
        businesses = [
            Business(
                name="Bright Smiles",
                address="1 First St",
                city="San Jose",
                state="CA",
                phone="4085551111",
                website="brightsmiles.com",
                source="client_input",
                source_url="https://client.example.test/bright-smiles",
                scraped_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
            ),
            Business(
                name="Sunny Dental",
                address="2 Second St",
                city="San Jose",
                state="CA",
                phone="4085552222",
                website="sunnydental.com",
                source="client_input",
                source_url="https://client.example.test/sunny-dental",
                scraped_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
            ),
        ]

        registry = SourceRegistry(
            executors={SourceKind.SCRAPER: _FixedExecutor(businesses)}
        )
        registry.register(
            "yellowpages", object, kind=SourceKind.SCRAPER, policy=CLIENT_INPUT_POLICY
        )

        destination = (
            Path(__file__).resolve().parent / "_tmp_job_runner_output.csv"
        )
        self.written_files.append(destination)

        job = _job("job-runner-test", str(destination))
        result = JobRunner(registry=registry).run(job)
        self._track_run_files(result)

        self.assertEqual(len(result.tasks), 1)
        self.assertEqual(result.tasks[0].raw_count, 2)
        self.assertIsNone(result.tasks[0].error)
        self.assertEqual(result.output.record_count, 2)

        self.assertTrue(destination.exists())
        rows = destination.read_text().strip().splitlines()
        self.assertEqual(len(rows), 3)  # header + 2 businesses

        manifest_path = config.RUNS_PATH / f"{result.run_id}.json"
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["job_name"], "job-runner-test")
        self.assertEqual(manifest["output"]["status_counts"], {"accepted": 2})
        history_counts = result.history.changes["counts"]
        self.assertEqual(history_counts["new"] + history_counts["unchanged"], 2)
        self.assertTrue(Path(result.history.destination).exists())
        self.assertEqual(
            manifest["source_health"],
            [
                {
                    "source": "yellowpages",
                    "failure_threshold": 3,
                    "attempts": 1,
                    "successful_attempts": 1,
                    "empty_attempts": 0,
                    "retryable_failures": 0,
                    "fatal_failures": 0,
                    "skipped_attempts": 0,
                    "consecutive_failures": 0,
                    "last_outcome": "success",
                    "last_error": None,
                    "observed_at": manifest["source_health"][0]["observed_at"],
                    "status": "healthy",
                    "should_stop": False,
                }
            ],
        )
        self.assertTrue(Path(manifest["output"]["quality_destination"]).exists())
        self.assertTrue(Path(manifest["output"]["evidence_destination"]).exists())
        summary_path = Path(manifest["output"]["summary_destination"])
        self.assertTrue(summary_path.exists())
        summary = json.loads(summary_path.read_text())
        self.assertEqual(summary["records"], {
            "acquired": 2,
            "classified": 2,
            "delivered": 2,
        })
        self.assertEqual(summary["duplicates_removed"], 0)
        self.assertEqual(summary["field_completeness"]["phone"], {
            "present": 2,
            "total": 2,
            "percent": 100.0,
        })

    def test_records_a_task_error_without_aborting_the_run(self) -> None:
        registry = SourceRegistry(
            executors={SourceKind.SCRAPER: _FailingExecutor()}
        )
        registry.register(
            "yellowpages", object, kind=SourceKind.SCRAPER, policy=CLIENT_INPUT_POLICY
        )

        destination = (
            Path(__file__).resolve().parent / "_tmp_job_runner_failure.csv"
        )
        self.written_files.append(destination)

        job = _job("job-runner-error-test", str(destination))
        result = JobRunner(registry=registry).run(job)
        self._track_run_files(result)

        self.assertEqual(len(result.tasks), 1)
        self.assertEqual(result.tasks[0].error, "fatal_source_failure")
        self.assertNotIn("secret.example.test", json.dumps(result.to_dict()))
        self.assertNotIn("secret.example.test", result.summary())
        self.assertEqual(result.output.record_count, 0)

    def test_rejects_unapproved_source_before_executor_runs(self) -> None:
        executor = _FixedExecutor([Business(name="Must not be collected")])
        registry = SourceRegistry(executors={SourceKind.SCRAPER: executor})
        registry.register(
            "yellowpages",
            object,
            kind=SourceKind.SCRAPER,
            policy=EXPERIMENTAL_OR_DISALLOWED_POLICY,
        )

        destination = (
            Path(__file__).resolve().parent / "_tmp_job_runner_rejected.csv"
        )
        job = _job("job-runner-rejected-test", str(destination))

        with self.assertRaisesRegex(
            SourcePolicyError,
            r"yellowpages \(experimental_or_disallowed; delivery disabled\)",
        ):
            JobRunner(registry=registry).run(job)

        self.assertFalse(destination.exists())

    def test_rejects_live_smoke_source_without_explicit_approval(self) -> None:
        executor = _FixedExecutor([Business(name="Must not be collected")])
        registry = SourceRegistry(executors={SourceKind.SCRAPER: executor})
        registry.register(
            "yellowpages", object, kind=SourceKind.SCRAPER, policy=CLIENT_INPUT_POLICY
        )
        destination = (
            Path(__file__).resolve().parent / "_tmp_job_runner_live_smoke.csv"
        )
        job_data = {
            "version": 1,
            "name": "job-runner-live-smoke-rejected",
            "search": {"query": "dentist", "cities": ["San Jose, CA"]},
            "sources": ["yellowpages"],
            "execution": {"mode": "live_smoke"},
            "output": {"format": "csv", "destination": str(destination)},
        }

        with self.assertRaisesRegex(SourcePolicyError, "live smoke disabled"):
            JobRunner(registry=registry).run(JobSpec.from_dict(job_data))

        self.assertFalse(destination.exists())

    def test_live_smoke_retries_and_audits_tasks_after_its_cap(self) -> None:
        executor = _FlakyExecutor(1, [Business(name="Recovered")])
        registry = SourceRegistry(executors={SourceKind.SCRAPER: executor})
        registry.register(
            "yellowpages",
            object,
            kind=SourceKind.SCRAPER,
            policy=replace(
                CLIENT_INPUT_POLICY,
                live_smoke_allowed=True,
                cost_model="zero-spend",
            ),
        )
        destination = (
            Path(__file__).resolve().parent / "_tmp_job_runner_live_smoke.csv"
        )
        self.written_files.append(destination)
        sleep_calls: list[float] = []
        runner = JobRunner(registry=registry, sleeper=sleep_calls.append)
        job = JobSpec.from_dict(
            {
                "version": 1,
                "name": "job-runner-live-smoke",
                "search": {
                    "query": "dentist",
                    "cities": ["San Jose, CA", "Oakland, CA"],
                },
                "sources": ["yellowpages"],
                "execution": {
                    "mode": "live_smoke",
                    "live_smoke": {
                        "max_tasks": 1,
                        "max_attempts": 2,
                        "retry_backoff_seconds": 1,
                        "failure_threshold": 2,
                    },
                },
                "output": {"format": "csv", "destination": str(destination)},
            }
        )

        result = runner.run(job)
        self._track_run_files(result)

        self.assertEqual(executor.calls, 2)
        self.assertEqual(sleep_calls, [1])
        self.assertEqual([task.outcome for task in result.tasks], ["success", "skipped"])
        self.assertEqual(result.tasks[1].detail, "live smoke task cap reached")
        self.assertEqual(result.source_health[0]["attempts"], 3)
        self.assertEqual(result.source_health[0]["retryable_failures"], 1)

    def test_populates_cost_from_enrichment_budget(self) -> None:
        """JobRunner reports enrichment spend in the manifest cost section."""
        from biz_intel.services.enrichment import EnrichmentBudget, EnrichmentRunner

        registry = SourceRegistry(
            executors={SourceKind.SCRAPER: _FixedExecutor([Business(name="B")])}
        )
        registry.register(
            "yellowpages", object, kind=SourceKind.SCRAPER, policy=CLIENT_INPUT_POLICY
        )

        budget = EnrichmentBudget.from_source_options(
            {"google": {"max_enrich": 10}},
            {"google"},
        )
        budget.record_paid_call("google")

        destination = (
            Path(__file__).resolve().parent / "_tmp_job_runner_cost.csv"
        )
        self.written_files.append(destination)

        job = _job("job-runner-cost-test", str(destination))

        with patch(
            "biz_intel.jobs.runner.EnrichmentRunner.from_job",
            return_value=EnrichmentRunner([], budget=budget),
        ):
            result = JobRunner(registry=registry).run(job)

        self._track_run_files(result)

        self.assertIsNotNone(result.cost)
        self.assertEqual(result.cost.total_paid_calls, 1)
        self.assertIn("google", [line.source for line in result.cost.lines])

    def test_retries_transient_source_errors_and_reports_health(self) -> None:
        executor = _FlakyExecutor(1, [Business(name="Recovered")])
        registry = SourceRegistry(executors={SourceKind.SCRAPER: executor})
        registry.register(
            "yellowpages", object, kind=SourceKind.SCRAPER, policy=CLIENT_INPUT_POLICY
        )
        job = _job("job-runner-retry-test", "")
        task = JobRunner(registry=registry).planner.plan(job)[0]
        collected: list[Business] = []
        runner = JobRunner(registry=registry, sleeper=lambda seconds: None)
        health = SourceHealthTracker(failure_threshold=3)

        result = runner._run_task(
            task,
            collected,
            health=health,
            max_attempts=2,
            retry_backoff=0.1,
        )

        self.assertEqual(executor.calls, 2)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.raw_count, 1)
        self.assertEqual(health.get("yellowpages").retryable_failures, 1)
        self.assertEqual(health.get("yellowpages").successful_attempts, 1)

    def test_skips_later_task_after_source_failure_threshold(self) -> None:
        registry = SourceRegistry(executors={SourceKind.SCRAPER: _FailingExecutor()})
        registry.register(
            "yellowpages", object, kind=SourceKind.SCRAPER, policy=CLIENT_INPUT_POLICY
        )
        job = _job("job-runner-skip-test", "")
        task = JobRunner(registry=registry).planner.plan(job)[0]
        runner = JobRunner(registry=registry)
        health = SourceHealthTracker(failure_threshold=1)
        collected: list[Business] = []

        failed = runner._run_task(
            task,
            collected,
            health=health,
            max_attempts=1,
            retry_backoff=0,
        )
        skipped = runner._run_task(
            task,
            collected,
            health=health,
            max_attempts=1,
            retry_backoff=0,
        )

        self.assertEqual(failed.outcome, "fatal_failure")
        self.assertEqual(skipped.outcome, "skipped")
        self.assertEqual(skipped.attempts, 0)
        self.assertEqual(health.get("yellowpages").skipped_attempts, 1)

    def test_aggregate_limits_bound_acquisition_and_audit_skips(self) -> None:
        businesses = [Business(name=f"Business {number}") for number in range(10)]
        executor = _FixedExecutor(businesses)
        registry = SourceRegistry(executors={SourceKind.SCRAPER: executor})
        registry.register(
            "yellowpages", object, kind=SourceKind.SCRAPER, policy=CLIENT_INPUT_POLICY
        )
        destination = Path(__file__).resolve().parent / "_tmp_job_runner_limits.csv"
        self.written_files.append(destination)
        job = JobSpec.from_dict(
            {
                "version": 1,
                "name": "job-runner-limits",
                "search": {
                    "query": "dentist",
                    "cities": ["San Jose, CA", "Oakland, CA", "Fresno, CA"],
                },
                "sources": ["yellowpages"],
                "limits": {"total_records": 3, "per_source_records": 3, "per_location_records": 2},
                "output": {"format": "csv", "destination": str(destination)},
            }
        )

        result = JobRunner(registry=registry).run(job)
        self._track_run_files(result)

        self.assertEqual([task.raw_count for task in result.tasks], [2, 1, 0])
        self.assertEqual(result.tasks[2].outcome, "skipped")
        self.assertEqual(result.tasks[2].detail, "total records cap reached")

    def test_parallel_execution_overlaps_distinct_sources_but_serializes_each_source(self) -> None:
        executor = _ConcurrentTrackingExecutor()
        registry = SourceRegistry(
            executors={
                SourceKind.SCRAPER: executor,
                SourceKind.API: executor,
            }
        )
        registry.register(
            "yellowpages", object, kind=SourceKind.SCRAPER, policy=CLIENT_INPUT_POLICY
        )
        registry.register(
            "nppes", object, kind=SourceKind.API, policy=CLIENT_INPUT_POLICY
        )
        job = JobSpec.from_dict(
            {
                "version": 1,
                "name": "parallel-source-safety",
                "search": {"query": "dentist", "cities": ["San Jose, CA", "Oakland, CA"]},
                "sources": ["yellowpages", "nppes"],
                "execution": {"max_parallel_tasks": 2},
                "output": {"format": "csv", "destination": ""},
            }
        )

        result = JobRunner(registry=registry, progress_reporter=None).run(job)
        self._track_run_files(result)

        self.assertEqual(executor.maximum_active, 2)
        self.assertEqual(executor.maximum_by_source, {"yellowpages": 1, "nppes": 1})
        self.assertEqual([task.task_index for task in result.tasks], [0, 1, 2, 3])
        self.assertEqual(
            [task.location for task in result.tasks],
            ["San Jose, CA", "Oakland, CA", "San Jose, CA", "Oakland, CA"],
        )

    def test_parallel_reservations_keep_aggregate_caps_strict(self) -> None:
        executor = _ConcurrentTrackingExecutor()
        registry = SourceRegistry(
            executors={
                SourceKind.SCRAPER: executor,
                SourceKind.API: executor,
            }
        )
        registry.register(
            "yellowpages", object, kind=SourceKind.SCRAPER, policy=CLIENT_INPUT_POLICY
        )
        registry.register(
            "nppes", object, kind=SourceKind.API, policy=CLIENT_INPUT_POLICY
        )
        job = JobSpec.from_dict(
            {
                "version": 1,
                "name": "parallel-limit-safety",
                "search": {"query": "dentist", "cities": ["San Jose, CA", "Oakland, CA"]},
                "sources": ["yellowpages", "nppes"],
                "limits": {"total_records": 2, "per_location_records": 1},
                "execution": {"max_parallel_tasks": 2},
                "output": {"format": "csv", "destination": ""},
            }
        )

        result = JobRunner(registry=registry, progress_reporter=None).run(job)
        self._track_run_files(result)

        self.assertEqual(sum(task.raw_count for task in result.tasks), 2)
        self.assertTrue(all(task.raw_count <= 1 for task in result.tasks))
        self.assertEqual(
            [task.task_index for task in result.tasks],
            list(range(4)),
        )

    def test_parallel_reservation_does_not_permanently_skip_capacity_after_short_result(self) -> None:
        executor = _ConcurrentTrackingExecutor()
        registry = SourceRegistry(
            executors={
                SourceKind.SCRAPER: executor,
                SourceKind.API: executor,
            }
        )
        registry.register(
            "yellowpages", object, kind=SourceKind.SCRAPER, policy=CLIENT_INPUT_POLICY
        )
        registry.register(
            "nppes", object, kind=SourceKind.API, policy=CLIENT_INPUT_POLICY
        )
        job = JobSpec.from_dict(
            {
                "version": 1,
                "name": "parallel-short-result",
                "search": {"query": "dentist", "cities": ["San Jose, CA"]},
                "sources": ["yellowpages", "nppes"],
                "limits": {"total_records": 2},
                "execution": {"max_parallel_tasks": 2},
                "output": {"format": "csv", "destination": ""},
            }
        )

        result = JobRunner(registry=registry, progress_reporter=None).run(job)
        self._track_run_files(result)

        self.assertEqual([task.raw_count for task in result.tasks], [1, 1])
        self.assertEqual(sum(task.raw_count for task in result.tasks), 2)

    def test_preflight_reports_known_ceiling_without_running_a_source(self) -> None:
        registry = SourceRegistry(
            executors={SourceKind.SCRAPER: _FailingExecutor()}
        )
        registry.register(
            "google", object, kind=SourceKind.SCRAPER, policy=CLIENT_INPUT_POLICY
        )
        job = JobSpec.from_dict(
            {
                "version": 1,
                "name": "preflight-test",
                "search": {
                    "query": "dentist",
                    "cities": ["San Jose, CA", "Oakland, CA"],
                },
                "sources": ["google"],
                "limits": {"total_records": 7},
                "output": {},
                "source_options": {
                    "google": {"enrich_details": True, "max_enrich": 5},
                },
                "budget": {
                    "max_total_usd": 1,
                    "approval_reference": "test-approval",
                },
            }
        )

        report = JobRunner(registry=registry).preflight(job)

        self.assertEqual(report.task_count, 2)
        self.assertEqual(report.maximum_source_invocations, 2)
        self.assertEqual(report.maximum_acquisition_records, 7)
        self.assertEqual(report.maximum_enrichment_calls, 5)
        self.assertEqual(report.estimated_max_enrichment_spend, 0.1)
        self.assertFalse(report.has_unbounded_cost)
        self.assertEqual(report.source_cost_models, {"google": "client engagement controlled"})

    def test_rejects_configured_spend_above_client_budget_before_executor_runs(self) -> None:
        executor = _FixedExecutor([Business(name="Must not be collected")])
        registry = SourceRegistry(executors={SourceKind.SCRAPER: executor})
        registry.register(
            "google", object, kind=SourceKind.SCRAPER, policy=CLIENT_INPUT_POLICY
        )
        job = JobSpec.from_dict(
            {
                "version": 1,
                "name": "budget-guard",
                "search": {"query": "dentist", "cities": ["San Jose, CA"]},
                "sources": ["google"],
                "output": {},
                "source_options": {"google": {"enrich_details": True, "max_enrich": 5}},
                "budget": {"max_total_usd": 0.01, "approval_reference": "client-42"},
            }
        )

        with self.assertRaisesRegex(ValueError, "exceeds budget.max_total_usd"):
            JobRunner(registry=registry, progress_reporter=None).run(job)

        self.assertEqual(executor.calls, 0)

    def test_accepted_website_only_record_has_history_identity(self) -> None:
        business = Business(
            name="Website Only Dental",
            city="San Jose",
            state="CA",
            website="https://website-only.example.test",
            source="client_input",
            source_url="https://client.example.test/website-only-dental",
            observed_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        )
        registry = SourceRegistry(
            executors={SourceKind.SCRAPER: _FixedExecutor([business])}
        )
        registry.register(
            "yellowpages", object, kind=SourceKind.SCRAPER, policy=CLIENT_INPUT_POLICY
        )
        destination = Path(__file__).resolve().parent / "_tmp_website_only_history.csv"
        self.written_files.append(destination)

        result = JobRunner(registry=registry).run(
            _job("website-only-history", str(destination))
        )
        self._track_run_files(result)

        self.assertEqual(result.output.record_count, 1)
        history_counts = result.history.changes["counts"]
        self.assertEqual(history_counts["new"] + history_counts["unchanged"], 1)

    def test_console_progress_reports_fixed_pipeline_milestones(self) -> None:
        business = Business(
            name="Progress Dental",
            city="San Jose",
            state="CA",
            phone="4085559999",
            source="client_input",
            source_url="https://client.example.test/progress-dental",
            observed_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        )
        registry = SourceRegistry(
            executors={SourceKind.SCRAPER: _FixedExecutor([business])}
        )
        registry.register(
            "yellowpages", object, kind=SourceKind.SCRAPER, policy=CLIENT_INPUT_POLICY
        )
        destination = Path(__file__).resolve().parent / "_tmp_progress.csv"
        self.written_files.append(destination)
        messages: list[str] = []

        result = JobRunner(
            registry=registry,
            progress_reporter=messages.append,
        ).run(_job("console-progress", str(destination)))
        self._track_run_files(result)

        self.assertEqual(
            [message.split(":", 1)[0] for message in messages[1:-1]],
            ["Acquire", "Acquire", "Validation", "Normalization", "Deduplication", "Enrich", "Verify contacts", "Classify", "Export"],
        )
        self.assertTrue(messages[0].startswith("Run console-progress-"))
        self.assertEqual(messages[-1], f"Run complete: {result.run_id}")

    def test_resume_retries_only_incomplete_tasks_from_sanitized_checkpoint(self) -> None:
        business = Business(
            name="Recovered",
            phone="4085551111",
            city="San Jose",
            state="CA",
            source="client_input",
            source_url="https://client.example.test/recovered",
            observed_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
            raw_data={"private_token": "not retained"},
            field_provenance={
                "name": FieldProvenance(
                    source="client_input",
                    evidence_url="https://client.example.test/recovered",
                    observed_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
                    method="client_file",
                )
            },
        )
        executor = _FlakyExecutor(1, [business])
        registry = SourceRegistry(executors={SourceKind.SCRAPER: executor})
        registry.register(
            "yellowpages", object, kind=SourceKind.SCRAPER, policy=CLIENT_INPUT_POLICY
        )
        destination = Path(__file__).resolve().parent / "_tmp_job_runner_resume.csv"
        self.written_files.append(destination)
        job = JobSpec.from_dict(
            {
                "version": 1,
                "name": "resume-test",
                "search": {
                    "query": "dentist",
                    "cities": ["San Jose, CA", "Oakland, CA"],
                },
                "sources": ["yellowpages"],
                "output": {"format": "csv", "destination": str(destination)},
            }
        )
        runner = JobRunner(registry=registry)

        interrupted = runner.run(job)
        self._track_run_files(interrupted)
        checkpoint_path = Path(interrupted.checkpoint_destination)
        self.written_files.append(checkpoint_path)
        self.assertIn("retryable_failure", [task.outcome for task in interrupted.tasks])
        self.assertNotIn("private_token", checkpoint_path.read_text())

        resumed = runner.run(job, resume_from=str(checkpoint_path))
        self._track_run_files(resumed)

        self.assertEqual(executor.calls, 3)
        self.assertEqual(resumed.run_id, interrupted.run_id)
        self.assertEqual(resumed.resumed_from, str(checkpoint_path))
        self.assertEqual(
            sorted((task.task_index, task.outcome) for task in resumed.tasks),
            [(0, "success"), (1, "success")],
        )
        self.assertEqual(resumed.output.record_count, 1)


if __name__ == "__main__":
    unittest.main()
