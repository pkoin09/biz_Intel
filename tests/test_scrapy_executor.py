"""Tests for the Scrapy-based SourceExecutor."""

from __future__ import annotations

import unittest

import scrapy

from biz_intel.core.base_spider import BaseBusinessSpider
from biz_intel.core.location import Location
from biz_intel.core.scrapy_executor import ScrapySourceExecutor
from biz_intel.core.source_name import SourceName
from biz_intel.core.source_task import SourceTask
from biz_intel.models.business import Business


class _FakeSpider(BaseBusinessSpider):
    """
    A network- and Playwright-free stand-in for a real BaseBusinessSpider,
    used only to exercise ScrapySourceExecutor's subprocess/signal plumbing.
    """

    name = "fake"
    source_name = "fake"

    def build_search_url(self) -> str:
        return "data:text/plain,ok"

    async def start(self):
        yield scrapy.Request(
            self.build_search_url(),
            callback=self.parse,
            dont_filter=True,
        )

    async def parse(self, response):
        yield Business(
            name=f"{self.query} in {self.location}",
            source=self.source_name,
        )


class _OptionsSpider(_FakeSpider):
    """
    Surfaces the constructor ``options`` so tests can assert the executor
    forwards ``SourceTask.options`` into the spider subprocess.
    """

    async def parse(self, response):
        yield Business(
            name=f"options={self.options}",
            source=self.source_name,
        )


class ScrapySourceExecutorTests(unittest.TestCase):
    """Protect the Scrapy-executor's public contract."""

    def test_runs_a_spider_and_translates_the_location(self) -> None:
        task = SourceTask(
            source=SourceName.YELLOWPAGES,
            category="dentist",
            location=Location(city="San Jose", state="CA"),
            limit=10,
        )

        businesses = list(ScrapySourceExecutor().run(_FakeSpider, task))

        self.assertEqual(len(businesses), 1)
        self.assertEqual(businesses[0].name, "dentist in San Jose, CA")

    def test_runs_twice_in_the_same_process(self) -> None:
        """Guards against ReactorNotRestartable regressions."""

        task = SourceTask(
            source=SourceName.YELLOWPAGES,
            category="dentist",
            location=Location(state="NJ"),
            limit=10,
        )

        first = list(ScrapySourceExecutor().run(_FakeSpider, task))
        second = list(ScrapySourceExecutor().run(_FakeSpider, task))

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(first[0].name, "dentist in NJ")
        self.assertEqual(second[0].name, "dentist in NJ")

    def test_forwards_task_options_to_the_spider(self) -> None:
        task = SourceTask(
            source=SourceName.YELLOWPAGES,
            category="dentist",
            location=Location(city="San Jose", state="CA"),
            limit=10,
            options={"max_pages": 5},
        )

        businesses = list(ScrapySourceExecutor().run(_OptionsSpider, task))

        self.assertEqual(len(businesses), 1)
        self.assertEqual(businesses[0].name, "options={'max_pages': 5}")

    def test_defaults_options_to_empty_dict(self) -> None:
        task = SourceTask(
            source=SourceName.YELLOWPAGES,
            category="dentist",
            location=Location(city="San Jose", state="CA"),
            limit=10,
        )

        businesses = list(ScrapySourceExecutor().run(_OptionsSpider, task))

        self.assertEqual(len(businesses), 1)
        self.assertEqual(businesses[0].name, "options={}")


if __name__ == "__main__":
    unittest.main()
