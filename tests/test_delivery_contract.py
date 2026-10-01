"""Offline tests for the V1 client-delivery acceptance contract."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from biz_intel.delivery.contract import DeliveryContract
from biz_intel.jobs.models import JobOutput
from biz_intel.models.business import Business, FieldProvenance
from biz_intel.services.exporter import export_delivery


OBSERVED_AT = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _business(**updates) -> Business:
    values = {
        "name": "Example Dental",
        "address": "1 First Street",
        "city": "San Jose",
        "state": "CA",
        "phone": "4085551111",
        "source": "official_registry",
        "source_url": "https://registry.example.test/example-dental",
        "scraped_at": OBSERVED_AT,
    }
    values.update(updates)
    return Business(**values)


class DeliveryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.written: list[Path] = []

    def tearDown(self) -> None:
        for path in self.written:
            path.unlink(missing_ok=True)

    def test_standard_accepts_evidenced_business_and_adds_field_provenance(self) -> None:
        business = DeliveryContract().classify_business(_business())

        self.assertEqual(business.record_status, "accepted")
        self.assertEqual(business.phone_status, "not_found")
        self.assertEqual(business.observed_at, OBSERVED_AT)
        evidence = business.field_provenance["phone"]
        self.assertEqual(evidence.source, "official_registry")
        self.assertEqual(evidence.evidence_url, "https://registry.example.test/example-dental")
        self.assertEqual(evidence.observed_at, OBSERVED_AT)
        self.assertEqual(evidence.method, "source_observation")

    def test_standard_marks_missing_evidence_incomplete_without_erasing_data(self) -> None:
        business = DeliveryContract().classify_business(
            _business(source_url="", scraped_at=None)
        )

        self.assertEqual(business.record_status, "incomplete")
        self.assertEqual(
            business.quality_reasons,
            ("missing_source_url", "missing_observed_at"),
        )
        self.assertEqual(business.phone, "4085551111")
        self.assertEqual(business.field_provenance, {})

    def test_terminal_record_status_is_preserved(self) -> None:
        business = DeliveryContract().classify_business(
            _business(record_status="out_of_scope", quality_reasons=("outside_client_area",))
        )

        self.assertEqual(business.record_status, "out_of_scope")
        self.assertEqual(business.quality_reasons, ("outside_client_area",))

    def test_max_age_marks_otherwise_accepted_record_incomplete(self) -> None:
        stale = datetime.now(timezone.utc) - timedelta(days=31)
        business = DeliveryContract(max_age_days=30).classify_business(
            _business(scraped_at=stale)
        )

        self.assertEqual(business.record_status, "incomplete")
        self.assertEqual(business.quality_reasons, ("stale_observation",))

    def test_export_writes_accepted_main_file_and_safe_sidecars(self) -> None:
        accepted = DeliveryContract().classify_business(_business())
        incomplete = DeliveryContract().classify_business(_business(name="Missing Evidence", source_url=""))
        destination = Path(__file__).with_name("_tmp_delivery.csv")
        self.written.extend(
            [
                destination,
                destination.with_name("_tmp_delivery.quality.json"),
                destination.with_name("_tmp_delivery.evidence.json"),
            ]
        )

        result = export_delivery(
            [accepted, incomplete],
            JobOutput(format="csv", fields=("name", "phone"), destination=str(destination)),
            "delivery-contract-test",
            include_non_accepted=False,
            include_sidecars=True,
        )

        self.assertEqual(result.record_count, 1)
        self.assertEqual(destination.read_text().strip().splitlines(), ["name,phone", "Example Dental,4085551111"])
        quality = json.loads(result.quality_destination.read_text())
        evidence = json.loads(result.evidence_destination.read_text())
        self.assertEqual([row["record_status"] for row in quality], ["accepted", "incomplete"])
        self.assertIn("phone", evidence[0]["field_provenance"])
        self.assertNotIn("raw_data", evidence[0])

    def test_first_party_evidence_is_not_overwritten(self) -> None:
        first_party = FieldProvenance(
            source="first_party_web",
            evidence_url="https://example.test/contact",
            observed_at=OBSERVED_AT,
            method="public_link",
        )
        business = DeliveryContract().classify_business(
            _business(field_provenance={"phone": first_party})
        )

        self.assertEqual(business.field_provenance["phone"], first_party)


if __name__ == "__main__":
    unittest.main()
