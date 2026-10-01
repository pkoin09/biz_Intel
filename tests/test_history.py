"""Offline tests for stable record identity and local run history."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from biz_intel.models.business import Business, FieldProvenance
from biz_intel.storage import RunHistoryStore, stable_record_id


def _business(**changes: object) -> Business:
    values: dict[str, object] = {
        "name": "Bright Smiles",
        "address": "1 First St",
        "city": "San Jose",
        "state": "CA",
        "phone": "4085551111",
        "website": "https://bright.example.test",
        "source": "client_input",
        "source_url": "https://client.example.test/bright-smiles",
    }
    values.update(changes)
    return Business(**values)


class HistoryTests(unittest.TestCase):
    def test_stable_id_excludes_source_and_observation_time(self) -> None:
        first = _business(source="client_input")
        second = _business(
            source="official_registry",
            scraped_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        )

        self.assertEqual(stable_record_id(first), stable_record_id(second))
        self.assertTrue(stable_record_id(first).startswith("biz_"))

    def test_history_tracks_new_updated_unchanged_and_missing(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunHistoryStore(directory)
            first = store.record(
                "dentists", "run-1", [_business(), _business(name="Sunny Dental", phone="4085552222")]
            )
            self.assertEqual(first.changes.counts, {
                "new": 2, "updated": 0, "unchanged": 0, "missing": 0,
            })

            second = store.record(
                "dentists",
                "run-2",
                [
                    _business(website="https://new-bright.example.test"),
                    _business(name="New Dental", phone="4085553333"),
                ],
            )

            self.assertEqual(second.changes.counts, {
                "new": 1, "updated": 1, "unchanged": 0, "missing": 1,
            })
            updated_fields = next(iter(second.changes.updated.values()))
            self.assertEqual(updated_fields, ("website",))
            payload = json.loads(Path(second.destination).read_text())
            self.assertNotIn("raw_data", json.dumps(payload))
            self.assertIn("record_id", payload["records"][0])

    def test_history_ignores_volatile_observation_and_provenance(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunHistoryStore(directory)
            store.record("dentists", "run-1", [_business()])
            second = store.record(
                "dentists",
                "run-2",
                [
                    _business(
                        scraped_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
                        field_provenance={
                            "phone": FieldProvenance(
                                source="client_input",
                                evidence_url="https://client.example.test/bright-smiles",
                                observed_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
                                method="provided",
                            )
                        },
                        raw_data={"private": "not persisted"},
                    )
                ],
            )
            self.assertEqual(second.changes.counts, {
                "new": 0, "updated": 0, "unchanged": 1, "missing": 0,
            })

    def test_history_rejects_records_without_durable_identity(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "sufficient stable identity"):
                RunHistoryStore(directory).record("dentists", "run-1", [Business(name="Only Name")])
