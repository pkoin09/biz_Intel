"""
Base spider for browser-driven business sources.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import scrapy

from biz_intel.browser import BrowserActions
from biz_intel.browser.helpers import screenshot_name
from biz_intel.config import config
from biz_intel.services.logger import FrameworkLogger


def should_follow_next_page(
    page: int,
    page_count: int,
    seen: int,
    limit: int,
    max_pages: int | None,
) -> bool:
    """
    Decide whether a paginating spider should request the next results page.

    Follow the next page only when the current page yielded items, the task
    ceiling has not been reached, and (when capped) more pages are allowed.
    An empty page means the results ran out, which terminates the crawl.
    """

    if page_count <= 0:
        return False

    if seen >= limit:
        return False

    if max_pages is not None and page >= max_pages:
        return False

    return True


class BaseBusinessSpider(
    scrapy.Spider,
    ABC,
):
    """
    Base class for browser-powered business spiders.

    Child spiders are responsible only for:

    - Building the search URL
    - Choosing an extractor

    Everything else is handled here.
    """

    source_name = ""

    extractor_class = None

    # Spiders that opt into walking multiple results pages set this True.
    # Off by default so a source must explicitly choose pagination.
    paginates = False

    custom_settings = {
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 30000,
    }

    def __init__(
        self,
        query: str = "",
        location: str = "",
        limit: int = 10,
        options: dict | None = None,
        *args,
        **kwargs,
    ):

        super().__init__(
            *args,
            **kwargs,
        )

        self.query = query
        self.location = location
        self.limit = int(limit)

        self.options = options or {}

        raw_max_pages = self.options.get("max_pages")
        self.max_pages = int(raw_max_pages) if raw_max_pages is not None else None

        self._seen = 0

        self.log = FrameworkLogger(self.name)

    @abstractmethod
    def build_search_url(self, page: int = 1) -> str:
        """
        Return the URL for the source; ``page`` is the 1-based results page.
        """

    async def start(self):

        url = self.build_search_url()

        self.log.section(f"{self.source_name.upper()} SEARCH")

        self.log.info(f"Query     : {self.query}")

        self.log.info(f"Location  : {self.location}")

        self.log.info(f"Limit     : {self.limit}")

        self.log.info(f"URL       : {url}")

        yield scrapy.Request(
            url,
            callback=self.parse,
            meta={
                "playwright": True,
                "playwright_include_page": True,
                "handle_httpstatus_all": True,
                "page": 1,
            },
        )

    async def parse(
        self,
        response,
    ):

        page_number = response.meta.get("page", 1)

        page = response.meta.get("playwright_page")
        if page is None:
            self.log.error(
                "Playwright page missing. " "Request did not use Playwright."
            )
            return

        self.log.info("Browser loaded.")

        self.log.info(f"Status Code : {response.status}")

        self.log.info(f"Final URL   : {response.url}")

        #
        # Browser lifecycle now belongs here
        #

        await BrowserActions.prepare(page)

        if page_number == 1:
            screenshot = config.SCREENSHOT_PATH / screenshot_name(
                f"{self.source_name}_{self.query}"
            )

            await BrowserActions.screenshot(
                page,
                screenshot,
            )

            self.log.info(f"Screenshot saved: {screenshot.name}")

        extractor = self.extractor_class()

        page_count = 0

        for item in extractor.extract(response):

            if self._seen >= self.limit:
                break

            self._seen += 1
            page_count += 1

            yield item

        self.log.success(
            f"Page {page_number}: extracted {page_count} businesses "
            f"(total {self._seen})."
        )

        if self.paginates and should_follow_next_page(
            page_number,
            page_count,
            self._seen,
            self.limit,
            self.max_pages,
        ):
            next_url = self.build_search_url(page=page_number + 1)

            await page.close()

            yield scrapy.Request(
                next_url,
                callback=self.parse,
                meta={
                    **response.meta,
                    "page": page_number + 1,
                },
            )

            return

        await page.close()
