"""
Pipeline base class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from biz_intel.models.business import Business


class Pipeline(ABC):
    """
    Base pipeline.
    """

    @abstractmethod
    def process(
        self,
        businesses: Iterator[Business],
    ) -> Iterator[Business]:
        ...
