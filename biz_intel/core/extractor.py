"""
Base extractor interface.

Every source extractor should inherit from this class.
"""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod

from scrapy.http import Response


class BaseExtractor(ABC):
    """
    Base class for all source extractors.
    """

    @abstractmethod
    def extract(
        self,
        response: Response,
    ):
        """
        Extract one or more BusinessItems
        from a response.
        """
        raise NotImplementedError
