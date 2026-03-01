"""Fanqie Novel short story (短篇) backend HTTP API client.

Calls internal REST APIs via page.evaluate(fetch), running entirely inside
the browser's JavaScript context.  This guarantees the request carries the
exact same cookies, headers, and anti-bot signals as a real user interaction.

Base URL : https://fanqienovel.com
Auth     : Cookie-based (managed by Playwright persistent browser context)
Encoding : application/x-www-form-urlencoded;charset=UTF-8
Params   : aid=2503&app_name=muye_novel (appended to every request)

Reverse-engineered from fanqienovel.com JS bundle, 2026-02-28.
"""

import json
import logging
import re
from typing import Optional

from playwright.async_api import Page

from config.exceptions import PublisherError
from publisher.fanqie_client import _text_to_html

logger = logging.getLogger(__name__)

BASE_URL = "https://fanqienovel.com"
_COMMON = "aid=2503&app_name=muye_novel"


def _clean_title(title: str) -> str:
    """Sanitise a story title for the Fanqie API.

    Strips: 《》, leading/trailing quotes, excess whitespace, Markdown bold.
    Ensures the title is within the 30-char limit.
    """
    title = title.strip()
    # Remove book title markers: 《...》 → content
    title = re.sub(r'^《(.+?)》$', r'\1', title)
    # Remove leading/trailing quotes (Chinese & English)
    title = title.strip('""\u201c\u201d\u2018\u2019\'')
    # Remove Markdown bold markers
    title = re.sub(r'\*{1,2}(.+?)\*{1,2}', r'\1', title)
    # Collapse whitespace
    title = re.sub(r'\s+', ' ', title).strip()
    # Truncate to 30 chars (Fanqie limit)
    if len(title) > 30:
        title = title[:30]
    return title


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class FanqieShortStoryClient:
    """Calls Fanqie short story (短篇) backend APIs via page.evaluate(fetch).

    All requests run inside the browser's JS context, so cookies and
    browser fingerprints are identical to a real user session.
    """

    def __init__(self, page: Page):
        self.page = page

    # ---- Low-level HTTP helpers ----------------------------------------

    async def _fetch(
        self,
        method: str,
        path: str,
        form: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> object:
        """Execute a fetch() call inside the browser page context.

        Returns the parsed JSON ``data`` field on success.
        Raises PublisherError on HTTP-level or API-level errors.
        """
        url = f"{BASE_URL}{path}?{_COMMON}"
        if params:
            url += "&" + "&".join(f"{k}={v}" for k, v in params.items())

        # Serialise form dict to JSON so we can pass it through evaluate()
        # Use "" (empty string) for no form data — avoids "null" string being truthy in JS
        form_json = json.dumps(form, ensure_ascii=False) if form else ""

        result = await self.page.evaluate(
            """async ([url, method, formJson]) => {
                try {
                    const opts = { method, credentials: 'include' };
                    if (formJson) {
                        const obj = JSON.parse(formJson);
                        opts.body = new URLSearchParams(obj).toString();
                        opts.headers = {
                            'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'
                        };
                    }
                    const resp = await fetch(url, opts);
                    const text = await resp.text();
                    return { ok: true, status: resp.status, body: text };
                } catch (e) {
                    return { ok: false, error: String(e) };
                }
            }""",
            [url, method, form_json],
        )

        if not result.get("ok"):
            raise PublisherError(
                f"fetch error for {path}: {result.get('error')}",
                {"path": path, "url": url},
            )

        raw = result.get("body", "")
        status = result.get("status", 0)
        # Log full response for short_article endpoints to aid debugging
        if "/short_article/" in path:
            logger.info("%s %s → HTTP %d  body=%s", method, path, status, raw[:500])
        else:
            logger.debug("%s %s → HTTP %d  body=%r", method, path, status, raw[:200])

        if not raw:
            raise PublisherError(
                f"API {path} returned empty response (HTTP {status})",
                {"path": path, "url": url},
            )

        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PublisherError(
                f"API {path} returned non-JSON (HTTP {status}): {raw[:300]}",
                {"path": path},
            ) from exc

        if body.get("code") != 0:
            raise PublisherError(
                f"API {path} failed: {body.get('message', 'unknown error')}",
                {"path": path, "code": body.get("code"), "form": form},
            )

        data = body.get("data")
        return data if data is not None else {}

    async def _post(self, path: str, form: Optional[dict] = None) -> object:
        return await self._fetch("POST", path, form=form)

    async def _get(self, path: str, params: Optional[dict] = None) -> object:
        return await self._fetch("GET", path, params=params)

    # ---- Short Story Category APIs ---------------------------------------

    async def get_category_list(self) -> list[dict]:
        """Return the short story category list.

        Each item has: category_id, label, name.
        Example: {"category_id": 1379, "label": "主分类", "name": "婚姻家庭"}
        """
        data = await self._get("/api/author/short_article/get_category_list/v1/")
        if isinstance(data, dict):
            return data.get("category_list", [])
        if isinstance(data, list):
            return data
        return []

    # ---- Short Story CRUD APIs -------------------------------------------

    async def create_short_story(self) -> str:
        """Create a new short story and return its item_id string."""
        data = await self._post("/api/author/short_article/new/v0/")

        if isinstance(data, dict):
            item_id = str(data.get("item_id", ""))
        else:
            item_id = ""

        if not item_id:
            raise PublisherError("create_short_story: no item_id in response", {"data": data})

        logger.info("Short story created: item_id=%s", item_id)
        return item_id

    async def save_content(
        self,
        item_id: str,
        title: str,
        content: str,
        category_ids: list[int],
        authorize_type: int = 1,
    ) -> dict:
        """Save/update short story content as draft.

        Args:
            item_id: The short story's item_id on Fanqie.
            title: Story title.
            content: Story content (plain text, will be converted to HTML).
            category_ids: List of category_id integers.
            authorize_type: 1=AI generated, 0=not AI generated.

        Returns:
            The API response data dict.
        """
        html_content = _text_to_html(content)
        clean = _clean_title(title)

        form = {
            "item_id": item_id,
            "title": clean,
            "content": html_content,
            "category_ids": json.dumps(category_ids),
            "authorize_type": str(authorize_type),
        }

        data = await self._post("/api/author/short_article/cover/v0/", form)
        logger.info("Short story content saved: item_id=%s, title=%s", item_id, title)

        if isinstance(data, dict):
            return data
        return {}

    async def get_content(self, item_id: str) -> dict:
        """Load a short story's content for editing.

        Returns dict with keys: content (HTML), multi_title, category,
        word_number, publish_status, etc.
        """
        data = await self._get(
            "/api/author/short_article/edit/v1/",
            {"item_id": item_id, "image_fmt_list": "270x480"},
        )
        if isinstance(data, dict):
            return data
        return {}

    async def list_short_stories(
        self,
        page_index: int = 0,
        page_count: int = 10,
    ) -> dict:
        """Return a paginated list of the author's short stories.

        Returns dict with keys: item_list (list[dict]), total_count (int).
        """
        data = await self._get(
            "/api/author/short_article/list/v0/",
            {
                "page_count": str(page_count),
                "page_index": str(page_index),
                "image_fmt_list": "396x220",
                "book_image_fmt_list": "190x250",
                "pack_type": "1",
            },
        )
        if isinstance(data, dict):
            return data
        return {"item_list": [], "total_count": 0}

    # ---- Short Story Publish APIs ----------------------------------------

    async def check_pre_publish(self, item_id: str) -> dict:
        """Run pre-publish validation on a short story.

        Returns the API response data dict (empty on success).
        """
        form = {"item_id": item_id}
        data = await self._post("/api/author/short_article/check_pre/v0", form)
        logger.info("Pre-publish check passed: item_id=%s", item_id)

        if isinstance(data, dict):
            return data
        return {}

    async def publish(self, item_id: str) -> dict:
        """Publish a short story.

        Returns the API response data dict.
        """
        form = {"item_id": item_id}
        data = await self._post("/api/author/short_article/publish/v0/", form)
        logger.info("Short story published: item_id=%s", item_id)

        if isinstance(data, dict):
            return data
        return {}

    # ---- Hot Topics API --------------------------------------------------

    async def get_hot_topics(self, type: int = 0) -> list[dict]:
        """Return trending topics from Douyin.

        Args:
            type: Topic type filter (0=default).

        Returns:
            List of hot topic dicts.
        """
        data = await self._get(
            "/api/author/short_article/douyin_hot_list/v0/",
            {"type": str(type)},
        )
        if isinstance(data, dict):
            # Try common nested structures
            return data.get("hot_list", data.get("list", []))
        if isinstance(data, list):
            return data
        return []

    # ---- High-level convenience method -----------------------------------

    async def publish_short_story(
        self,
        title: str,
        content: str,
        category_ids: list[int],
        authorize_type: int = 1,
        publish_mode: str = "draft",
    ) -> str:
        """Create a new short story, save its content, and optionally publish.

        This is a convenience method that chains: create → save → publish.

        Args:
            title: Story title.
            content: Story content (plain text, will be converted to HTML).
            category_ids: List of category_id integers.
            authorize_type: 1=AI generated, 0=not AI generated.
            publish_mode: "draft" to save as draft only, "publish" to publish.

        Returns:
            The item_id of the created short story.
        """
        # Step 1: Create a new short story slot
        item_id = await self.create_short_story()

        # Step 2: Save the content
        await self.save_content(
            item_id=item_id,
            title=title,
            content=content,
            category_ids=category_ids,
            authorize_type=authorize_type,
        )

        # Step 3: Optionally publish
        if publish_mode == "publish":
            await self.check_pre_publish(item_id)
            await self.publish(item_id)
            logger.info(
                "Short story created and published: item_id=%s, title=%s",
                item_id, title,
            )
        else:
            logger.info(
                "Short story created as draft: item_id=%s, title=%s",
                item_id, title,
            )

        return item_id
