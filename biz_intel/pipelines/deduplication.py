"""
Business deduplication pipeline.
"""

from __future__ import annotations

from collections.abc import Iterator
from difflib import SequenceMatcher

from .base import Pipeline
from biz_intel.deduplication import (
    IdentifierMatchStrategy,
)
from biz_intel.models.business import Business
from biz_intel.metrics import metrics


class DeduplicationPipeline(Pipeline):
    """
    Remove duplicate Business records.
    """

    def __init__(self, *, fuzzy: bool = False) -> None:
        self.strategy = IdentifierMatchStrategy()
        self.fuzzy = fuzzy

    def process(
        self,
        businesses: Iterator[Business],
    ) -> Iterator[Business]:

        seen = set()
        retained: list[Business] = []

        for business in businesses:

            key = self.strategy.key(
                business,
            )

            if key in seen:
                # Temporary debug print
                metrics.increment("duplicates_removed",)
                # TODO:
                # Replace with proper logging.
                # print(
                #     f"Duplicate removed: {business.name}"
                # )
                continue

            if self.fuzzy and self._strong_fuzzy_match(business, retained):
                metrics.increment("fuzzy_duplicates_removed")
                continue

            seen.add(key)
            retained.append(business)

            yield business

    @staticmethod
    def _strong_fuzzy_match(candidate: Business, retained: list[Business]) -> bool:
        """Merge only near-identical names at the same normalized location."""
        name = _comparison_name(candidate.name)
        address = candidate.address.casefold().strip()
        if not name or not address:
            return False
        for existing in retained:
            if address != existing.address.casefold().strip():
                continue
            similarity = SequenceMatcher(None, name, _comparison_name(existing.name)).ratio()
            if similarity >= 0.96:
                return True
        return False


def _comparison_name(value: str) -> str:
    tokens = value.casefold().replace(".", "").split()
    return " ".join(token for token in tokens if token not in {"llc", "inc", "ltd"})
