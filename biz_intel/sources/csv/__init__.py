"""
CSV source plugin.
"""

SOURCE_NAME = "csv"

from .source import CSVSource
from .extractor import CSVExtractor

__all__ = [
    "SOURCE_NAME",
    "CSVSource",
    "CSVExtractor",
]
