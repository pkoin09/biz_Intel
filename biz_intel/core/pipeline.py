"""
Pipeline runner.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from biz_intel.metrics import metrics
from biz_intel.models.business import Business
from biz_intel.pipelines import (
    DeduplicationPipeline,
    NormalizationPipeline,
    ValidationPipeline,
)


class PipelineRunner:

    def __init__(self, *, fuzzy_deduplicate: bool = False) -> None:

        self.pipelines = [
            ValidationPipeline(),
            NormalizationPipeline(),
            DeduplicationPipeline(fuzzy=fuzzy_deduplicate),
        ]

    def run(
        self,
        businesses: Iterator[Business],
        *,
        on_stage_complete: Callable[[str, int], None] | None = None,
    ) -> Iterator[Business]:

        metrics.clear()

        for pipeline in self.pipelines:
            businesses = pipeline.process(
                businesses,
            )
            if on_stage_complete is not None:
                completed = list(businesses)
                on_stage_complete(_stage_name(pipeline), len(completed))
                businesses = iter(completed)

        return businesses


def _stage_name(pipeline: object) -> str:
    """Return a stable, human-readable stage label for optional progress."""

    return type(pipeline).__name__.removesuffix("Pipeline").lower()
