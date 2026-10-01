"""Tests for the file-based SourceExecutor."""

from __future__ import annotations

from pathlib import Path
import unittest

from biz_intel.core.file_executor import FileSourceExecutor
from biz_intel.core.source_name import SourceName
from biz_intel.core.source_task import SourceTask
from biz_intel.sources.csv import CSVSource


SAMPLE_CSV = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/businesses_messy_synthetic.csv"
)


class FileSourceExecutorTests(unittest.TestCase):
    """Protect the file-executor's public contract."""

    def test_runs_a_file_source_from_task_options(self) -> None:
        task = SourceTask(
            source=SourceName.YELLOWPAGES,
            options={"path": SAMPLE_CSV},
        )

        businesses = list(FileSourceExecutor().run(CSVSource, task))

        self.assertEqual(len(businesses), 18)

    def test_raises_for_a_missing_file(self) -> None:
        task = SourceTask(
            source=SourceName.YELLOWPAGES,
            options={"path": "does/not/exist.csv"},
        )

        with self.assertRaises(FileNotFoundError):
            FileSourceExecutor().run(CSVSource, task)


if __name__ == "__main__":
    unittest.main()
