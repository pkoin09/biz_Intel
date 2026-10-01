from __future__ import annotations

from biz_intel.core.base_spider import BaseBusinessSpider

# from biz_intel.sources.yellowpages import (
#     YellowPagesExtractor,
#     build_search_url,
# )

from .extractor import YellowPagesExtractor
from .urls import build_search_url

class YellowPagesSpider(BaseBusinessSpider):

    name = "yellowpages"

    source_name = "yellowpages"

    allowed_domains = ["yellowpages.com"]

    extractor_class = YellowPagesExtractor

    # Yellow Pages is free (no per-page billing), so pagination is a quality
    # lever: walk pages until the task's limit is filled or results run out.
    paginates = True

    def build_search_url(self, page: int = 1) -> str:
        return build_search_url(
            self.query,
            self.location,
            page=page,
        )
