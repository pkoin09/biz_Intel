"""Tests for the smallest progressive-research loop."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import Mock
import unittest

from biz_intel.models import Business, Claim
from biz_intel.research import (
    ClaimFilterPlugin,
    LongevityEvidencePlugin,
    MediCalDentalEnrollmentPlugin,
    OperationalStatusEvidencePlugin,
    OwnershipEvidencePlugin,
    PublicEmailPlugin,
    PublicSocialPlugin,
    ResearchRunner,
    ResearchSession,
)
from biz_intel.services.enrichment import CrawlOutcome


class ResearchSessionTests(unittest.TestCase):
    def test_refinement_keeps_evidence_backed_matches_and_survives_reload(self) -> None:
        observed_at = datetime(2026, 10, 11, tzinfo=timezone.utc)
        supported = Business(
            name="Neighborhood Dental",
            claims=(
                Claim(
                    key="accepts_medi_cal",
                    value=True,
                    source="provider-directory",
                    source_record_id="dentist-1",
                    evidence_url="https://example.test/dentist-1",
                    observed_at=observed_at,
                ),
            ),
        )
        unknown = Business(name="Downtown Dental")
        session = ResearchSession("Dentists in San Jose", [supported, unknown])
        runner = ResearchRunner([ClaimFilterPlugin("accepts_medi_cal", True)])

        runner.refine(
            session,
            "Keep the dentists that accept Medi-Cal",
            plugin="claim-filter",
        )

        self.assertEqual([item.name for item in session.businesses], ["Neighborhood Dental"])
        self.assertEqual(session.refinements[0].before_count, 2)
        self.assertEqual(session.refinements[0].after_count, 1)

        with TemporaryDirectory() as directory:
            path = session.save(Path(directory) / "session.json")
            restored = ResearchSession.load(path)

        self.assertEqual(restored.request, "Dentists in San Jose")
        self.assertEqual(restored.businesses[0].claims[0].key, "accepts_medi_cal")
        self.assertEqual(restored.refinements[0].instruction, "Keep the dentists that accept Medi-Cal")

    def test_unknown_plugin_is_rejected_without_changing_session(self) -> None:
        session = ResearchSession("Dentists in San Jose", [Business(name="Example")])

        with self.assertRaisesRegex(KeyError, "Unknown research plugin"):
            ResearchRunner().refine(session, "Do something", plugin="missing")

        self.assertEqual(len(session.businesses), 1)
        self.assertEqual(session.refinements, [])

    def test_medi_cal_plugin_adds_only_exact_official_npi_matches(self) -> None:
        response = Mock()
        response.json.return_value = {
            "features": [{"attributes": {"Provider_NPI": "1234567890"}}]
        }
        client = Mock()
        client.post.return_value = response
        matched = Business(name="Matched", source_ids={"npi": "1234567890"})
        unmatched = Business(name="Unmatched", source_ids={"npi": "9999999999"})
        no_npi = Business(name="No NPI")
        session = ResearchSession(
            "Dentists in San Jose",
            [matched, unmatched, no_npi],
        )

        ResearchRunner([MediCalDentalEnrollmentPlugin(client)]).refine(
            session,
            "Check which dentists are enrolled in Medi-Cal Dental",
            plugin="medi-cal-dental-enrollment",
        )

        self.assertEqual(matched.claims[0].key, "program.medi_cal_dental_ffs_enrolled")
        self.assertTrue(matched.claims[0].value)
        self.assertEqual(unmatched.claims, ())
        self.assertEqual(no_npi.claims, ())
        submitted = client.post.call_args.kwargs["data"]["where"]
        self.assertIn("1234567890", submitted)
        self.assertIn("9999999999", submitted)
        response.raise_for_status.assert_called_once_with()
        self.assertIn("does not guarantee", session.refinements[0].note)

    def test_ownership_plugin_uses_only_explicit_first_party_wording(self) -> None:
        class Crawler:
            def crawl(self, website):
                pages = {
                    "https://neighbor.test": [
                        ("https://neighbor.test/about", "<p>A family-owned dental practice.</p>")
                    ],
                    "https://network.test": [
                        ("https://network.test/about", "<p>Part of a nationwide network.</p>")
                    ],
                    "https://unknown.test": [
                        ("https://unknown.test/about", "<p>We care for every smile.</p>")
                    ],
                }
                return pages[website]

        independent = Business(name="Neighbor", website="https://neighbor.test")
        corporate = Business(name="Network", website="https://network.test")
        unclear = Business(name="Unknown", website="https://unknown.test")
        no_website = Business(name="No Website")
        session = ResearchSession(
            "Dentists in San Jose",
            [independent, corporate, unclear, no_website],
        )

        ResearchRunner([OwnershipEvidencePlugin(Crawler())]).refine(
            session,
            "Which look family-owned or independent?",
            plugin="ownership-evidence",
        )

        self.assertEqual(independent.claims[0].value, "likely_independent")
        self.assertEqual(corporate.claims[0].value, "likely_corporate")
        self.assertEqual(unclear.claims, ())
        self.assertEqual(no_website.claims, ())
        self.assertIn("1 readable site with no clear signal", session.refinements[0].note)
        self.assertIn("1 record without a website", session.refinements[0].note)

    def test_public_email_plugin_keeps_source_evidence_without_verifying(self) -> None:
        observed_at = datetime(2026, 10, 11, tzinfo=timezone.utc)

        class Enricher:
            def enrich(self, business):
                if business.name == "Published":
                    from biz_intel.models import FieldProvenance

                    return Business(
                        name=business.name,
                        website=business.website,
                        email="hello@published.test",
                        email_status="not_checked",
                        field_provenance={
                            "email": FieldProvenance(
                                source="first_party_web",
                                evidence_url="https://published.test/contact",
                                observed_at=observed_at,
                                method="public_link",
                            )
                        },
                    )
                return business

        published = Business(name="Published", website="https://published.test")
        missing = Business(name="Missing", website="https://missing.test")
        session = ResearchSession("Dentists", [published, missing])

        ResearchRunner([PublicEmailPlugin(Enricher())]).refine(
            session,
            "Find public email addresses",
            plugin="public-email",
        )

        found = session.businesses[0]
        self.assertEqual(found.email, "hello@published.test")
        self.assertEqual(found.email_status, "not_checked")
        self.assertEqual(
            found.field_provenance["email"].evidence_url,
            "https://published.test/contact",
        )
        self.assertEqual(session.businesses[1].email, "")
        self.assertIn("Deliverability was not checked", session.refinements[0].note)

    def test_public_social_plugin_keeps_profiles_and_source_evidence(self) -> None:
        observed_at = datetime(2026, 10, 11, tzinfo=timezone.utc)

        class Enricher:
            def enrich(self, business):
                from biz_intel.models import FieldProvenance

                evidence = FieldProvenance(
                    source="first_party_web",
                    evidence_url="https://practice.test/about",
                    observed_at=observed_at,
                    method="public_link",
                )
                return replace(
                    business,
                    linkedin="https://www.linkedin.com/company/practice",
                    instagram="https://www.instagram.com/practice",
                    field_provenance={
                        **business.field_provenance,
                        "linkedin": evidence,
                        "instagram": evidence,
                    },
                )

        session = ResearchSession(
            "Dentists",
            [Business(name="Practice", website="https://practice.test")],
        )
        ResearchRunner([PublicSocialPlugin(Enricher())]).refine(
            session,
            "Find LinkedIn and other social profiles",
            plugin="public-socials",
        )

        found = session.businesses[0]
        self.assertIn("linkedin.com/company/practice", found.linkedin)
        self.assertIn("instagram.com/practice", found.instagram)
        self.assertEqual(
            found.field_provenance["linkedin"].evidence_url,
            "https://practice.test/about",
        )
        self.assertIn("2 new first-party social links", session.refinements[0].note)

    def test_refinement_persists_per_site_crawl_failure_details(self) -> None:
        class Crawler:
            def crawl_with_outcome(self, website):
                return CrawlOutcome(website, "tls_error")

        session = ResearchSession(
            "Dentists",
            [Business(name="Broken TLS Practice", website="https://broken.test")],
        )
        ResearchRunner([OwnershipEvidencePlugin(Crawler())]).refine(
            session,
            "Check ownership",
            plugin="ownership-evidence",
        )

        with TemporaryDirectory() as directory:
            path = session.save(Path(directory) / "session.json")
            restored = ResearchSession.load(path)

        detail = restored.refinements[0].details[0]
        self.assertEqual(detail["business"], "Broken TLS Practice")
        self.assertEqual(detail["website"], "https://broken.test")
        self.assertEqual(detail["status"], "tls_error")
        self.assertEqual(detail["pages_read"], 0)
        self.assertIn("1 tls_error", restored.refinements[0].note)

    def test_longevity_plugin_uses_explicit_business_wording_not_npi_age(self) -> None:
        class Crawler:
            def crawl_with_outcome(self, website):
                pages = {
                    "https://founded.test": "<p>Our practice was established in 2008.</p>",
                    "https://opened.test": "<p>She opened her office in 1993.</p>",
                    "https://serving.test": "<p>Serving local families for over 12 years.</p>",
                    "https://experience.test": "<p>Our dentist has 20 years of experience.</p>",
                }
                return CrawlOutcome(
                    website,
                    "success",
                    ((website + "/about", pages[website]),),
                )

        session = ResearchSession(
            "Dentists",
            [
                Business(name="Founded", website="https://founded.test"),
                Business(name="Opened", website="https://opened.test"),
                Business(name="Serving", website="https://serving.test"),
                Business(name="Experience", website="https://experience.test"),
                Business(name="NPI only", source_ids={"npi": "1234567890"}),
            ],
        )
        ResearchRunner([LongevityEvidencePlugin(Crawler())]).refine(
            session,
            "Which have been open 10+ years?",
            plugin="longevity-evidence",
        )

        self.assertEqual(
            session.businesses[0].claims[0].value,
            datetime.now(timezone.utc).year - 2008,
        )
        self.assertEqual(
            session.businesses[1].claims[0].value,
            datetime.now(timezone.utc).year - 1993,
        )
        self.assertEqual(session.businesses[2].claims[0].value, 12)
        self.assertEqual(session.businesses[3].claims, ())
        self.assertEqual(session.businesses[4].claims, ())
        self.assertIn("3 have evidence for at least 10 years", session.refinements[0].note)
        self.assertIn("NPI age was not treated as business age", session.refinements[0].note)

    def test_operational_status_records_only_explicit_first_party_closure(self) -> None:
        class Crawler:
            def crawl_with_outcome(self, website):
                pages = {
                    "https://closed.test": (
                        "<p>After retirement, our office is officially closed.</p>"
                    ),
                    "https://live.test": "<p>Welcome to our dental office.</p>",
                }
                return CrawlOutcome(
                    website,
                    "success",
                    ((website, pages[website]),),
                )

        closed = Business(name="Closed", website="https://closed.test")
        unknown = Business(name="Live Site", website="https://live.test")
        session = ResearchSession("Dentists", [closed, unknown])

        ResearchRunner([OperationalStatusEvidencePlugin(Crawler())]).refine(
            session,
            "Which practices are closed or retired?",
            plugin="operational-status-evidence",
        )

        self.assertEqual(closed.claims[0].key, "business.operational_status")
        self.assertEqual(closed.claims[0].value, "closed")
        self.assertEqual(unknown.claims, ())
        self.assertIn("lack of closure wording was not treated", session.refinements[0].note)


if __name__ == "__main__":
    unittest.main()
