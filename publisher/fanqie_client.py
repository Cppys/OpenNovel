"""Fanqie Novel writer backend HTTP API client.

Calls internal REST APIs via page.evaluate(fetch), running entirely inside
the browser's JavaScript context.  This guarantees the request carries the
exact same cookies, headers, and anti-bot signals as a real user interaction.

Base URL : https://fanqienovel.com
Auth     : Cookie-based (managed by Playwright persistent browser context)
Encoding : application/x-www-form-urlencoded;charset=UTF-8
Params   : aid=2503&app_name=muye_novel (appended to every request)

Reverse-engineered from fanqienovel.com JS bundle, 2026-02-23.
"""

import json
import logging
import re
from typing import Optional

from playwright.async_api import Page

from config.exceptions import PublisherError

logger = logging.getLogger(__name__)

BASE_URL = "https://fanqienovel.com"
_COMMON = "aid=2503&app_name=muye_novel"

# Genres that belong to 女频 (gender=0); everything else is 男频 (gender=1)
_FEMALE_GENRES = {"言情", "女频", "现代言情", "古代言情", "仙侠言情", "豪门", "穿越", "宫斗"}


def _clean_protagonist_name(name: str) -> str:
    """Strip annotations like （孙悟空） and /alias from protagonist names.

    Fanqie API likely rejects fullwidth parentheses and forward slashes.
    """
    name = re.sub(r'（[^）]*）', '', name)   # remove （...）
    name = re.sub(r'\([^)]*\)', '', name)    # remove (...)
    name = name.split('/')[0].strip()        # keep only first part of a/b
    return name[:20]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text_to_html(text: str) -> str:
    """Wrap each non-empty line of plain text in <p> tags for Fanqie editor."""
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    return "".join(f"<p>{p}</p>" for p in paragraphs)


def _find_label_ids(labels: list[dict], genre: str, max_count: int = 4) -> list[str]:
    """Return up to max_count label IDs whose names overlap with the genre string."""
    def get_name(l: dict) -> str:
        return l.get("label_name") or l.get("name", "")

    def get_id(l: dict) -> str:
        v = l.get("label_id") or l.get("id") or l.get("category_id")
        return str(v) if v else ""

    selected: list[str] = []
    # Split genre into individual words for matching
    genre_tokens = set(genre.replace(" ", ""))

    for label in labels:
        name = get_name(label)
        lid = get_id(label)
        if not name or not lid:
            continue
        # Match if any char in genre appears in label name, or label name substring of genre
        if any(ch in name for ch in genre_tokens) or name in genre:
            selected.append(lid)
        if len(selected) >= max_count:
            break

    # Fallback: use first two labels so we at least send something
    if not selected and labels:
        selected = [get_id(l) for l in labels[:2] if get_id(l)]

    return selected


