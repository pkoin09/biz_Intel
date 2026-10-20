"""Offline contracts for reviewed Overture GeoParquet snapshots."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

import duckdb

from biz_intel.core.source_policy import OVERTURE_POLICY, SourceClass, SourceRole
from biz_intel.sources.overture import OvertureSnapshotSource


class OvertureSnapshotSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(__file__).parent / "_tmp_overture.parquet"
        self.manifest_path = self.path.with_suffix(".manifest.json")
        self.addCleanup(self.path.unlink, missing_ok=True)
        self.addCleanup(self.manifest_path.unlink, missing_ok=True)

    def _write_snapshot(self, *, valid_record: bool = True) -> None:
        name_sql = "'Sample Dental Group'" if valid_record else "''"
        with duckdb.connect() as connection:
            connection.execute(
                f"""
                COPY (
                    SELECT
                        '08f1example' AS id,
                        {{'primary': {name_sql}}} AS names,
                        'dentist' AS basic_category,
                        {{'primary': 'general_dentistry',
                          'hierarchy': ['health_care', 'outpatient_care_facility',
                                        'dental_clinic', 'general_dentistry'],
                          'alternates': NULL::VARCHAR[]}} AS taxonomy,
                        [{{'freeform': '1 Main St', 'locality': 'San Jose',
                          'region': 'CA', 'postcode': '95112', 'country': 'US'}}] AS addresses,
                        ['+14085550100'] AS phones,
                        ['https://example.test'] AS websites,
                        0.95 AS confidence
                ) TO ? (FORMAT PARQUET)
                """,
                [str(self.path)],
            )
        self._write_manifest(row_count=1)

    def _write_manifest(self, **updates: object) -> None:
        data: dict[str, object] = {
            "schema_version": 1,
            "source": "overture",
            "release": "2026-10-01.0",
            "retrieved_at": "2026-10-03T12:00:00+00:00",
            "source_reference": "https://example.test/overture/2026-10-01.0",
            "geography": "San Jose, CA bounding box",
            "taxonomy_filters": ["dentist"],
            "license": "Overture Maps data license reviewed for this snapshot",
            "attribution": "Overture Maps Foundation",
            "row_count": 1,
            "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
            "review_status": "reviewed",
        }
        data.update(updates)
        self.manifest_path.write_text(json.dumps(data), encoding="utf-8")

    def test_imports_auditable_candidate_from_reviewed_snapshot(self) -> None:
        self._write_snapshot()

        business = next(OvertureSnapshotSource(self.path).extract())

        self.assertEqual(business.name, "Sample Dental Group")
        self.assertEqual(business.category, "general_dentistry")
        self.assertEqual(business.city, "San Jose")
        self.assertEqual(business.source_ids, {"overture_id": "08f1example"})
        self.assertEqual(business.source_url, "https://example.test/overture/2026-10-01.0")
        self.assertEqual(
            {claim.key for claim in business.claims},
            {
                "candidate.overture.id",
                "candidate.overture.release",
                "candidate.overture.confidence",
            },
        )
        self.assertNotIn("sources", business.raw_data or {})

    def test_rejects_tampered_snapshot_and_manifest_count_mismatch(self) -> None:
        self._write_snapshot()
        self.path.write_bytes(self.path.read_bytes() + b"tampered")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            list(OvertureSnapshotSource(self.path).extract())

        self._write_snapshot()
        self._write_manifest(row_count=2)
        with self.assertRaisesRegex(ValueError, "row count"):
            list(OvertureSnapshotSource(self.path).extract())

    def test_rejects_unreviewed_manifest_and_invalid_snapshot_record(self) -> None:
        self._write_snapshot()
        self._write_manifest(review_status="pending")
        with self.assertRaisesRegex(ValueError, "review_status"):
            list(OvertureSnapshotSource(self.path).extract())

        self._write_snapshot(valid_record=False)
        with self.assertRaisesRegex(ValueError, "names.primary/name"):
            list(OvertureSnapshotSource(self.path).extract())

    def test_policy_is_offline_candidate_acquisition_pending_delivery_review(self) -> None:
        self.assertEqual(OVERTURE_POLICY.source_class, SourceClass.LICENSED)
        self.assertFalse(OVERTURE_POLICY.allows_delivery)
        self.assertIn(SourceRole.CANDIDATE, OVERTURE_POLICY.roles)
        self.assertIn("offline", OVERTURE_POLICY.rate_limit)


if __name__ == "__main__":
    unittest.main()
