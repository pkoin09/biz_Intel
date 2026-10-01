"""
Scrapy Items.

These represent the data extracted by spiders before
being processed by pipelines.
"""

import scrapy


class BusinessItem(scrapy.Item):

    # Identity
    name = scrapy.Field()
    category = scrapy.Field()

    # Location
    address = scrapy.Field()
    city = scrapy.Field()
    state = scrapy.Field()
    postal_code = scrapy.Field()
    country = scrapy.Field()

    # Contact
    phone = scrapy.Field()
    email = scrapy.Field()
    website = scrapy.Field()

    # Socials
    facebook = scrapy.Field()
    instagram = scrapy.Field()
    linkedin = scrapy.Field()
    twitter = scrapy.Field()

    # Business Metrics
    rating = scrapy.Field()
    review_count = scrapy.Field()

    # Metadata
    source = scrapy.Field()
    source_url = scrapy.Field()
    scraped_at = scrapy.Field()

    # Raw payload
    raw_data = scrapy.Field()
