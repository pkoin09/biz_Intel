"""Tests for BaseBusinessSpider's pagination decision helper."""

from __future__ import annotations

import unittest

from biz_intel.core.base_spider import should_follow_next_page


class ShouldFollowNextPageTests(unittest.TestCase):
    """Protect the pagination stop conditions (pure logic, no browser)."""

    def test_follows_when_more_results_needed(self) -> None:
        self.assertTrue(
            should_follow_next_page(
                page=1,
                page_count=10,
                seen=10,
                limit=50,
                max_pages=None,
            )
        )

    def test_stops_on_empty_page(self) -> None:
        # An empty page means the results ran out — terminate the crawl.
        self.assertFalse(
            should_follow_next_page(
                page=1,
                page_count=0,
                seen=10,
                limit=50,
                max_pages=None,
            )
        )

    def test_stops_when_limit_reached(self) -> None:
        self.assertFalse(
            should_follow_next_page(
                page=1,
                page_count=5,
                seen=50,
                limit=50,
                max_pages=None,
            )
        )

    def test_stops_at_max_pages_cap(self) -> None:
        # Current page == max_pages: the next page would exceed the cap.
        self.assertFalse(
            should_follow_next_page(
                page=5,
                page_count=10,
                seen=40,
                limit=50,
                max_pages=5,
            )
        )

    def test_allows_page_below_max_pages_cap(self) -> None:
        self.assertTrue(
            should_follow_next_page(
                page=4,
                page_count=10,
                seen=40,
                limit=50,
                max_pages=5,
            )
        )


if __name__ == "__main__":
    unittest.main()
