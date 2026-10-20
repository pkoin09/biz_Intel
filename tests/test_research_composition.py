"""Tests for safely composing supplemental evidence into research sessions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from biz_intel.models import Business
from biz_intel.research import ResearchSession, compose_research_session


def _write_records(path: Path, records: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps(records))
    return path


class ResearchCompositionTests(unittest.TestCase):
    def test_unique_exact_phone_match_attaches_missing_website_with_audit(self) -> None:
        observed_at = datetime(2026, 10, 20, 12, 30, tzinfo=timezone.utc)
        session = ResearchSession(
            "Dentists in San Jose",
            [
                Business(
                    name="Neighborhood Dental",
                    address="1 Main St",
                    city="San Jose",
                    state="CA",
                    phone="(408) 555-0100",
                    source="nppes",
                    source_ids={"npi": "1234567890"},
                )
            ],
        )

        with TemporaryDirectory() as directory:
            source_file = _write_records(
                Path(directory) / "website-candidates.json",
                [
                    {
                        "name": "Neighborhood Dental",
                        "address": "1 Main St",
                        "city": "San Jose",
                        "state": "CA",
                        "phone": "+1 408-555-0100",
                        "email": "directory-only@example.test",
                        "website": "https://neighborhood.example",
                        "source": "approved-directory",
                        "source_url": "https://directory.example/neighborhood",
                        "observed_at": observed_at.isoformat(),
                        "source_ids": {"place_id": "place-1"},
                    }
                ],
            )

            step = compose_research_session(session, source_file)
            saved = session.save(Path(directory) / "session.json")
            restored = ResearchSession.load(saved)

        business = restored.businesses[0]
        self.assertEqual(business.website, "https://neighborhood.example")
        self.assertEqual(business.email, "")
        self.assertEqual(
            business.discovery_sources,
            ("nppes", "approved-directory"),
        )
        self.assertEqual(business.field_provenance["website"].source, "approved-directory")
        self.assertEqual(
            business.field_provenance["website"].evidence_url,
            "https://directory.example/neighborhood",
        )
        self.assertEqual(business.field_provenance["website"].observed_at, observed_at)
        self.assertEqual(
            business.field_provenance["website"].method,
            "cross_source_exact_match",
        )
        self.assertEqual(step.matched_count, 1)
        self.assertEqual(step.website_count, 1)
        self.assertEqual(step.contact_count, 0)
        self.assertEqual(len(restored.compositions), 1)
        audit = restored.compositions[0]
        self.assertEqual(audit.source, "approved-directory")
        self.assertEqual(audit.record_count, 1)
        self.assertEqual(audit.matches[0]["decision"], "matched")
        self.assertEqual(
            audit.matches[0]["match_method"],
            "exact_phone_and_name_and_address",
        )

    def test_phone_only_collision_does_not_attach_another_business_website(self) -> None:
        session = ResearchSession(
            "Dentists",
            [
                Business(
                    name="Neighborhood Dental",
                    address="1 Main St",
                    city="San Jose",
                    state="CA",
                    phone="4085550100",
                    source="nppes",
                )
            ],
        )

        with TemporaryDirectory() as directory:
            source_file = _write_records(
                Path(directory) / "collision.json",
                [
                    {
                        "name": "Unrelated Dental Corporation",
                        "address": "99 Market St",
                        "city": "San Jose",
                        "state": "CA",
                        "phone": "408-555-0100",
                        "website": "https://unrelated.example",
                        "source": "directory",
                    }
                ],
            )
            step = compose_research_session(session, source_file)

        self.assertEqual(session.businesses[0].website, "")
        self.assertNotIn("website", session.businesses[0].field_provenance)
        self.assertEqual(step.website_count, 0)

    def test_name_and_address_candidate_is_review_only(self) -> None:
        session = ResearchSession(
            "Dentists",
            [
                Business(
                    name="Neighborhood Dental",
                    address="1 Main St",
                    city="San Jose",
                    state="CA",
                    source="nppes",
                )
            ],
        )

        with TemporaryDirectory() as directory:
            source_file = _write_records(
                Path(directory) / "candidates.json",
                [
                    {
                        "name": "Neighborhood Dental",
                        "address": "1 Main St",
                        "city": "San Jose",
                        "state": "CA",
                        "website": "https://possible.example",
                        "source": "directory",
                    }
                ],
            )
            step = compose_research_session(session, source_file)

        self.assertEqual(session.businesses[0].website, "")
        self.assertNotIn("website", session.businesses[0].field_provenance)
        self.assertEqual(step.candidate_count, 1)
        self.assertEqual(step.website_count, 0)
        self.assertEqual(step.matches[0]["decision"], "candidate")

    def test_existing_website_is_not_overwritten_by_exact_match(self) -> None:
        session = ResearchSession(
            "Dentists",
            [
                Business(
                    name="Neighborhood Dental",
                    phone="4085550100",
                    website="https://first-party.example",
                    source="nppes",
                    source_ids={"shared": "same-business"},
                )
            ],
        )

        with TemporaryDirectory() as directory:
            source_file = _write_records(
                Path(directory) / "candidates.json",
                [
                    {
                        "name": "Neighborhood Dental",
                        "phone": "408-555-0100",
                        "website": "https://directory-value.example",
                        "source": "directory",
                        "source_ids": {"shared": "same-business"},
                    }
                ],
            )
            step = compose_research_session(session, source_file)

        self.assertEqual(session.businesses[0].website, "https://first-party.example")
        self.assertEqual(step.matched_count, 1)
        self.assertEqual(step.website_count, 0)

    def test_manual_first_party_review_fills_blank_email_without_verifying_it(self) -> None:
        session = ResearchSession(
            "Dentists",
            [
                Business(
                    name="Neighborhood Dental",
                    source="nppes",
                    source_ids={"npi": "1234567890"},
                )
            ],
        )

        with TemporaryDirectory() as directory:
            source_file = _write_records(
                Path(directory) / "reviewed.json",
                [
                    {
                        "name": "Neighborhood Dental",
                        "email": "hello@neighborhood.example",
                        "website": "https://neighborhood.example",
                        "source": "manual_first_party_review",
                        "source_url": "https://neighborhood.example/contact",
                        "observed_at": "2026-10-20T12:30:00+00:00",
                        "source_ids": {"npi": "1234567890"},
                    }
                ],
            )
            step = compose_research_session(session, source_file)

        business = session.businesses[0]
        self.assertEqual(business.email, "hello@neighborhood.example")
        self.assertEqual(business.email_status, "not_checked")
        self.assertEqual(
            business.field_provenance["email"].evidence_url,
            "https://neighborhood.example/contact",
        )
        self.assertEqual(step.contact_count, 1)


if __name__ == "__main__":
    unittest.main()
