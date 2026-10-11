"""Tests for the flat, usable projection of a research session."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from biz_intel import cli
from biz_intel.models import Business, Claim, FieldProvenance
from biz_intel.research import RESEARCH_COLUMNS, ResearchSession, export_research_session


class ResearchExportTests(unittest.TestCase):
    def test_csv_flattens_claims_and_combines_evidence_urls(self) -> None:
        observed_at = datetime(2026, 10, 11, tzinfo=timezone.utc)
        business = Business(
            name="Neighborhood Dental",
            email="hello@neighbor.test",
            email_status="not_checked",
            linkedin="https://linkedin.com/company/neighbor",
            source="overture",
            discovery_sources=("overture", "google"),
            source_url="https://directory.test/neighbor",
            field_provenance={
                "email": FieldProvenance(
                    source="first_party_web",
                    evidence_url="https://neighbor.test/contact",
                    observed_at=observed_at,
                    method="public_link",
                )
            },
            claims=(
                Claim(
                    key="ownership.independence_assessment",
                    value="likely_independent",
                    source="first-party-website",
                    source_record_id="neighbor.test",
                    evidence_url="https://neighbor.test/about",
                    observed_at=observed_at,
                ),
            ),
        )
        session = ResearchSession("Dentists", [business])

        with TemporaryDirectory() as directory:
            destination = export_research_session(
                session, Path(directory) / "results.csv"
            )
            with destination.open(newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))

        self.assertEqual(tuple(rows[0]), RESEARCH_COLUMNS)
        self.assertEqual(rows[0]["ownership_assessment"], "likely_independent")
        self.assertEqual(rows[0]["discovery_sources"], "overture | google")
        self.assertEqual(rows[0]["medi_cal_dental_enrolled"], "unknown")
        self.assertIn("https://neighbor.test/contact", rows[0]["evidence_urls"])
        self.assertIn("https://neighbor.test/about", rows[0]["evidence_urls"])

    def test_cli_exports_json_without_changing_session(self) -> None:
        session = ResearchSession("Dentists", [Business(name="Example")])
        with TemporaryDirectory() as directory:
            session_path = session.save(Path(directory) / "session.json")
            destination = Path(directory) / "results.json"

            exit_code = cli.main(
                ["research-export", str(session_path), str(destination)]
            )
            rows = json.loads(destination.read_text())
            restored = ResearchSession.load(session_path)

        self.assertEqual(exit_code, 0)
        self.assertEqual(rows[0]["ownership_assessment"], "unclear")
        self.assertEqual(len(restored.refinements), 0)

    def test_rejects_an_ambiguous_export_extension(self) -> None:
        with self.assertRaisesRegex(ValueError, "csv or .json"):
            export_research_session(
                ResearchSession("Dentists", []),
                "results.txt",
            )


if __name__ == "__main__":
    unittest.main()
