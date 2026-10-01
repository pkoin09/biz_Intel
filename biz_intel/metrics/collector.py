"""
Pipeline metrics collector.
"""

from __future__ import annotations


class MetricsCollector:

    def __init__(self) -> None:

        self._metrics: dict[str, int] = {}

    def increment(
        self,
        name: str,
        amount: int = 1,
    ) -> None:

        self._metrics[name] = (
            self._metrics.get(name, 0)
            + amount
        )

    def get(
        self,
        name: str,
    ) -> int:

        return self._metrics.get(
            name,
            0,
        )

    def items(self):

        return self._metrics.items()

    def clear(self) -> None:

        self._metrics.clear()


metrics = MetricsCollector()
