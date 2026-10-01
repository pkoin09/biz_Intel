"""
URL helpers for Yellow Pages.
"""

from urllib.parse import quote_plus


BASE_URL = "https://www.yellowpages.com"


def build_search_url(
    query: str,
    location: str,
    page: int | None = None,
) -> str:
    """
    Build a Yellow Pages search URL.

    ``page`` is the 1-based results page; the ``&page=N`` parameter is only
    appended for pages 2+, so the first-page URL is byte-identical to the
    pre-pagination version.
    """

    query = quote_plus(query)

    location = quote_plus(location)

    url = (
        f"{BASE_URL}"
        f"/search?"
        f"search_terms={query}"
        f"&geo_location_terms={location}"
    )

    if page and page >= 2:
        url += f"&page={page}"

    return url
