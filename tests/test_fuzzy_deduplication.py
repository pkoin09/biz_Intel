"""Regression coverage for opt-in conservative fuzzy deduplication."""

from __future__ import annotations

import unittest

from biz_intel.core.pipeline import PipelineRunner
from biz_intel.models.business import Business


def _business(name: str, address: str) -> Business:
    return Business(name=name, address=address, city="Denver", state="CO")


class FuzzyDeduplicationTests(unittest.TestCase):
    def test_high_confidence_variant_merges_only_when_enabled(self) -> None:
        records = [_business("Peak Office Care", "1000 Market St"), _business("Peak Office Care LLC", "1000 Market St")]
        self.assertEqual(len(list(PipelineRunner().run(iter(records)))), 2)
        self.assertEqual(len(list(PipelineRunner(fuzzy_deduplicate=True).run(iter(records)))), 1)

    def test_same_name_at_different_address_is_not_merged(self) -> None:
        records = [_business("Peak Office Care", "1000 Market St"), _business("Peak Office Care LLC", "2000 Market St")]
        self.assertEqual(len(list(PipelineRunner(fuzzy_deduplicate=True).run(iter(records)))), 2)
