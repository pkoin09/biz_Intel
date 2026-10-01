"""
Global Scrapy settings.
"""

# from inspect import AGEN_CREATED
from pathlib import Path

from dotenv import load_dotenv
import os

####################################################
# Environment
####################################################

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

####################################################
# Scrapy
####################################################

BOT_NAME = "biz_intel"

SPIDER_MODULES = ["biz_intel.spiders"]

NEWSPIDER_MODULE = "biz_intel.spiders"

ROBOTSTXT_OBEY = False

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

####################################################
# Request Settings
####################################################

CONCURRENT_REQUESTS = 8

DOWNLOAD_DELAY = 1

COOKIES_ENABLED = False

####################################################
# Playwright
####################################################

PLAYWRIGHT_MAX_CONTEXTS = 1

DOWNLOAD_HANDLERS = {
    # "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

PLAYWRIGHT_BROWSER_TYPE = "chromium"

PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": os.getenv("HEADLESS", "True").lower() == "true",
}

PLAYWRIGHT_CONTEXTS = {
    "default": {
        "viewport": {"width": 1440, "height": 900},
        "locale": "en-US",
        "timezone_id": "America/Los_Angeles",
    }
}

####################################################
# Pipelines
####################################################

ITEM_PIPELINES = {
    # Added later
}

####################################################
# Export
####################################################

EXPORT_PATH = os.getenv("EXPORT_PATH", "exports")

SCREENSHOT_PATH = os.getenv(
    "SCREENSHOT_PATH",
    "screenshots",
)

####################################################
# USER AGENT
####################################################

# USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)

####################################################
# DEFAULT REQUEST HEADERS
####################################################

DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
}
