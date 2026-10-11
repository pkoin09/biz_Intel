"""Shared Keychain-first provider credential loading."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SERVICE = "biz-intel"


class CredentialLoader:
    """Load an account-scoped credential from Keychain, then ``.env``.

    Diagnostics intentionally name only the account label. Keychain output and
    credential values are never included in raised errors.
    """

    def __init__(self, env_path: Path | None = None) -> None:
        self._env_path = env_path or PROJECT_ROOT / ".env"

    def load(self, service: str, account: str) -> str:
        value = self.load_optional(service, account)
        if value:
            return value
        raise RuntimeError(
            "Credential is unavailable from macOS Keychain or environment "
            f"variable {account}."
        )

    def load_optional(self, service: str, account: str) -> str:
        try:
            completed = subprocess.run(
                [
                    "security",
                    "find-generic-password",
                    "-s",
                    service,
                    "-a",
                    account,
                    "-w",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            value = completed.stdout.strip()
            if value:
                return value
        except (OSError, subprocess.CalledProcessError):
            pass

        load_dotenv(self._env_path)
        return os.getenv(account, "").strip()


def load_provider_credential(account: str) -> str:
    """Load an optional provider credential using the standard service."""

    return CredentialLoader().load_optional(DEFAULT_SERVICE, account)
