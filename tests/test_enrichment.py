"""Tests for post-dedup enrichment: cache, contact enricher, social enricher, runner."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb
from unittest.mock import MagicMock, patch

from biz_intel.models.business import Business
from biz_intel.services.enrichment.budget import EnrichmentBudget
from biz_intel.services.enrichment.cache import PlaceDetailsCache, CACHE_TTL_DAYS
from biz_intel.services.enrichment.contact import ContactEnricher
from biz_intel.services.enrichment.runner import EnrichmentRunner
from biz_intel.services.enrichment.social import SocialEnricher


def _business(**kwargs) -> Business:
    defaults = {
        "name": "City Dentistry",
        "source": "google",
        "raw_data": {"place_id": "ChIJtest"},
    }
    defaults.update(kwargs)
    return Business(**defaults)


class PlaceDetailsCacheTests(unittest.TestCase):

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._path = Path(self._tmpdir.name) / "test.db"
        self._cache = PlaceDetailsCache(self._path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_miss_returns_none(self) -> None:
        self.assertIsNone(self._cache.get("google", "missing-id"))

    def test_set_and_get_roundtrip(self) -> None:
        self._cache.set("google", "ChIJtest", "(408) 555-0100", "https://example.com")

        result = self._cache.get("google", "ChIJtest")

        self.assertEqual(result, ("(408) 555-0100", "https://example.com"))

    def test_different_sources_are_independent(self) -> None:
        self._cache.set("google", "id1", "111", "https://a.com")
        self._cache.set("yelp", "id1", "222", "https://b.com")

        self.assertEqual(self._cache.get("google", "id1")[0], "111")
        self.assertEqual(self._cache.get("yelp", "id1")[0], "222")

    def test_expired_entry_returns_none(self) -> None:
        from datetime import datetime, timedelta, timezone
        old_ts = (
            datetime.now(timezone.utc) - timedelta(days=CACHE_TTL_DAYS + 1)
        ).isoformat()

        with duckdb.connect(str(self._path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO place_details_cache "
                "(source, source_id, phone, website, fetched_at) VALUES (?,?,?,?,?)",
                ["google", "old-id", "123", "https://old.com", old_ts],
            )

        self.assertIsNone(self._cache.get("google", "old-id"))

    def test_set_overwrites_existing(self) -> None:
        self._cache.set("google", "id1", "old-phone", "")
        self._cache.set("google", "id1", "new-phone", "https://new.com")

        result = self._cache.get("google", "id1")
        self.assertEqual(result[0], "new-phone")

    def test_zero_retention_never_persists_a_source_value(self) -> None:
        cache = PlaceDetailsCache(self._path, {"google": 0})

        cache.set("google", "ChIJtest", "111", "https://example.com")

        self.assertIsNone(cache.get("google", "ChIJtest"))

    def test_zero_retention_deletes_a_preexisting_source_value(self) -> None:
        self._cache.set("google", "ChIJtest", "111", "https://example.com")
        restricted = PlaceDetailsCache(self._path, {"google": 0})

        self.assertIsNone(restricted.get("google", "ChIJtest"))
        self.assertIsNone(self._cache.get("google", "ChIJtest"))


class ContactEnricherTests(unittest.TestCase):

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cache = PlaceDetailsCache(Path(self._tmpdir.name) / "cache.db")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _enricher(self, sources=None) -> ContactEnricher:
        return ContactEnricher(sources or {"google"}, self._cache)

    def test_skips_business_from_other_source(self) -> None:
        b = _business(source="yellowpages")
        result = self._enricher().enrich(b)
        self.assertIs(result, b)

    def test_skips_fully_enriched_business(self) -> None:
        b = _business(phone="111", website="https://example.com")
        result = self._enricher().enrich(b)
        self.assertIs(result, b)

    def test_skips_business_without_source_id(self) -> None:
        b = _business(raw_data=None)
        result = self._enricher().enrich(b)
        self.assertIs(result, b)

    @patch("biz_intel.services.enrichment.contact.httpx.get")
    @patch("biz_intel.services.enrichment.contact.config")
    def test_fetches_and_applies_google_details(self, mock_config, mock_get) -> None:
        mock_config.GOOGLE_PLACES_API_KEY = "test-key"
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "result": {
                "formatted_phone_number": "(408) 555-0100",
                "website": "https://example.com",
            }
        }
        mock_get.return_value = mock_resp

        b = _business()
        result = self._enricher().enrich(b)

        self.assertEqual(result.phone, "(408) 555-0100")
        self.assertEqual(result.website, "https://example.com")

    @patch("biz_intel.services.enrichment.contact.httpx.get")
    @patch("biz_intel.services.enrichment.contact.config")
    def test_caches_result_on_first_fetch(self, mock_config, mock_get) -> None:
        mock_config.GOOGLE_PLACES_API_KEY = "test-key"
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "result": {"formatted_phone_number": "(408) 555-0100", "website": ""}
        }
        mock_get.return_value = mock_resp

        b = _business()
        enricher = self._enricher()
        enricher.enrich(b)
        enricher.enrich(b)

        self.assertEqual(mock_get.call_count, 1)

    def test_only_fills_missing_fields(self) -> None:
        self._cache.set("google", "ChIJtest", "(408) 555-0100", "https://example.com")

        b = _business(phone="existing-phone")
        result = self._enricher().enrich(b)

        self.assertEqual(result.phone, "existing-phone")
        self.assertEqual(result.website, "https://example.com")


class EnrichmentBudgetTests(unittest.TestCase):
    """Protect the max_enrich cap semantics."""

    def test_default_blocks_paid_calls(self) -> None:
        budget = EnrichmentBudget()
        self.assertFalse(budget.allows("google"))
        self.assertTrue(budget.was_capped("google"))

    def test_cap_allows_below_and_blocks_at_limit(self) -> None:
        budget = EnrichmentBudget.from_source_options(
            {"google": {"max_enrich": 2}},
            {"google"},
        )
        self.assertTrue(budget.allows("google"))
        budget.record_paid_call("google")
        budget.record_paid_call("google")
        self.assertFalse(budget.allows("google"))
        self.assertTrue(budget.was_capped("google"))

    def test_per_source_independence(self) -> None:
        budget = EnrichmentBudget.from_source_options(
            {"google": {"max_enrich": 1}, "yelp": {"max_enrich": 5}},
            {"google", "yelp"},
        )
        budget.record_paid_call("google")
        self.assertFalse(budget.allows("google"))
        self.assertTrue(budget.allows("yelp"))

    def test_unconfigured_source_is_blocked_even_with_other_caps(self) -> None:
        budget = EnrichmentBudget.from_source_options(
            {"google": {"max_enrich": 2}},
            {"google", "yelp"},
        )
        self.assertFalse(budget.allows("yelp"))

    def test_cost_line_tracks_spend_and_cap(self) -> None:
        budget = EnrichmentBudget.from_source_options(
            {"google": {"max_enrich": 2}},
            {"google"},
        )
        budget.record_paid_call("google")
        line = budget.cost_line("google")

        self.assertEqual(line.paid_calls, 1)
        self.assertFalse(line.capped)
        self.assertGreater(line.estimated_spend, 0)


class ContactEnricherCapTests(unittest.TestCase):
    """The cap stops *paid* calls; cache hits and source values survive."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cache = PlaceDetailsCache(Path(self._tmpdir.name) / "cache.db")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("biz_intel.services.enrichment.contact.httpx.get")
    @patch("biz_intel.services.enrichment.contact.config")
    def test_cap_limits_paid_calls_and_leaves_business_unenriched(
        self, mock_config, mock_get
    ) -> None:
        mock_config.GOOGLE_PLACES_API_KEY = "test-key"
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "result": {"formatted_phone_number": "(408) 555-0100", "website": ""}
        }
        mock_get.return_value = mock_resp

        budget = EnrichmentBudget.from_source_options(
            {"google": {"max_enrich": 2}},
            {"google"},
        )
        enricher = ContactEnricher({"google"}, self._cache, budget)

        b1 = _business(raw_data={"place_id": "one"})
        b2 = _business(name="Two", raw_data={"place_id": "two"})
        b3 = _business(name="Three", raw_data={"place_id": "three"})

        self.assertIsNot(enricher.enrich(b1), b1)
        self.assertIsNot(enricher.enrich(b2), b2)
        # Third is a cache miss but the cap is exhausted -> unenriched, not dropped.
        self.assertIs(enricher.enrich(b3), b3)

        self.assertEqual(mock_get.call_count, 2)
        self.assertTrue(budget.was_capped("google"))

    @patch("biz_intel.services.enrichment.contact.httpx.get")
    def test_cache_hits_are_free_even_when_capped(self, mock_get) -> None:
        self._cache.set(
            "google",
            "known-id",
            "(408) 555-0100",
            "https://example.com",
        )

        # max_enrich: 0 = zero paid calls allowed, but cached values still apply.
        budget = EnrichmentBudget.from_source_options(
            {"google": {"max_enrich": 0}},
            {"google"},
        )
        enricher = ContactEnricher({"google"}, self._cache, budget)

        result = enricher.enrich(_business(raw_data={"place_id": "known-id"}))

        self.assertEqual(result.phone, "(408) 555-0100")
        self.assertEqual(result.website, "https://example.com")
        self.assertEqual(mock_get.call_count, 0)


