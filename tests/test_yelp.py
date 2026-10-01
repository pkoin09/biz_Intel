"""Tests for the Yelp Fusion API source."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from biz_intel.core.location import Location
from biz_intel.core.source_name import SourceName
from biz_intel.core.source_task import SourceTask
from biz_intel.sources.yelp.source import YelpSource, _YELP_LIMIT_MAX


def _fake_response(businesses: list) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"businesses": businesses, "total": len(businesses)}
    return mock


_SAMPLE_RESULT = {
    "id": "city-dentistry-san-jose",
    "name": "City Dentistry",
    "location": {
        "address1": "123 Main St",
        "city": "San Jose",
        "state": "CA",
        "zip_code": "95110",
        "country": "US",
    },
    "phone": "+14085550100",
    "display_phone": "(408) 555-0100",
    "categories": [{"alias": "dentists", "title": "Dentists"}],
    "rating": 4.5,
    "review_count": 200,
    "url": "https://www.yelp.com/biz/city-dentistry-san-jose",
}


class YelpSourceTests(unittest.TestCase):

    def _make_task(self, limit: int = 5, options: dict | None = None) -> SourceTask:
        return SourceTask(
            source=SourceName.YELP,
            category="dentists",
            location=Location(city="San Jose", state="CA"),
            limit=limit,
            options=options or {},
        )

    @patch("biz_intel.sources.yelp.source.config")
    @patch("biz_intel.sources.yelp.source.httpx.get")
    def test_fetch_yields_businesses(self, mock_get, mock_config) -> None:
        mock_config.YELP_API_KEY = "test-key"
        mock_get.return_value = _fake_response([_SAMPLE_RESULT])

        businesses = list(YelpSource(self._make_task()).fetch())

        self.assertEqual(len(businesses), 1)
        b = businesses[0]
        self.assertEqual(b.name, "City Dentistry")
        self.assertEqual(b.city, "San Jose")
        self.assertEqual(b.state, "CA")
        self.assertEqual(b.postal_code, "95110")
        self.assertEqual(b.country, "US")
        self.assertAlmostEqual(b.rating, 4.5)
        self.assertEqual(b.review_count, 200)
        self.assertEqual(b.source, "yelp")

    @patch("biz_intel.sources.yelp.source.config")
    @patch("biz_intel.sources.yelp.source.httpx.get")
    def test_phone_mapped_from_display_phone(self, mock_get, mock_config) -> None:
        mock_config.YELP_API_KEY = "test-key"
        mock_get.return_value = _fake_response([_SAMPLE_RESULT])

        b = list(YelpSource(self._make_task()).fetch())[0]

        self.assertEqual(b.phone, "(408) 555-0100")

    @patch("biz_intel.sources.yelp.source.config")
    @patch("biz_intel.sources.yelp.source.httpx.get")
    def test_category_mapped_from_first_category_title(self, mock_get, mock_config) -> None:
        mock_config.YELP_API_KEY = "test-key"
        mock_get.return_value = _fake_response([_SAMPLE_RESULT])

        b = list(YelpSource(self._make_task()).fetch())[0]

        self.assertEqual(b.category, "Dentists")

    @patch("biz_intel.sources.yelp.source.config")
    @patch("biz_intel.sources.yelp.source.httpx.get")
    def test_fetch_returns_empty_on_no_results(self, mock_get, mock_config) -> None:
        mock_config.YELP_API_KEY = "test-key"
        mock_get.return_value = _fake_response([])

        businesses = list(YelpSource(self._make_task()).fetch())

        self.assertEqual(businesses, [])

    @patch("biz_intel.sources.yelp.source.config")
    def test_fetch_raises_without_api_key(self, mock_config) -> None:
        mock_config.YELP_API_KEY = ""

        with self.assertRaises(RuntimeError):
            list(YelpSource(self._make_task()).fetch())

    @patch("biz_intel.sources.yelp.source.config")
    @patch("biz_intel.sources.yelp.source.httpx.get")
    def test_limit_passed_as_query_param(self, mock_get, mock_config) -> None:
        mock_config.YELP_API_KEY = "test-key"
        mock_get.return_value = _fake_response([])

        list(YelpSource(self._make_task(limit=10)).fetch())

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"]["limit"], 10)

    @patch("biz_intel.sources.yelp.source.config")
    @patch("biz_intel.sources.yelp.source.httpx.get")
    def test_limit_capped_at_yelp_maximum(self, mock_get, mock_config) -> None:
        mock_config.YELP_API_KEY = "test-key"
        mock_get.return_value = _fake_response([])

        list(YelpSource(self._make_task(limit=200)).fetch())

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"]["limit"], _YELP_LIMIT_MAX)

    @patch("biz_intel.sources.yelp.source.config")
    @patch("biz_intel.sources.yelp.source.httpx.get")
    def test_bearer_token_sent_in_header(self, mock_get, mock_config) -> None:
        mock_config.YELP_API_KEY = "my-yelp-key"
        mock_get.return_value = _fake_response([])

        list(YelpSource(self._make_task()).fetch())

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer my-yelp-key")

    @patch("biz_intel.sources.yelp.source.config")
    @patch("biz_intel.sources.yelp.source.httpx.get")
    def test_location_and_term_in_params(self, mock_get, mock_config) -> None:
        mock_config.YELP_API_KEY = "test-key"
        mock_get.return_value = _fake_response([])

        list(YelpSource(self._make_task()).fetch())

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"]["term"], "dentists")
        self.assertEqual(kwargs["params"]["location"], "San Jose, CA")


if __name__ == "__main__":
    unittest.main()
