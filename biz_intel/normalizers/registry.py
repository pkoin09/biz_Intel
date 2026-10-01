"""
Normalizer registry.
"""

from __future__ import annotations

from collections.abc import Callable

Normalizer = Callable[[str], str]


class NormalizerRegistry:

    def __init__(self):

        self._registry: dict[str, Normalizer] = {}

    def register(
        self,
        field: str,
        normalizer: Normalizer,
    ) -> None:

        self._registry[field] = normalizer

    def get(
        self,
        field: str,
    ) -> Normalizer | None:

        return self._registry.get(field)


registry = NormalizerRegistry()
