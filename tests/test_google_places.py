"""Tests for the Google Places API source."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from biz_intel.core.api_executor import ApiSourceExecutor
from biz_intel.core.location import Location
from biz_intel.core.source_name import SourceName
from biz_intel.core.source_task import SourceTask
from biz_intel.sources.google.source import GooglePlacesSource, _parse_address


def _fake_response(results: list, status: str = "OK") -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"status": status, "results": results}
    return mock



_SAMPLE_RESULT = {
    "name": "City Dentistry",
    "formatted_address": "123 Main St, San Jose, CA 95110, USA",
    "rating": 4.5,
    "user_ratings_total": 200,
    "types": ["dentist", "health", "point_of_interest", "establishment"],
    "place_id": "ChIJtest",
}


class ParseAddressTests(unittest.TestCase):

    def test_full_us_address(self) -> None:
        address, city, state, postal_code, country = _parse_address(
            "123 Main St, San Jose, CA 95110, USA"
        )
        self.assertEqual(address, "123 Main St")
        self.assertEqual(city, "San Jose")
        self.assertEqual(state, "CA")
        self.assertEqual(postal_code, "95110")
        self.assertEqual(country, "USA")

    def test_no_street_address(self) -> None:
        address, city, state, postal_code, country = _parse_address(
            "San Jose, CA 95110, USA"
        )
        self.assertEqual(address, "")
        self.assertEqual(city, "San Jose")
        self.assertEqual(state, "CA")
        self.assertEqual(postal_code, "95110")
        self.assertEqual(country, "USA")

    def test_unexpected_format_falls_back(self) -> None:
        address, city, state, postal_code, country = _parse_address("San Jose")
        self.assertEqual(address, "San Jose")
        self.assertEqual(city, "")
        self.assertEqual(state, "")


class GooglePlacesSourceTests(unittest.TestCase):

    def _make_task(self, limit: int = 5, options: dict | None = None) -> SourceTask:
        return SourceTask(
            source=SourceName.GOOGLE,
            category="dentists",
            location=Location(city="San Jose", state="CA"),
            limit=limit,
            options=options or {},
        )

    @patch("biz_intel.sources.google.source.config")
    @patch("biz_intel.sources.google.source.httpx.get")
    def test_fetch_yields_businesses(self, mock_get, mock_config) -> None:
        mock_config.GOOGLE_PLACES_API_KEY = "test-key"
        mock_get.return_value = _fake_response([_SAMPLE_RESULT])

        task = self._make_task()
        source = GooglePlacesSource(task)
        businesses = list(source.fetch())

        self.assertEqual(len(businesses), 1)
        b = businesses[0]
        self.assertEqual(b.name, "City Dentistry")
        self.assertEqual(b.city, "San Jose")
        self.assertEqual(b.state, "CA")
        self.assertEqual(b.postal_code, "95110")
        self.assertAlmostEqual(b.rating, 4.5)
        self.assertEqual(b.review_count, 200)
        self.assertEqual(b.source, "google")
        self.assertEqual(b.category, "Dentist")

    @patch("biz_intel.sources.google.source.config")
    @patch("biz_intel.sources.google.source.httpx.get")
    def test_fetch_respects_limit(self, mock_get, mock_config) -> None:
        mock_config.GOOGLE_PLACES_API_KEY = "test-key"
        mock_get.return_value = _fake_response([_SAMPLE_RESULT] * 10)

        task = self._make_task(limit=3)
        businesses = list(GooglePlacesSource(task).fetch())

        self.assertEqual(len(businesses), 3)

    @patch("biz_intel.sources.google.source.config")
    @patch("biz_intel.sources.google.source.httpx.get")
    def test_fetch_returns_empty_on_zero_results(self, mock_get, mock_config) -> None:
        mock_config.GOOGLE_PLACES_API_KEY = "test-key"
        mock_get.return_value = _fake_response([], status="ZERO_RESULTS")

        businesses = list(GooglePlacesSource(self._make_task()).fetch())
        self.assertEqual(businesses, [])

    @patch("biz_intel.sources.google.source.config")
    def test_fetch_raises_without_api_key(self, mock_config) -> None:
        mock_config.GOOGLE_PLACES_API_KEY = ""

        with self.assertRaises(RuntimeError, msg="GOOGLE_PLACES_API_KEY"):
            list(GooglePlacesSource(self._make_task()).fetch())

    @patch("biz_intel.sources.google.source.config")
    @patch("biz_intel.sources.google.source.httpx.get")
    def test_fetch_raises_on_api_error_status(self, mock_get, mock_config) -> None:
        mock_config.GOOGLE_PLACES_API_KEY = "test-key"
        mock_get.return_value = _fake_response([], status="REQUEST_DENIED")

        with self.assertRaises(RuntimeError):
            list(GooglePlacesSource(self._make_task()).fetch())

    @patch("biz_intel.sources.google.source.config")
    @patch("biz_intel.sources.google.source.httpx.get")
    def test_api_executor_dispatches_to_source(self, mock_get, mock_config) -> None:
        mock_config.GOOGLE_PLACES_API_KEY = "test-key"
        mock_get.return_value = _fake_response([_SAMPLE_RESULT])

        task = self._make_task()
        businesses = list(ApiSourceExecutor().run(GooglePlacesSource, task))

        self.assertEqual(len(businesses), 1)
        self.assertEqual(businesses[0].name, "City Dentistry")

    @patch("biz_intel.sources.google.source.config")
    @patch("biz_intel.sources.google.source.httpx.get")
    def test_fetch_leaves_phone_and_website_empty(self, mock_get, mock_config) -> None:
        mock_config.GOOGLE_PLACES_API_KEY = "test-key"
        mock_get.return_value = _fake_response([_SAMPLE_RESULT])

        businesses = list(GooglePlacesSource(self._make_task()).fetch())

        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(businesses[0].phone, "")
        self.assertEqual(businesses[0].website, "")


if __name__ == "__main__":
    unittest.main()
