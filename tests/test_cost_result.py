"""Tests for the run manifest's cost section."""

from __future__ import annotations

import json
import unittest
from dataclasses import asdict
from datetime import datetime, timezone

from biz_intel.jobs.run import CostResult, RunResult
from biz_intel.services.enrichment.budget import CostLine


def _line(source: str, paid_calls: int, capped: bool = False) -> CostLine:
    return CostLine(source=source, paid_calls=paid_calls, capped=capped)


class CostResultTests(unittest.TestCase):

    def test_aggregates_totals_across_lines(self) -> None:
        cost = CostResult(lines=[_line("google", 100), _line("yelp", 50)])

        self.assertEqual(cost.total_paid_calls, 150)
        self.assertGreater(cost.total_estimated_spend, 0)

    def test_empty_cost_result(self) -> None:
        cost = CostResult()

        self.assertEqual(cost.total_paid_calls, 0)
        self.assertEqual(cost.total_estimated_spend, 0)

    def test_unknown_source_costs_zero(self) -> None:
        line = CostLine(source="yellowpages", paid_calls=10)

        self.assertEqual(line.estimated_unit_cost, 0.0)
        self.assertEqual(line.estimated_spend, 0.0)


class RunResultCostTests(unittest.TestCase):

    def test_to_dict_serializes_cost_section(self) -> None:
        result = RunResult(
            run_id="x",
            job_name="j",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            cost=CostResult(lines=[_line("google", 3, capped=True)]),
        )

        data = result.to_dict()

        self.assertEqual(data["cost"]["lines"][0]["source"], "google")
        self.assertEqual(data["cost"]["lines"][0]["paid_calls"], 3)
        self.assertTrue(data["cost"]["lines"][0]["capped"])
        json.dumps(data)  # must be JSON-serializable

    def test_summary_includes_cost_when_present(self) -> None:
        result = RunResult(
            run_id="x",
            job_name="j",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            cost=CostResult(lines=[_line("google", 2)]),
        )

        summary = result.summary()

        self.assertIn("Enrichment cost", summary)
        self.assertIn("google: 2 paid calls", summary)

    def test_summary_omits_cost_when_absent(self) -> None:
        result = RunResult(
            run_id="x",
            job_name="j",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )

        self.assertNotIn("Enrichment cost", result.summary())

    def test_asdict_roundtrip(self) -> None:
        """asdict() must still work so CostResult is a plain dataclass."""
        line = _line("google", 1)
        self.assertEqual(asdict(line)["paid_calls"], 1)


if __name__ == "__main__":
    unittest.main()
