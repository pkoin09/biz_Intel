"""Focused tests for the public command-line job workflow."""

from __future__ import annotations

import os
import json
from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest

from biz_intel import cli
from biz_intel.models import Business
from biz_intel.research import ResearchSession
from biz_intel.sources.overture import PreparedSnapshot


class CliTests(unittest.TestCase):
    def test_display_path_does_not_expose_external_absolute_directory(self) -> None:
        external = Path("/private/example/research.json")

        self.assertEqual(cli._display_path(external), "research.json")

    def test_display_path_keeps_project_relative_context(self) -> None:
        project_file = Path.cwd() / "runs" / "research" / "dentists.json"

        self.assertEqual(
            cli._display_path(project_file),
            "runs/research/dentists.json",
        )

    @patch("biz_intel.cli.prepare_overture_snapshot")
    def test_overture_snapshot_command_passes_explicit_reviewed_scope(
        self, prepare: Mock
    ) -> None:
        prepare.return_value = PreparedSnapshot(
            Path("data/overture/dental.parquet"),
            Path("data/overture/dental.manifest.json"),
            12,
            "a" * 64,
        )

        exit_code = cli.main(
            [
                "overture-snapshot",
                "data/overture/raw/*.parquet",
                "data/overture/dental.parquet",
                "--release",
                "2026-09-23.1",
                "--retrieved-at",
                "2026-10-20T12:00:00-07:00",
                "--source-reference",
                "https://stac.overturemaps.org/2026-09-23.1/catalog.json",
                "--bbox",
                "-122.18",
                "37.17",
                "-121.75",
                "37.55",
                "--geography",
                "San Jose-area dental candidate rectangle",
                "--license",
                "Reviewed multi-license assertion",
                "--attribution",
                "Overture Maps Foundation",
                "--locality",
                "San Jose",
            ]
        )

        self.assertEqual(exit_code, 0)
        prepare.assert_called_once_with(
            "data/overture/raw/*.parquet",
            "data/overture/dental.parquet",
            release="2026-09-23.1",
            retrieved_at="2026-10-20T12:00:00-07:00",
            source_reference="https://stac.overturemaps.org/2026-09-23.1/catalog.json",
            bbox=[-122.18, 37.17, -121.75, 37.55],
            geography_label="San Jose-area dental candidate rectangle",
            license="Reviewed multi-license assertion",
            attribution="Overture Maps Foundation",
            manifest_path=None,
            localities=["San Jose"],
        )

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

    @patch("biz_intel.cli.config")
    def test_research_export_can_select_latest_session(self, cli_config: Mock) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cli_config.RUNS_PATH = root
            research = root / "research"
            research.mkdir()
            ResearchSession(
                "Dentists",
                [Business(name="Practice", phone="4085550100")],
            ).save(research / "dentists.json")
            destination = root / "dentists.json"

            exit_code = cli.main(
                ["research-export", "--latest", str(destination)]
            )
            exported = json.loads(destination.read_text())

        self.assertEqual(exit_code, 0)
        self.assertEqual(exported[0]["name"], "Practice")
        self.assertEqual(exported[0]["phone"], "4085550100")

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

    @patch("biz_intel.research.plugins.FirstPartyWebsiteCrawler.crawl_with_outcome")
    def test_refine_routes_family_owned_request(self, crawl: Mock) -> None:
        from biz_intel.services.enrichment import CrawlOutcome

        crawl.return_value = CrawlOutcome(
            "https://example.test",
            "success",
            (("https://example.test/about", "<p>We are a locally owned practice.</p>"),),
        )
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

    @patch("biz_intel.research.plugins.FirstPartyWebsiteCrawler.crawl_with_outcome")
    def test_refine_routes_business_longevity_request(self, crawl: Mock) -> None:
        from datetime import datetime, timezone
        from biz_intel.services.enrichment import CrawlOutcome

        crawl.return_value = CrawlOutcome(
            "https://example.test",
            "success",
            (("https://example.test/about", "<p>Established in 2008.</p>"),),
        )
        session = ResearchSession(
            "Dentists in San Jose",
            [Business(name="Example", website="https://example.test")],
        )

        with TemporaryDirectory() as directory:
            destination = session.save(Path(directory) / "research.json")
            exit_code = cli.main(
                [str(value) for value in ("refine", destination, "Open 10+ years?")]
            )
            restored = ResearchSession.load(destination)

        self.assertEqual(exit_code, 0)
        self.assertEqual(restored.refinements[0].plugin, "longevity-evidence")
        self.assertEqual(
            restored.businesses[0].claims[0].value,
            datetime.now(timezone.utc).year - 2008,
        )

    @patch("biz_intel.research.plugins.FirstPartyWebsiteCrawler.crawl_with_outcome")
    def test_refine_routes_explicit_closure_request(self, crawl: Mock) -> None:
        from biz_intel.services.enrichment import CrawlOutcome

        crawl.return_value = CrawlOutcome(
            "https://example.test",
            "success",
            (("https://example.test", "<p>Our office is officially closed.</p>"),),
        )
        session = ResearchSession(
            "Dentists in San Jose",
            [Business(name="Example", website="https://example.test")],
        )

        with TemporaryDirectory() as directory:
            destination = session.save(Path(directory) / "research.json")
            exit_code = cli.main(
                ["refine", str(destination), "Which practices are closed?"]
            )
            restored = ResearchSession.load(destination)

        self.assertEqual(exit_code, 0)
        self.assertEqual(restored.refinements[0].plugin, "operational-status-evidence")
        self.assertEqual(restored.businesses[0].claims[0].value, "closed")

    @patch("biz_intel.research.plugins.FirstPartyWebsiteCrawler.crawl_with_outcome")
    @patch("biz_intel.research.plugins.httpx.post")
    def test_refine_applies_every_plugin_in_a_compound_request(
        self, post: Mock, crawl: Mock
    ) -> None:
        from biz_intel.services.enrichment import CrawlOutcome

        post.return_value.json.return_value = {
            "features": [{"attributes": {"Provider_NPI": "1234567890"}}]
        }
        crawl.return_value = CrawlOutcome(
            "https://example.test",
            "success",
            (
                (
                    "https://example.test/about",
                    "<p>A family-owned practice, established in 2008.</p>",
                ),
            ),
        )
        session = ResearchSession(
            "Dentists",
            [
                Business(
                    name="Example",
                    website="https://example.test",
                    source_ids={"npi": "1234567890"},
                )
            ],
        )

        with TemporaryDirectory() as directory:
            destination = session.save(Path(directory) / "research.json")
            exit_code = cli.main(
                [
                    "refine",
                    str(destination),
                    "Which accept Medi-Cal, are family-owned, and open 10+ years?",
                ]
            )
            restored = ResearchSession.load(destination)

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            [step.plugin for step in restored.refinements],
            [
                "medi-cal-dental-enrollment",
                "ownership-evidence",
                "longevity-evidence",
            ],
        )
        self.assertEqual(
            {claim.key for claim in restored.businesses[0].claims},
            {
                "program.medi_cal_dental_ffs_enrolled",
                "ownership.independence_assessment",
                "business.longevity.minimum_years",
            },
        )

    @patch("biz_intel.research.plugins.FirstPartyWebsiteCrawler.crawl_with_outcome")
    def test_refine_routes_not_a_corporation_to_ownership_evidence(
        self, crawl: Mock
    ) -> None:
        from biz_intel.services.enrichment import CrawlOutcome

        crawl.return_value = CrawlOutcome(
            "https://example.test",
            "success",
            (("https://example.test/about", "<p>A locally owned practice.</p>"),),
        )
        session = ResearchSession(
            "Dentists",
            [Business(name="Example", website="https://example.test")],
        )

        with TemporaryDirectory() as directory:
            destination = session.save(Path(directory) / "research.json")
            exit_code = cli.main(
                ["refine", str(destination), "Which are not a corporation?"]
            )
            restored = ResearchSession.load(destination)

        self.assertEqual(exit_code, 0)
        self.assertEqual(restored.refinements[-1].plugin, "ownership-evidence")
        self.assertEqual(
            restored.businesses[0].claims[0].value,
            "likely_independent",
        )

    @patch("biz_intel.services.enrichment.social.httpx.get")
    def test_compound_first_party_refinement_reads_each_site_once(
        self, get: Mock
    ) -> None:
        def fetch(url: str, **kwargs: object) -> Mock:
            current = Mock()
            current.url = url
            current.raise_for_status.return_value = None
            current.text = (
                "User-agent: *\nAllow: /\n"
                if url.endswith("robots.txt")
                else (
                    '<p>A family-owned practice established in 2008.</p>'
                    '<a href="mailto:hello@example.test">Email</a>'
                    '<a href="https://instagram.com/example">Instagram</a>'
                )
            )
            return current

        get.side_effect = fetch
        session = ResearchSession(
            "Dentists",
            [Business(name="Example", website="https://example.test")],
        )

        with TemporaryDirectory() as directory:
            destination = session.save(Path(directory) / "research.json")
            exit_code = cli.main(
                [
                    "refine",
                    str(destination),
                    "Which are family-owned, open 10+ years, with email and Instagram?",
                ]
            )
            restored = ResearchSession.load(destination)

        self.assertEqual(exit_code, 0)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(restored.businesses[0].email, "hello@example.test")
        self.assertEqual(
            restored.businesses[0].instagram,
            "https://www.instagram.com/example",
        )

    @patch("biz_intel.research.plugins.SocialEnricher.enrich_with_outcome")
    def test_refine_routes_public_email_request(self, enrich: Mock) -> None:
        from biz_intel.models import FieldProvenance
        from biz_intel.services.enrichment import CrawlOutcome, SocialEnrichmentResult
        from datetime import datetime, timezone

        enrich.return_value = SocialEnrichmentResult(
            Business(
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
            ),
            CrawlOutcome("https://example.test", "success"),
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

    @patch("biz_intel.research.plugins.SocialEnricher.enrich_with_outcome")
    def test_refine_routes_social_request(self, enrich: Mock) -> None:
        from biz_intel.models import FieldProvenance
        from biz_intel.services.enrichment import CrawlOutcome, SocialEnrichmentResult
        from datetime import datetime, timezone

        evidence = FieldProvenance(
            source="first_party_web",
            evidence_url="https://example.test/about",
            observed_at=datetime(2026, 10, 11, tzinfo=timezone.utc),
            method="public_link",
        )
        enrich.return_value = SocialEnrichmentResult(
            Business(
                name="Example",
                website="https://example.test",
                linkedin="https://www.linkedin.com/company/example",
                field_provenance={"linkedin": evidence},
            ),
            CrawlOutcome("https://example.test", "success"),
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

    @patch("biz_intel.cli.config")
    @patch("biz_intel.research.plugins.httpx.post")
    def test_refine_can_select_the_third_latest_session(
        self, post: Mock, cli_config: Mock
    ) -> None:
        post.return_value.json.return_value = {"features": []}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cli_config.RUNS_PATH = root
            research = root / "research"
            research.mkdir()
            for position in range(1, 4):
                path = ResearchSession(
                    f"Session {position}",
                    [Business(name=str(position), source_ids={"npi": str(position) * 10})],
                ).save(research / f"session-{position}.json")
                os.utime(path, (position * 100, position * 100))

            exit_code = cli.main(
                ["refine", "--latest", "3", "Which accept Medi-Cal?"]
            )

            restored = ResearchSession.load(research / "session-1.json")

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(restored.refinements), 1)

    @patch("biz_intel.cli.config")
    def test_sessions_lists_saved_sessions(self, cli_config: Mock) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cli_config.RUNS_PATH = root
            research = root / "research"
            research.mkdir()
            ResearchSession("Dentists in San Jose", [Business(name="Example")]).save(
                research / "dentists.json"
            )

            with patch("builtins.print") as print_mock:
                exit_code = cli.main(["sessions"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Dentists in San Jose", print_mock.call_args.args[0])

    @patch("biz_intel.cli.config")
    @patch("biz_intel.research.plugins.httpx.post")
    def test_refine_accepts_bare_latest_and_a_copied_session_name(
        self, post: Mock, cli_config: Mock
    ) -> None:
        post.return_value.json.return_value = {"features": []}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cli_config.RUNS_PATH = root
            research = root / "research"
            research.mkdir()
            destination = ResearchSession(
                "Dentists", [Business(name="Example", source_ids={"npi": "1234567890"})]
            ).save(research / "dentists.json")

            self.assertEqual(
                cli.main(["refine", "--latest", "Which accept Medi-Cal?"]), 0
            )
            self.assertEqual(
                cli.main(["refine", "dentists", "Which accept Medi-Cal?"]), 0
            )

            restored = ResearchSession.load(destination)

        self.assertEqual(len(restored.refinements), 2)

    @patch("biz_intel.cli.config")
    def test_view_latest_is_read_only_and_shows_names_and_phones(
        self, cli_config: Mock
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cli_config.RUNS_PATH = root
            research = root / "research"
            research.mkdir()
            destination = ResearchSession(
                "Dentists",
                [Business(name="Neighborhood Dental", phone="408-555-0100")],
            ).save(research / "dentists.json")
            before = destination.read_text()

            with patch("builtins.print") as print_mock:
                exit_code = cli.main(["view", "--latest"])

            after = destination.read_text()

        self.assertEqual(exit_code, 0)
        self.assertEqual(before, after)
        output = json.loads(print_mock.call_args.args[0])
        self.assertEqual(
            output,
            [{"name": "Neighborhood Dental", "phone": "408-555-0100"}],
        )

    @patch("biz_intel.cli.config")
    def test_view_numeric_shorthand_limits_a_large_preview(self, cli_config: Mock) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cli_config.RUNS_PATH = root
            research = root / "research"
            research.mkdir()
            ResearchSession(
                "Large list",
                [Business(name=f"Business {number}") for number in range(25)],
            ).save(research / "large.json")

            with patch("builtins.print") as print_mock:
                exit_code = cli.main(["view", "-10"])

        self.assertEqual(exit_code, 0)
        output = json.loads(print_mock.call_args.args[0])
        self.assertEqual(len(output), 10)
        self.assertEqual(output[-1], {"name": "Business 9", "phone": None})

    @patch("biz_intel.cli.config")
    def test_view_can_select_safe_contact_and_social_fields(self, cli_config: Mock) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cli_config.RUNS_PATH = root
            research = root / "research"
            research.mkdir()
            ResearchSession(
                "Dentists",
                [
                    Business(
                        name="Practice",
                        website="https://practice.test",
                        instagram="https://instagram.com/practice",
                    )
                ],
            ).save(research / "dentists.json")

            with patch("builtins.print") as print_mock:
                exit_code = cli.main(
                    [
                        "view",
                        "--with",
                        "instagram",
                        "--fields",
                        "name,website,instagram",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            json.loads(print_mock.call_args.args[0]),
            [
                {
                    "name": "Practice",
                    "website": "https://practice.test",
                    "instagram": "https://instagram.com/practice",
                }
            ],
        )

    @patch("biz_intel.cli.config")
    def test_view_summary_reports_coverage_without_changing_session(
        self, cli_config: Mock
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cli_config.RUNS_PATH = root
            research = root / "research"
            research.mkdir()
            destination = ResearchSession(
                "Dentists",
                [
                    Business(name="One", phone="4085550100", website="https://one.test"),
                    Business(name="Two"),
                ],
            ).save(research / "dentists.json")
            before = destination.read_text()

            with patch("builtins.print") as print_mock:
                exit_code = cli.main(["view", "--summary"])

            after = destination.read_text()

        self.assertEqual(exit_code, 0)
        self.assertEqual(before, after)
        summary = json.loads(print_mock.call_args.args[0])
        self.assertEqual(summary["total_records"], 2)
        self.assertEqual(summary["latest_matches"], 2)
        self.assertEqual(summary["with_phone"], 1)
        self.assertEqual(summary["with_website"], 1)

    @patch("biz_intel.cli.config")
    def test_view_rejects_internal_fields(self, cli_config: Mock) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cli_config.RUNS_PATH = root
            research = root / "research"
            research.mkdir()
            ResearchSession("Dentists", [Business(name="Practice")]).save(
                research / "dentists.json"
            )

            with self.assertRaisesRegex(ValueError, "Unsupported view fields"):
                cli.main(["view", "--fields", "name,raw_data"])

    @patch("biz_intel.cli.config")
    def test_view_audit_shows_latest_refinement_details_without_changes(
        self, cli_config: Mock
    ) -> None:
        from biz_intel.research import RefinementStep
        from datetime import datetime, timezone

        with TemporaryDirectory() as directory:
            root = Path(directory)
            cli_config.RUNS_PATH = root
            research = root / "research"
            research.mkdir()
            session = ResearchSession("Dentists", [Business(name="Example")])
            session.refinements.append(
                RefinementStep(
                    instruction="Check ownership",
                    plugin="ownership-evidence",
                    before_count=1,
                    after_count=1,
                    applied_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
                    note="Crawl outcomes: 1 tls_error.",
                    details=(
                        {
                            "business": "Example",
                            "website": "https://example.test",
                            "status": "tls_error",
                            "pages_read": 0,
                        },
                    ),
                )
            )
            session.refinements.append(
                RefinementStep(
                    instruction="Find socials",
                    plugin="public-socials",
                    before_count=1,
                    after_count=1,
                    applied_at=datetime(2026, 10, 20, 1, tzinfo=timezone.utc),
                    note="Crawl outcomes: 1 success.",
                )
            )
            destination = session.save(research / "dentists.json")
            before = destination.read_text()

            with patch("builtins.print") as print_mock:
                exit_code = cli.main(["view", "--audit", "2"])

            after = destination.read_text()

        self.assertEqual(exit_code, 0)
        self.assertEqual(before, after)
        output = json.loads(print_mock.call_args.args[0])
        self.assertEqual(output["plugin"], "ownership-evidence")
        self.assertEqual(output["details"][0]["status"], "tls_error")

    @patch("biz_intel.cli.config")
    def test_view_audit_groups_plugins_from_the_latest_instruction(
        self, cli_config: Mock
    ) -> None:
        from biz_intel.research import RefinementStep
        from datetime import datetime, timezone

        with TemporaryDirectory() as directory:
            root = Path(directory)
            cli_config.RUNS_PATH = root
            research = root / "research"
            research.mkdir()
            session = ResearchSession("Dentists", [Business(name="Example")])
            for plugin in ("ownership-evidence", "longevity-evidence"):
                session.refinements.append(
                    RefinementStep(
                        instruction="Which are independent and open 10+ years?",
                        plugin=plugin,
                        before_count=1,
                        after_count=1,
                        applied_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
                        note=f"{plugin} complete",
                    )
                )
            session.save(research / "dentists.json")

            with patch("builtins.print") as print_mock:
                exit_code = cli.main(["view", "--audit"])

        self.assertEqual(exit_code, 0)
        output = json.loads(print_mock.call_args.args[0])
        self.assertEqual(
            [item["plugin"] for item in output["plugins"]],
            ["ownership-evidence", "longevity-evidence"],
        )

    @patch("biz_intel.cli.config")
    def test_compose_can_select_latest_session(self, cli_config: Mock) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cli_config.RUNS_PATH = root
            research = root / "research"
            research.mkdir()
            older = ResearchSession(
                "Older",
                [Business(name="Old", phone="4085550100", source="nppes")],
            ).save(research / "older.json")
            latest = ResearchSession(
                "Latest",
                [
                    Business(
                        name="New",
                        address="1 Main St",
                        city="San Jose",
                        state="CA",
                        phone="4085550199",
                        source="nppes",
                    )
                ],
            ).save(research / "latest.json")
            os.utime(older, (100, 100))
            os.utime(latest, (200, 200))
            candidates = root / "candidates.json"
            candidates.write_text(
                json.dumps(
                    [
                        {
                            "name": "New",
                            "address": "1 Main St",
                            "city": "San Jose",
                            "state": "CA",
                            "phone": "408-555-0199",
                            "website": "https://new.example",
                            "source": "directory",
                        }
                    ]
                )
            )

            with patch("builtins.print") as print_mock:
                exit_code = cli.main(["compose", "--latest", str(candidates)])

            restored_latest = ResearchSession.load(latest)
            restored_older = ResearchSession.load(older)

        self.assertEqual(exit_code, 0)
        self.assertEqual(restored_latest.businesses[0].website, "https://new.example")
        self.assertEqual(len(restored_latest.compositions), 1)
        self.assertEqual(restored_older.businesses[0].website, "")
        self.assertEqual(len(restored_older.compositions), 0)
        self.assertIn("1 websites attached", print_mock.call_args.args[0])

    @patch("biz_intel.cli.config")
    def test_compose_applies_multiple_files_and_saves_once(self, cli_config: Mock) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cli_config.RUNS_PATH = root
            research = root / "research"
            research.mkdir()
            destination = ResearchSession(
                "Dentists",
                [
                    Business(name="One", source="nppes", source_ids={"npi": "1"}),
                    Business(name="Two", source="nppes", source_ids={"npi": "2"}),
                ],
            ).save(research / "dentists.json")
            files = []
            for number in (1, 2):
                path = root / f"candidate-{number}.json"
                path.write_text(
                    json.dumps(
                        [
                            {
                                "name": "One" if number == 1 else "Two",
                                "website": f"https://{number}.example",
                                "source": "reviewed",
                                "source_ids": {"npi": str(number)},
                            }
                        ]
                    )
                )
                files.append(str(path))

            with patch("builtins.print") as print_mock:
                exit_code = cli.main(["compose", "--latest", *files])

            restored = ResearchSession.load(destination)

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            [business.website for business in restored.businesses],
            ["https://1.example", "https://2.example"],
        )
        self.assertEqual(len(restored.compositions), 2)
        self.assertIn("2 websites attached from 2 file(s)", print_mock.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
