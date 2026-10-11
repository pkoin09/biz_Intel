"""Offline contract tests for optional Twilio Lookup Basic verification."""

from __future__ import annotations

import subprocess
from unittest.mock import Mock, patch
import unittest

import httpx

from biz_intel.jobs.models import JobSpec
from biz_intel.models.business import Business
from biz_intel.services.verification.runner import PhoneVerificationRunner
from biz_intel.services.verification.twilio import (
    CredentialLoader,
    TwilioLookupBasicVerifier,
)


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

    @patch("biz_intel.credentials.subprocess.run")
    def test_account_scoped_keychain_credentials_are_used_first(self, run: Mock) -> None:
        run.side_effect = [
            Mock(stdout="key-from-keychain\n"),
            Mock(stdout="secret-from-keychain\n"),
        ]
        configuration = JobSpec.from_dict(_phone_job(account_scoped=True)).verification.phone

        verifier = TwilioLookupBasicVerifier.from_keychain(configuration)

        self.assertEqual(verifier._auth, ("key-from-keychain", "secret-from-keychain"))
        self.assertEqual(
            run.call_args_list[0].args[0],
            [
                "security",
                "find-generic-password",
                "-s",
                "biz-intel",
                "-a",
                "TWILIO_API_KEY",
                "-w",
            ],
        )


class CredentialLoaderTests(unittest.TestCase):
    @patch("biz_intel.credentials.load_dotenv")
    @patch("biz_intel.credentials.subprocess.run")
    def test_falls_back_to_environment_when_keychain_item_is_unavailable(
        self,
        run: Mock,
        load_dotenv: Mock,
    ) -> None:
        run.side_effect = subprocess.CalledProcessError(44, "security")
        loader = CredentialLoader()

        with patch.dict("os.environ", {"TWILIO_API_KEY": "local-fallback"}, clear=True):
            value = loader.load("biz-intel", "TWILIO_API_KEY")

        self.assertEqual(value, "local-fallback")
        load_dotenv.assert_called_once()

    @patch("biz_intel.credentials.load_dotenv")
    @patch("biz_intel.credentials.subprocess.run")
    def test_missing_credential_does_not_expose_keychain_errors(
        self, run: Mock, load_dotenv: Mock
    ) -> None:
        run.side_effect = subprocess.CalledProcessError(
            44, "security", stderr="sensitive diagnostic"
        )

        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "TWILIO_API_SECRET") as error:
                CredentialLoader().load("biz-intel", "TWILIO_API_SECRET")

        self.assertNotIn("sensitive diagnostic", str(error.exception))
        load_dotenv.assert_called_once()

    @patch(
        "biz_intel.services.verification.twilio.KeychainCredentialLoader.load",
        side_effect=subprocess.CalledProcessError(44, "security"),
    )
    def test_legacy_service_only_jobs_keep_environment_fallback(self, load: Mock) -> None:
        configuration = JobSpec.from_dict(_phone_job()).verification.phone

        with patch.dict(
            "os.environ",
            {
                "TWILIO_API_KEY": "legacy-key",
                "TWILIO_API_SECRET": "legacy-secret",
            },
            clear=True,
        ):
            verifier = TwilioLookupBasicVerifier.from_keychain(configuration)

        self.assertEqual(verifier._auth, ("legacy-key", "legacy-secret"))
        self.assertEqual(load.call_count, 2)


class PhoneVerificationJobTests(unittest.TestCase):
    def test_requires_credentials_and_disallows_live_smoke(self) -> None:
        data = _phone_job()
        data["verification"]["phone"] = {"provider": "twilio_lookup_basic"}
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

    def test_accepts_account_scoped_keychain_configuration(self) -> None:
        job = JobSpec.from_dict(_phone_job(account_scoped=True))

        self.assertTrue(job.verification.phone.uses_account_scoped_credentials)
        self.assertEqual(job.verification.phone.credential_service, "biz-intel")
        self.assertEqual(job.verification.phone.api_key_account, "TWILIO_API_KEY")

    def test_rejects_partial_account_scoped_configuration(self) -> None:
        data = _phone_job(account_scoped=True)
        del data["verification"]["phone"]["api_secret_account"]

        with self.assertRaisesRegex(ValueError, "api_secret_account is required"):
            JobSpec.from_dict(data)


def _phone_job(*, account_scoped: bool = False) -> dict[str, object]:
    phone: dict[str, str] = {"provider": "twilio_lookup_basic"}
    if account_scoped:
        phone.update(
            {
                "credential_service": "biz-intel",
                "api_key_account": "TWILIO_API_KEY",
                "api_secret_account": "TWILIO_API_SECRET",
            }
        )
    else:
        phone.update(
            {
                "api_key_service": "biz-intel-twilio-key",
                "api_secret_service": "biz-intel-twilio-secret",
            }
        )
    return {
        "version": 1,
        "name": "phone-verify",
        "search": {"query": "dentist"},
        "sources": ["csv"],
        "output": {},
        "verification": {"phone": phone},
    }
