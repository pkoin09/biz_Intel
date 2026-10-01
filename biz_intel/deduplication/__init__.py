"""
Business deduplication.
"""

from .strategy import ExactMatchStrategy
from .identifier import IdentifierMatchStrategy

__all__ = [
    "ExactMatchStrategy",
    "IdentifierMatchStrategy",
]
