"""
Base class for API-backed sources.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from biz_intel.models.business import Business

from .source_task import SourceTask


class BaseApiSource(ABC):
    """
    Contract for sources that fetch data from an external API.

    Concrete subclasses receive the SourceTask on construction and
    implement fetch() to yield Business records.
    """

    def __init__(self, task: SourceTask) -> None:
        self.task = task

    @abstractmethod
    def fetch(self) -> Iterator[Business]:
        raise NotImplementedError
