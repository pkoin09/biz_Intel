"""
Source plugin registry.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from biz_intel.models.business import Business

from .api_executor import ApiSourceExecutor
from .apify_executor import ApifySourceExecutor
from .executor import SourceExecutor
from .file_executor import FileSourceExecutor
from .scrapy_executor import ScrapySourceExecutor
from .source_kind import SourceKind
from .source_policy import SourcePolicy
from .source_policy import SourcePolicyError
from .source_task import SourceTask


class SourceRegistry:
    """
    Registry of available source plugins.

    Owns the SourceTask -> Business execution boundary: each registered
    source carries a SourceKind, and run() dispatches to the SourceExecutor
    for that kind, so callers never need to know how a given source runs.
    """

    def __init__(
        self,
        executors: dict[SourceKind, SourceExecutor] | None = None,
    ) -> None:
        self._sources: dict[str, tuple[type[Any], SourceKind, SourcePolicy]] = {}
        self._executors = executors or {
            SourceKind.FILE: FileSourceExecutor(),
            SourceKind.SCRAPER: ScrapySourceExecutor(),
            SourceKind.API: ApiSourceExecutor(),
            SourceKind.APIFY: ApifySourceExecutor(),
        }

    def register(
        self,
        name: str,
        source: type[Any],
        kind: SourceKind,
        policy: SourcePolicy,
    ) -> None:
        key = name.lower()

        if key in self._sources:
            raise ValueError(f"Source '{name}' is already registered.")

        self._sources[key] = (source, kind, policy)

    def unregister(
        self,
        name: str,
    ) -> None:
        self._sources.pop(name.lower(), None)

    def get(
        self,
        name: str,
    ) -> type[Any]:
        return self._sources[name.lower()][0]

    def get_kind(
        self,
        name: str,
    ) -> SourceKind:
        return self._sources[name.lower()][1]

    def get_policy(
        self,
        name: str,
    ) -> SourcePolicy:
        """Return the declared use policy for a registered source."""

        return self._sources[name.lower()][2]

    def require_delivery_approval(self, names: tuple[str, ...]) -> None:
        """Reject a delivery job before it can execute an unapproved source."""

        rejected: list[str] = []
        for name in names:
            try:
                policy = self.get_policy(name)
            except KeyError:
                rejected.append(f"{name} (not registered)")
                continue
            if not policy.allows_delivery:
                rejected.append(
                    f"{name} ({policy.source_class.value}; delivery disabled)"
                )

        if rejected:
            sources = ", ".join(rejected)
            raise SourcePolicyError(
                "Job cannot execute delivery sources without approval: "
                f"{sources}."
            )

    def require_live_smoke_approval(self, names: tuple[str, ...]) -> None:
        """Reject a live smoke run unless every source is explicitly approved."""

        rejected: list[str] = []
        for name in names:
            try:
                policy = self.get_policy(name)
            except KeyError:
                rejected.append(f"{name} (not registered)")
                continue
            if not policy.allows_live_smoke:
                rejected.append(
                    f"{name} ({policy.source_class.value}; live smoke disabled)"
                )
            elif policy.cost_model != "zero-spend":
                rejected.append(
                    f"{name} ({policy.source_class.value}; not zero-spend)"
                )

        if rejected:
            sources = ", ".join(rejected)
            raise SourcePolicyError(
                "Job cannot execute live smoke sources without approval: "
                f"{sources}."
            )

    def list(self) -> list[str]:
        return sorted(self._sources.keys())

    def run(
        self,
        name: str,
        task: SourceTask,
    ) -> Iterator[Business]:
        source_class, kind, _policy = self._sources[name.lower()]
        executor = self._executors[kind]
        return executor.run(source_class, task)


registry = SourceRegistry()
