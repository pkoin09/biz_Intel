"""
Business normalization pipeline.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import fields

from .base import Pipeline
from biz_intel.models.business import Business
from biz_intel.normalizers import registry


class NormalizationPipeline(Pipeline):

    def process(
        self,
        businesses: Iterator[Business],
    ) -> Iterator[Business]:

        for business in businesses:

            for field in fields(business):

                normalizer = registry.get(
                    field.name,
                )

                if normalizer is None:
                    continue

                value = getattr(
                    business,
                    field.name,
                )

                setattr(
                    business,
                    field.name,
                    normalizer(value),
                )

            yield business
