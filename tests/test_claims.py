"""Offline contracts for additive source claims."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
import unittest

from biz_intel.delivery.contract import provenance_payload
from biz_intel.jobs.models import JobSpec
from biz_intel.jobs.run import _business_from_checkpoint, _checkpoint_business
from biz_intel.models import Business, Claim
from biz_intel.storage import RunHistoryStore


OBSERVED_AT = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def _claim(**updates: object) -> Claim:
    values: dict[str, object] = {
        "key": "license.status",
        "value": "ACTIVE",
        "source": "wa_li",
        "source_record_id": "WA-123",
        "evidence_url": "https://data.example.test/WA-123",
        "observed_at": OBSERVED_AT,
    }
    values.update(updates)
    return Claim(**values)


def _business(**updates: object) -> Business:
    values: dict[str, object] = {
        "name": "Example Contractor",
        "address": "1 First Street",
        "city": "Seattle",
        "state": "WA",
        "phone": "2065551111",
        "source": "client_input",
        "source_url": "https://client.example.test/example-contractor",
    }
    values.update(updates)
    return Business(**values)


class ClaimTests(unittest.TestCase):
    def test_business_to_dict_round_trips_typed_claims(self) -> None:
        business = _business(claims=(_claim(),))

        self.assertEqual(Business.from_dict(business.to_dict()), business)

    def test_claims_restore_as_typed_values_from_business_data(self) -> None:
        restored = Business.from_dict(
            {
                **_business().to_dict(),
                "claims": [
                    {
                        **asdict(_claim()),
                        "observed_at": OBSERVED_AT.isoformat(),
                    }
                ],
            }
        )

        self.assertEqual(restored.claims, (_claim(),))

    def test_claim_is_emitted_only_in_evidence_when_present(self) -> None:
        self.assertNotIn("claims", provenance_payload(_business()))

        payload = provenance_payload(_business(claims=(_claim(),)))

        self.assertEqual(payload["claims"], [
            {
                "key": "license.status",
                "value": "ACTIVE",
                "source": "wa_li",
                "source_record_id": "WA-123",
                "evidence_url": "https://data.example.test/WA-123",
                "observed_at": OBSERVED_AT.isoformat(),
                "method": "source_observation",
                "authority": "supplemental",
            }
        ])

    def test_checkpoint_round_trip_preserves_claims_without_raw_data(self) -> None:
        checkpointed = _checkpoint_business(
            _business(claims=(_claim(),), source_ids={"wa_li_license": "WA-123"})
        )
        restored = _business_from_checkpoint(checkpointed)

        self.assertEqual(restored.claims, (_claim(),))
        self.assertEqual(restored.source_ids, {"wa_li_license": "WA-123"})
        self.assertIsNone(restored.raw_data)

    def test_history_ignores_claims_until_claim_change_tracking_is_defined(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunHistoryStore(directory)
            store.record("contractors", "run-1", [_business()])
            second = store.record(
                "contractors",
                "run-2",
                [_business(claims=(_claim(),), source_ids={"wa_li_license": "WA-123"})],
            )

        self.assertEqual(second.changes.counts, {
            "new": 0,
            "updated": 0,
            "unchanged": 1,
            "missing": 0,
        })

    def test_claim_containers_are_not_direct_export_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown fields: claims"):
            JobSpec.from_dict(
                {
                    "version": 1,
                    "name": "invalid-claim-export",
                    "search": {"query": "contractor"},
                    "sources": ["csv"],
                    "output": {"fields": ["name", "claims"]},
                }
            )


if __name__ == "__main__":
    unittest.main()
