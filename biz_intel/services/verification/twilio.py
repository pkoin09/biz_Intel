"""Twilio Lookup Basic phone validation without persisting provider payloads."""

from __future__ import annotations

import subprocess
from urllib.parse import quote

import httpx


_LOOKUP_URL = "https://lookups.twilio.com/v2/PhoneNumbers/{}"


class KeychainCredentialLoader:
    """Read a generic-password secret from the local macOS Keychain only."""

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
        loader = KeychainCredentialLoader()
        return cls(
            loader.load(configuration.api_key_service),
            loader.load(configuration.api_secret_service),
        )

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
