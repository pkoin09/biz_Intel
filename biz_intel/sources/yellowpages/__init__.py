"""
Yellow Pages source plugin.
"""

SOURCE_NAME = "yellowpages"

from .spider import YellowPagesSpider
from .extractor import YellowPagesExtractor
from .urls import build_search_url

__all__ = [
    "SOURCE_NAME",
    "YellowPagesSpider",
    "YellowPagesExtractor",
    "build_search_url",
]
