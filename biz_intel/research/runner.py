"""Apply small plugins to the same research session."""

from __future__ import annotations

from datetime import datetime, timezone

from .plugins import RefinementPlugin
from .session import RefinementStep, ResearchSession


class ResearchRunner:
    def __init__(self, plugins: list[RefinementPlugin] | None = None) -> None:
        self._plugins = {plugin.name: plugin for plugin in plugins or []}

    def register(self, plugin: RefinementPlugin) -> None:
        if plugin.name in self._plugins:
            raise ValueError(f"Research plugin already registered: {plugin.name}")
        self._plugins[plugin.name] = plugin

    def refine(
        self,
        session: ResearchSession,
        instruction: str,
        *,
        plugin: str,
    ) -> ResearchSession:
        if not instruction.strip():
            raise ValueError("A refinement instruction is required.")
        try:
            selected = self._plugins[plugin]
        except KeyError as exc:
            raise KeyError(f"Unknown research plugin: {plugin}") from exc

        before_count = len(session.businesses)
        result = selected.apply(list(session.businesses), instruction)
        session.businesses = list(result.businesses)
        session.refinements.append(
            RefinementStep(
                instruction=instruction,
                plugin=plugin,
                before_count=before_count,
                after_count=len(session.businesses),
                applied_at=datetime.now(timezone.utc),
                note=result.note,
            )
        )
        return session
