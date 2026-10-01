"""Tests for the Yellow Pages URL builder."""

from __future__ import annotations

import unittest

from biz_intel.sources.yellowpages.urls import build_search_url


class YellowPagesUrlTests(unittest.TestCase):
    """Protect the search-URL contract, including the pagination param."""

    def test_first_page_has_no_page_param(self) -> None:
        url = build_search_url("dentist", "San Jose, CA")

        self.assertEqual(
            url,
            "https://www.yellowpages.com/search?"
            "search_terms=dentist&geo_location_terms=San+Jose%2C+CA",
        )

    def test_explicit_page_one_omits_page_param(self) -> None:
        url = build_search_url("dentist", "San Jose, CA", page=1)

        self.assertNotIn("page=", url)

    def test_page_two_appends_page_param(self) -> None:
        url = build_search_url("dentist", "San Jose, CA", page=2)

        self.assertTrue(url.endswith("&page=2"))

    def test_encodes_query_and_location(self) -> None:
        url = build_search_url("dental clinic", "New York, NY", page=3)

        self.assertIn("search_terms=dental+clinic", url)
        self.assertIn("geo_location_terms=New+York%2C+NY", url)
        self.assertTrue(url.endswith("&page=3"))


if __name__ == "__main__":
    unittest.main()
