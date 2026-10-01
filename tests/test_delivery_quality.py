"""Tests for aggregate client-delivery quality reporting."""

from __future__ import annotations

import unittest

from biz_intel.delivery import delivery_summary_payload
from biz_intel.models.business import Business


class DeliveryQualityTests(unittest.TestCase):
    def test_reports_completeness_reasons_and_duplicate_metric(self) -> None:
        payload = delivery_summary_payload(
            [
                Business(
                    name="Complete Dental",
                    city="San Jose",
                    state="CA",
                    phone="4085551111",
                    website="example.test",
                    record_status="accepted",
                ),
                Business(
                    name="Missing Contact",
                    city="San Jose",
                    state="CA",
                    record_status="incomplete",
                    quality_reasons=("missing_phone_or_website",),
                ),
                Business(name="Closed Dental", record_status="closed"),
            ],
            acquired_records=5,
            delivered_records=1,
            pipeline_metrics={"duplicates_removed": 2, "invalid_phones": 1},
        )

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["records"], {
            "acquired": 5,
            "classified": 3,
            "delivered": 1,
        })
        self.assertEqual(payload["duplicates_removed"], 2)
        self.assertEqual(payload["status_counts"], {
            "accepted": 1,
            "closed": 1,
            "incomplete": 1,
        })
        self.assertEqual(payload["non_accepted_reason_counts"], {
            "missing_phone_or_website": 1,
            "status:closed": 1,
        })
        self.assertEqual(payload["field_completeness"]["phone"], {
            "present": 1,
            "total": 3,
            "percent": 33.33,
        })
        self.assertEqual(payload["field_completeness"]["website"]["percent"], 33.33)


if __name__ == "__main__":
    unittest.main()
