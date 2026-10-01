"""
Yellow Pages extractor.

Responsible for converting HTML into BusinessItems.
"""

from __future__ import annotations

from datetime import datetime

from scrapy.http import Response

from biz_intel.core import BaseExtractor
from biz_intel.items import BusinessItem

from . import selectors


class YellowPagesExtractor(BaseExtractor):
    """
    Extract businesses from Yellow Pages.
    """

    def extract(
        self,
        response: Response,
    ):

        cards = response.css(selectors.BUSINESS_CARD)

        for card in cards:

            yield self.build_item(
                response,
                card,
            )

    def build_item(
        self,
        response: Response,
        card,
    ) -> BusinessItem:

        item = BusinessItem(
            {
                #
                # Identity
                #
                "name": self.text(
                    card,
                    selectors.NAME,
                ),
                "category": self.text(
                    card,
                    selectors.CATEGORY,
                ),
                #
                # Address
                #
                "address": self.text(
                    card,
                    selectors.STREET,
                ),
                "city": "",
                "state": "",
                "postal_code": "",
                "country": "USA",
                #
                # Contact
                #
                "phone": self.text(
                    card,
                    selectors.PHONE,
                ),
                "website": self.attribute(
                    card,
                    selectors.WEBSITE,
                    "href",
                ),
                "email": "",
                #
                # Social
                #
                "facebook": "",
                "instagram": "",
                "linkedin": "",
                "twitter": "",
                #
                # Ratings
                #
                "rating": self.text(
                    card,
                    selectors.RATING,
                ),
                "review_count": self.text(
                    card,
                    selectors.REVIEWS,
                ),
                #
                # Metadata
                #
                "source": "yellowpages",
                "source_url": response.url,
                "scraped_at": datetime.utcnow(),
                "raw_data": {},
            }
        )

        return item

    @staticmethod
    def text(
        selector,
        css: str,
    ) -> str:

        value = selector.css(f"{css}::text").get()

        return value.strip() if value else ""

    @staticmethod
    def attribute(
        selector,
        css: str,
        attribute: str,
    ) -> str:

        value = selector.css(css).attrib.get(attribute, "")

        return value.strip()
