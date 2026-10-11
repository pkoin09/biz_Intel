"""Bounded LinkedIn public-profile observations through Apify.

This adapter accepts an explicit list of public profile URLs only. It does not
perform keyword/person discovery, use authenticated sessions, or retain email,
phone, employment history, or other profile detail. Its registered policy
blocks delivery and execution in live-smoke runs until a client-specific review
approves the configured actor and intended use.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from biz_intel.core.apify_source import BaseApifySource
from biz_intel.models.business import Business
from biz_intel.models.claim import Claim


SOURCE_NAME = "linkedin-apify"
_MAX_PROFILE_URLS = 100


class LinkedInApifySource(BaseApifySource):
    """Observe supplied public LinkedIn profiles with one bounded Actor run."""

    source_name = SOURCE_NAME
    actor_id = "automation-lab/linkedin-profile-scraper"

    def _build_actor_input(self) -> dict:
        raw_urls = self.task.options.get("profile_urls")
        if not isinstance(raw_urls, list) or not raw_urls:
            raise ValueError(
                "linkedin-apify source_options.profile_urls must be a non-empty list."
            )
        if len(raw_urls) > _MAX_PROFILE_URLS:
            raise ValueError(
                f"linkedin-apify accepts at most {_MAX_PROFILE_URLS} profile URLs per run."
            )
        if self.task.limit is not None and self.task.limit < len(raw_urls):
            raw_urls = raw_urls[: self.task.limit]
        urls = [_public_profile_url(value) for value in raw_urls]
        return {"profileUrls": urls}

    def _to_business(self, item: dict) -> Business | None:
        profile_url = _profile_url(item)
        name = _text(item.get("fullName")) or _text(item.get("name"))
        if not profile_url or not name:
            return None
        observed_at = datetime.now(timezone.utc)
        headline = _text(item.get("headline"))
        return Business(
            name=name,
            category=headline,
            linkedin=profile_url,
            source=SOURCE_NAME,
            source_url=profile_url,
            observed_at=observed_at,
            claims=(
                Claim(
                    key="social.linkedin.profile_url",
                    value=profile_url,
                    source=SOURCE_NAME,
                    source_record_id=profile_url,
                    evidence_url=profile_url,
                    observed_at=observed_at,
                    method="apify_public_profile_actor",
                    authority="source_observation",
                ),
            ),
            source_ids={"linkedin_profile_url": profile_url},
            raw_data={
                key: value
                for key, value in {"name": name, "headline": headline}.items()
                if value
            },
        )


def _public_profile_url(value: object) -> str:
    url = _text(value)
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() not in {"linkedin.com", "www.linkedin.com"}
        or not parsed.path.startswith("/in/")
    ):
        raise ValueError(
            "linkedin-apify profile_urls must contain public https://www.linkedin.com/in/... URLs."
        )
    return url


def _profile_url(item: dict) -> str:
    for key in ("profileUrl", "profile_url", "url"):
        value = _text(item.get(key))
        if value:
            try:
                return _public_profile_url(value)
            except ValueError:
                continue
    return ""


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
