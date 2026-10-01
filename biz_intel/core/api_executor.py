"""
Executor for API-backed sources.
"""

from __future__ import annotations

from collections.abc import Iterator

from biz_intel.models.business import Business

from .executor import SourceExecutor
from .source_task import SourceTask


class ApiSourceExecutor(SourceExecutor):
    """
    Runs a BaseApiSource subclass by constructing it from the task
    and calling fetch().

    No subprocess isolation is needed — API sources are plain HTTP
    clients and carry no Twisted reactor or similar lifecycle constraints.
    """

    def run(
        self,
        source_class: type,
        task: SourceTask,
    ) -> Iterator[Business]:
        source = source_class(task)
        return source.fetch()
