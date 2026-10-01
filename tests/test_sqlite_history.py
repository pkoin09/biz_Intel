"""Focused offline tests for the opt-in SQLite history store."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from biz_intel.models.business import Business
from biz_intel.storage import SQLiteHistoryStore, stable_record_id


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
        "record_status": "accepted",
    }
    values.update(changes)
    return Business(**values)


class SQLiteHistoryStoreTests(unittest.TestCase):
    def test_upsert_versions_and_change_queries_are_sanitized(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "history.sqlite3"
            store = SQLiteHistoryStore(database)
            first = store.record("dentists", "run-1", [_business()])
            record_id = stable_record_id(_business())
            assert record_id is not None
            self.assertEqual(first.changes.counts, {"new": 1, "updated": 0, "unchanged": 0, "missing": 0})

            second = store.record(
                "dentists",
                "run-2",
                [_business(website="https://updated.example.test", raw_data={"secret": "never stored"})],
            )
            self.assertEqual(second.changes.counts, {"new": 0, "updated": 1, "unchanged": 0, "missing": 0})
            self.assertEqual(second.changes.updated, {record_id: ("website",)})
            self.assertEqual(store.get_run_changes("dentists", "run-2"), second.changes)

            current = store.get_record("dentists", record_id)
            assert current is not None
            self.assertEqual(current.first_seen_run_id, "run-1")
            self.assertEqual(current.last_seen_run_id, "run-2")
            self.assertEqual(current.business["website"], "https://updated.example.test")
            self.assertNotIn("raw_data", current.business)
            self.assertEqual([version.run_id for version in store.get_record_versions("dentists", record_id)], ["run-1", "run-2"])
            self.assertEqual([run.run_id for run in store.list_runs("dentists")], ["run-2", "run-1"])

    def test_missing_records_remain_versioned_but_are_not_current(self) -> None:
        with TemporaryDirectory() as directory:
            store = SQLiteHistoryStore(Path(directory) / "history.sqlite3")
            business = _business()
            record_id = stable_record_id(business)
            assert record_id is not None
            store.record("dentists", "run-1", [business])
            result = store.record("dentists", "run-2", [])
            self.assertEqual(result.changes.counts, {"new": 0, "updated": 0, "unchanged": 0, "missing": 1})
            self.assertIsNone(store.get_record("dentists", record_id))
            self.assertEqual([version.run_id for version in store.get_record_versions("dentists", record_id)], ["run-1"])

    def test_non_accepted_records_are_not_persisted_and_run_ids_are_immutable(self) -> None:
        with TemporaryDirectory() as directory:
            store = SQLiteHistoryStore(Path(directory) / "history.sqlite3")
            result = store.record("dentists", "run-1", [_business(record_status="needs_review")])
            self.assertEqual(result.changes.counts, {"new": 0, "updated": 0, "unchanged": 0, "missing": 0})
            self.assertEqual(store.list_runs("dentists")[0].changes, result.changes)
            with self.assertRaisesRegex(ValueError, "already exists"):
                store.record("dentists", "run-1", [])

    def test_invalid_query_limit_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "positive"):
                SQLiteHistoryStore(Path(directory) / "history.sqlite3").list_runs("dentists", limit=0)
