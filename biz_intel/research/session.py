"""A result set that survives multiple research refinements."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from biz_intel.models.business import Business


@dataclass(frozen=True, slots=True)
class RefinementStep:
    """A compact audit entry for one plugin application."""

    instruction: str
    plugin: str
    before_count: int
    after_count: int
    applied_at: datetime
    note: str = ""
    details: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class CompositionStep:
    """Audit entry for one supplemental result set attached to a session."""

    source: str
    source_file: str
    record_count: int
    matched_count: int
    ambiguous_count: int
    candidate_count: int
    website_count: int
    applied_at: datetime
    contact_count: int = 0
    matches: tuple[dict[str, object], ...] = ()


@dataclass(slots=True)
class ResearchSession:
    """The current state of one progressively refined investigation."""

    request: str
    businesses: list[Business]
    session_id: str = field(default_factory=lambda: uuid4().hex[:12])
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    refinements: list[RefinementStep] = field(default_factory=list)
    compositions: list[CompositionStep] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.request.strip():
            raise ValueError("A research request is required.")

    def save(self, destination: str | Path) -> Path:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "session_id": self.session_id,
            "request": self.request,
            "created_at": self.created_at.isoformat(),
            "businesses": [business.to_dict() for business in self.businesses],
            "refinements": [asdict(step) for step in self.refinements],
            "compositions": [asdict(step) for step in self.compositions],
        }
        path.write_text(json.dumps(payload, indent=2, default=_json_default))
        return path

    @classmethod
    def load(cls, source: str | Path) -> "ResearchSession":
        path = Path(source)
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to load research session: {path}") from exc
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("Research session must be a version 1 mapping.")
        try:
            return cls(
                session_id=payload["session_id"],
                request=payload["request"],
                created_at=datetime.fromisoformat(payload["created_at"]),
                businesses=[Business.from_dict(item) for item in payload["businesses"]],
                refinements=[
                    RefinementStep(
                        **{
                            **item,
                            "applied_at": datetime.fromisoformat(item["applied_at"]),
                            "details": tuple(item.get("details", ())),
                        }
                    )
                    for item in payload["refinements"]
                ],
                compositions=[
                    CompositionStep(
                        **{
                            **item,
                            "applied_at": datetime.fromisoformat(item["applied_at"]),
                            "matches": tuple(item.get("matches", ())),
                        }
                    )
                    for item in payload.get("compositions", ())
                ],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Research session has an invalid shape.") from exc


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}.")
