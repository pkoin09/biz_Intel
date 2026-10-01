"""
Reusable Playwright browser actions.
"""

from __future__ import annotations

from pathlib import Path

from playwright.async_api import Page


class BrowserActions:
    """
    Reusable Playwright browser operations.

    This layer owns browser behavior.
    It should not know anything about business data.
    """

    @staticmethod
    async def prepare(page: Page) -> None:
        """
        Prepare a page before extraction.

        Centralized browser readiness lifecycle.
        """

        await BrowserActions.wait_for_dom_ready(page)

        await BrowserActions.wait_for_network_idle(page)

    @staticmethod
    async def wait_for_dom_ready(page: Page) -> None:
        """
        Wait until the DOM is ready.
        """

        await page.wait_for_load_state("domcontentloaded")

    @staticmethod
    async def wait_for_network_idle(page: Page) -> None:
        """
        Wait until network activity settles.
        """

        await page.wait_for_load_state("networkidle")

    @staticmethod
    async def wait(
        page: Page,
        milliseconds: int = 1000,
    ) -> None:
        """
        Pause execution.
        """

        await page.wait_for_timeout(milliseconds)

    @staticmethod
    async def scroll_to_bottom(
        page: Page,
        pause: int = 1000,
        max_scrolls: int = 20,
    ) -> None:
        """
        Scroll until page height stops growing.
        """

        previous_height = 0

        for _ in range(max_scrolls):

            current_height = await page.evaluate("document.body.scrollHeight")

            if current_height == previous_height:
                break

            previous_height = current_height

            await page.evaluate(
                """
                window.scrollTo(
                    0,
                    document.body.scrollHeight
                );
                """
            )

            await page.wait_for_timeout(pause)

    @staticmethod
    async def click(
        page: Page,
        selector: str,
        timeout: int = 5000,
    ) -> bool:
        """
        Click an element if it exists.
        """

        try:
            await page.locator(selector).click(timeout=timeout)

            return True

        except Exception:
            return False

    @staticmethod
    async def screenshot(
        page: Page,
        path: Path,
        full_page: bool = True,
    ) -> None:
        """
        Capture a screenshot.
        """

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        await page.screenshot(
            path=str(path),
            full_page=full_page,
        )

    @staticmethod
    async def html(
        page: Page,
    ) -> str:
        """
        Return rendered HTML.
        """

        return await page.content()
