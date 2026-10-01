"""
Source execution families.
"""

from enum import StrEnum


class SourceKind(StrEnum):
    """
    How a registered source is executed.

    Determines which SourceExecutor runs a source, independent of the
    source class's own inheritance (see SourceExecutor).
    """

    FILE = "file"
    SCRAPER = "scraper"
    API = "api"
    APIFY = "apify"
