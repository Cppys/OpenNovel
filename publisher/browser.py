"""Playwright browser lifecycle management."""

import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# Chrome args that prevent common bot-detection heuristics
_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]


class BrowserManager:
    """Manages a Playwright browser session.

    Two modes:
    - Persistent context (setup-browser / interactive login): uses a Chromium
      user-data directory so the user can log in visually. Call ``launch()``
      without ``storage_state``.
    - Ephemeral context (publish / automated): loads saved cookies +
      localStorage from a JSON file produced by ``storage_state()``. Call
      ``launch(storage_state=path)``.
    """

    def __init__(self, user_data_dir: str | Path):
        self.user_data_dir = str(user_data_dir)
        self._playwright = None
        self._browser: Optional[Browser] = None   # only for ephemeral mode
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser not launched. Call launch() first.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if not self._context:
            raise RuntimeError("Browser not launched. Call launch() first.")
        return self._context

    async def launch(
        self,
        headless: bool = False,
        storage_state: Optional[str] = None,
    ):
        """Launch browser.

        Args:
            headless: Whether to run headless.
            storage_state: Path to a ``storage_state.json`` file.  When
                provided *and* the file exists the browser is launched in
                ephemeral mode with the saved cookies / localStorage restored.
                When absent (or the file doesn't exist) a persistent Chromium
                user-data directory is used instead (interactive login mode).
        """
        Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()

        use_storage = storage_state and Path(storage_state).exists()

        if use_storage:
            # Ephemeral context with saved auth state
            logger.info("Launching ephemeral browser from storage state: %s", storage_state)
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=_STEALTH_ARGS,
            )
            self._context = await self._browser.new_context(
                storage_state=storage_state,
                viewport={"width": 1280, "height": 800},
                locale="zh-CN",
            )
        else:
            # Persistent context for interactive login
            logger.info("Launching persistent browser context in %s", self.user_data_dir)
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=headless,
                viewport={"width": 1280, "height": 800},
                locale="zh-CN",
                args=_STEALTH_ARGS,
            )

        self._page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )
        logger.info(
            "Browser ready (headless=%s, storage_state=%s)",
            headless,
            "yes" if use_storage else "no",
        )

    async def close(self):
        """Close browser and stop Playwright."""
        if self._context:
            await self._context.close()
            self._context = None
            self._page = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("Browser closed")

    async def __aenter__(self):
        await self.launch()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
