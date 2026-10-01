"""
Base class for file-based sources.
"""

from __future__ import annotations

from pathlib import Path

from biz_intel.core.source import BaseSource


class FileSource(BaseSource):
    """
    Base class for file-based sources.
    """

    def __init__(
        self,
        path: str | Path,
    ) -> None:

        self.path = Path(path)

        if not self.path.exists():
            raise FileNotFoundError(f"File not found: {self.path}")
