from dataclasses import dataclass


@dataclass(slots=True)
class Location:
    city: str | None = None
    state: str |None = None
    country: str | None = None
    postal_code: str | None = None

    radius: int | None = None