def _find_category_id(categories: list[dict], genre: str) -> int:
    """Return the best-matching category_id for a genre string."""
    # API returns items with key "name" (not "category_name")
    def get_name(cat: dict) -> str:
        return cat.get("name") or cat.get("category_name", "")

    # Exact match
    for cat in categories:
        if get_name(cat) == genre:
            return int(cat["category_id"])
    # Partial match
    for cat in categories:
        name = get_name(cat)
        if genre in name or name in genre:
            return int(cat["category_id"])
    # Fallback to first available
    if categories:
        logger.warning("No category match for '%s', falling back to: %s", genre, categories[0])
        return int(categories[0]["category_id"])
    return 0


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class FanqieClient:
    """Calls Fanqie writer backend APIs via page.evaluate(fetch).

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
        # Log full response for publish-related endpoints to aid debugging
        if "/article/" in path or "/publish" in path or "book/create" in path:
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

    async def _post(self, path: str, form: dict) -> object:
        return await self._fetch("POST", path, form=form)

    async def _get(self, path: str, params: Optional[dict] = None) -> object:
        return await self._fetch("GET", path, params=params)

    # ---- Book APIs -------------------------------------------------------

    async def get_category_list(self, gender: int = 1) -> list[dict]:
        """Return the book category list for the given gender (0=女频, 1=男频)."""
        data = await self._get("/api/author/book/category_list/v0/", {"gender": gender})
        if isinstance(data, list):
            return data
        return data.get("category_list", [])

    async def get_label_list(self, gender: int = 1) -> list[dict]:
        """Return the flat list of all book labels/tags for the given gender.

        Calls group_category_list which returns label groups; we flatten to a
        single list of individual label dicts.
        """
        data = await self._get(
            "/api/author/book/group_category_list/v0/", {"gender": gender}
        )
        logger.info("group_category_list raw response: %s", str(data)[:400])

        labels: list[dict] = []
        if isinstance(data, list):
            # Direct list of labels
            labels = data
        elif isinstance(data, dict):
            # Try common nested structures
            for group in data.get("group_list", data.get("label_list", [])):
                if isinstance(group, dict):
                    labels.extend(
                        group.get("label_list", group.get("labels", []))
                    )
                elif isinstance(group, (int, str)):
                    # flat list of IDs — unexpected, skip
                    pass
        return labels

    async def get_book_list(self) -> list[dict]:
        """Return all books owned by the logged-in author."""
        data = await self._get(
            "/api/author/homepage/book_list/v0/",
            {"page_count": "50", "page_index": "0"},
        )
        if isinstance(data, dict):
            books = data.get("book_list", [])
            if isinstance(books, list):
                return books
        if isinstance(data, list):
            return data
        return []

    async def create_book(
        self,
        title: str,
        genre: str,
        synopsis: str,
        protagonist_name_1: str = "",
        protagonist_name_2: str = "",
    ) -> str:
        """Create a new book and return its book_id string."""
        # Gender: only treat as female if genre is *exclusively* female-type keywords
        gender = 0 if any(g in genre for g in _FEMALE_GENRES) and not any(
            m in genre for m in ("仙侠", "玄幻", "武侠", "男频", "都市", "科幻")
        ) else 1
        categories = await self.get_category_list(gender)
        category_id = _find_category_id(categories, genre)

        # Fetch labels (tags) — required field in UI
        labels = await self.get_label_list(gender)
        label_ids = _find_label_ids(labels, genre)
        logger.info(
            "create_book: genre=%r  gender=%d  category_id=%d  label_ids=%s",
            genre, gender, category_id, label_ids,
        )

        # Fanqie abstract field: single-line only (no newlines), >= 50 chars
        abstract = " ".join(line.strip() for line in synopsis.splitlines() if line.strip())
        if len(abstract) < 50:
            abstract = abstract + "。" * (50 - len(abstract))

        p1 = _clean_protagonist_name(protagonist_name_1)[:5]
        p2 = _clean_protagonist_name(protagonist_name_2)[:5]

        try:
            data = await self._post("/api/author/book/create/v0/", {
                "aid": "2503",
                "app_name": "muye_novel",
                "book_name": title,
                "gender": str(gender),
                "abstract": abstract,
                "category_id": str(category_id),
                "original_type": "1",                # 原创
                "label_id_list": ",".join(label_ids), # 作品标签
                "protagonist_name_1": p1,
                "protagonist_name_2": p2,
            })
        except PublisherError as e:
            # Platform allows max 1 new book per day; surface this prominently
            raise PublisherError(
                f"创建书籍失败（注意：番茄平台每天限创建1本新书，如已创建过请明天再试）: {e}",
                {"original_error": str(e)},
            ) from e

        if isinstance(data, dict):
            book_id = str(data.get("book_id", ""))
        else:
            book_id = ""

        if not book_id:
            raise PublisherError("create_book: no book_id in response", {"data": data})

        logger.info("Book created: id=%s, title=%s", book_id, title)
        return book_id

    # ---- Volume APIs -----------------------------------------------------

    async def get_volume_list(self, book_id: str) -> list[dict]:
        """Return the volume list for a book."""
        data = await self._get("/api/author/volume/volume_list/v1/", {"book_id": book_id})
        if isinstance(data, list):
            return data
        return data.get("volume_list", [])

    async def _get_first_volume(self, book_id: str) -> tuple[str, str]:
        """Return (volume_id, volume_name) for the first volume of a book."""
        volumes = await self.get_volume_list(book_id)
        if not volumes:
            raise PublisherError(f"No volumes found for book {book_id}", {})
        vol = volumes[0]
        return str(vol["volume_id"]), vol.get("volume_name", "第一卷：默认")

    # ---- Chapter / Article APIs -----------------------------------------

    async def get_draft_list(self, book_id: str) -> list[dict]:
        """Return the draft chapter list for a book."""
        data = await self._get("/api/author/chapter/draft_list/v1/", {"book_id": book_id})
        if isinstance(data, list):
            return data
        return data.get("draft_list", [])

    async def save_draft(
        self,
        book_id: str,
        volume_id: str,
        volume_name: str,
        title: str,
        content: str,
        item_id: str = "",
    ) -> str:
        """Save a chapter as draft and return its item_id.

        For new chapters (no item_id): first calls new_article to allocate an
        item_id, then calls cover_article to actually save the title & content.
        For existing chapters (item_id provided): calls cover_article directly.

        Args:
            title: Full title including chapter number prefix,
                   e.g. "第 1 章 替嫁之局" (5-30 chars).
        """
        html_content = _text_to_html(content)

        if not item_id:
            # Step 1: Allocate a new article slot (returns item_id only)
            create_form = {
                "book_id": book_id,
                "title": title,
                "content": html_content,
                "volume_id": volume_id,
                "volume_name": volume_name,
            }
            data = await self._post("/api/author/article/new_article/v0/", create_form)
            if isinstance(data, dict):
                item_id = str(data.get("item_id", ""))
            if not item_id:
                logger.warning("save_draft: new_article returned no item_id for '%s'", title)
                return ""
            logger.info("Draft slot created: item_id=%s", item_id)

        # Step 2: Save actual content via cover_article
        save_form = {
            "book_id": book_id,
            "item_id": item_id,
            "title": title,
            "content": html_content,
            "volume_id": volume_id,
            "volume_name": volume_name,
        }
        data = await self._post("/api/author/article/cover_article/v0/", save_form)
        returned_id = item_id
        if isinstance(data, dict) and data.get("item_id"):
            returned_id = str(data["item_id"])

        logger.info("Draft saved: item_id=%s, title=%s", returned_id, title)
        return returned_id

    async def publish_article(
        self,
        book_id: str,
        volume_id: str,
        volume_name: str,
        title: str,
        content: str,
    ) -> str:
        """Create draft then publish a chapter. Returns item_id.

        Args:
            title: Full title including chapter number prefix.
        """
        item_id = await self.save_draft(
            book_id=book_id,
            volume_id=volume_id,
            volume_name=volume_name,
            title=title,
            content=content,
        )

        form: dict = {
            "book_id": book_id,
            "item_id": item_id,
            "title": title,
            "content": _text_to_html(content),
            "volume_id": volume_id,
            "volume_name": volume_name,
        }

        await self._post("/api/author/publish_article/v0/", form)

        logger.info("Article published: item_id=%s, title=%s", item_id, title)
        return item_id

    # ---- High-level batch upload ----------------------------------------

    async def publish_chapters(
        self,
        book_id: str,
        chapters: list[dict],
        publish_mode: str = "draft",
    ) -> list[dict]:
        """Upload multiple chapters to an existing book.

        Each chapter dict should have keys: chapter_number, title, content.
        The title is automatically prefixed with "第 X 章 " for Fanqie format.
        """
        volume_id, volume_name = await self._get_first_volume(book_id)
        logger.info(
            "Uploading %d chapters to book %s, volume '%s'",
            len(chapters), book_id, volume_name,
        )

        results = []
        for ch in chapters:
            ch_number = ch.get("chapter_number", 0)
            raw_title = ch["title"]
            # Compose Fanqie title: "第 X 章 标题" (5-30 chars)
            full_title = f"第 {ch_number} 章 {raw_title}" if ch_number > 0 else raw_title
            # Truncate to 30 chars if needed
            if len(full_title) > 30:
                full_title = full_title[:30]

            ch_content = ch["content"]
            try:
                if publish_mode == "draft":
                    item_id = await self.save_draft(
                        book_id=book_id,
                        volume_id=volume_id,
                        volume_name=volume_name,
                        title=full_title,
                        content=ch_content,
                    )
                    results.append({
                        "success": True,
                        "message": f"草稿已保存：{full_title}",
                        "item_id": item_id,
                    })
                else:
                    item_id = await self.publish_article(
                        book_id=book_id,
                        volume_id=volume_id,
                        volume_name=volume_name,
                        title=full_title,
                        content=ch_content,
                    )
                    results.append({
                        "success": True,
                        "message": f"已发布：{full_title}",
                        "item_id": item_id,
                    })

            except Exception as e:
                logger.error("Failed to upload chapter '%s': %s", full_title, e)
                results.append({
                    "success": False,
                    "message": str(e),
                    "item_id": "",
                })

        return results
