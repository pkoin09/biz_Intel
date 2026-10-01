"""Tests for Apify actor-backed sources."""

from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from biz_intel.core.apify_executor import ApifySourceExecutor
from biz_intel.core.location import Location
from biz_intel.core.source_name import SourceName
from biz_intel.core.source_task import SourceTask
from biz_intel.sources.google.apify_source import GoogleMapsApifySource
from biz_intel.sources.yelp.apify_source import YelpApifySource


def _fake_response(items: list) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = items
    return mock


_GOOGLE_ITEM = {
    "title": "City Dentistry",
    "categoryName": "Dentist",
    "street": "123 Main St",
    "city": "San Jose",
    "state": "CA",
    "postalCode": "95110",
    "countryCode": "US",
    "phone": "(408) 555-0100",
    "website": "https://citydentistry.example.com",
    "totalScore": 4.5,
    "reviewsCount": 200,
    "url": "https://maps.google.com/?cid=test",
    "placeId": "ChIJtest",
}

_YELP_ITEM = {
    "name": "City Dentistry",
    "categories": [{"alias": "dentists", "title": "Dentists"}],
    "location": {
        "address1": "123 Main St",
        "city": "San Jose",
        "state": "CA",
        "zipCode": "95110",
        "country": "US",
    },
    "phone": "(408) 555-0100",
    "website": "https://citydentistry.example.com",
    "rating": 4.5,
    "reviewCount": 200,
    "url": "https://www.yelp.com/biz/city-dentistry",
}

_FIXTURES = Path(__file__).parent / "fixtures"


class GoogleMapsApifySourceTests(unittest.TestCase):

    def _make_task(self, limit: int = 5) -> SourceTask:
        return SourceTask(
            source=SourceName.GOOGLE_APIFY,
            category="dentists",
            location=Location(city="San Jose", state="CA"),
            limit=limit,
        )

    @patch("biz_intel.core.apify_source.config")
    @patch("biz_intel.core.apify_source.httpx.post")
    def test_fetch_yields_businesses(self, mock_post, mock_config) -> None:
        mock_config.APIFY_API_KEY = "test-key"
        mock_post.return_value = _fake_response([_GOOGLE_ITEM])

        businesses = list(GoogleMapsApifySource(self._make_task()).fetch())

        self.assertEqual(len(businesses), 1)
        b = businesses[0]
        self.assertEqual(b.name, "City Dentistry")
        self.assertEqual(b.phone, "(408) 555-0100")
        self.assertEqual(b.website, "https://citydentistry.example.com")
        self.assertEqual(b.city, "San Jose")
        self.assertEqual(b.state, "CA")
        self.assertEqual(b.category, "Dentist")
        self.assertAlmostEqual(b.rating, 4.5)
        self.assertEqual(b.review_count, 200)
        self.assertEqual(b.source, "google-apify")

    @patch("biz_intel.core.apify_source.config")
    @patch("biz_intel.core.apify_source.httpx.post")
    def test_actor_id_converted_to_url_safe_form(self, mock_post, mock_config) -> None:
        mock_config.APIFY_API_KEY = "test-key"
        mock_post.return_value = _fake_response([])

        list(GoogleMapsApifySource(self._make_task()).fetch())

        url = mock_post.call_args[0][0]
        self.assertIn("apify~google-maps-scraper", url)

    @patch("biz_intel.core.apify_source.config")
    @patch("biz_intel.core.apify_source.httpx.post")
    def test_query_includes_category_and_location(self, mock_post, mock_config) -> None:
        mock_config.APIFY_API_KEY = "test-key"
        mock_post.return_value = _fake_response([])

        list(GoogleMapsApifySource(self._make_task()).fetch())

        body = mock_post.call_args[1]["json"]
        self.assertIn("dentists", body["searchStringsArray"][0])
        self.assertIn("San Jose", body["searchStringsArray"][0])

    @patch("biz_intel.core.apify_source.config")
    @patch("biz_intel.core.apify_source.httpx.post")
    def test_skips_items_with_no_title(self, mock_post, mock_config) -> None:
        mock_config.APIFY_API_KEY = "test-key"
        empty_item = {**_GOOGLE_ITEM, "title": ""}
        mock_post.return_value = _fake_response([empty_item, _GOOGLE_ITEM])

        businesses = list(GoogleMapsApifySource(self._make_task()).fetch())

        self.assertEqual(len(businesses), 1)

    def test_normalizes_sanitized_google_fixture(self) -> None:
        [item] = json.loads(
            (_FIXTURES / "apify_google_maps_example.json").read_text()
        )

        business = GoogleMapsApifySource(self._make_task())._to_business(item)

        assert business is not None
        self.assertEqual(business.name, "Example Dental Studio")
        self.assertEqual(business.website, "https://dental.example.test")
        self.assertEqual(business.city, "Exampletown")
        self.assertEqual(business.source_url, "https://maps.example.test/place/example-dental-studio")

    @patch("biz_intel.core.apify_source.config")
    def test_raises_without_api_key(self, mock_config) -> None:
        mock_config.APIFY_API_KEY = ""

        with self.assertRaises(RuntimeError):
            list(GoogleMapsApifySource(self._make_task()).fetch())

    @patch("biz_intel.core.apify_source.config")
    @patch("biz_intel.core.apify_source.httpx.post")
    def test_executor_dispatches_to_source(self, mock_post, mock_config) -> None:
        mock_config.APIFY_API_KEY = "test-key"
        mock_post.return_value = _fake_response([_GOOGLE_ITEM])

        businesses = list(
            ApifySourceExecutor().run(GoogleMapsApifySource, self._make_task())
        )

        self.assertEqual(len(businesses), 1)
        self.assertEqual(businesses[0].name, "City Dentistry")