class SocialEnricherTests(unittest.TestCase):

    def _enricher(self) -> SocialEnricher:
        return SocialEnricher()

    def test_skips_business_without_website(self) -> None:
        b = _business(website="")
        result = self._enricher().enrich(b)
        self.assertIs(result, b)

    def test_skips_fully_populated_business(self) -> None:
        b = _business(
            website="https://example.com",
            email="hello@example.com",
            phone="+14085550100",
            linkedin="https://www.linkedin.com/company/test",
            instagram="https://www.instagram.com/test",
            facebook="https://www.facebook.com/test",
            twitter="https://www.twitter.com/test",
        )
        result = self._enricher().enrich(b)
        self.assertIs(result, b)

    @patch("biz_intel.services.enrichment.social.httpx.get")
    def test_extracts_linkedin_from_page(self, mock_get) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.text = (
            '<html><body>'
            '<a href="https://www.linkedin.com/company/city-dentistry">LinkedIn</a>'
            '</body></html>'
        )
        mock_get.return_value = mock_resp

        b = _business(website="https://citydentistry.example.com")
        result = self._enricher().enrich(b)

        self.assertIn("linkedin.com/company/city-dentistry", result.linkedin)

    def test_crawls_only_same_origin_likely_pages_and_extracts_public_contacts(self) -> None:
        pages = {
            "https://citydentistry.example.com/robots.txt": "User-agent: *\nAllow: /\n",
            "https://citydentistry.example.com": (
                '<a href="/contact">Contact us</a>'
                '<a href="https://outside.example/contact">Partner contact</a>'
            ),
            "https://citydentistry.example.com/contact": (
                '<a href="mailto:hello%40citydentistry.example.com?subject=Hello">Email</a>'
                '<a href="tel:+1-408-555-0100">Call</a>'
                '<a href="https://instagram.com/citydentistry">Instagram</a>'
            ),
        }
        calls = []

        class Response:
            def __init__(self, text, url):
                self.text = text
                self.url = url

            def raise_for_status(self):
                return None

        def get(url, **kwargs):
            calls.append(url)
            return Response(pages[url], url)

        result = SocialEnricher(get).enrich(
            _business(website="https://citydentistry.example.com")
        )

        self.assertEqual(result.email, "hello@citydentistry.example.com")
        self.assertEqual(result.phone, "+1-408-555-0100")
        self.assertIn("instagram.com/citydentistry", result.instagram)
        self.assertEqual(
            calls,
            [
                "https://citydentistry.example.com/robots.txt",
                "https://citydentistry.example.com",
                "https://citydentistry.example.com/contact",
            ],
        )

    def test_robots_disallow_leaves_business_unchanged_without_homepage_request(self) -> None:
        calls = []

        class Response:
            text = "User-agent: *\nDisallow: /\n"

            def raise_for_status(self):
                return None

        def get(url, **kwargs):
            calls.append(url)
            return Response()

        business = _business(website="https://citydentistry.example.com")
        result = SocialEnricher(get).enrich(business)

        self.assertIs(result, business)
        self.assertEqual(calls, ["https://citydentistry.example.com/robots.txt"])

    def test_fetch_failure_leaves_business_unchanged(self) -> None:
        business = _business(website="https://citydentistry.example.com")

        result = SocialEnricher(lambda url, **kwargs: (_ for _ in ()).throw(OSError())).enrich(business)

        self.assertIs(result, business)

    @patch("biz_intel.services.enrichment.social.httpx.get")
    def test_returns_business_unchanged_on_crawl_error(self, mock_get) -> None:
        mock_get.side_effect = Exception("connection refused")

        b = _business(website="https://citydentistry.example.com")
        result = self._enricher().enrich(b)

        self.assertIs(result, b)


