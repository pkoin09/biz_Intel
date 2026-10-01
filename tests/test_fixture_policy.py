"""Offline fixture safety tests."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest

from biz_intel.core.fixture_policy import (
    FixtureManifestEntry,
    FixturePolicyError,
    load_fixture_manifest,
    validate_offline_fixture,
)
from biz_intel.core.source_policy import (
    EXPERIMENTAL_OR_DISALLOWED_POLICY,
    FixtureBehavior,
    SourcePolicy,
)


_ROOT = Path(__file__).parent / "fixtures"


class FixturePolicyTests(unittest.TestCase):
    def test_versioned_synthetic_fixtures_are_valid_offline(self) -> None:
        entries = load_fixture_manifest(_ROOT / "manifest.json")

        paths = [
            validate_offline_fixture(entry, EXPERIMENTAL_OR_DISALLOWED_POLICY, _ROOT)
            for entry in entries
        ]

        self.assertEqual([path.name for path in paths], [
            "apify_google_maps_example.json",
            "apify_yelp_headply_example.json",
        ])

    def test_sanitized_only_rejects_real_contact_claim(self) -> None:
        entry = load_fixture_manifest(_ROOT / "manifest.json")[0]

        with self.assertRaisesRegex(FixturePolicyError, "no real contact data"):
            validate_offline_fixture(
                replace(entry, contains_real_contact_data=True),
                EXPERIMENTAL_OR_DISALLOWED_POLICY,
                _ROOT,
            )

    def test_prohibited_policy_rejects_even_synthetic_fixture(self) -> None:
        entry = load_fixture_manifest(_ROOT / "manifest.json")[0]
        prohibited = replace(
            EXPERIMENTAL_OR_DISALLOWED_POLICY,
            fixture_behavior=FixtureBehavior.PROHIBITED,
        )

        with self.assertRaisesRegex(FixturePolicyError, "prohibited"):
            validate_offline_fixture(entry, prohibited, _ROOT)

    def test_rejects_tampered_fixture_content(self) -> None:
        entry = load_fixture_manifest(_ROOT / "manifest.json")[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / entry.path
            path.write_text('{"url": "https://maps.example.test/changed"}')

            with self.assertRaisesRegex(FixturePolicyError, "integrity hash"):
                validate_offline_fixture(entry, EXPERIMENTAL_OR_DISALLOWED_POLICY, root)

    def test_rejects_non_reserved_url_when_hash_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "unsafe.json"
            raw = b'{"url": "https://provider.example.com/live"}'
            path.write_bytes(raw)
            entry = FixtureManifestEntry(
                source="test-source",
                path=path.name,
                sha256=hashlib.sha256(raw).hexdigest(),
                sanitization="synthetic",
                contains_real_contact_data=False,
            )

            with self.assertRaisesRegex(FixturePolicyError, "example.test"):
                validate_offline_fixture(entry, EXPERIMENTAL_OR_DISALLOWED_POLICY, root)


if __name__ == "__main__":
    unittest.main()
