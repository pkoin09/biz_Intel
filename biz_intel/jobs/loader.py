"""Load YAML job specifications."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import JobSpec


def load_job(path: str | Path) -> JobSpec:
    """Load a versioned YAML job specification from disk."""

    job_path = Path(path)
    with job_path.open(encoding="utf-8") as file:
        data: Any = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError("Job file must contain a YAML mapping.")

    return JobSpec.from_dict(data)
