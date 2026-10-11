"""Twilio Lookup Basic phone validation without persisting provider payloads."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import load_dotenv

from biz_intel.credentials import CredentialLoader


_LOOKUP_URL = "https://lookups.twilio.com/v2/PhoneNumbers/{}"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class KeychainCredentialLoader:
    """Read a legacy service-only generic-password item from macOS Keychain."""

    def load(self, service: str) -> str:
        completed = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            check=True,
            capture_output=True,
            text=True,
        )
        value = completed.stdout.strip()
        if not value:
            raise ValueError("Keychain returned an empty credential.")
        return value


class TwilioLookupBasicVerifier:
    """Use Twilio's free Basic Lookup; never log or retain its JSON response."""

    def __init__(self, api_key: str, api_secret: str) -> None:
        self._auth = (api_key, api_secret)

    @classmethod
    def from_keychain(cls, configuration: object) -> "TwilioLookupBasicVerifier":
        if getattr(configuration, "uses_account_scoped_credentials", False):
            loader = CredentialLoader()
            return cls(
                loader.load(
                    configuration.credential_service,
                    configuration.api_key_account,
                ),
                loader.load(
                    configuration.credential_service,
                    configuration.api_secret_account,
                ),
            )

        loader = KeychainCredentialLoader()
        return cls(
            cls._load_legacy_credential(
                loader, configuration.api_key_service, "TWILIO_API_KEY"
            ),
            cls._load_legacy_credential(
                loader, configuration.api_secret_service, "TWILIO_API_SECRET"
            ),
        )

    @staticmethod
    def _load_legacy_credential(
        loader: KeychainCredentialLoader,
        service: str,
        environment_variable: str,
    ) -> str:
        """Keep existing service-only jobs working while allowing env fallback."""

        try:
            return loader.load(service)
        except (OSError, subprocess.CalledProcessError, ValueError):
            load_dotenv(_PROJECT_ROOT / ".env")
            value = os.getenv(environment_variable, "").strip()
            if value:
                return value
            raise RuntimeError(
                "Credential is unavailable from macOS Keychain or environment "
                f"variable {environment_variable}."
            ) from None

    def verify(self, phone: str, country: str, state: str) -> str | None:
        params: dict[str, str] = {}
        if state or country.casefold() in {"united states", "usa", "us"}:
            params["CountryCode"] = "US"
        try:
            response = httpx.get(
                _LOOKUP_URL.format(quote(phone, safe="")),
                params=params,
                auth=self._auth,
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        return "provider_valid" if payload.get("valid") is True else "provider_invalid"
