"""Typed representation of a user-requested data job."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from biz_intel.models.business import Business


SUPPORTED_OUTPUT_FORMATS = frozenset({"csv", "json"})
SUPPORTED_DELIVERY_PROFILES = frozenset({"standard"})
SUPPORTED_EXECUTION_MODES = frozenset({"delivery", "live_smoke"})
BUSINESS_FIELDS = frozenset(
    field.name
    for field in fields(Business)
)
EXPORTABLE_BUSINESS_FIELDS = BUSINESS_FIELDS - {
    "raw_data",
    "field_provenance",
    "quality_reasons",
}


@dataclass(frozen=True, slots=True)
class JobSearch:
    """The business type and geography a job should search."""

    query: str
    cities: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    radius_miles: int | None = None


@dataclass(frozen=True, slots=True)
class JobOutput:
    """The projection and destination requested by a job."""

    format: str = "csv"
    fields: tuple[str, ...] = ()
    destination: str = ""


@dataclass(frozen=True, slots=True)
class JobProcessing:
    """Optional data-processing capabilities requested by a job."""

    deduplicate: bool = True
    fuzzy_deduplicate: bool = False
    enrich: bool = False


@dataclass(frozen=True, slots=True)
class JobDelivery:
    """Client-facing acceptance and sidecar controls for a job."""

    profile: str = "standard"
    include_non_accepted: bool = False
    include_sidecars: bool = True
    max_age_days: int | None = None


@dataclass(frozen=True, slots=True)
class JobLiveSmoke:
    """Hard-bounded controls for an explicitly approved live smoke run."""

    max_tasks: int = 1
    max_records_per_task: int = 10
    max_attempts: int = 2
    retry_backoff_seconds: int = 1
    failure_threshold: int = 2
    max_cost_usd: int = 0


@dataclass(frozen=True, slots=True)
class JobExecution:
    """Execution mode and its opt-in live smoke safety controls."""

    mode: str = "delivery"
    live_smoke: JobLiveSmoke | None = None
    max_parallel_tasks: int = 1


@dataclass(frozen=True, slots=True)
class JobLimits:
    """Explicit caps at total, source, and location acquisition boundaries."""

    total_records: int | None = None
    per_source_records: int | None = None
    per_location_records: int | None = None


@dataclass(frozen=True, slots=True)
class JobBudget:
    """Explicit authorization ceiling for paid, per-record enrichment."""

    max_total_usd: float = 0.0
    approval_reference: str = ""


@dataclass(frozen=True, slots=True)
class JobPhoneVerification:
    """Explicit configuration for a post-dedup phone verification provider."""

    provider: str = ""
    api_key_service: str = ""
    api_secret_service: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.provider)


@dataclass(frozen=True, slots=True)
class JobVerification:
    phone: JobPhoneVerification = field(default_factory=JobPhoneVerification)


@dataclass(frozen=True, slots=True)
class JobSpec:
    """A source-agnostic, reproducible business-data request."""

    version: int
    name: str
    search: JobSearch
    sources: tuple[str, ...]
    output: JobOutput
    processing: JobProcessing
    delivery: JobDelivery
    execution: JobExecution = field(default_factory=JobExecution)
    limits: JobLimits = field(default_factory=JobLimits)
    budget: JobBudget = field(default_factory=JobBudget)
    verification: JobVerification = field(default_factory=JobVerification)
    source_options: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def limit(self) -> int | None:
        """Compatibility alias for the former top-level job limit."""

        return self.limits.total_records

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "JobSpec":
        """Build and validate a job specification from parsed YAML data."""

        version = data.get("version")
        if version != 1:
            raise ValueError("Job version must be 1.")

        name = cls._required_string(data, "name")
        sources = cls._string_list(data, "sources")
        if not sources:
            raise ValueError("Job sources must include at least one source.")
        search_data = cls._mapping(data, "search")
        output_data = cls._mapping(data, "output")
        processing_data = data.get("processing", {})
        if not isinstance(processing_data, dict):
            raise ValueError("Job processing must be a mapping.")
        delivery_data = data.get("delivery", {})
        if not isinstance(delivery_data, dict):
            raise ValueError("Job delivery must be a mapping.")
        execution_data = data.get("execution", {})
        if not isinstance(execution_data, dict):
            raise ValueError("Job execution must be a mapping.")
        limits_data = data.get("limits", {})
        if not isinstance(limits_data, dict):
            raise ValueError("Job limits must be a mapping.")
        budget_data = data.get("budget", {})
        if not isinstance(budget_data, dict):
            raise ValueError("Job budget must be a mapping.")
        verification_data = data.get("verification", {})
        if not isinstance(verification_data, dict):
            raise ValueError("Job verification must be a mapping.")

        search = JobSearch(
            query=cls._required_string(search_data, "query"),
            cities=cls._string_list(search_data, "cities"),
            states=cls._string_list(search_data, "states"),
            radius_miles=cls._positive_int(
                search_data.get("radius_miles"),
                "search.radius_miles",
            ),
        )
        output = JobOutput(
            format=cls._output_format(output_data),
            fields=cls._output_fields(output_data),
            destination=cls._optional_string(output_data, "destination"),
        )
        processing = JobProcessing(
            deduplicate=cls._boolean(
                processing_data,
                "deduplicate",
                True,
            ),
            fuzzy_deduplicate=cls._boolean(
                processing_data,
                "fuzzy_deduplicate",
                False,
            ),
            enrich=cls._boolean(
                processing_data,
                "enrich",
                False,
            ),
        )
        delivery = JobDelivery(
            profile=cls._delivery_profile(delivery_data),
            include_non_accepted=cls._boolean(
                delivery_data,
                "include_non_accepted",
                False,
                prefix="delivery",
            ),
            include_sidecars=cls._boolean(
                delivery_data,
                "include_sidecars",
                True,
                prefix="delivery",
            ),
            max_age_days=cls._positive_int(
                delivery_data.get("max_age_days"),
                "delivery.max_age_days",
            ),
        )
        execution = cls._execution(execution_data)
        limits = cls._limits(data, limits_data)
        budget = cls._budget(budget_data)
        verification = cls._verification(verification_data)

        source_options = cls._source_options(data)
        cls._validate_live_smoke_zero_spend(
            execution, processing, source_options, verification
        )
        cls._validate_paid_enrichment(budget, source_options)

        return cls(
            version=version,
            name=name,
            search=search,
            sources=sources,
            output=output,
            processing=processing,
            delivery=delivery,
            execution=execution,
            limits=limits,
            budget=budget,
            verification=verification,
            source_options=source_options,
        )

    @staticmethod
    def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
        value = data.get(key)
        if not isinstance(value, dict):
            raise ValueError(f"Job {key} must be a mapping.")
        return value

    @staticmethod
    def _required_string(data: dict[str, Any], key: str) -> str:
        value = JobSpec._optional_string(data, key)
        if not value:
            raise ValueError(f"Job {key} is required.")
        return value

    @staticmethod
    def _optional_string(data: dict[str, Any], key: str) -> str:
        value = data.get(key, "")
        if not isinstance(value, str):
            raise ValueError(f"Job {key} must be a string.")
        return value.strip()

    @staticmethod
    def _string_list(
        data: dict[str, Any],
        key: str,
    ) -> tuple[str, ...]:
        value = data.get(key, [])
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip()
            for item in value
        ):
            raise ValueError(f"Job {key} must be a list of strings.")
        return tuple(item.strip() for item in value)

    @staticmethod
    def _positive_int(
        value: Any,
        field: str,
    ) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"Job {field} must be a positive integer.")
        return value

    @staticmethod
    def _output_format(data: dict[str, Any]) -> str:
        value = JobSpec._optional_string(data, "format") or "csv"
        if value not in SUPPORTED_OUTPUT_FORMATS:
            options = ", ".join(sorted(SUPPORTED_OUTPUT_FORMATS))
            raise ValueError(f"Job output.format must be one of: {options}.")
        return value

    @staticmethod
    def _output_fields(data: dict[str, Any]) -> tuple[str, ...]:
        output_fields = JobSpec._string_list(data, "fields")
        unknown_fields = set(output_fields) - EXPORTABLE_BUSINESS_FIELDS
        if unknown_fields:
            names = ", ".join(sorted(unknown_fields))
            raise ValueError(f"Job output.fields contains unknown fields: {names}.")
        return output_fields

    @staticmethod
    def _delivery_profile(data: dict[str, Any]) -> str:
        value = JobSpec._optional_string(data, "profile") or "standard"
        if value not in SUPPORTED_DELIVERY_PROFILES:
            options = ", ".join(sorted(SUPPORTED_DELIVERY_PROFILES))
            raise ValueError(f"Job delivery.profile must be one of: {options}.")
        return value

    @staticmethod
    def _execution(data: dict[str, Any]) -> JobExecution:
        mode = JobSpec._optional_string(data, "mode") or "delivery"
        if mode not in SUPPORTED_EXECUTION_MODES:
            options = ", ".join(sorted(SUPPORTED_EXECUTION_MODES))
            raise ValueError(f"Job execution.mode must be one of: {options}.")

        raw_live_smoke = data.get("live_smoke")
        max_parallel_tasks = JobSpec._bounded_positive_int(
            data.get("max_parallel_tasks", 1),
            "execution.max_parallel_tasks",
            maximum=8,
        )

        if mode == "delivery":
            if raw_live_smoke is not None:
                raise ValueError(
                    "Job execution.live_smoke is only valid in live_smoke mode."
                )
            return JobExecution(max_parallel_tasks=max_parallel_tasks)

        if raw_live_smoke is None:
            raw_live_smoke = {}
        if not isinstance(raw_live_smoke, dict):
            raise ValueError("Job execution.live_smoke must be a mapping.")

        smoke = JobLiveSmoke(
            max_tasks=JobSpec._bounded_positive_int(
                raw_live_smoke.get("max_tasks", 1),
                "execution.live_smoke.max_tasks",
                maximum=3,
            ),
            max_records_per_task=JobSpec._bounded_positive_int(
                raw_live_smoke.get("max_records_per_task", 10),
                "execution.live_smoke.max_records_per_task",
                maximum=25,
            ),
            max_attempts=JobSpec._bounded_positive_int(
                raw_live_smoke.get("max_attempts", 2),
                "execution.live_smoke.max_attempts",
                maximum=3,
            ),
            retry_backoff_seconds=JobSpec._bounded_positive_int(
                raw_live_smoke.get("retry_backoff_seconds", 1),
                "execution.live_smoke.retry_backoff_seconds",
                maximum=5,
            ),
            failure_threshold=JobSpec._bounded_positive_int(
                raw_live_smoke.get("failure_threshold", 2),
                "execution.live_smoke.failure_threshold",
                maximum=3,
            ),
            max_cost_usd=JobSpec._zero_cost(raw_live_smoke),
        )
        if max_parallel_tasks != 1:
            raise ValueError(
                "Job execution.max_parallel_tasks must be 1 in live_smoke mode."
            )
        return JobExecution(
            mode=mode,
            live_smoke=smoke,
            max_parallel_tasks=max_parallel_tasks,
        )

    @staticmethod
    def _validate_live_smoke_zero_spend(
        execution: JobExecution,
        processing: JobProcessing,
        source_options: dict[str, dict[str, Any]],
        verification: JobVerification,
    ) -> None:
        """Keep the live-smoke path to acquisition-only, zero-cost work.

        Enrichment can turn one bounded acquisition call into many website or
        provider-detail calls, so it is deliberately not part of this mode.
        """

        if execution.mode != "live_smoke":
            return
        if processing.enrich:
            raise ValueError(
                "Job processing.enrich is not allowed in live_smoke mode."
            )
        if any(
            options.get("enrich_details", False)
            for options in source_options.values()
        ):
            raise ValueError(
                "Job source_options.*.enrich_details is not allowed in "
                "live_smoke mode."
            )
        if verification.phone.enabled:
            raise ValueError("Job verification.phone is not allowed in live_smoke mode.")

    @staticmethod
    def _limits(data: dict[str, Any], limits_data: dict[str, Any]) -> JobLimits:
        legacy_limit = data.get("limit")
        explicit_total = limits_data.get("total_records")
        if legacy_limit is not None and explicit_total is not None:
            raise ValueError(
                "Job limit cannot be combined with limits.total_records."
            )
        return JobLimits(
            total_records=JobSpec._positive_int(
                explicit_total if explicit_total is not None else legacy_limit,
                "limits.total_records" if explicit_total is not None else "limit",
            ),
            per_source_records=JobSpec._positive_int(
                limits_data.get("per_source_records"),
                "limits.per_source_records",
            ),
            per_location_records=JobSpec._positive_int(
                limits_data.get("per_location_records"),
                "limits.per_location_records",
            ),
        )

    @staticmethod
    def _budget(data: dict[str, Any]) -> JobBudget:
        value = data.get("max_total_usd", 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError("Job budget.max_total_usd must be a non-negative number.")
        reference = JobSpec._optional_string(data, "approval_reference")
        if value == 0 and reference:
            raise ValueError(
                "Job budget.approval_reference requires a positive max_total_usd."
            )
        return JobBudget(max_total_usd=float(value), approval_reference=reference)

    @staticmethod
    def _verification(data: dict[str, Any]) -> JobVerification:
        phone_data = data.get("phone", {})
        if not isinstance(phone_data, dict):
            raise ValueError("Job verification.phone must be a mapping.")
        provider = JobSpec._optional_string(phone_data, "provider")
        if not provider:
            if phone_data:
                raise ValueError("Job verification.phone.provider is required.")
            return JobVerification()
        if provider != "twilio_lookup_basic":
            raise ValueError("Job verification.phone.provider is unsupported.")
        key_service = JobSpec._required_string(phone_data, "api_key_service")
        secret_service = JobSpec._required_string(phone_data, "api_secret_service")
        return JobVerification(
            phone=JobPhoneVerification(provider, key_service, secret_service)
        )

    @staticmethod
    def _validate_paid_enrichment(
        budget: JobBudget,
        source_options: dict[str, dict[str, Any]],
    ) -> None:
        """Require a finite, client-approved cap before paid calls are possible."""

        for source, options in source_options.items():
            if not options.get("enrich_details", False):
                continue
            cap = options.get("max_enrich")
            if isinstance(cap, bool) or not isinstance(cap, int) or cap < 0:
                raise ValueError(
                    f"Job source_options.{source}.max_enrich must be a non-negative "
                    "integer when enrich_details is enabled."
                )
            if cap > 0 and (budget.max_total_usd <= 0 or not budget.approval_reference):
                raise ValueError(
                    "Paid enrichment requires budget.max_total_usd and a "
                    "budget.approval_reference."
                )

    @staticmethod
    def _bounded_positive_int(value: Any, field: str, *, maximum: int) -> int:
        parsed = JobSpec._positive_int(value, field)
        assert parsed is not None
        if parsed > maximum:
            raise ValueError(f"Job {field} must be at most {maximum}.")
        return parsed

    @staticmethod
    def _zero_cost(data: dict[str, Any]) -> int:
        value = data.get("max_cost_usd", 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != 0:
            raise ValueError(
                "Job execution.live_smoke.max_cost_usd must be exactly 0."
            )
        return 0

    @staticmethod
    def _source_options(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
        raw = data.get("source_options", {})
        if not isinstance(raw, dict):
            raise ValueError("Job source_options must be a mapping.")
        result: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            if not isinstance(value, dict):
                raise ValueError(
                    f"Job source_options.{key} must be a mapping."
                )
            result[key] = value
        return result

    @staticmethod
    def _boolean(
        data: dict[str, Any],
        key: str,
        default: bool,
        *,
        prefix: str = "processing",
    ) -> bool:
        value = data.get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"Job {prefix}.{key} must be a boolean.")
        return value
