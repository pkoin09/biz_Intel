"""Offline fixture manifest validation.

Provider parsers are exercised with repository fixtures, never a provider's
runtime cache or an unreviewed captured response.  This module keeps that
boundary small and dependency-free: a fixture is admitted only when its
manifest records a synthetic sanitization claim, its content hash, and a
policy that permits fixtures for the source.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from .source_policy import FixtureBehavior, SourcePolicy


class FixturePolicyError(ValueError):
    """Raised when a fixture cannot be used in an offline test."""


@dataclass(frozen=True, slots=True)
class FixtureManifestEntry:
    """A reviewed fixture declaration kept beside the fixture files."""

    source: str
    path: str
    sha256: str
    sanitization: str
    contains_real_contact_data: bool

    @classmethod
    def from_mapping(cls, value: object) -> "FixtureManifestEntry":
        if not isinstance(value, dict):
            raise FixturePolicyError("Fixture manifest entry must be an object.")
        try:
            return cls(
                source=str(value["source"]),
                path=str(value["path"]),
                sha256=str(value["sha256"]),
                sanitization=str(value["sanitization"]),
                contains_real_contact_data=bool(value["contains_real_contact_data"]),
            )
        except KeyError as error:
            raise FixturePolicyError(
                f"Fixture manifest entry is missing {error.args[0]!r}."
            ) from error


def load_fixture_manifest(path: Path) -> tuple[FixtureManifestEntry, ...]:
    """Load the versioned JSON manifest without touching network state."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FixturePolicyError(f"Cannot read fixture manifest {path}: {error}") from error

    if not isinstance(payload, dict) or not isinstance(payload.get("fixtures"), list):
        raise FixturePolicyError("Fixture manifest must contain a 'fixtures' list.")
    return tuple(FixtureManifestEntry.from_mapping(item) for item in payload["fixtures"])


def validate_offline_fixture(
    entry: FixtureManifestEntry,
    policy: SourcePolicy,
    fixture_root: Path,
) -> Path:
    """Validate a fixture and return its safe local path.

    ``SANITIZED_ONLY`` fixtures are intentionally conservative: they must be
    declared synthetic, contain no real contact data, use an integrity hash,
    and only reference RFC-reserved ``.example.test`` URLs.  A source with a
    ``PROHIBITED`` fixture policy cannot opt itself back in through metadata.
    """

    if policy.fixture_behavior is FixtureBehavior.PROHIBITED:
        raise FixturePolicyError(f"Fixtures are prohibited for source {entry.source!r}.")

    root = fixture_root.resolve()
    candidate = (root / entry.path).resolve()
    if candidate == root or root not in candidate.parents:
        raise FixturePolicyError("Fixture path must stay inside the fixture directory.")
    if not candidate.is_file():
        raise FixturePolicyError(f"Fixture file does not exist: {entry.path}")

    if policy.fixture_behavior is FixtureBehavior.SANITIZED_ONLY:
        if entry.sanitization != "synthetic" or entry.contains_real_contact_data:
            raise FixturePolicyError(
                "Sanitized-only fixtures must be synthetic and contain no real contact data."
            )
        if not re.fullmatch(r"[0-9a-f]{64}", entry.sha256):
            raise FixturePolicyError("Fixture sha256 must be a lowercase SHA-256 digest.")

    raw = candidate.read_bytes()
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != entry.sha256:
        raise FixturePolicyError(f"Fixture integrity hash does not match: {entry.path}")

    if policy.fixture_behavior is FixtureBehavior.SANITIZED_ONLY:
        _validate_synthetic_json(raw, entry.path)

    return candidate


def _validate_synthetic_json(raw: bytes, path: str) -> None:
    """Reject obvious credentials or real-looking web endpoints in JSON fixtures."""

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise FixturePolicyError(f"Synthetic fixture must be JSON: {path}") from error

    for key, value in _walk_json(payload):
        if key and key.casefold() in {"api_key", "authorization", "cookie", "password", "token"}:
            raise FixturePolicyError(f"Synthetic fixture contains prohibited key {key!r}.")
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            hostname = urlparse(value).hostname or ""
            if not hostname.endswith(".example.test"):
                raise FixturePolicyError(
                    "Synthetic fixture URLs must use the reserved .example.test domain."
                )


def _walk_json(value: object, key: str | None = None):
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            yield from _walk_json(child_value, str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)
    else:
        yield key, value
