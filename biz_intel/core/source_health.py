"""Source-neutral health accounting for bounded acquisition runs.

This module only observes source-task outcomes.  It deliberately does not
retry, sleep, or invoke a source; callers can use its snapshots to decide when
to stop attempting a source and to include an honest health section in a run
manifest.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from threading import RLock


class SourceTaskOutcome(StrEnum):
    """The outcome class reported after one source-task attempt."""

    SUCCESS = "success"
    EMPTY = "empty"
    RETRYABLE_FAILURE = "retryable_failure"
    FATAL_FAILURE = "fatal_failure"
    SKIPPED = "skipped"

    @property
    def is_failure(self) -> bool:
        return self in {
            SourceTaskOutcome.RETRYABLE_FAILURE,
            SourceTaskOutcome.FATAL_FAILURE,
        }

    @property
    def resets_failure_streak(self) -> bool:
        return self in {SourceTaskOutcome.SUCCESS, SourceTaskOutcome.EMPTY}

    @property
    def retryable(self) -> bool:
        return self is SourceTaskOutcome.RETRYABLE_FAILURE


class SourceHealthStatus(StrEnum):
    """A source's current health relative to its configured threshold."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILURE_THRESHOLD_REACHED = "failure_threshold_reached"


@dataclass(frozen=True, slots=True)
class SourceHealth:
    """A JSON-safe snapshot of one source's task outcomes."""

    source: str
    failure_threshold: int
    attempts: int = 0
    successful_attempts: int = 0
    empty_attempts: int = 0
    retryable_failures: int = 0
    fatal_failures: int = 0
    skipped_attempts: int = 0
    consecutive_failures: int = 0
    last_outcome: SourceTaskOutcome | None = None
    last_error: str | None = None
    observed_at: datetime | None = None

    @property
    def status(self) -> SourceHealthStatus:
        if self.consecutive_failures >= self.failure_threshold:
            return SourceHealthStatus.FAILURE_THRESHOLD_REACHED
        if self.consecutive_failures:
            return SourceHealthStatus.DEGRADED
        return SourceHealthStatus.HEALTHY

    @property
    def should_stop(self) -> bool:
        """Whether later tasks for this source should be withheld this run."""

        return self.status is SourceHealthStatus.FAILURE_THRESHOLD_REACHED

    def to_dict(self) -> dict[str, object]:
        """Return a manifest-ready representation without exception payloads."""

        data = asdict(self)
        data["last_outcome"] = (
            self.last_outcome.value if self.last_outcome is not None else None
        )
        data["observed_at"] = (
            self.observed_at.isoformat() if self.observed_at is not None else None
        )
        data["status"] = self.status.value
        data["should_stop"] = self.should_stop
        return data


class SourceHealthTracker:
    """Keep independent failure streaks for source-task attempts.

    An empty response is a completed attempt, not a source failure.  Skipped
    work is recorded for auditing but does not change the prior failure streak.
    A fatal failure tells an executor not to retry *that attempt*; the shared
    threshold still governs whether future tasks for the source are stopped.
    """

    def __init__(self, *, failure_threshold: int = 3) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        self.failure_threshold = failure_threshold
        self._health_by_source: dict[str, SourceHealth] = {}
        self._lock = RLock()

    def record(
        self,
        source: str,
        outcome: SourceTaskOutcome,
        *,
        error: str | None = None,
        observed_at: datetime | None = None,
    ) -> SourceHealth:
        """Record one outcome and return that source's updated snapshot."""

        if not source.strip():
            raise ValueError("source must be non-empty")
        if error and not outcome.is_failure:
            raise ValueError("error details are only valid for failure outcomes")

        with self._lock:
            prior = self._health_by_source.get(
                source,
                SourceHealth(source=source, failure_threshold=self.failure_threshold),
            )
            now = observed_at or datetime.now(timezone.utc)
            consecutive_failures = prior.consecutive_failures
            if outcome.is_failure:
                consecutive_failures += 1
            elif outcome.resets_failure_streak:
                consecutive_failures = 0

            health = SourceHealth(
                source=source,
                failure_threshold=self.failure_threshold,
                attempts=prior.attempts + 1,
                successful_attempts=prior.successful_attempts
                + (outcome is SourceTaskOutcome.SUCCESS),
                empty_attempts=prior.empty_attempts + (outcome is SourceTaskOutcome.EMPTY),
                retryable_failures=prior.retryable_failures
                + (outcome is SourceTaskOutcome.RETRYABLE_FAILURE),
                fatal_failures=prior.fatal_failures
                + (outcome is SourceTaskOutcome.FATAL_FAILURE),
                skipped_attempts=prior.skipped_attempts
                + (outcome is SourceTaskOutcome.SKIPPED),
                consecutive_failures=consecutive_failures,
                last_outcome=outcome,
                last_error=error if outcome.is_failure else None,
                observed_at=now,
            )
            self._health_by_source[source] = health
            return health

    def get(self, source: str) -> SourceHealth:
        """Return a source snapshot, including a healthy zero-attempt state."""

        with self._lock:
            return self._health_by_source.get(
                source,
                SourceHealth(source=source, failure_threshold=self.failure_threshold),
            )

    def reports(self) -> list[SourceHealth]:
        """Return deterministic manifest snapshots for all observed sources."""

        with self._lock:
            return [self._health_by_source[source] for source in sorted(self._health_by_source)]