class YelpApifySourceTests(unittest.TestCase):

    def _make_task(self, limit: int = 5) -> SourceTask:
        return SourceTask(
            source=SourceName.YELP_APIFY,
            category="dentists",
            location=Location(city="San Jose", state="CA"),
            limit=limit,
        )

    @patch("biz_intel.core.apify_source.config")
    @patch("biz_intel.core.apify_source.httpx.post")
    def test_fetch_yields_businesses(self, mock_post, mock_config) -> None:
        mock_config.APIFY_API_KEY = "test-key"
        mock_post.return_value = _fake_response([_YELP_ITEM])

        businesses = list(YelpApifySource(self._make_task()).fetch())

        self.assertEqual(len(businesses), 1)
        b = businesses[0]
        self.assertEqual(b.name, "City Dentistry")
        self.assertEqual(b.phone, "(408) 555-0100")
        self.assertEqual(b.website, "https://citydentistry.example.com")
        self.assertEqual(b.source, "yelp-apify")

    @patch("biz_intel.core.apify_source.config")
    @patch("biz_intel.core.apify_source.httpx.post")
    def test_skips_items_with_no_name(self, mock_post, mock_config) -> None:
        mock_config.APIFY_API_KEY = "test-key"
        mock_post.return_value = _fake_response([{**_YELP_ITEM, "name": ""}])

        businesses = list(YelpApifySource(self._make_task()).fetch())

        self.assertEqual(businesses, [])

    def test_normalizes_headply_fixture_shape(self) -> None:
        items = json.loads(
            (_FIXTURES / "apify_yelp_headply_example.json").read_text()
        )
        source = YelpApifySource(self._make_task())

        businesses = [source._to_business(item) for item in items]

        first, second = businesses
        assert first is not None
        assert second is not None
        self.assertEqual(first.name, "Example Cafe")
        self.assertEqual(first.category, "Cafes")
        self.assertEqual(first.address, "200 Example Street")
        self.assertEqual(first.city, "Exampletown")
        self.assertEqual(first.state, "TX")
        self.assertEqual(first.postal_code, "73301")
        self.assertEqual(first.website, "https://cafe.example.test")
        self.assertEqual(first.source_url, "https://yelp.example.test/biz/example-cafe-exampletown")
        self.assertAlmostEqual(first.rating, 4.2)
        self.assertEqual(first.review_count, 34)
        self.assertEqual(second.category, "")
        self.assertEqual(second.address, "")
        self.assertEqual(second.phone, "")
        self.assertEqual(second.website, "")
        self.assertIsNone(second.rating)
        self.assertIsNone(second.review_count)


if __name__ == "__main__":
    unittest.main()
