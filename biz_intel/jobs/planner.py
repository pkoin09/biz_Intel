from __future__ import annotations

from biz_intel.core.location import Location
from biz_intel.core.source_name import SourceName
from biz_intel.core.source_task import SourceTask

from .models import JobSpec


class Planner:

    def plan(self, job: JobSpec) -> list[SourceTask]:
        tasks: list[SourceTask] = []
        locations = self._locations(job)
        task_limit = self._task_limit(job)

        for source_name in job.sources:
            source = self._parse_source(source_name)

            options = job.source_options.get(source_name, {})

            for location in locations:
                task = SourceTask(
                    source=source,
                    category=job.search.query,
                    limit=task_limit,
                    location=location,
                    options=options,
                )
                tasks.append(task)

        return tasks

    @staticmethod
    def _task_limit(job: JobSpec) -> int | None:
        """Return only a cap that is safe to apply to each individual task.

        ``limits`` describe aggregate acquisition/delivery boundaries.  They
        cannot be projected onto every source/location task without silently
        multiplying the requested work.  The runner enforces those aggregate
        limits.  A live-smoke run is different: its per-task record cap is an
        explicit, hard safety control and belongs on every planned task.
        """

        if job.execution.mode == "live_smoke":
            # JobSpec validation guarantees this exists for live_smoke jobs.
            assert job.execution.live_smoke is not None
            return job.execution.live_smoke.max_records_per_task

        return None

    def _locations(self, job: JobSpec) -> list[Location]:
        locations: list[Location] = []

        for city_state in job.search.cities:
            city, state = self._parse_city_state(city_state)
            locations.append(Location(city=city, state=state))

        for state in job.search.states:
            locations.append(Location(state=state))

        return locations

    def _parse_source(self, name: str) -> SourceName:
        try:
            return SourceName(name.lower())
        except ValueError:
            raise ValueError(f"Unknown source: {name}")

    def _parse_city_state(self, city_state: str) -> tuple[str, str]:
        parts = [part.strip() for part in city_state.split(",")]
        if len(parts) != 2:
            raise ValueError(f"City must be in format 'City, State': {city_state}")
        return parts[0], parts[1]
