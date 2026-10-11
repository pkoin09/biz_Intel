"""
Application entry point.
"""

from biz_intel.core.pipeline import PipelineRunner
from biz_intel.core.registry import registry
from biz_intel.core.source_kind import SourceKind
from biz_intel.core.source_policy import CLIENT_INPUT_POLICY
from biz_intel.core.source_policy import CA_DENTAL_BOARD_POLICY
from biz_intel.core.source_policy import EXPERIMENTAL_OR_DISALLOWED_POLICY
from biz_intel.core.source_policy import LINKEDIN_APIFY_POLICY
from biz_intel.core.source_policy import NPPES_POLICY
from biz_intel.core.source_policy import OVERTURE_POLICY
from biz_intel.core.source_policy import WA_LI_POLICY
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
from biz_intel.sources.ca_dental_board import (
    SOURCE_NAME as CA_DENTAL_BOARD_NAME,
    CaliforniaDentalBoardSource,
)
from biz_intel.sources.wa_li import SOURCE_NAME as WA_LI_NAME, WaLiSource
from biz_intel.sources.overture import SOURCE_NAME as OVERTURE_NAME, OvertureSnapshotSource
from biz_intel.sources.linkedin import (
    SOURCE_NAME as LINKEDIN_APIFY_NAME,
    LinkedInApifySource,
)


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
        LINKEDIN_APIFY_NAME,
        LinkedInApifySource,
        kind=SourceKind.APIFY,
        policy=LINKEDIN_APIFY_POLICY,
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
    registry.register(
        WA_LI_NAME,
        WaLiSource,
        kind=SourceKind.API,
        policy=WA_LI_POLICY,
    )
    registry.register(
        CA_DENTAL_BOARD_NAME,
        CaliforniaDentalBoardSource,
        kind=SourceKind.FILE,
        policy=CA_DENTAL_BOARD_POLICY,
    )
    registry.register(
        OVERTURE_NAME,
        OvertureSnapshotSource,
        kind=SourceKind.FILE,
        policy=OVERTURE_POLICY,
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
