"""
Executor for browser-driven (Scrapy) sources.

Each run() call executes the spider in its own subprocess. Twisted's
reactor cannot be restarted once stopped in the same process, so a fresh
subprocess gives every crawl a fresh reactor instead of crashing on the
second SourceTask a run touches.
"""

from __future__ import annotations

import multiprocessing
from collections.abc import Iterator

from biz_intel.models.business import Business

from .executor import SourceExecutor
from .location import Location
from .source_task import SourceTask


def _location_string(location: Location | None) -> str:
    if location is None:
        return ""
    return ", ".join(part for part in (location.city, location.state) if part)


def _crawl(
    source_class: type,
    query: str,
    location: str,
    limit: int,
    options: dict,
    queue: multiprocessing.Queue,
) -> None:
    """
    Runs in a fresh subprocess; owns its own Twisted reactor for the
    duration of exactly one crawl.
    """

    import biz_intel.settings as settings_module
    from scrapy import signals
    from scrapy.crawler import CrawlerProcess
    from scrapy.settings import Settings

    settings = Settings()
    settings.setmodule(settings_module)

    process = CrawlerProcess(settings)
    crawler = process.create_crawler(source_class)
    crawler.signals.connect(
        lambda item, response, spider: queue.put(item),
        signal=signals.item_scraped,
        weak=False,
    )
    process.crawl(
        crawler,
        query=query,
        location=location,
        limit=limit,
        options=options,
    )
    process.start()

    queue.put(None)


class ScrapySourceExecutor(SourceExecutor):
    """
    Runs a BaseBusinessSpider subclass in an isolated subprocess and
    streams the Business items it scrapes back to the caller.

    Translates SourceTask.location (a Location) into the plain
    "City, State" string a spider's build_search_url() expects.
    """

    def run(
        self,
        source_class: type,
        task: SourceTask,
    ) -> Iterator[Business]:
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()

        process = ctx.Process(
            target=_crawl,
            args=(
                source_class,
                task.category or "",
                _location_string(task.location),
                task.limit or 10,
                task.options or {},
                queue,
            ),
        )
        process.start()

        return self._drain(queue, process)

    def _drain(
        self,
        queue: multiprocessing.Queue,
        process: multiprocessing.process.BaseProcess,
    ) -> Iterator[Business]:
        try:
            while True:
                item = queue.get()
                if item is None:
                    break
                yield item
        finally:
            process.join()
