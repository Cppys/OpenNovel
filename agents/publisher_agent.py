"""Publisher Agent: Fanqie Novel platform integration.

Uses Playwright only for authentication (persistent cookie session).
All actual API calls go through FanqieClient which uses page.request
(HTTP) directly — no UI automation needed.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from config.settings import Settings
from publisher.browser import BrowserManager
from publisher.auth import ensure_logged_in
from publisher.fanqie_client import FanqieClient

logger = logging.getLogger(__name__)


class PublisherAgent:
    """Manages authentication and delegates API calls to FanqieClient."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self._browser_mgr: Optional[BrowserManager] = None
        self._client: Optional[FanqieClient] = None

    async def launch_browser(self, headless: bool = False, use_auth_state: bool = False):
        """Launch Playwright browser.

        Args:
            headless:       Run headless.  Fanqie's bot-detection redirects to
                            login when True, so publish flows default to False.
            use_auth_state: Load cookies / localStorage from the saved
                            auth_state.json produced by setup-browser.
        """
        storage_state: Optional[str] = None
        if use_auth_state:
            auth_path = Path(self.settings.auth_state_path)
            if auth_path.exists():
                storage_state = str(auth_path)
            else:
                logger.warning(
                    "auth_state.json not found at %s — please run 'opennovel setup-browser' first",
                    auth_path,
                )

        self._browser_mgr = BrowserManager(self.settings.browser_user_data_dir)
        await self._browser_mgr.launch(headless=headless, storage_state=storage_state)
        logger.info("Browser launched (headless=%s, auth_state=%s)", headless, storage_state or "none")

    async def ensure_logged_in(self) -> bool:
        """Navigate to Fanqie writer backend and verify the session is authenticated."""
        return await ensure_logged_in(self._browser_mgr.page)

    def _get_client(self) -> FanqieClient:
        if self._client is None:
            self._client = FanqieClient(page=self._browser_mgr.page)
        return self._client

    async def close(self):
        """Close browser and cleanup."""
        if self._browser_mgr:
            await self._browser_mgr.close()
        logger.info("Publisher closed")

    # ---- Public async API -----------------------------------------------

    async def publish_chapters(
        self,
        book_id: str,
        chapters: list[dict],
        publish_mode: str = "draft",
    ) -> list[dict]:
        """Upload chapters to Fanqie via HTTP API.

        Args:
            book_id:      Fanqie book ID (stored in novel.fanqie_book_id).
            chapters:     List of dicts with 'title' and 'content' keys.
            publish_mode: 'draft' or 'publish'.

        Returns:
            List of result dicts per chapter.
        """
        return await self._get_client().publish_chapters(
            book_id=book_id,
            chapters=chapters,
            publish_mode=publish_mode,
        )

    async def create_book_on_platform(
        self,
        title: str,
        genre: str,
        synopsis: str,
        protagonist_name_1: str = "",
        protagonist_name_2: str = "",
    ) -> str:
        """Create a new book via HTTP API and return book_id."""
        return await self._get_client().create_book(
            title=title,
            genre=genre,
            synopsis=synopsis,
            protagonist_name_1=protagonist_name_1,
            protagonist_name_2=protagonist_name_2,
        )

    # ---- Sync wrappers (for CLI) -----------------------------------------

    def publish_sync(
        self,
        book_id: str,
        chapters: list[dict],
        publish_mode: str = "draft",
    ) -> list[dict]:
        """Synchronous wrapper: launch → login → publish → close."""
        return asyncio.run(self._run_publish(book_id, chapters, publish_mode))

    def create_book_sync(
        self,
        title: str,
        genre: str,
        synopsis: str,
        protagonist_name_1: str = "",
        protagonist_name_2: str = "",
    ) -> str:
        """Synchronous wrapper: launch → login → create book → close."""
        return asyncio.run(
            self._run_create_book(title, genre, synopsis, protagonist_name_1, protagonist_name_2)
        )

    def get_book_list_sync(self) -> list[dict]:
        """Synchronous wrapper: launch → login → get book list → close."""
        return asyncio.run(self._run_get_book_list())

    # ---- Internal async runners -----------------------------------------

    async def _run_get_book_list(self) -> list[dict]:
        try:
            await self.launch_browser(headless=False, use_auth_state=True)
            if not await self.ensure_logged_in():
                return []
            return await self._get_client().get_book_list()
        finally:
            await self.close()

    async def _run_publish(
        self, book_id: str, chapters: list[dict], publish_mode: str,
    ) -> list[dict]:
        try:
            # Use saved auth state; headless=False avoids Fanqie's bot detection
            await self.launch_browser(headless=False, use_auth_state=True)
            if not await self.ensure_logged_in():
                return [{
                    "success": False,
                    "message": "登录失败——请先运行 opennovel setup-browser 完成登录",
                    "item_id": "",
                }]
            return await self.publish_chapters(book_id, chapters, publish_mode)
        finally:
            await self.close()

    async def _run_create_book(
        self,
        title: str,
        genre: str,
        synopsis: str,
        protagonist_name_1: str = "",
        protagonist_name_2: str = "",
    ) -> str:
        try:
            await self.launch_browser(headless=False, use_auth_state=True)
            if not await self.ensure_logged_in():
                logger.error("Login failed, cannot create book")
                return ""
            return await self.create_book_on_platform(
                title, genre, synopsis, protagonist_name_1, protagonist_name_2
            )
        finally:
            await self.close()
