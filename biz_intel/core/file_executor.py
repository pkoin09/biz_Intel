"""
Executor for file-based sources.
"""

from __future__ import annotations

from collections.abc import Iterator

from biz_intel.models.business import Business

from .executor import SourceExecutor
from .source_task import SourceTask


class FileSourceExecutor(SourceExecutor):
    """
    Runs a BaseSource subclass by constructing it from task.options and
    calling .extract().

    Stays neutral about what a given file source's constructor needs
    (e.g. CSVSource's path) by passing task.options through as kwargs.
    """

    def run(
        self,
        source_class: type,
        task: SourceTask,
    ) -> Iterator[Business]:
        source = source_class(**task.options)
        return source.extract()
