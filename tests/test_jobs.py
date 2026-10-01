"""Tests for versioned YAML job specifications."""

from __future__ import annotations

from pathlib import Path
import unittest

from biz_intel.jobs import JobSpec, load_job


SAMPLE_JOB = (
    Path(__file__).resolve().parents[1]
    / "jobs/dentists_san_jose.yaml"
)


class JobSpecTests(unittest.TestCase):
    """Protect the job specification's public contract."""

    def test_loads_the_sample_job(self) -> None:
        job = load_job(SAMPLE_JOB)

        self.assertEqual(job.version, 1)
        self.assertEqual(job.name, "client-business-import")
        self.assertEqual(job.search.query, "local businesses")
        self.assertEqual(job.search.cities, ("San Jose, CA",))
        self.assertEqual(job.sources, ("csv",))
        self.assertIsNone(job.limit)
        self.assertEqual(job.output.fields, ("name", "phone", "website"))
        self.assertTrue(job.processing.deduplicate)
        self.assertFalse(job.processing.enrich)
        self.assertTrue(job.delivery.include_non_accepted)
        self.assertTrue(job.delivery.include_sidecars)
        self.assertEqual(
            job.source_options,
            {"csv": {"path": "tests/fixtures/businesses_messy_synthetic.csv"}},
        )

    def test_rejects_unknown_output_fields(self) -> None:
        data = {
            "version": 1,
            "name": "invalid-output-field",
            "search": {"query": "dentist"},
            "sources": ["yellowpages"],
            "output": {"fields": ["name", "fax_number"]},
        }

        with self.assertRaisesRegex(
            ValueError,
            "unknown fields: fax_number",
        ):
            JobSpec.from_dict(data)

    def test_rejects_invalid_limits(self) -> None:
        data = {
            "version": 1,
            "name": "invalid-limit",
            "search": {"query": "dentist"},
            "sources": ["yellowpages"],
            "output": {},
            "limit": 0,
        }

        with self.assertRaisesRegex(
            ValueError,
            "limit must be a positive integer",
        ):
            JobSpec.from_dict(data)

    def test_parses_source_options(self) -> None:
        data = {
            "version": 1,
            "name": "test-source-opts",
            "search": {"query": "dentist"},
            "sources": ["google"],
            "output": {},
            "source_options": {"google": {"enrich_details": True, "max_enrich": 0}},
        }
        job = JobSpec.from_dict(data)
        self.assertEqual(job.source_options, {"google": {"enrich_details": True, "max_enrich": 0}})

    def test_paid_enrichment_requires_a_finite_client_approved_budget(self) -> None:
        data = {
            "version": 1,
            "name": "paid-enrichment",
            "search": {"query": "dentist"},
            "sources": ["google"],
            "output": {},
            "source_options": {"google": {"enrich_details": True, "max_enrich": 1}},
        }
        with self.assertRaisesRegex(ValueError, "requires budget.max_total_usd"):
            JobSpec.from_dict(data)

        data["budget"] = {
            "max_total_usd": 1,
            "approval_reference": "client-order-42",
        }
        job = JobSpec.from_dict(data)
        self.assertEqual(job.budget.max_total_usd, 1.0)
        self.assertEqual(job.budget.approval_reference, "client-order-42")

    def test_source_options_defaults_to_empty(self) -> None:
        data = {
            "version": 1,
            "name": "no-opts",
            "search": {"query": "dentist"},
            "sources": ["yellowpages"],
            "output": {},
        }
        job = JobSpec.from_dict(data)
        self.assertEqual(job.source_options, {})

    def test_rejects_non_mapping_source_options(self) -> None:
        data = {
            "version": 1,
            "name": "bad-opts",
            "search": {"query": "dentist"},
            "sources": ["google"],
            "output": {},
            "source_options": {"google": "bad"},
        }
        with self.assertRaisesRegex(ValueError, "source_options.google must be a mapping"):
            JobSpec.from_dict(data)

    def test_delivery_defaults_and_rejects_unknown_profile(self) -> None:
        data = {
            "version": 1,
            "name": "delivery-defaults",
            "search": {"query": "dentist"},
            "sources": ["csv"],
            "output": {},
        }
        self.assertEqual(JobSpec.from_dict(data).delivery.profile, "standard")

        data["delivery"] = {"profile": "outreach_ready"}
        with self.assertRaisesRegex(ValueError, "delivery.profile must be one of: standard"):
            JobSpec.from_dict(data)

    def test_delivery_parses_a_positive_freshness_requirement(self) -> None:
        data = {
            "version": 1,
            "name": "fresh-delivery",
            "search": {"query": "dentist"},
            "sources": ["csv"],
            "output": {},
            "delivery": {"max_age_days": 30},
        }
        self.assertEqual(JobSpec.from_dict(data).delivery.max_age_days, 30)

        data["delivery"] = {"max_age_days": 0}
        with self.assertRaisesRegex(ValueError, "delivery.max_age_days must be a positive integer"):
            JobSpec.from_dict(data)

    def test_rejects_empty_sources(self) -> None:
        data = {
            "version": 1,
            "name": "no-sources",
            "search": {"query": "dentist"},
            "sources": [],
            "output": {},
        }

        with self.assertRaisesRegex(
            ValueError,
            "sources must include at least one source",
        ):
            JobSpec.from_dict(data)

    def test_live_smoke_uses_strict_zero_spend_defaults(self) -> None:
        data = {
            "version": 1,
            "name": "safe-live-smoke",
            "search": {"query": "dentist"},
            "sources": ["csv"],
            "output": {},
            "execution": {"mode": "live_smoke"},
        }

        execution = JobSpec.from_dict(data).execution
        self.assertEqual(execution.mode, "live_smoke")
        self.assertEqual(execution.max_parallel_tasks, 1)
        self.assertIsNotNone(execution.live_smoke)
        self.assertEqual(execution.live_smoke.max_tasks, 1)
        self.assertEqual(execution.live_smoke.max_records_per_task, 10)
        self.assertEqual(execution.live_smoke.max_attempts, 2)
        self.assertEqual(execution.live_smoke.retry_backoff_seconds, 1)
        self.assertEqual(execution.live_smoke.failure_threshold, 2)
        self.assertEqual(execution.live_smoke.max_cost_usd, 0)

    def test_rejects_unsafe_live_smoke_configuration(self) -> None:
        base = {
            "version": 1,
            "name": "unsafe-live-smoke",
            "search": {"query": "dentist"},
            "sources": ["csv"],
            "output": {},
            "execution": {"mode": "live_smoke", "live_smoke": {}},
        }
        base["execution"]["live_smoke"]["max_tasks"] = 4
        with self.assertRaisesRegex(ValueError, "max_tasks must be at most 3"):
            JobSpec.from_dict(base)

        base["execution"]["live_smoke"] = {}
        base["execution"]["max_parallel_tasks"] = 2
        with self.assertRaisesRegex(ValueError, "must be 1 in live_smoke"):
            JobSpec.from_dict(base)
        base["execution"].pop("max_parallel_tasks")

        base["execution"]["live_smoke"] = {"max_cost_usd": 0.01}
        with self.assertRaisesRegex(ValueError, "max_cost_usd must be exactly 0"):
            JobSpec.from_dict(base)

        base["execution"]["live_smoke"] = {}
        base["processing"] = {"enrich": True}
        with self.assertRaisesRegex(ValueError, "processing.enrich is not allowed"):
            JobSpec.from_dict(base)

        base["processing"] = {}
        base["source_options"] = {"csv": {"enrich_details": True}}
        with self.assertRaisesRegex(ValueError, "enrich_details is not allowed"):
            JobSpec.from_dict(base)

    def test_limits_are_explicit_and_legacy_limit_aliases_total_records(self) -> None:
        data = {
            "version": 1,
            "name": "explicit-limits",
            "search": {"query": "dentist"},
            "sources": ["csv"],
            "output": {},
            "limits": {
                "total_records": 30,
                "per_source_records": 20,
                "per_location_records": 10,
            },
        }
        job = JobSpec.from_dict(data)
        self.assertEqual(job.limits.total_records, 30)
        self.assertEqual(job.limits.per_source_records, 20)
        self.assertEqual(job.limits.per_location_records, 10)
        self.assertEqual(job.limit, 30)

        data.pop("limits")
        data["limit"] = 15
        self.assertEqual(JobSpec.from_dict(data).limits.total_records, 15)

        data["limits"] = {"total_records": 20}
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            JobSpec.from_dict(data)


if __name__ == "__main__":
    unittest.main()
