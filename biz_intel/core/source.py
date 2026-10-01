"""
Base source interface.
"""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from collections.abc import Iterator

from biz_intel.models.business import Business


class BaseSource(ABC):
    """
    Base class for all business data sources.

    Every source is responsible for producing Business
    objects, regardless of where the data originates.
    """

    source_name: str = ""

    @abstractmethod
    def extract(self) -> Iterator[Business]:
        """
        Yield Business records from this source.
        """
        raise NotImplementedError
