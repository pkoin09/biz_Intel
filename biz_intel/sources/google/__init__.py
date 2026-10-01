"""
Google source plugins: Places API and Apify actor.
"""

SOURCE_NAME = "google"
APIFY_SOURCE_NAME = "google-apify"

from .apify_source import GoogleMapsApifySource
from .source import GooglePlacesSource

__all__ = [
    "SOURCE_NAME",
    "APIFY_SOURCE_NAME",
    "GooglePlacesSource",
    "GoogleMapsApifySource",
]
