"""
CSV source.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator

from biz_intel.core.file_source import FileSource
from biz_intel.models.business import Business

from .extractor import CSVExtractor


class CSVSource(FileSource):
    """
    CSV business source.
    """

    source_name = "csv"

    def __init__(self, path):

        super().__init__(path)

        self.extractor = CSVExtractor()

    def extract(self) -> Iterator[Business]:

        with self.path.open(
            newline="",
            encoding="utf-8-sig",
        ) as file:

            reader = csv.DictReader(file)

            for row in reader:

                yield self.extractor.extract(row)
