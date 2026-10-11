"""Tests for continuing research from saved result files."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from biz_intel import cli
from biz_intel.research import ResearchSession, import_research_session


class ResearchImportTests(unittest.TestCase):
    def test_imports_csv_and_recovers_npi_lineage_from_registry_url(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "dentists.csv"
            source.write_text(
                "name,city,state,phone,source_url\n"
                "Neighborhood Dental,San Jose,CA,4085550100,"
                "https://npiregistry.cms.hhs.gov/provider-view/1234567890\n"
            )

            session = import_research_session(source, "Dentists in San Jose")

        business = session.businesses[0]
        self.assertEqual(business.name, "Neighborhood Dental")
        self.assertEqual(business.source, "nppes")
        self.assertEqual(business.discovery_sources, ("nppes",))
        self.assertEqual(business.source_ids, {"npi": "1234567890"})

    def test_cli_saves_import_as_a_reusable_session(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "businesses.csv"
            source.write_text("name,city,state\nExample Vet,Oakland,CA\n")
            destination = Path(directory) / "session.json"

            exit_code = cli.main(
                [
                    "research-import",
                    str(source),
                    "Bay Area veterinarians",
                    "--session",
                    str(destination),
                ]
            )
            restored = ResearchSession.load(destination)

        self.assertEqual(exit_code, 0)
        self.assertEqual(restored.request, "Bay Area veterinarians")
        self.assertEqual(restored.businesses[0].name, "Example Vet")


if __name__ == "__main__":
    unittest.main()
