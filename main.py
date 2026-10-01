"""
Application entry point.
"""

from biz_intel.core.pipeline import PipelineRunner
from biz_intel.core.registry import registry
from biz_intel.core.source_kind import SourceKind
from biz_intel.core.source_policy import CLIENT_INPUT_POLICY
from biz_intel.core.source_policy import EXPERIMENTAL_OR_DISALLOWED_POLICY
from biz_intel.core.source_policy import NPPES_POLICY
from biz_intel.metrics import metrics

from biz_intel.sources.csv import (
    CSVSource,
    SOURCE_NAME as CSV_NAME,
)

from biz_intel.sources.google import (
    SOURCE_NAME as GOOGLE_NAME,
    APIFY_SOURCE_NAME as GOOGLE_APIFY_NAME,
    GooglePlacesSource,
    GoogleMapsApifySource,
)
from biz_intel.sources.yelp import (
    SOURCE_NAME as YELP_NAME,
    APIFY_SOURCE_NAME as YELP_APIFY_NAME,
    YelpSource,
    YelpApifySource,
)
from biz_intel.sources.yellowpages import (
    SOURCE_NAME as YP_NAME,
    YellowPagesSpider,
)
from biz_intel.sources.nppes import SOURCE_NAME as NPPES_NAME, NppesSource


def register_sources() -> None:
    """
    Register available source plugins.
    """

    registry.register(
        YP_NAME,
        YellowPagesSpider,
        kind=SourceKind.SCRAPER,
        policy=EXPERIMENTAL_OR_DISALLOWED_POLICY,
    )

    registry.register(
        GOOGLE_NAME,
        GooglePlacesSource,
        kind=SourceKind.API,
        policy=EXPERIMENTAL_OR_DISALLOWED_POLICY,
    )

    registry.register(
        YELP_NAME,
        YelpSource,
        kind=SourceKind.API,
        policy=EXPERIMENTAL_OR_DISALLOWED_POLICY,
    )

    registry.register(
        GOOGLE_APIFY_NAME,
        GoogleMapsApifySource,
        kind=SourceKind.APIFY,
        policy=EXPERIMENTAL_OR_DISALLOWED_POLICY,
    )

    registry.register(
        YELP_APIFY_NAME,
        YelpApifySource,
        kind=SourceKind.APIFY,
        policy=EXPERIMENTAL_OR_DISALLOWED_POLICY,
    )

    registry.register(
        CSV_NAME,
        CSVSource,
        kind=SourceKind.FILE,
        policy=CLIENT_INPUT_POLICY,
    )
    registry.register(
        NPPES_NAME,
        NppesSource,
        kind=SourceKind.API,
        policy=NPPES_POLICY,
    )

def main() -> None:
    register_sources()
    source_class = registry.get("csv")

    source = source_class(
        "tests/fixtures/businesses_messy_synthetic.csv",
    )

    businesses = list(
        PipelineRunner().run(
            source.extract(),
        )
    )

    print(f"\nBusinesses after pipeline: {len(businesses)}\n")
    print("Pipeline Metrics")
    print("----------------")

    for key, value in sorted(metrics.items()):
        print(f"{key:25} {value}")
    print()

    for business in businesses:
        print(business)

if __name__ == "__main__":
    main()
