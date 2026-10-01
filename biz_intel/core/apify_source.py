"""
Base class for Apify actor-backed sources.

Concrete sources declare an actor_id and implement _build_actor_input() and
_to_business(). The base class handles authentication, the synchronous run
call, and iteration over dataset items.

Actor IDs use the Apify format "username/actor-name". The base class converts
this to the URL-safe form "username~actor-name" automatically.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator

import httpx

from biz_intel.config import config
from biz_intel.core.api_source import BaseApiSource
from biz_intel.models.business import Business

_APIFY_BASE = "https://api.apify.com/v2/acts"
_RUN_TIMEOUT_SECONDS = 600


class BaseApifySource(BaseApiSource):
    """
    Runs an Apify actor synchronously and yields Business records from its
    dataset output.

    Subclasses must set actor_id at the class level and implement
    _build_actor_input() and _to_business().
    """

    actor_id: str

    def fetch(self) -> Iterator[Business]:
        api_key = config.APIFY_API_KEY
        if not api_key:
            raise RuntimeError(
                "APIFY_API_KEY is not set. Add it to your .env file."
            )

        actor_url_id = self.actor_id.replace("/", "~")
        url = f"{_APIFY_BASE}/{actor_url_id}/run-sync-get-dataset-items"

        response = httpx.post(
            url,
            params={
                "token": api_key,
                "format": "json",
                "clean": "true",
                "timeout": _RUN_TIMEOUT_SECONDS,
            },
            json=self._build_actor_input(),
            timeout=_RUN_TIMEOUT_SECONDS + 30,
        )
        response.raise_for_status()

        for item in response.json():
            business = self._to_business(item)
            if business is not None:
                yield business

    @abstractmethod
    def _build_actor_input(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def _to_business(self, item: dict) -> Business | None:
        raise NotImplementedError
