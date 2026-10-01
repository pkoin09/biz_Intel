"""Integration tests for the sample CSV ingestion path."""

from __future__ import annotations

from pathlib import Path
import unittest

from biz_intel.core.pipeline import PipelineRunner
from biz_intel.metrics import metrics
from biz_intel.sources.csv import CSVSource


SAMPLE_CSV = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/businesses_messy_synthetic.csv"
)


class CSVIngestionPipelineTests(unittest.TestCase):
    """Protect the current CSV-to-Business pipeline contract."""

    def run_sample_pipeline(self):
        return list(
            PipelineRunner().run(
                CSVSource(SAMPLE_CSV).extract(),
            )
        )

    def test_sample_pipeline_returns_deduplicated_businesses(self) -> None:
        businesses = self.run_sample_pipeline()

        self.assertEqual(len(businesses), 15)
        self.assertEqual(metrics.get("duplicates_removed"), 3)

    def test_sample_pipeline_normalizes_contacts(self) -> None:
        businesses = self.run_sample_pipeline()
        joe = next(
            business
            for business in businesses
            if business.name == "Joe's Coffee Shop"
        )

        self.assertEqual(joe.phone, "4085551212")
        self.assertEqual(joe.email, "joe@joescoffee.example.test")
        self.assertEqual(joe.website, "joescoffee.example.test")
        self.assertEqual(joe.rating, 4.5)
        self.assertEqual(joe.review_count, 124)

    def test_sample_pipeline_removes_invalid_email_values(self) -> None:
        businesses = self.run_sample_pipeline()
        by_name = {
            business.name: business
            for business in businesses
        }

        self.assertEqual(by_name["Unknown Cafe"].email, "")
        self.assertEqual(by_name["Mocha Madness"].email, "")
        self.assertEqual(metrics.get("invalid_emails"), 3)

    def test_each_run_starts_with_fresh_metrics(self) -> None:
        self.run_sample_pipeline()
        self.assertEqual(metrics.get("duplicates_removed"), 3)

        self.run_sample_pipeline()
        self.assertEqual(metrics.get("duplicates_removed"), 3)


if __name__ == "__main__":
    unittest.main()
