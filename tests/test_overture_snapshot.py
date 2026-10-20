"""Focused contracts for deterministic local Overture snapshot preparation."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import duckdb

from biz_intel.sources.overture.snapshot import prepare_overture_snapshot
from biz_intel.sources.overture.source import OvertureSnapshotSource


class OvertureSnapshotPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "places-source.parquet"
        self.output = self.root / "dental-candidates.parquet"

    def _write_source(self) -> None:
        with duckdb.connect() as connection:
            connection.execute(
                """
                COPY (
                    SELECT * FROM (VALUES
                      ('z-specialty', {'primary': 'Z Specialty'}, 'dentist',
                       {'primary': 'general_dentistry', 'hierarchy': ['health_care', 'dental_clinic', 'general_dentistry']},
                       [{'freeform': '2 Main St', 'locality': 'Santa Clara', 'region': 'CA', 'postcode': '95050', 'country': 'US'}],
                       ['+14085550102'], ['https://z.test'], 0.9,
                       [{'dataset': 'Overture', 'license': 'CDLA-Permissive-2.0', 'provider': 'overture'}],
                       {'xmin': -121.9, 'ymin': 37.3, 'xmax': -121.9, 'ymax': 37.3}),
                      ('a-root', {'primary': 'A Dental'}, 'dentist',
                       {'primary': 'dental_clinic', 'hierarchy': ['health_care', 'dental_clinic']},
                       [{'freeform': '1 Main St', 'locality': 'San Jose', 'region': 'CA', 'postcode': '95112', 'country': 'US'}],
                       ['+14085550101'], ['https://a.test'], 0.8,
                       [{'dataset': 'Foursquare', 'license': 'Apache-2.0', 'provider': 'foursquare'}],
                       {'xmin': -122.0, 'ymin': 37.0, 'xmax': -122.0, 'ymax': 37.0}),
                      ('outside', {'primary': 'Outside Dental'}, 'dentist',
                       {'primary': 'orthodontics', 'hierarchy': ['dental_clinic', 'orthodontics']},
                       [], [], [], 0.7,
                       [{'dataset': 'Overture', 'license': 'CDLA-Permissive-2.0', 'provider': 'overture'}],
                       {'xmin': -123.0, 'ymin': 38.0, 'xmax': -123.0, 'ymax': 38.0}),
                      ('not-dental', {'primary': 'Clinic'}, 'clinic',
                       {'primary': 'medical_clinic', 'hierarchy': ['health_care', 'medical_clinic']},
                       [], [], [], 0.6,
                       [{'dataset': 'Overture', 'license': 'CDLA-Permissive-2.0', 'provider': 'overture'}],
                       {'xmin': -121.8, 'ymin': 37.4, 'xmax': -121.8, 'ymax': 37.4})
                    ) AS places(id, names, basic_category, taxonomy, addresses, phones,
                                websites, confidence, sources, bbox)
                ) TO ? (FORMAT PARQUET)
                """,
                [str(self.source)],
            )

    def _prepare(self, **updates: object):
        arguments = {
            "source": self.source,
            "destination": self.output,
            "release": "2026-10-01.0",
            "retrieved_at": datetime(2026, 10, 3, 12, tzinfo=timezone.utc),
            "source_reference": "https://example.test/overture/2026-10-01.0",
            "bbox": (-122.0, 37.0, -121.7, 37.5),
            "geography_label": "San Jose reviewed boundary",
            "license": "Reviewed Overture license assertion",
            "attribution": "Overture Maps Foundation",
        }
        arguments.update(updates)
        return prepare_overture_snapshot(**arguments)

    def test_filters_schema_v2_scope_orders_ids_and_writes_compatible_manifest(self) -> None:
        self._write_source()

        result = self._prepare()

        with duckdb.connect() as connection:
            ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM read_parquet(?)", [str(self.output)]
                ).fetchall()
            ]
        self.assertEqual(ids, ["a-root", "z-specialty"])
        self.assertEqual(result.row_count, 2)
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 1)
        self.assertFalse(manifest["delivery_approved"])
        self.assertEqual(manifest["row_count"], 2)
        self.assertEqual(
            {item["license"] for item in manifest["license_inventory"]},
            {"Apache-2.0", "CDLA-Permissive-2.0"},
        )
        self.assertEqual(
            manifest["sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest()
        )
        self.assertIn("bbox=[-122.0,37.0,-121.7,37.5]", manifest["geography"])
        imported = list(OvertureSnapshotSource(self.output).extract())
        self.assertEqual([business.name for business in imported], ["A Dental", "Z Specialty"])

    def test_rejects_network_invalid_scope_and_existing_output(self) -> None:
        self._write_source()
        with self.assertRaisesRegex(ValueError, "explicit local"):
            self._prepare(source="https://example.test/places.parquet")
        with self.assertRaisesRegex(ValueError, "antimeridian"):
            self._prepare(bbox=(170, -10, -170, 10))

        self.output.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            self._prepare()
        self.assertEqual(self.output.read_bytes(), b"preserve")

    def test_optional_localities_narrow_the_candidate_scope(self) -> None:
        self._write_source()
        narrowed = self.root / "san-jose-only.parquet"

        result = self._prepare(
            destination=narrowed,
            localities=("San Jose",),
        )

        with duckdb.connect() as connection:
            ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM read_parquet(?)", [str(narrowed)]
                ).fetchall()
            ]
        self.assertEqual(ids, ["a-root"])
        self.assertIn(
            "address localities=san jose",
            result.manifest_path.read_text(encoding="utf-8"),
        )

    def test_rejects_missing_schema_duplicate_ids_and_empty_selection(self) -> None:
        with duckdb.connect() as connection:
            connection.execute(
                "COPY (SELECT 'one' AS id) TO ? (FORMAT PARQUET)", [str(self.source)]
            )
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            self._prepare()

        self.source.unlink()
        self._write_source()
        duplicate = self.root / "duplicate.parquet"
        with duckdb.connect() as connection:
            connection.execute(
                "CREATE TEMP TABLE duplicate_row AS "
                "SELECT * FROM read_parquet(?) WHERE id = 'a-root'",
                [str(self.source)],
            )
            connection.execute(
                "COPY duplicate_row TO ? (FORMAT PARQUET)", [str(duplicate)]
            )
        with self.assertRaisesRegex(ValueError, "duplicate place ids"):
            self._prepare(source=str(self.root / "*.parquet"))

        duplicate.unlink()
        with self.assertRaisesRegex(ValueError, "selected no dental"):
            self._prepare(bbox=(-120.0, 35.0, -119.0, 36.0))


if __name__ == "__main__":
    unittest.main()
