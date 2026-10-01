"""Conservative, first-party website enrichment."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from biz_intel.models.business import Business, FieldProvenance

_PATTERNS: dict[str, re.Pattern[str]] = {
    "linkedin": re.compile(r"linkedin\.com/company/[\w\-\.]+", re.I),
    "instagram": re.compile(r"instagram\.com/[\w\.]+", re.I),
    "facebook": re.compile(r"facebook\.com/[\w\.\-]+", re.I),
    "twitter": re.compile(r"(?:twitter|x)\.com/[\w]+", re.I),
}
_LIKELY_PAGE_WORDS = ("contact", "about", "team", "staff", "people")
_CRAWL_TIMEOUT = 10
_MAX_PAGES = 4
_USER_AGENT = "biz-intel/1.0"

HttpGet = Callable[..., Any]


class SocialEnricher:
    """Fill blank public contact and social fields from a first-party website.

    ``http_get`` is deliberately injectable. It should behave like
    :func:`httpx.get`, accepting keyword arguments and returning an object with
    ``text`` and ``raise_for_status``. Failures are a no-op for that business.
    """

    def __init__(
        self,
        http_get: HttpGet | None = None,
        *,
        respect_robots: bool = True,
        max_pages: int = _MAX_PAGES,
    ) -> None:
        self._http_get = http_get or httpx.get
        self._respect_robots = respect_robots
        self._max_pages = max(1, max_pages)

    def enrich(self, business: Business) -> Business:
        if not business.website or self._all_populated(business):
            return business

        pages = self._crawl(business.website)
        if not pages:
            return business

        updates: dict[str, str] = {}
        evidence: dict[str, FieldProvenance] = {}
        for page_url, html in pages:
            soup = BeautifulSoup(html, "html.parser")
            self._add_contact_updates(soup, business, updates, evidence, page_url)
            self._add_social_updates(soup, business, updates, evidence, page_url)

        if not updates:
            return business
        return replace(
            business,
            **updates,
            field_provenance={**business.field_provenance, **evidence},
            email_status=("not_checked" if "email" in updates else business.email_status),
            phone_status=("not_checked" if "phone" in updates else business.phone_status),
        )

    def _all_populated(self, business: Business) -> bool:
        return all(
            getattr(business, field)
            for field in ("phone", "email", "linkedin", "instagram", "facebook", "twitter")
        )

    def _add_contact_updates(
        self,
        soup: BeautifulSoup,
        business: Business,
        updates: dict[str, str],
        evidence: dict[str, FieldProvenance],
        page_url: str,
    ) -> None:
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            lower_href = href.lower()
            if lower_href.startswith("mailto:") and not business.email and "email" not in updates:
                # Query parameters are not part of the explicitly published address.
                email = unquote(href[7:].split("?", 1)[0]).strip()
                if email:
                    updates["email"] = email
                    evidence["email"] = _first_party_evidence(page_url)
            elif lower_href.startswith("tel:") and not business.phone and "phone" not in updates:
                phone = unquote(href[4:].split("?", 1)[0]).strip()
                if phone:
                    updates["phone"] = phone
                    evidence["phone"] = _first_party_evidence(page_url)

    def _add_social_updates(
        self,
        soup: BeautifulSoup,
        business: Business,
        updates: dict[str, str],
        evidence: dict[str, FieldProvenance],
        page_url: str,
    ) -> None:
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            for field, pattern in _PATTERNS.items():
                if getattr(business, field) or field in updates:
                    continue
                match = pattern.search(href)
                if match:
                    updates[field] = _normalise(match.group())
                    evidence[field] = _first_party_evidence(page_url)

    def _crawl(self, url: str) -> list[tuple[str, str]]:
        homepage = _normalise_site_url(url)
        if not homepage:
            return []
        if self._respect_robots and not self._robots_allow(homepage):
            return []

        origin = _origin(homepage)
        if not origin:
            return []

        pending = [homepage]
        visited: set[str] = set()
        pages: list[tuple[str, str]] = []
        while pending and len(pages) < self._max_pages:
            page_url = pending.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)
            response = self._fetch(page_url)
            if response is None or not _is_same_origin(_response_url(response, page_url), origin):
                continue

            html = response.text
            resolved_url = _response_url(response, page_url)
            pages.append((resolved_url, html))
            soup = BeautifulSoup(html, "html.parser")
            for candidate in self._likely_pages(soup, page_url, origin):
                if candidate not in visited and candidate not in pending:
                    pending.append(candidate)
        return pages

    def _robots_allow(self, homepage: str) -> bool:
        parsed = urlparse(homepage)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        response = self._fetch(robots_url)
        if response is None:
            # A crawler that cannot determine policy must not proceed.
            return False
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        return parser.can_fetch(_USER_AGENT, homepage)

    def _fetch(self, url: str) -> Any | None:
        try:
            response = self._http_get(
                url,
                timeout=_CRAWL_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            )
            response.raise_for_status()
            return response
        except Exception:
            return None

    def _likely_pages(self, soup: BeautifulSoup, base_url: str, origin: tuple[str, str]) -> list[str]:
        pages: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            label = anchor.get_text(" ", strip=True).lower()
            candidate = urljoin(base_url, href)
            path = urlparse(candidate).path.lower()
            if (
                _is_same_origin(candidate, origin)
                and any(word in f"{label} {path}" for word in _LIKELY_PAGE_WORDS)
            ):
                pages.append(candidate.split("#", 1)[0])
        return pages


def _normalise_site_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme:
        return f"https://{url.strip()}" if url.strip() else ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def _origin(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return parsed.scheme.lower(), parsed.netloc.lower()


def _is_same_origin(url: str, origin: tuple[str, str]) -> bool:
    return _origin(url) == origin


def _response_url(response: Any, fallback: str) -> str:
    value = getattr(response, "url", None)
    if isinstance(value, (str, httpx.URL)):
        return str(value)
    return fallback


def _normalise(match: str) -> str:
    """Add https:// scheme if the match came from a bare href."""
    parsed = urlparse(match)
    if not parsed.scheme:
        return f"https://www.{match}"
    return match


def _first_party_evidence(page_url: str) -> FieldProvenance:
    return FieldProvenance(
        source="first_party_web",
        evidence_url=page_url,
        observed_at=datetime.now(timezone.utc),
        method="public_link",
    )
