"""
Core framework components.
"""

from .api_source import BaseApiSource
from .apify_source import BaseApifySource
from .extractor import BaseExtractor

__all__ = [
    "BaseApiSource",
    "BaseApifySource",
    "BaseExtractor",
]
