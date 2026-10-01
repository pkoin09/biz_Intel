"""Tests for planning validated jobs into executable source tasks."""

from __future__ import annotations

from pathlib import Path
import unittest

from biz_intel.core.source_name import SourceName
from biz_intel.jobs import load_job
from biz_intel.jobs.models import JobSpec
from biz_intel.jobs.planner import Planner


SAMPLE_JOB = (
    Path(__file__).resolve().parents[1]
    / "jobs/dentists_san_jose.yaml"
)


class PlannerTests(unittest.TestCase):
    """Protect the planner's public contract."""

    def load_sample_job(self):
        return load_job(SAMPLE_JOB)

    def test_plans_single_source_task(self) -> None:
        job = self.load_sample_job()

        tasks = Planner().plan(job)

        self.assertEqual(len(tasks), 1)

        task = tasks[0]

        self.assertEqual(task.source, SourceName.CSV)
        self.assertEqual(task.category, "local businesses")
        self.assertIsNone(task.limit)

        self.assertEqual(task.location.city, "San Jose")
        self.assertEqual(task.location.state, "CA")

    def test_plans_state_only_task(self) -> None:
        job = JobSpec.from_dict(
            {
                "version": 1,
                "name": "dentists-nj",
                "search": {"query": "dentist", "states": ["NJ"]},
                "sources": ["yellowpages"],
                "limit": 50,
                "processing": {},
                "output": {},
            }
        )

        tasks = Planner().plan(job)

        self.assertEqual(len(tasks), 1)

        task = tasks[0]

        self.assertIsNone(task.location.city)
        self.assertEqual(task.location.state, "NJ")
        self.assertIsNone(task.limit)

    def test_plans_cities_and_states_without_cross_product(self) -> None:
        job = JobSpec.from_dict(
            {
                "version": 1,
                "name": "dentists-mixed",
                "search": {
                    "query": "dentist",
                    "cities": ["San Jose, CA"],
                    "states": ["NJ", "NY"],
                },
                "sources": ["yellowpages"],
                "limit": 50,
                "processing": {},
                "output": {},
            }
        )

        tasks = Planner().plan(job)

        locations = {(task.location.city, task.location.state) for task in tasks}

        self.assertEqual(
            locations,
            {("San Jose", "CA"), (None, "NJ"), (None, "NY")},
        )

    def test_legacy_limit_is_a_total_limit_not_a_per_task_cap(self) -> None:
        job = JobSpec.from_dict(
            {
                "version": 1,
                "name": "legacy-total-limit",
                "search": {
                    "query": "dentist",
                    "cities": ["San Jose, CA", "Oakland, CA"],
                },
                "sources": ["yellowpages"],
                "limit": 50,
                "processing": {},
                "output": {},
            }
        )

        tasks = Planner().plan(job)

        self.assertEqual(job.limit, 50)
        self.assertEqual([task.limit for task in tasks], [None, None])

    def test_live_smoke_applies_its_hard_per_task_record_cap(self) -> None:
        job = JobSpec.from_dict(
            {
                "version": 1,
                "name": "bounded-live-smoke",
                "search": {
                    "query": "dentist",
                    "cities": ["San Jose, CA", "Oakland, CA"],
                },
                "sources": ["yellowpages"],
                "execution": {
                    "mode": "live_smoke",
                    "live_smoke": {"max_records_per_task": 3},
                },
                "processing": {},
                "output": {},
            }
        )

        tasks = Planner().plan(job)

        self.assertEqual([task.limit for task in tasks], [3, 3])


    def test_source_options_flow_to_task(self) -> None:
        job = JobSpec.from_dict(
            {
                "version": 1,
                "name": "opts-flow",
                "search": {"query": "dentist", "cities": ["San Jose, CA"]},
                "sources": ["google"],
                "output": {},
                "source_options": {"google": {"enrich_details": True, "max_enrich": 0}},
            }
        )

        tasks = Planner().plan(job)

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].options, {"enrich_details": True, "max_enrich": 0})

    def test_task_options_empty_when_no_source_options(self) -> None:
        job = JobSpec.from_dict(
            {
                "version": 1,
                "name": "no-opts",
                "search": {"query": "dentist", "cities": ["San Jose, CA"]},
                "sources": ["yellowpages"],
                "output": {},
            }
        )

        tasks = Planner().plan(job)

        self.assertEqual(tasks[0].options, {})


if __name__ == "__main__":
    unittest.main()
