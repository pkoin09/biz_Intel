"""Offline tests for shared provider credential loading."""

from __future__ import annotations

import subprocess
from unittest.mock import Mock, patch
import unittest

from biz_intel.credentials import CredentialLoader, load_provider_credential


class ProviderCredentialTests(unittest.TestCase):
    @patch("biz_intel.credentials.subprocess.run")
    def test_standard_provider_loader_uses_account_scoped_keychain_first(
        self, run: Mock
    ) -> None:
        run.return_value = Mock(stdout="keychain-value\n")

        value = load_provider_credential("APIFY_API_KEY")

        self.assertEqual(value, "keychain-value")
        self.assertEqual(
            run.call_args.args[0],
            [
                "security",
                "find-generic-password",
                "-s",
                "biz-intel",
                "-a",
                "APIFY_API_KEY",
                "-w",
            ],
        )

    @patch("biz_intel.credentials.load_dotenv")
    @patch("biz_intel.credentials.subprocess.run")
    def test_optional_loader_falls_back_to_environment(
        self, run: Mock, load_dotenv: Mock
    ) -> None:
        run.side_effect = subprocess.CalledProcessError(44, "security")

        with patch.dict("os.environ", {"YELP_API_KEY": "env-value"}, clear=True):
            value = CredentialLoader().load_optional("biz-intel", "YELP_API_KEY")

        self.assertEqual(value, "env-value")
        load_dotenv.assert_called_once()

    @patch("biz_intel.credentials.load_dotenv")
    @patch("biz_intel.credentials.subprocess.run")
    def test_optional_loader_allows_an_unconfigured_provider(
        self, run: Mock, load_dotenv: Mock
    ) -> None:
        run.side_effect = subprocess.CalledProcessError(44, "security")

        with patch.dict("os.environ", {}, clear=True):
            value = CredentialLoader().load_optional("biz-intel", "SUPABASE_KEY")

        self.assertEqual(value, "")
        load_dotenv.assert_called_once()
