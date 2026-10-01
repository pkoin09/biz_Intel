"""
Business validation pipeline.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urlparse

from .base import Pipeline
from biz_intel.models.business import Business
from biz_intel.metrics import metrics


class ValidationPipeline(Pipeline):
    """
    Validate Business records.
    """

    def process(
        self,
        businesses: Iterator[Business],
    ) -> Iterator[Business]:

        for business in businesses:

            self.clean_strings(business)

            business.rating = self.to_float(
                business.rating,
            )

            business.review_count = self.to_int(
                business.review_count,
            )

            yield business

    @staticmethod
    def clean(value):

        if isinstance(value, str):
            return value.strip()

        return value

    def clean_strings(
        self,
        business: Business,
    ) -> None:

        business.name = self.clean(
            business.name,
        )

        business.category = self.clean(
            business.category,
        )

        business.address = self.clean(
            business.address,
        )

        business.city = self.clean(
            business.city,
        )

        business.state = self.clean(
            business.state,
        )

        business.postal_code = self.clean(
            business.postal_code,
        )

        business.country = self.clean(
            business.country,
        )

        raw_phone = business.phone
        business.phone = self.clean_phone(raw_phone)
        business.phone_status = _phone_status(raw_phone, business.phone)

        raw_email = business.email
        business.email = self.clean_email(raw_email)
        business.email_status = _email_status(raw_email, business.email)

        business.website = self.clean_website(
            business.website,
        )

        business.facebook = self.clean(
            business.facebook,
        )

        business.instagram = self.clean(
            business.instagram,
        )

        business.linkedin = self.clean(
            business.linkedin,
        )

        business.twitter = self.clean(
            business.twitter,
        )

    @staticmethod
    def to_float(value):

        if value in ("", None):
            return None

        try:
            return float(value)

        except (TypeError, ValueError):
            return None

    @staticmethod
    def to_int(value):

        if value in ("", None):
            return None

        try:
            return int(
                str(value).replace(",", ""),
            )

        except (TypeError, ValueError):
            return None

    @staticmethod
    def clean_email(
        value: str,
    ) -> str:

        if not value:
            return ""

        value = value.strip().lower()

        pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

        if re.match(pattern, value):
            return value

        metrics.increment(
            "invalid_emails",
        )

        return ""

    @staticmethod
    def clean_website(
        value: str,
    ) -> str:

        if not value:
            return ""

        value = value.strip().lower()

        # Remove common accidental wrappers
        value = value.strip(
            "[](){}<>\"'"
        )

        if not value.startswith(
            (
                "http://",
                "https://",
            )
        ):
            value = "https://" + value

        try:
            parsed = urlparse(value)

        except ValueError:
            metrics.increment(
                "invalid_websites",
            )

            return ""

        if parsed.netloc:
            return parsed.netloc.replace(
                "www.",
                "",
            )

        return ""

    @staticmethod
    def clean_phone(
        value: str,
    ) -> str:

        if not value:
            return ""

        digits = "".join(
            c for c in value
            if c.isdigit()
        )

        if len(digits) < 7:
            metrics.increment(
                "invalid_phones",
            )

            return ""

        return digits


def _email_status(raw_value: str, cleaned_value: str) -> str:
    if cleaned_value:
        return "syntax_valid"
    return "not_found" if not raw_value else "unknown"


def _phone_status(raw_value: str, cleaned_value: str) -> str:
    if cleaned_value:
        return "format_valid"
    return "not_found" if not raw_value else "invalid"
