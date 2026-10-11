"""Focused tests for the public command-line job workflow."""

from __future__ import annotations

from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest

from biz_intel import cli
from biz_intel.models import Business
from biz_intel.research import ResearchSession


class CliTests(unittest.TestCase):
    @patch("biz_intel.cli.JobRunner")
    @patch("biz_intel.cli.load_job", return_value=object())
    @patch("main.register_sources")
    def test_preflight_prints_json_without_running_a_job(
        self, register_sources: Mock, load_job: Mock, runner_class: Mock
    ) -> None:
        runner_class.return_value.preflight.return_value.to_dict.return_value = {"task_count": 1}

        with patch("builtins.print") as print_mock:
            exit_code = cli.main(["preflight", "jobs/example.yaml", "--quiet"])

        self.assertEqual(exit_code, 0)
        register_sources.assert_called_once_with()
        runner_class.assert_called_once_with(progress_reporter=None)
        runner_class.return_value.run.assert_not_called()
        self.assertIn('"task_count": 1', print_mock.call_args.args[0])

    @patch("biz_intel.cli.JobRunner")
    @patch("biz_intel.cli.load_job", return_value=object())
    @patch("main.register_sources")
    def test_resume_passes_checkpoint_to_runner(
        self, register_sources: Mock, load_job: Mock, runner_class: Mock
    ) -> None:
        runner_class.return_value.run.return_value.summary.return_value = "done"

        exit_code = cli.main(["resume", "jobs/example.yaml", "runs/run.checkpoint.json", "--quiet"])

        self.assertEqual(exit_code, 0)
        runner_class.return_value.run.assert_called_once_with(
            load_job.return_value,
            resume_from="runs/run.checkpoint.json",
        )

    @patch("biz_intel.cli.JobRunner")
    @patch("biz_intel.cli.load_job", return_value=object())
    @patch("main.register_sources")
    def test_research_runs_existing_job_and_saves_session(
        self, register_sources: Mock, load_job: Mock, runner_class: Mock
    ) -> None:
        result = runner_class.return_value.run.return_value
        result.run_id = "dentists-test"
        result.summary.return_value = "done"

        def capture_records(_job: object, *, record_consumer: object) -> object:
            record_consumer([Business(name="Neighborhood Dental")])
            return result

        runner_class.return_value.run.side_effect = capture_records

        with TemporaryDirectory() as directory:
            destination = Path(directory) / "research.json"
            exit_code = cli.main(
                [
                    "research",
                    "jobs/dentists.yaml",
                    "Dentists in San Jose",
                    "--session",
                    str(destination),
                    "--quiet",
                ]
            )
            restored = ResearchSession.load(destination)

        self.assertEqual(exit_code, 0)
        self.assertEqual(restored.request, "Dentists in San Jose")
        self.assertEqual(restored.businesses[0].name, "Neighborhood Dental")
        runner_class.return_value.run.assert_called_once()

    @patch("biz_intel.research.plugins.httpx.post")
    def test_refine_routes_plain_language_medi_cal_request(self, post: Mock) -> None:
        response = post.return_value
        response.json.return_value = {
            "features": [{"attributes": {"Provider_NPI": "1234567890"}}]
        }
        session = ResearchSession(
            "Dentists in San Jose",
            [Business(name="Example Dental", source_ids={"npi": "1234567890"})],
        )

        with TemporaryDirectory() as directory:
            destination = session.save(Path(directory) / "research.json")
            exit_code = cli.main(
                ["refine", str(destination), "Which dentists accept Medi-Cal?"]
            )
            restored = ResearchSession.load(destination)

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            restored.businesses[0].claims[0].key,
            "program.medi_cal_dental_ffs_enrolled",
        )
        self.assertEqual(restored.refinements[0].plugin, "medi-cal-dental-enrollment")
        response.raise_for_status.assert_called_once_with()

    @patch("biz_intel.research.plugins.FirstPartyWebsiteCrawler.crawl")
    def test_refine_routes_family_owned_request(self, crawl: Mock) -> None:
        crawl.return_value = [
            ("https://example.test/about", "<p>We are a locally owned practice.</p>")
        ]
        session = ResearchSession(
            "Dentists in San Jose",
            [Business(name="Example", website="https://example.test")],
        )

        with TemporaryDirectory() as directory:
            destination = session.save(Path(directory) / "research.json")
            exit_code = cli.main(
                ["refine", str(destination), "Find family-owned practices"]
            )
            restored = ResearchSession.load(destination)

        self.assertEqual(exit_code, 0)
        self.assertEqual(restored.refinements[0].plugin, "ownership-evidence")
        self.assertEqual(restored.businesses[0].claims[0].value, "likely_independent")

    @patch("biz_intel.research.plugins.SocialEnricher.enrich")
    def test_refine_routes_public_email_request(self, enrich: Mock) -> None:
        from biz_intel.models import FieldProvenance
        from datetime import datetime, timezone

        enrich.return_value = Business(
            name="Example",
            website="https://example.test",
            email="hello@example.test",
            email_status="not_checked",
            field_provenance={
                "email": FieldProvenance(
                    source="first_party_web",
                    evidence_url="https://example.test/contact",
                    observed_at=datetime(2026, 10, 11, tzinfo=timezone.utc),
                    method="public_link",
                )
            },
        )
        session = ResearchSession(
            "Dentists in San Jose",
            [Business(name="Example", website="https://example.test")],
        )

        with TemporaryDirectory() as directory:
            destination = session.save(Path(directory) / "research.json")
            exit_code = cli.main(
                ["refine", str(destination), "Find their public email addresses"]
            )
            restored = ResearchSession.load(destination)

        self.assertEqual(exit_code, 0)
        self.assertEqual(restored.refinements[0].plugin, "public-email")
        self.assertEqual(restored.businesses[0].email, "hello@example.test")
        self.assertEqual(restored.businesses[0].email_status, "not_checked")

    @patch("biz_intel.research.plugins.SocialEnricher.enrich")
    def test_refine_routes_social_request(self, enrich: Mock) -> None:
        from biz_intel.models import FieldProvenance
        from datetime import datetime, timezone

        evidence = FieldProvenance(
            source="first_party_web",
            evidence_url="https://example.test/about",
            observed_at=datetime(2026, 10, 11, tzinfo=timezone.utc),
            method="public_link",
        )
        enrich.return_value = Business(
            name="Example",
            website="https://example.test",
            linkedin="https://www.linkedin.com/company/example",
            field_provenance={"linkedin": evidence},
        )
        session = ResearchSession(
            "Dentists in San Jose",
            [Business(name="Example", website="https://example.test")],
        )

        with TemporaryDirectory() as directory:
            destination = session.save(Path(directory) / "research.json")
            exit_code = cli.main(
                ["refine", str(destination), "Find LinkedIn and other socials"]
            )
            restored = ResearchSession.load(destination)

        self.assertEqual(exit_code, 0)
        self.assertEqual(restored.refinements[0].plugin, "public-socials")
        self.assertIn("linkedin.com/company/example", restored.businesses[0].linkedin)

    def test_refine_rejects_an_unsupported_request_without_guessing(self) -> None:
        session = ResearchSession("Dentists in San Jose", [Business(name="Example")])

        with TemporaryDirectory() as directory:
            destination = session.save(Path(directory) / "research.json")
            with self.assertRaisesRegex(ValueError, "currently supports"):
                cli.main(["refine", str(destination), "Find open appointments"])


if __name__ == "__main__":
    unittest.main()
