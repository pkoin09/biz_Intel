"""Read-only Overture candidate review contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import duckdb

from biz_intel.models import Business
from biz_intel.research import ResearchSession, review_overture_snapshot


class OvertureReviewTests(unittest.TestCase):
    def test_reports_matches_without_changing_the_session(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "candidates.parquet"
            with duckdb.connect() as connection:
                connection.execute(
                    """
                    COPY (
                      SELECT 'place-1' AS id,
                             {'primary': 'Example Dental'} AS names,
                             'dental_clinic' AS basic_category,
                             {'primary': 'general_dentistry',
                              'hierarchy': ['health_care', 'dental_clinic', 'general_dentistry']} AS taxonomy,
                             [{'freeform': '1 Main St', 'locality': 'San Jose',
                               'region': 'CA', 'postcode': '95112', 'country': 'US'}] AS addresses,
                             ['+14085550100'] AS phones,
                             ['https://example.test'] AS websites,
                             0.95 AS confidence
                    ) TO ? (FORMAT PARQUET)
                    """,
                    [str(snapshot)],
                )
            snapshot.with_suffix(".manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source": "overture",
                        "release": "2026-09-23.1",
                        "retrieved_at": "2026-10-20T00:00:00-07:00",
                        "source_reference": "https://example.test/overture",
                        "geography": "San Jose test bbox",
                        "taxonomy_filters": ["dental_clinic hierarchy"],
                        "license": "synthetic test fixture",
                        "attribution": "synthetic fixture",
                        "row_count": 1,
                        "sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                        "review_status": "reviewed",
                    }
                )
            )
            session = ResearchSession(
                "Dentists",
                [
                    Business(
                        name="Example Dental",
                        address="1 Main St",
                        city="San Jose",
                        state="CA",
                        phone="4085550100",
                        source="nppes",
                        source_ids={"npi": "1234567890"},
                    )
                ],
            )
            before = session.businesses[0].to_dict()

            report = review_overture_snapshot(session, snapshot, limit=10)
            paged = review_overture_snapshot(
                session,
                snapshot,
                limit=10,
                offset=1,
                decision="matched",
            )

        self.assertEqual(report["candidate_records"], 1)
        self.assertFalse(report["delivery_approved"])
        self.assertEqual(report["counts"]["matched"], 1)
        self.assertEqual(report["selection"]["available"], 1)
        self.assertEqual(report["preview"][0]["primary"]["name"], "Example Dental")
        self.assertEqual(paged["selection"]["decision"], "matched")
        self.assertEqual(paged["selection"]["offset"], 1)
        self.assertEqual(paged["preview"], [])
        self.assertEqual(session.businesses[0].to_dict(), before)

    def test_rejects_invalid_review_window(self) -> None:
        session = ResearchSession("Dentists", [Business(source="nppes")])

        with self.assertRaisesRegex(ValueError, "offset cannot be negative"):
            review_overture_snapshot(session, "unused.parquet", offset=-1)
        with self.assertRaisesRegex(ValueError, "decision must be"):
            review_overture_snapshot(session, "unused.parquet", decision="rejected")


if __name__ == "__main__":
    unittest.main()
