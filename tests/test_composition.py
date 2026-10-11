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

    def test_name_address_only_is_a_review_candidate(self) -> None:
        primary = _business("primary", phone="", website="", source_ids={})
        supplemental = _business("registry", phone="", website="", source_ids={})
        result = CrossSourceMatcher("primary", ("registry",)).match(
            [primary, supplemental]
        )
        self.assertEqual(result.matches[0].decision, "candidate")
        self.assertEqual(result.matches[0].match_method, "exact_name_address_candidate")

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
