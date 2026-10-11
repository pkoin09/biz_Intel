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


class SourceRole(StrEnum):
    """The operational contribution a source can make to a job."""

    CANDIDATE = "candidate"
    REGISTRY = "registry"
    CATALOG = "catalog"
    ENRICHER = "enricher"
    VERIFIER = "verifier"


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
    roles: tuple[SourceRole, ...] = ()

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
    roles=(SourceRole.CANDIDATE,),
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
    roles=(SourceRole.REGISTRY,),
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
    roles=(SourceRole.CANDIDATE, SourceRole.REGISTRY),
)

# Washington L&I publishes this contractor-registration dataset under the
# Open Data Commons Public Domain Dedication and License.  The connector is
# intentionally limited to the General dataset; it does not collect insurer,
# policy, principal, or other unnecessary fields from related datasets.
WA_LI_POLICY = SourcePolicy(
    source_class=SourceClass.OFFICIAL_REGISTRY,
    delivery_allowed=True,
    export_allowed=True,
    retention=RetentionBehavior.SOURCE_TERMS,
    fixture_behavior=FixtureBehavior.SANITIZED_ONLY,
    attribution="Washington State Labor & Industries Contractor License Data",
    field_coverage=(
        "contractor identity",
        "mailing location",
        "business phone",
        "registration status",
        "registration dates",
    ),
    rate_limit="one bounded Socrata query per task; no concurrent calls to this source by default",
    cost_model="zero-spend",
    runtime_cache_ttl_days=0,
    live_smoke_allowed=False,
    roles=(SourceRole.CANDIDATE, SourceRole.REGISTRY),
)

# This connector imports a client-provided/manual snapshot from the official
# California Dental Board lookup. It does not automate Board queries. Every
# row must retain the profile URL and observation time needed for review.
CA_DENTAL_BOARD_POLICY = SourcePolicy(
    source_class=SourceClass.OFFICIAL_REGISTRY,
    delivery_allowed=True,
    export_allowed=True,
    retention=RetentionBehavior.SOURCE_TERMS,
    fixture_behavior=FixtureBehavior.SANITIZED_ONLY,
    attribution="California Dental Board / Department of Consumer Affairs",
    field_coverage=("dentist license identity", "license status", "license dates"),
    rate_limit="manual evidence import only; no automated Board lookup",
    cost_model="zero-spend",
    runtime_cache_ttl_days=0,
    live_smoke_allowed=False,
    roles=(SourceRole.REGISTRY, SourceRole.VERIFIER),
)

# Overture snapshot imports are deliberately a candidate-acquisition boundary.
# A snapshot must be reviewed with its release and license metadata before it
# can become part of a client-delivery policy.  The importer itself is offline
# and has no ability to query the Overture cloud.
OVERTURE_POLICY = SourcePolicy(
    source_class=SourceClass.LICENSED,
    delivery_allowed=False,
    export_allowed=False,
    retention=RetentionBehavior.LICENSE_TERMS,
    fixture_behavior=FixtureBehavior.SANITIZED_ONLY,
    attribution="Overture Maps Foundation data; snapshot manifest required",
    field_coverage=("business identity", "location", "category", "public contact when present"),
    rate_limit="offline local snapshot import only; no live Overture query",
    cost_model="zero-spend offline import; review release and license before delivery",
    runtime_cache_ttl_days=0,
    live_smoke_allowed=False,
    roles=(SourceRole.CANDIDATE,),
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
    roles=(SourceRole.CANDIDATE,),
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
    roles=(SourceRole.ENRICHER,),
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
    roles=(SourceRole.CANDIDATE,),
)

# LinkedIn observations are produced by a separately configured Apify Actor.
# The adapter deliberately excludes contact details, and is not a delivery
# path until the actor, LinkedIn terms, and client use have been reviewed.
LINKEDIN_APIFY_POLICY = SourcePolicy(
    source_class=SourceClass.EXPERIMENTAL_OR_DISALLOWED,
    delivery_allowed=False,
    export_allowed=False,
    retention=RetentionBehavior.EPHEMERAL,
    fixture_behavior=FixtureBehavior.SANITIZED_ONLY,
    attribution="LinkedIn public-profile observation via configured Apify actor",
    field_coverage=("public profile URL", "public profile headline"),
    rate_limit="explicit URL list only; maximum 100 profiles per actor run",
    cost_model="actor-priced; explicit approval required",
    runtime_cache_ttl_days=0,
    live_smoke_allowed=False,
    enabled=False,
    roles=(SourceRole.ENRICHER,),
)


class SourcePolicyError(ValueError):
    """Raised when a source is not approved for a client delivery run."""
