"""Fanqie Novel writer backend authentication."""

import asyncio
import logging

from playwright.async_api import Page

logger = logging.getLogger(__name__)

WRITER_URL = "https://fanqienovel.com/main/writer/?enter_from=author_zone"

# URL fragments that indicate the user is on a login/auth page
_LOGIN_URL_KEYWORDS = ["login", "passport", "sso", "sign"]


def _is_writer_url(url: str) -> bool:
    """Return True if the URL looks like the writer dashboard (not a login page)."""
    url_lower = url.lower()
    if any(kw in url_lower for kw in _LOGIN_URL_KEYWORDS):
        return False
    return "fanqienovel.com" in url_lower and (
        "writer" in url_lower or "main" in url_lower or "author" in url_lower
    )


async def _save_auth_state(page: Page) -> None:
    """Save full auth state (cookies + localStorage) to disk for reuse."""
    try:
        from config.settings import Settings
        settings = Settings()
        settings.auth_state_path.parent.mkdir(parents=True, exist_ok=True)
        await page.context.storage_state(path=str(settings.auth_state_path))
        logger.info("Auth state saved to %s", settings.auth_state_path)
    except Exception as e:
        logger.warning("Failed to save auth state: %s", e)


async def ensure_logged_in(page: Page, timeout_ms: int = 180000) -> bool:
    """Navigate to writer backend and verify the session is authenticated.

    Detection strategy: after navigating to the writer URL, check whether the
    browser stayed on a writer page or was redirected to a login page.
    This is far more reliable than DOM element detection or API calls.

    After successful login, saves the full browser storage state (cookies +
    localStorage) to disk so subsequent publish runs can restore it without
    needing to re-login.

    Args:
        page:       Playwright page instance.
        timeout_ms: Max wait time for manual login in milliseconds (default 3 min).

    Returns:
        True if authenticated, False if timed out.
    """
    logger.info("Navigating to Fanqie writer backend: %s", WRITER_URL)
    try:
        # "commit" fires as soon as the navigation URL is committed — much faster
        # than waiting for domcontentloaded on a JS-heavy SPA.
        await page.goto(WRITER_URL, wait_until="commit", timeout=60_000)
    except Exception as e:
        logger.warning("Navigation error (may still be OK): %s", e)

    # Wait for the page to reach a stable state so cookies and JS tokens are set
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        await asyncio.sleep(5)  # fallback if networkidle never fires

    if _is_writer_url(page.url):
        logger.info("Already logged in (URL: %s)", page.url)
        await _save_auth_state(page)
        return True

    # Redirected to login page — wait for user to complete login
    logger.info("Login required (URL: %s)", page.url)
    print("\n" + "=" * 50)
    print("  请在弹出的浏览器窗口中登录番茄小说作家后台")
    print("  （扫码登录或手机号登录均可）")
    print("=" * 50)
    print(f"等待登录中（最长 {timeout_ms // 1000} 秒）...\n")

    # Poll: watch page URL until it becomes a writer page
    poll_interval_s = 2
    elapsed_ms = 0
    while elapsed_ms < timeout_ms:
        await asyncio.sleep(poll_interval_s)
        elapsed_ms += poll_interval_s * 1000

        current_url = page.url
        if _is_writer_url(current_url):
            logger.info("Login successful (URL: %s)", current_url)
            print("登录成功！\n")
            await asyncio.sleep(3)  # let page fully settle before saving state
            await _save_auth_state(page)
            return True

    logger.error("Login timed out after %d seconds", timeout_ms // 1000)
    print("登录超时，请重试。\n")
    return False