class EnrichmentRunnerTests(unittest.TestCase):

    def test_run_with_no_enrichers_returns_unchanged(self) -> None:
        runner = EnrichmentRunner([])
        businesses = [_business(), _business(name="Other")]

        result = runner.run(businesses)

        self.assertEqual(result, businesses)

    def test_enrichers_applied_in_order(self) -> None:
        calls = []

        class RecordingEnricher:
            def __init__(self, tag):
                self.tag = tag
            def enrich(self, b):
                calls.append(self.tag)
                return b

        runner = EnrichmentRunner([RecordingEnricher("first"), RecordingEnricher("second")])
        runner.run([_business()])

        self.assertEqual(calls, ["first", "second"])

    def test_from_job_adds_social_enricher_when_enrich_true(self) -> None:
        from biz_intel.jobs.models import JobSpec
        from biz_intel.services.enrichment.social import SocialEnricher

        job = JobSpec.from_dict({
            "version": 1,
            "name": "test",
            "search": {"query": "dentist", "cities": ["San Jose, CA"]},
            "sources": ["google"],
            "output": {},
            "processing": {"enrich": True},
        })

        runner = EnrichmentRunner.from_job(job)

        self.assertTrue(
            any(isinstance(e, SocialEnricher) for e in runner._enrichers)
        )

    def test_from_job_no_enrichers_when_enrich_false_no_options(self) -> None:
        from biz_intel.jobs.models import JobSpec

        job = JobSpec.from_dict({
            "version": 1,
            "name": "test",
            "search": {"query": "dentist", "cities": ["San Jose, CA"]},
            "sources": ["google"],
            "output": {},
        })

        runner = EnrichmentRunner.from_job(job)

        self.assertEqual(runner._enrichers, [])

    def test_from_job_adds_contact_enricher_when_enrich_details_set(self) -> None:
        from biz_intel.jobs.models import JobSpec
        from biz_intel.services.enrichment.contact import ContactEnricher

        job = JobSpec.from_dict({
            "version": 1,
            "name": "test",
            "search": {"query": "dentist", "cities": ["San Jose, CA"]},
            "sources": ["google"],
            "output": {},
            "source_options": {"google": {"enrich_details": True, "max_enrich": 0}},
        })

        runner = EnrichmentRunner.from_job(job)

        self.assertTrue(
            any(isinstance(e, ContactEnricher) for e in runner._enrichers)
        )

    def test_from_job_builds_budget_from_max_enrich(self) -> None:
        from biz_intel.jobs.models import JobSpec

        job = JobSpec.from_dict({
            "version": 1,
            "name": "test",
            "search": {"query": "dentist", "cities": ["San Jose, CA"]},
            "sources": ["google", "yelp"],
            "output": {},
            "source_options": {
                "google": {"enrich_details": True, "max_enrich": 50},
                "yelp": {"enrich_details": True, "max_enrich": 0},
            },
            "budget": {"max_total_usd": 2, "approval_reference": "test"},
        })

        runner = EnrichmentRunner.from_job(job)

        self.assertIsNotNone(runner.budget)
        self.assertTrue(runner.budget.allows("google"))  # 0/50 so far
        self.assertFalse(runner.budget.allows("yelp"))  # explicit zero-call cap

        for _ in range(50):
            runner.budget.record_paid_call("google")

        self.assertFalse(runner.budget.allows("google"))  # 50/50 reached
        self.assertTrue(runner.budget.was_capped("google"))
        self.assertFalse(runner.budget.allows("yelp"))


if __name__ == "__main__":
    unittest.main()
