"""
Source execution boundary: SourceTask -> Business.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from biz_intel.models.business import Business

from .source_task import SourceTask


class RetryableSourceError(Exception):
    """A transient source failure that a bounded runner may retry.

    Executors raise this only when another attempt could reasonably succeed
    (for example, a temporary timeout or rate-limit response). All other
    exceptions are recorded as fatal for the current task.
    """


class SourceExecutor(ABC):
    """
    Runs a registered source class against a SourceTask.

    Concrete executors bridge whatever lifecycle a source's class requires
    (a plain generator, a Scrapy CrawlerProcess, ...) to this one contract,
    so SourceTask -> Business does not depend on how a given source runs.
    """

    @abstractmethod
    def run(
        self,
        source_class: type,
        task: SourceTask,
    ) -> Iterator[Business]:
        """
        Execute source_class for task, yielding Business records.
        """
        raise NotImplementedError
