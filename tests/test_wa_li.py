"""Offline contract tests for the Washington L&I registry source."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch

from biz_intel.core.location import Location
from biz_intel.core.source_name import SourceName
from biz_intel.core.source_policy import SourceClass, WA_LI_POLICY
from biz_intel.core.source_task import SourceTask
from biz_intel.sources.wa_li import WaLiSource


def _record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "businessname": "Example Construction LLC",
        "contractorlicensenumber": "EXAMPLC123AB",
        "contractorlicensetypecode": "CC",
        "contractorlicensetypecodedesc": "CONSTRUCTION CONTRACTOR",
        "contractorlicensestatus": "ACTIVE",
        "address1": "1 Main St",
        "address2": "Suite 200",
        "city": "Seattle",
        "state": "WA",
        "zip": "98101",
        "phonenumber": "2065551212",
        "licenseeffectivedate": "2025-01-01T00:00:00.000",
        "licenseexpirationdate": "2027-01-01T00:00:00.000",
        "primaryprincipalname": "Not for collection",
    }
    record.update(overrides)
    return record


class WaLiSourceTests(unittest.TestCase):
    def _source(self, **options: object) -> WaLiSource:
        return WaLiSource(SourceTask(
            source=SourceName.WA_LI,
            location=Location(city="Seattle", state="WA"),
            limit=2,
            options=options,
        ))

    def test_builds_bounded_active_construction_query(self) -> None:
        source = self._source()
        self.assertEqual(
            source._where_clause(),
            "contractorlicensetypecode IN ('CC') AND upper(contractorlicensestatus) IN ('ACTIVE') AND upper(city) = 'SEATTLE'",
        )

    def test_rejects_non_washington_scope_and_unbounded_limit(self) -> None:
        outside = WaLiSource(SourceTask(
            source=SourceName.WA_LI, location=Location(state="OR"), limit=2,
        ))
        with self.assertRaisesRegex(ValueError, "Washington"):
            list(outside.fetch())
        too_many = WaLiSource(SourceTask(
            source=SourceName.WA_LI, location=Location(state="WA"), limit=251,
        ))
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            too_many._limit()

        no_state = WaLiSource(SourceTask(source=SourceName.WA_LI, location=Location()))
        with self.assertRaisesRegex(ValueError, "Washington"):
            list(no_state.fetch())

    def test_rejects_malformed_query_options(self) -> None:
        source = self._source(license_statuses=["ACTIVE", "' OR 1=1 --"])
        with self.assertRaisesRegex(ValueError, "invalid code"):
            source._where_clause()

    @patch("biz_intel.sources.wa_li.source.httpx.get")
    def test_fetch_uses_one_capped_query_and_sanitizes_record(self, mocked_get: Mock) -> None:
        response = Mock()
        response.json.return_value = [_record(), _record(contractorlicensenumber="SECONDCC234BC")]
        mocked_get.return_value = response
        businesses = list(self._source().fetch())

        self.assertEqual(len(businesses), 2)
        self.assertEqual(mocked_get.call_count, 1)
        self.assertEqual(mocked_get.call_args.kwargs["params"]["$limit"], 2)
        business = businesses[0]
        self.assertEqual(business.source_ids, {"wa_li_contractor_license": "EXAMPLC123AB"})
        self.assertEqual(business.address, "1 Main St Suite 200")
        self.assertEqual(
            {claim.key for claim in business.claims},
            {
                "registry.wa_li.license_number",
                "registry.wa_li.license_status",
                "registry.wa_li.license_type",
                "registry.wa_li.license_effective_date",
                "registry.wa_li.license_expiration_date",
            },
        )
        self.assertNotIn("primaryprincipalname", business.raw_data or {})
        response.raise_for_status.assert_called_once()

    def test_omits_incomplete_records_and_keeps_evidence(self) -> None:
        observed_at = datetime(2026, 10, 2, tzinfo=timezone.utc)
        business = self._source()._to_business(_record(), observed_at=observed_at)
        self.assertIsNotNone(business)
        assert business is not None
        self.assertEqual(business.claims[0].observed_at, observed_at)
        self.assertIn("LIC=EXAMPLC123AB", business.source_url)
        self.assertIsNone(self._source()._to_business(
            _record(businessname=""), observed_at=observed_at,
        ))

    def test_connector_policy_is_official_and_zero_spend(self) -> None:
        self.assertEqual(WA_LI_POLICY.source_class, SourceClass.OFFICIAL_REGISTRY)
        self.assertTrue(WA_LI_POLICY.allows_delivery)
        self.assertEqual(WA_LI_POLICY.cost_model, "zero-spend")
        self.assertFalse(WA_LI_POLICY.allows_live_smoke)
        self.assertIn("registration status", WA_LI_POLICY.field_coverage)


if __name__ == "__main__":
    unittest.main()
