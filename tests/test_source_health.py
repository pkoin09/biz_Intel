"""Focused tests for source task health accounting."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest

from biz_intel.core.source_health import SourceHealthStatus
from biz_intel.core.source_health import SourceHealthTracker
from biz_intel.core.source_health import SourceTaskOutcome


class SourceHealthTrackerTests(unittest.TestCase):
    def test_failure_threshold_marks_source_for_stop(self) -> None:
        tracker = SourceHealthTracker(failure_threshold=2)

        first = tracker.record(
            "registry", SourceTaskOutcome.RETRYABLE_FAILURE, error="timeout"
        )
        second = tracker.record(
            "registry", SourceTaskOutcome.FATAL_FAILURE, error="bad schema"
        )

        self.assertEqual(first.status, SourceHealthStatus.DEGRADED)
        self.assertFalse(first.should_stop)
        self.assertEqual(second.consecutive_failures, 2)
        self.assertEqual(second.status, SourceHealthStatus.FAILURE_THRESHOLD_REACHED)
        self.assertTrue(second.should_stop)
        self.assertEqual(second.retryable_failures, 1)
        self.assertEqual(second.fatal_failures, 1)

    def test_success_and_empty_reset_failure_streak(self) -> None:
        tracker = SourceHealthTracker(failure_threshold=3)
        tracker.record("registry", SourceTaskOutcome.RETRYABLE_FAILURE, error="timeout")

        successful = tracker.record("registry", SourceTaskOutcome.SUCCESS)
        tracker.record("registry", SourceTaskOutcome.RETRYABLE_FAILURE, error="timeout")
        empty = tracker.record("registry", SourceTaskOutcome.EMPTY)

        self.assertEqual(successful.consecutive_failures, 0)
        self.assertEqual(empty.consecutive_failures, 0)
        self.assertEqual(empty.empty_attempts, 1)
        self.assertEqual(empty.status, SourceHealthStatus.HEALTHY)

    def test_skipped_attempt_preserves_failure_streak(self) -> None:
        tracker = SourceHealthTracker()
        tracker.record("registry", SourceTaskOutcome.RETRYABLE_FAILURE, error="timeout")

        report = tracker.record("registry", SourceTaskOutcome.SKIPPED)

        self.assertEqual(report.consecutive_failures, 1)
        self.assertEqual(report.skipped_attempts, 1)
        self.assertIsNone(report.last_error)

    def test_reports_are_source_isolated_and_sorted(self) -> None:
        tracker = SourceHealthTracker()
        tracker.record("zeta", SourceTaskOutcome.SUCCESS)
        tracker.record("alpha", SourceTaskOutcome.RETRYABLE_FAILURE, error="timeout")

        reports = tracker.reports()

        self.assertEqual([report.source for report in reports], ["alpha", "zeta"])
        self.assertEqual(reports[0].consecutive_failures, 1)
        self.assertEqual(reports[1].consecutive_failures, 0)

    def test_to_dict_is_manifest_ready(self) -> None:
        observed_at = datetime(2026, 9, 29, tzinfo=timezone.utc)
        tracker = SourceHealthTracker(failure_threshold=1)
        report = tracker.record(
            "registry",
            SourceTaskOutcome.RETRYABLE_FAILURE,
            error="timeout",
            observed_at=observed_at,
        )

        self.assertEqual(
            report.to_dict(),
            {
                "source": "registry",
                "failure_threshold": 1,
                "attempts": 1,
                "successful_attempts": 0,
                "empty_attempts": 0,
                "retryable_failures": 1,
                "fatal_failures": 0,
                "skipped_attempts": 0,
                "consecutive_failures": 1,
                "last_outcome": "retryable_failure",
                "last_error": "timeout",
                "observed_at": "2026-09-29T00:00:00+00:00",
                "status": "failure_threshold_reached",
                "should_stop": True,
            },
        )

    def test_rejects_invalid_configuration_and_observation(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 1"):
            SourceHealthTracker(failure_threshold=0)

        tracker = SourceHealthTracker()
        with self.assertRaisesRegex(ValueError, "non-empty"):
            tracker.record(" ", SourceTaskOutcome.SUCCESS)
        with self.assertRaisesRegex(ValueError, "only valid"):
            tracker.record("registry", SourceTaskOutcome.SUCCESS, error="not applicable")


if __name__ == "__main__":
    unittest.main()
