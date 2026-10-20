"""Conservative, first-party website enrichment."""

from __future__ import annotations

import re
import socket
import ssl
from dataclasses import dataclass, replace
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


@dataclass(frozen=True, slots=True)
class CrawlOutcome:
    """Observable result of one conservative first-party crawl."""

    url: str
    status: str
    pages: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class SocialEnrichmentResult:
    """A business plus the crawl outcome used to enrich it."""

    business: Business
    crawl: CrawlOutcome | None


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
        crawler: FirstPartyWebsiteCrawler | None = None,
    ) -> None:
        if crawler is not None and http_get is not None:
            raise ValueError("Provide either crawler or http_get, not both.")
        self._crawler = crawler or FirstPartyWebsiteCrawler(
            http_get, respect_robots=respect_robots, max_pages=max_pages
        )

    def enrich(self, business: Business) -> Business:
        return self.enrich_with_outcome(business).business

    def enrich_with_outcome(self, business: Business) -> SocialEnrichmentResult:
        if not business.website or self._all_populated(business):
            return SocialEnrichmentResult(business, None)

        crawl = self._crawler.crawl_with_outcome(business.website)
        if not crawl.pages:
            return SocialEnrichmentResult(business, crawl)

        updates: dict[str, str] = {}
        evidence: dict[str, FieldProvenance] = {}
        for page_url, html in crawl.pages:
            soup = BeautifulSoup(html, "html.parser")
            self._add_contact_updates(soup, business, updates, evidence, page_url)
            self._add_social_updates(soup, business, updates, evidence, page_url)

        if not updates:
            return SocialEnrichmentResult(business, crawl)
        return SocialEnrichmentResult(
            replace(
                business,
                **updates,
                field_provenance={**business.field_provenance, **evidence},
                email_status=("not_checked" if "email" in updates else business.email_status),
                phone_status=("not_checked" if "phone" in updates else business.phone_status),
            ),
            crawl,
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

class FirstPartyWebsiteCrawler:
    """Fetch a small set of same-origin public pages from a business website."""

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
        self._outcomes: dict[str, CrawlOutcome] = {}

    def crawl(self, url: str) -> list[tuple[str, str]]:
        return list(self.crawl_with_outcome(url).pages)

    def crawl_with_outcome(self, url: str) -> CrawlOutcome:
        homepage = _normalise_site_url(url)
        if not homepage:
            return CrawlOutcome(url, "invalid_url")
        if homepage in self._outcomes:
            return self._outcomes[homepage]
        outcome = self._crawl_uncached(homepage)
        self._outcomes[homepage] = outcome
        return outcome

    def _crawl_uncached(self, homepage: str) -> CrawlOutcome:
        if self._respect_robots:
            robots = self._robots_outcome(homepage)
            if robots != "allowed":
                return CrawlOutcome(homepage, robots)

        origin = _origin(homepage)
        if not origin:
            return CrawlOutcome(homepage, "invalid_url")

        pending = [homepage]
        visited: set[str] = set()
        pages: list[tuple[str, str]] = []
        while pending and len(pages) < self._max_pages:
            page_url = pending.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)
            response, failure = self._fetch(page_url)
            if response is None:
                if not pages:
                    return CrawlOutcome(homepage, failure or "network_error")
                continue
            if not _is_same_origin(_response_url(response, page_url), origin):
                if not pages:
                    return CrawlOutcome(homepage, "redirect_blocked")
                continue

            html = response.text
            resolved_url = _response_url(response, page_url)
            pages.append((resolved_url, html))
            soup = BeautifulSoup(html, "html.parser")
            for candidate in self._likely_pages(soup, page_url, origin):
                if candidate not in visited and candidate not in pending:
                    pending.append(candidate)
        return CrawlOutcome(homepage, "success", tuple(pages))

    def _robots_outcome(self, homepage: str) -> str:
        parsed = urlparse(homepage)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        response, failure = self._fetch(robots_url)
        if response is None:
            # A crawler that cannot determine policy must not proceed.
            return failure or "robots_unavailable"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        return "allowed" if parser.can_fetch(_USER_AGENT, homepage) else "robots_denied"

    def _fetch(self, url: str) -> tuple[Any | None, str | None]:
        try:
            response = self._http_get(
                url,
                timeout=_CRAWL_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            )
            response.raise_for_status()
            return response, None
        except Exception as exc:
            return None, _failure_status(exc)

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


def _failure_status(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return "http_error"
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, ssl.SSLError) or "certificate verify failed" in str(current).casefold():
            return "tls_error"
        if isinstance(current, socket.gaierror):
            return "dns_error"
        current = current.__cause__ or current.__context__
    if isinstance(exc, httpx.ConnectError):
        return "connection_error"
    return "network_error"
