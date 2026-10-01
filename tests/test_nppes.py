"""Offline contract tests for the CMS NPPES source."""

from __future__ import annotations

import unittest

from biz_intel.core.location import Location
from biz_intel.core.source_policy import NPPES_POLICY, SourceClass
from biz_intel.core.source_name import SourceName
from biz_intel.core.source_task import SourceTask
from biz_intel.sources.nppes import NppesSource


def _record(*, city: str = "SAN JOSE", taxonomy: str = "Dentist") -> dict:
    return {
        "number": "1234567890",
        "basic": {"organization_name": "Example Dental"},
        "addresses": [{
            "address_purpose": "LOCATION", "address_1": "1 Main St",
            "city": city, "state": "CA", "postal_code": "95112",
            "country_name": "United States", "telephone_number": "4085551212",
        }],
        "taxonomies": [{"primary": True, "desc": taxonomy}],
    }


class NppesSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = NppesSource(SourceTask(
            source=SourceName.NPPES,
            category="Dentist",
            location=Location(city="San Jose", state="CA"),
        ))

    def test_filters_candidate_records_outside_requested_scope(self) -> None:
        self.assertTrue(self.source._matches_scope(self.source._to_business(_record())))
        self.assertFalse(self.source._matches_scope(self.source._to_business(_record(city="Oakland"))))
        self.assertFalse(self.source._matches_scope(
            self.source._to_business(_record(taxonomy="Nurse Practitioner, Family"))
        ))

    def test_rejects_record_without_complete_practice_contact(self) -> None:
        incomplete = _record()
        incomplete["addresses"][0]["telephone_number"] = ""
        self.assertIsNone(self.source._to_business(incomplete))

    def test_connector_policy_is_narrow_and_zero_spend(self) -> None:
        self.assertEqual(NPPES_POLICY.source_class, SourceClass.OFFICIAL_REGISTRY)
        self.assertTrue(NPPES_POLICY.allows_delivery)
        self.assertEqual(NPPES_POLICY.cost_model, "zero-spend")
        self.assertFalse(NPPES_POLICY.allows_live_smoke)
        self.assertIn("practice phone", NPPES_POLICY.field_coverage)


if __name__ == "__main__":
    unittest.main()
