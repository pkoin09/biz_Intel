"""Offline contracts for California Dental Board manual evidence imports."""

from __future__ import annotations

import csv
from pathlib import Path
import unittest

from biz_intel.composition import CrossSourceMatcher
from biz_intel.core.source_policy import CA_DENTAL_BOARD_POLICY, SourceClass
from biz_intel.models.business import Business
from biz_intel.sources.ca_dental_board import CaliforniaDentalBoardSource


class CaliforniaDentalBoardSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(__file__).parent / "_tmp_ca_dental_board.csv"
        self.addCleanup(self.path.unlink, missing_ok=True)

    def _write(self, row: dict[str, str]) -> None:
        with self.path.open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)

    @staticmethod
    def _row(**updates: str) -> dict[str, str]:
        row = {
            "license_number": "DDS12345",
            "licensee_name": "EXAMPLE, DENTIST",
            "license_type": "Dentist",
            "license_status": "Current - Active",
            "expiration_date": "2027-03-31",
            "address": "1 Main St",
            "city": "San Jose",
            "state": "CA",
            "zip": "95112",
            "evidence_url": "https://search.dca.ca.gov/profile/440/4401/12345/DDS",
            "observed_at": "2026-10-03T12:00:00+00:00",
            "policy_number": "must not be retained",
        }
        row.update(updates)
        return row

    def test_imports_auditable_license_evidence_without_extra_columns(self) -> None:
        self._write(self._row())
        business = next(CaliforniaDentalBoardSource(self.path).extract())
        self.assertEqual(business.source_ids, {"ca_dental_license": "DDS12345"})
        self.assertEqual(
            {claim.key for claim in business.claims},
            {
                "registry.ca_dental_board.license_number",
                "registry.ca_dental_board.license_status",
                "registry.ca_dental_board.license_type",
                "registry.ca_dental_board.expiration_date",
            },
        )
        self.assertNotIn("policy_number", business.raw_data or {})

    def test_matches_nppes_candidate_by_california_dental_license(self) -> None:
        self._write(self._row())
        board_record = next(CaliforniaDentalBoardSource(self.path).extract())
        nppes_candidate = Business(
            name="Example Dentist",
            source="nppes",
            source_url="https://npiregistry.cms.hhs.gov/provider-view/1234567890",
            source_ids={"npi": "1234567890", "ca_dental_license": "DDS12345"},
        )
        result = CrossSourceMatcher("nppes", ("ca-dental-board",)).match(
            [nppes_candidate, board_record]
        )
        self.assertEqual(result.matches[0].decision, "matched")
        self.assertIn("source_id", result.matches[0].matched_fields)

    def test_rejects_missing_evidence_and_invalid_timestamp(self) -> None:
        self._write(self._row(evidence_url=""))
        with self.assertRaisesRegex(ValueError, "evidence_url"):
            list(CaliforniaDentalBoardSource(self.path).extract())

        self._write(self._row(observed_at="yesterday"))
        with self.assertRaisesRegex(ValueError, "invalid observed_at"):
            list(CaliforniaDentalBoardSource(self.path).extract())

    def test_policy_declares_manual_official_verification(self) -> None:
        self.assertEqual(CA_DENTAL_BOARD_POLICY.source_class, SourceClass.OFFICIAL_REGISTRY)
        self.assertTrue(CA_DENTAL_BOARD_POLICY.allows_delivery)
        self.assertIn("manual evidence import", CA_DENTAL_BOARD_POLICY.rate_limit)


if __name__ == "__main__":
    unittest.main()
