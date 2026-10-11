"""Offline contract tests for the policy-gated LinkedIn Apify adapter."""

from __future__ import annotations

import unittest

from biz_intel.core.source_name import SourceName
from biz_intel.core.source_task import SourceTask
from biz_intel.sources.linkedin import LinkedInApifySource


class LinkedInApifySourceTests(unittest.TestCase):
    def _source(self, urls: list[str], *, limit: int | None = None) -> LinkedInApifySource:
        return LinkedInApifySource(
            SourceTask(
                source=SourceName.LINKEDIN_APIFY,
                limit=limit,
                options={"profile_urls": urls},
            )
        )

    def test_accepts_only_a_bounded_explicit_public_url_list(self) -> None:
        source = self._source(
            ["https://www.linkedin.com/in/example", "https://www.linkedin.com/in/second"],
            limit=1,
        )

        self.assertEqual(
            source._build_actor_input(),
            {"profileUrls": ["https://www.linkedin.com/in/example"]},
        )

        with self.assertRaisesRegex(ValueError, "profile_urls"):
            self._source([])._build_actor_input()
        with self.assertRaisesRegex(ValueError, "public"):
            self._source(["https://www.linkedin.com/company/example"])._build_actor_input()

    def test_maps_only_profile_url_name_and_headline(self) -> None:
        business = self._source(["https://www.linkedin.com/in/example"])._to_business(
            {
                "profileUrl": "https://www.linkedin.com/in/example",
                "fullName": "Example Person",
                "headline": "Owner at Example Co.",
                "email": "must-not-be-copied@example.test",
                "phone": "+15551212",
                "experience": [{"company": "Private"}],
            }
        )

        assert business is not None
        self.assertEqual(business.name, "Example Person")
        self.assertEqual(business.linkedin, "https://www.linkedin.com/in/example")
        self.assertEqual(business.category, "Owner at Example Co.")
        self.assertEqual(business.email, "")
        self.assertEqual(business.phone, "")
        self.assertNotIn("email", business.raw_data or {})
        self.assertEqual(business.claims[0].key, "social.linkedin.profile_url")

    def test_skips_records_without_name_or_public_profile_url(self) -> None:
        source = self._source(["https://www.linkedin.com/in/example"])
        self.assertIsNone(source._to_business({"fullName": "No URL"}))
        self.assertIsNone(source._to_business({"profileUrl": "https://example.test/a"}))


if __name__ == "__main__":
    unittest.main()
