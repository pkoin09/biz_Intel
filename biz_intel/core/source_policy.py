"""Source-use policy metadata and delivery guardrails.

Policies live beside the plugin registry so a source's technical execution
mechanism cannot accidentally be confused with whether its results are fit for
client delivery.  A registered source must declare its policy explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SourceClass(StrEnum):
    """The approved-use class for a data source."""

    CLIENT_INPUT = "client_input"
    OFFICIAL_REGISTRY = "official_registry"
    LICENSED = "licensed"
    FIRST_PARTY_WEB = "first_party_web"
    EXPERIMENTAL_OR_DISALLOWED = "experimental_or_disallowed"


class RetentionBehavior(StrEnum):
    """How source data may be retained outside a specific run."""

    CLIENT_CONTROLLED = "client_controlled"
    SOURCE_TERMS = "source_terms"
    LICENSE_TERMS = "license_terms"
    EPHEMERAL = "ephemeral"


class FixtureBehavior(StrEnum):
    """Whether source-shaped test fixtures may be kept in the repository."""

    ALLOWED = "allowed"
    SANITIZED_ONLY = "sanitized_only"
    PROHIBITED = "prohibited"


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    """Use constraints declared by every registered source plugin."""

    source_class: SourceClass
    delivery_allowed: bool
    export_allowed: bool
    retention: RetentionBehavior
    fixture_behavior: FixtureBehavior
    attribution: str = ""
    field_coverage: tuple[str, ...] = ()
    rate_limit: str = ""
    cost_model: str = "zero-spend"
    runtime_cache_ttl_days: int = 0
    live_smoke_allowed: bool = False
    enabled: bool = True

    @property
    def allows_delivery(self) -> bool:
        """Whether the source can participate in a client-exporting job."""

        return self.enabled and self.delivery_allowed and self.export_allowed

    @property
    def allows_live_smoke(self) -> bool:
        """Whether this specific source has been approved for a live smoke run."""

        return self.enabled and self.live_smoke_allowed


CLIENT_INPUT_POLICY = SourcePolicy(
    source_class=SourceClass.CLIENT_INPUT,
    delivery_allowed=True,
    export_allowed=True,
    retention=RetentionBehavior.CLIENT_CONTROLLED,
    fixture_behavior=FixtureBehavior.SANITIZED_ONLY,
    field_coverage=("client-supplied fields",),
    cost_model="client engagement controlled",
    runtime_cache_ttl_days=0,
)

OFFICIAL_REGISTRY_POLICY = SourcePolicy(
    source_class=SourceClass.OFFICIAL_REGISTRY,
    delivery_allowed=True,
    export_allowed=True,
    retention=RetentionBehavior.SOURCE_TERMS,
    fixture_behavior=FixtureBehavior.SANITIZED_ONLY,
    field_coverage=("identity", "location"),
    cost_model="review before use",
    runtime_cache_ttl_days=0,
)

# CMS's public NPPES Registry is the narrow, approved V1 acquisition path.
# This policy describes the connector's operational boundary, not a blanket
# license for every government registry.
NPPES_POLICY = SourcePolicy(
    source_class=SourceClass.OFFICIAL_REGISTRY,
    delivery_allowed=True,
    export_allowed=True,
    retention=RetentionBehavior.SOURCE_TERMS,
    fixture_behavior=FixtureBehavior.SANITIZED_ONLY,
    attribution="CMS NPPES NPI Registry",
    field_coverage=("provider identity", "practice location", "practice phone"),
    rate_limit="bounded API requests; no concurrent calls to this source by default",
    cost_model="zero-spend",
    runtime_cache_ttl_days=0,
    live_smoke_allowed=False,
)

LICENSED_POLICY = SourcePolicy(
    source_class=SourceClass.LICENSED,
    delivery_allowed=True,
    export_allowed=True,
    retention=RetentionBehavior.LICENSE_TERMS,
    fixture_behavior=FixtureBehavior.SANITIZED_ONLY,
    field_coverage=("provider-specific"),
    cost_model="review before use",
    runtime_cache_ttl_days=0,
)

FIRST_PARTY_WEB_POLICY = SourcePolicy(
    source_class=SourceClass.FIRST_PARTY_WEB,
    delivery_allowed=True,
    export_allowed=True,
    retention=RetentionBehavior.SOURCE_TERMS,
    fixture_behavior=FixtureBehavior.SANITIZED_ONLY,
    field_coverage=("public business contact", "social links"),
    rate_limit="bounded same-origin crawl; obey robots policy",
    runtime_cache_ttl_days=0,
)

EXPERIMENTAL_OR_DISALLOWED_POLICY = SourcePolicy(
    source_class=SourceClass.EXPERIMENTAL_OR_DISALLOWED,
    delivery_allowed=False,
    export_allowed=False,
    retention=RetentionBehavior.EPHEMERAL,
    fixture_behavior=FixtureBehavior.SANITIZED_ONLY,
    cost_model="disabled by default",
    runtime_cache_ttl_days=0,
    enabled=False,
)


class SourcePolicyError(ValueError):
    """Raised when a source is not approved for a client delivery run."""
