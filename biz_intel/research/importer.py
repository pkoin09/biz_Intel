"""Start a research session from a previously exported result set."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import fields
from pathlib import Path

from biz_intel.models import Business

from .session import ResearchSession


_BUSINESS_FIELDS = {field.name for field in fields(Business)}
_NPI_URL = re.compile(r"npiregistry\.cms\.hhs\.gov/provider-view/(\d{10})(?:\D|$)", re.I)


def load_business_records(source: str | Path) -> list[Business]:
    """Load a safe business projection from a CSV or JSON result file."""

    path = Path(source)
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as file:
            rows: object = list(csv.DictReader(file))
    elif suffix == ".json":
        try:
            rows = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"Unable to parse research import: {path}") from exc
    else:
        raise ValueError("Research import must use a .csv or .json source.")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Research import must contain a list of business records.")

    return [_business_from_row(row) for row in rows]


def import_research_session(source: str | Path, request: str) -> ResearchSession:
    """Load a safe business projection from CSV or JSON for continued research."""

    return ResearchSession(request, load_business_records(source))


def _business_from_row(row: dict[str, object]) -> Business:
    data = {
        key: value
        for key, value in row.items()
        if key in _BUSINESS_FIELDS and value not in (None, "")
    }
    source_url = str(data.get("source_url", ""))
    npi_match = _NPI_URL.search(source_url)
    if npi_match:
        data.setdefault("source", "nppes")
        data.setdefault("discovery_sources", ("nppes",))
        data.setdefault("source_ids", {"npi": npi_match.group(1)})
    return Business.from_dict(data)
