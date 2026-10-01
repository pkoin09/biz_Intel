"""
Executor for Apify actor-backed sources.
"""

from __future__ import annotations

from collections.abc import Iterator

from biz_intel.models.business import Business

from .executor import SourceExecutor
from .source_task import SourceTask


class ApifySourceExecutor(SourceExecutor):

    def run(self, source_class: type, task: SourceTask) -> Iterator[Business]:
        source = source_class(task)
        return source.fetch()
