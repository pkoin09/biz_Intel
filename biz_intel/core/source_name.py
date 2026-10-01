from enum import StrEnum


class SourceName(StrEnum):
    """
    Sources a job can request.

    CSV is the initial approved client-input path. Its ``path`` belongs in
    ``source_options.csv``; the search fields remain useful job metadata and
    keep the file source on the same planning/execution boundary as others.
    """

    CSV = "csv"
    GOOGLE = "google"
    GOOGLE_APIFY = "google-apify"
    YELP = "yelp"
    YELP_APIFY = "yelp-apify"
    YELLOWPAGES = "yellowpages"
    NPPES = "nppes"
