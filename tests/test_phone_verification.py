"""Offline contract tests for optional Twilio Lookup Basic verification."""

from __future__ import annotations

from unittest.mock import Mock, patch
import unittest

import httpx

from biz_intel.jobs.models import JobSpec
from biz_intel.models.business import Business
from biz_intel.services.verification.runner import PhoneVerificationRunner
from biz_intel.services.verification.twilio import TwilioLookupBasicVerifier


class TwilioLookupBasicVerifierTests(unittest.TestCase):
    @patch("biz_intel.services.verification.twilio.httpx.get")
    def test_maps_only_validity_and_never_exposes_response(self, get: Mock) -> None:
        response = Mock()
        response.json.return_value = {"valid": True, "caller_name": {"caller_name": "Private"}}
        get.return_value = response
        verifier = TwilioLookupBasicVerifier("sid", "secret")

        self.assertEqual(verifier.verify("4085551212", "United States", "CA"), "provider_valid")
        self.assertEqual(get.call_args.kwargs["params"], {"CountryCode": "US"})

    @patch("biz_intel.services.verification.twilio.httpx.get", side_effect=httpx.ConnectError("offline"))
    def test_provider_failure_keeps_existing_status(self, get: Mock) -> None:
        verifier = TwilioLookupBasicVerifier("sid", "secret")
        runner = PhoneVerificationRunner(verifier)
        business = Business(phone="4085551212", phone_status="format_valid")
        self.assertEqual(runner.run([business])[0].phone_status, "format_valid")


class PhoneVerificationJobTests(unittest.TestCase):
    def test_requires_keychain_service_names_and_disallows_live_smoke(self) -> None:
        data = {
            "version": 1,
            "name": "phone-verify",
            "search": {"query": "dentist"},
            "sources": ["csv"],
            "output": {},
            "verification": {"phone": {"provider": "twilio_lookup_basic"}},
        }
        with self.assertRaisesRegex(ValueError, "api_key_service is required"):
            JobSpec.from_dict(data)

        data["verification"]["phone"].update({
            "api_key_service": "biz-intel-twilio-key",
            "api_secret_service": "biz-intel-twilio-secret",
        })
        job = JobSpec.from_dict(data)
        self.assertTrue(job.verification.phone.enabled)

        data["execution"] = {"mode": "live_smoke"}
        with self.assertRaisesRegex(ValueError, "not allowed in live_smoke"):
            JobSpec.from_dict(data)
