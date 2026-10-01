"""Provider-neutral orchestration for optional phone verification."""

from __future__ import annotations

from dataclasses import replace

from biz_intel.models.business import Business

from .twilio import TwilioLookupBasicVerifier


class PhoneVerificationRunner:
    """Run only the explicitly configured phone verifier after deduplication."""

    def __init__(self, verifier: TwilioLookupBasicVerifier | None = None) -> None:
        self._verifier = verifier

    @classmethod
    def from_job(cls, job: object) -> "PhoneVerificationRunner":
        phone = getattr(getattr(job, "verification", None), "phone", None)
        if not phone or not phone.enabled:
            return cls()
        if phone.provider != "twilio_lookup_basic":
            raise ValueError("Unsupported phone verification provider.")
        return cls(TwilioLookupBasicVerifier.from_keychain(phone))

    def run(self, businesses: list[Business]) -> list[Business]:
        if self._verifier is None:
            return businesses
        result: list[Business] = []
        for business in businesses:
            if not business.phone:
                result.append(business)
                continue
            status = self._verifier.verify(business.phone, business.country, business.state)
            # Provider outages never turn a structurally valid number invalid.
            result.append(replace(business, phone_status=status or business.phone_status))
        return result
