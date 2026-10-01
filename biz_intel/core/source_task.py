from dataclasses import dataclass, field
from typing import Any

from .location import Location
from .source_name import SourceName


@dataclass(slots=True)
class SourceTask:
    source: SourceName

    category: str | None = None
    keywords: list[str] = field(default_factory=list)

    location: Location | None = None

    limit: int | None = None

    options: dict[str, Any] = field(default_factory=dict)
