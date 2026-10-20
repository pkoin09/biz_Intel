"""Offline contracts for evidence-only cross-source matching."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from biz_intel.composition import CrossSourceMatcher
from biz_intel.jobs.models import JobSpec
from biz_intel.models.business import Business
from biz_intel.services.exporter import export_delivery


def _business(source: str, **overrides: object) -> Business:
    data: dict[str, object] = {
        "name": "Example Contractor",
        "address": "1 Main St",
        "city": "Seattle",
        "state": "WA",
        "phone": "206-555-1212",
        "website": "https://www.example.test/",
        "source": source,
        "source_url": f"https://evidence.example.test/{source}",
        "source_ids": {"shared_id": "ABC-123"},
    }
    data.update(overrides)
    return Business(**data)


class CrossSourceMatcherTests(unittest.TestCase):
    def test_exact_identifiers_link_without_mutating_businesses(self) -> None:
        primary = _business("primary")
        supplemental = _business("registry")

        result = CrossSourceMatcher("primary", ("registry",)).match(
            [primary, supplemental]
        )

        self.assertEqual(len(result.matches), 1)
        match = result.matches[0]
        self.assertEqual(match.decision, "matched")
        self.assertEqual(match.match_method, "exact_source_id_and_phone_and_website")
        self.assertEqual(primary.name, "Example Contractor")
        self.assertEqual(supplemental.name, "Example Contractor")

    def test_shared_identifier_with_conflicting_name_and_address_needs_review(self) -> None:
        primary = _business(
            "primary",
            name="Al R Abad",
            address="2664 Berryessa Rd",
            city="San Jose",
            state="CA",
            phone="408-292-1654",
            website="https://abatedentistry.test",
            source_ids={"npi": "1104992148"},
        )
        supplemental = _business(
            "reviewed",
            name="Gregory R Abate",
            address="2075 Forest Ave",
            city="San Jose",
            state="CA",
            source_ids={"npi": "1104992148"},
        )

        result = CrossSourceMatcher("primary", ("reviewed",)).match(
            [primary, supplemental]
        )

        self.assertEqual(result.matches[0].decision, "candidate")
        self.assertEqual(result.matches[0].match_method, "exact_source_id_candidate")

    def test_multiple_exact_candidates_stay_ambiguous(self) -> None:
        primary = _business("primary")
        supplemental = [
            _business("registry", source_ids={"shared_id": f"ABC-{number}"})
            for number in ("123", "456")
        ]

        result = CrossSourceMatcher("primary", ("registry",)).match(
            [primary, *supplemental]
        )

        self.assertEqual([match.decision for match in result.matches], ["ambiguous", "ambiguous"])

    def test_one_supplemental_candidate_for_multiple_primaries_is_ambiguous(self) -> None:
        primary = [
            _business("primary", name=f"Dentist {number}", source_ids={"npi": str(number)})
            for number in (1, 2)
        ]
        supplemental = _business("registry", source_ids={})

        result = CrossSourceMatcher("primary", ("registry",)).match(
            [*primary, supplemental]
        )

        self.assertEqual(
            [match.decision for match in result.matches],
            ["ambiguous", "ambiguous"],
        )

    def test_shared_identifier_wins_over_another_primary_sharing_the_phone(self) -> None:
        organization = _business(
            "primary",
            name="Dental Group",
            source_ids={"npi": "1111111111"},
        )
        individual = _business(
            "primary",
            name="Dentist Name",
            source_ids={"npi": "2222222222"},
        )
        supplemental = _business(
            "directory",
            name="Dental Group",
            source_ids={"npi": "1111111111"},
        )

        result = CrossSourceMatcher("primary", ("directory",)).match(
            [organization, individual, supplemental]
        )

        self.assertEqual(len(result.matches), 1)
        self.assertEqual(result.matches[0].decision, "matched")
        self.assertEqual(result.matches[0].primary.record_id, "npi:1111111111")
        self.assertIn("source_id", result.matches[0].matched_fields)

    def test_name_address_only_is_a_review_candidate(self) -> None:
        primary = _business("primary", phone="", website="", source_ids={})
        supplemental = _business("registry", phone="", website="", source_ids={})
        result = CrossSourceMatcher("primary", ("registry",)).match(
            [primary, supplemental]
        )
        self.assertEqual(result.matches[0].decision, "candidate")
        self.assertEqual(result.matches[0].match_method, "exact_name_address_candidate")

    def test_unique_phone_without_matching_practice_identity_is_a_candidate(self) -> None:
        primary = _business(
            "primary",
            name="Jane Dentist",
            address="1 Main St",
            website="",
            source_ids={"npi": "1234567890"},
        )
        supplemental = _business(
            "overture",
            name="Downtown Dental Group",
            address="99 Market St",
            website="https://downtown.test",
            source_ids={"overture_id": "place-1"},
        )

        result = CrossSourceMatcher("primary", ("overture",)).match(
            [primary, supplemental]
        )

        self.assertEqual(len(result.matches), 1)
        self.assertEqual(result.matches[0].decision, "candidate")
        self.assertEqual(result.matches[0].match_method, "exact_phone_candidate")

    def test_unique_phone_with_exact_practice_identity_is_matched(self) -> None:
        primary = _business("primary", website="", source_ids={"npi": "1234567890"})
        supplemental = _business(
            "overture",
            website="https://example.test",
            source_ids={"overture_id": "place-1"},
        )

        result = CrossSourceMatcher("primary", ("overture",)).match(
            [primary, supplemental]
        )

        self.assertEqual(result.matches[0].decision, "matched")
        self.assertEqual(
            result.matches[0].matched_fields,
            ("phone", "name", "address"),
        )

    def test_job_config_requires_declared_distinct_sources_and_sidecars(self) -> None:
        base = {
            "version": 1,
            "name": "composition-test",
            "search": {"query": "contractor", "states": ["WA"]},
            "sources": ["csv", "wa-li"],
            "processing": {},
            "output": {"format": "csv", "fields": ["name"]},
            "composition": {"primary_source": "csv", "supplemental_sources": ["wa-li"]},
        }
        job = JobSpec.from_dict(base)
        self.assertTrue(job.composition.enabled)
        self.assertEqual(job.composition.primary_source, "csv")

        without_sidecars = {**base, "delivery": {"include_sidecars": False}}
        with self.assertRaisesRegex(ValueError, "requires delivery.include_sidecars"):
            JobSpec.from_dict(without_sidecars)

    def test_sidecar_is_written_only_when_composition_is_requested(self) -> None:
        destination = Path(__file__).parent / "_tmp_composition.csv"
        sidecar = destination.with_name("_tmp_composition.composition.json")
        quality = destination.with_name("_tmp_composition.quality.json")
        evidence = destination.with_name("_tmp_composition.evidence.json")
        self.addCleanup(destination.unlink, missing_ok=True)
        self.addCleanup(sidecar.unlink, missing_ok=True)
        self.addCleanup(quality.unlink, missing_ok=True)
        self.addCleanup(evidence.unlink, missing_ok=True)
        result = CrossSourceMatcher("primary", ("registry",)).match([
            _business("primary"), _business("registry"),
        ])
        exported = export_delivery(
            [_business("primary")],
            JobSpec.from_dict({
                "version": 1,
                "name": "composition-export-test",
                "search": {"query": "contractor", "states": ["WA"]},
                "sources": ["csv"],
                "processing": {},
                "output": {"format": "csv", "fields": ["name"], "destination": str(destination)},
            }).output,
            "composition-export-test",
            include_non_accepted=True,
            include_sidecars=True,
            composition_payload=result.to_dict(),
        )
        self.assertEqual(exported.composition_destination, sidecar)
        payload = json.loads(sidecar.read_text())
        self.assertEqual(payload["counts"]["matched"], 1)


if __name__ == "__main__":
    unittest.main()
