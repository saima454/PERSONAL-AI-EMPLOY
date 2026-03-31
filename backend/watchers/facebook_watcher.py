"""Facebook watcher — monitors Facebook notifications and Messenger via Playwright.

This is a PERCEPTION layer component. It observes Facebook and writes action
files to the vault. It never posts, replies, or modifies Facebook state.

Shared Meta session: uses config/meta_session/ (same directory as Instagram).
Run with --setup for first-time login; session is then reused automatically.

Privacy: All data is processed locally. No data is sent externally.

Usage:
    # First-time setup (headed browser for manual login)
    uv run python backend/watchers/facebook_watcher.py --setup

    # Continuous polling
    uv run python backend/watchers/facebook_watcher.py

    # Single check
    uv run python backend/watchers/facebook_watcher.py --once
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from backend.utils.frontmatter import create_file_with_frontmatter
from backend.utils.logging_utils import log_action
from backend.utils.timestamps import format_filename_timestamp, is_within_hours, now_iso
from backend.utils.uuid_utils import correlation_id, short_id
from backend.watchers.base_watcher import BaseWatcher

logger = logging.getLogger(__name__)

DEFAULT_KEYWORDS = [
    "urgent",
    "invoice",
    "meeting",
    "proposal",
    "partnership",
    "opportunity",
    "project",
    "deadline",
]

HIGH_PRIORITY_KEYWORDS = {"urgent", "invoice", "deadline", "proposal"}
MEDIUM_PRIORITY_KEYWORDS = {"meeting", "partnership", "opportunity", "project"}

PROCESSED_IDS_RETENTION_DAYS = 7
MAX_NOTIFICATIONS = 20
MAX_MESSAGES = 60


def _slugify(text: str, max_length: int = 40) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:max_length].rstrip("-")


def _classify_priority(text: str, keywords: list[str]) -> tuple[str, str | None]:
    text_lower = text.lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            kw_lower = kw.lower()
            if kw_lower in HIGH_PRIORITY_KEYWORDS:
                return "high", kw
            if kw_lower in MEDIUM_PRIORITY_KEYWORDS:
                return "medium", kw
            return "low", kw
    return "low", None


def _make_dedup_key(sender: str, text: str, timestamp: str) -> str:
    return f"{sender}|{text[:100]}|{timestamp}"


class FacebookWatcher(BaseWatcher):
    """Watches Facebook notifications and Messenger, creates vault action files."""

    def __init__(
        self,
        vault_path: str,
        session_path: str = "config/meta_session",
        check_interval: int = 120,
        keywords: list[str] | None = None,
        headless: bool = True,
        dry_run: bool = True,
        dev_mode: bool = True,
    ) -> None:
        super().__init__(vault_path, check_interval)
        self.session_path = Path(session_path)
        self.keywords = keywords or DEFAULT_KEYWORDS[:]
        self.headless = headless
        self.dry_run = dry_run
        self.dev_mode = dev_mode
        self.processed_ids_path = self.logs_path / "processed_facebook.json"
        self._processed_ids: dict[str, str] = {}
        self._last_cleanup: str | None = None
        self._consecutive_errors = 0
        self._context = None
        self._page = None

    # ── Browser Management ──────────────────────────────────────────

    async def _launch_browser(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self.session_path.mkdir(parents=True, exist_ok=True)

        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.session_path),
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )

    async def _close_browser(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None
            self._page = None
        if hasattr(self, "_playwright") and self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _ensure_browser(self) -> None:
        if self._page is None or self._context is None:
            await self._launch_browser()

    async def _navigate_and_wait(self, url: str, wait_seconds: float = 8.0) -> None:
        assert self._page is not None
        self.logger.debug("Navigating to %s ...", url)
        await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            await self._page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            self.logger.debug("Network idle not reached within 15s, continuing")
        await asyncio.sleep(wait_seconds)

    async def _save_debug_screenshot(self, label: str = "debug") -> None:
        if self._page is None:
            return
        try:
            screenshot_path = self.logs_path / f"debug_screenshot_fb_{label}.png"
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            await self._page.screenshot(path=str(screenshot_path), full_page=False)
            self.logger.info("Debug screenshot saved: %s", screenshot_path)
        except Exception:
            self.logger.debug("Could not save debug screenshot", exc_info=True)

    # ── Checkpoint / OTP Handler ────────────────────────────────────

    async def _wait_for_checkpoint(self, source: str = "scan", max_wait: int = 180) -> bool:
        """Wait for user to complete OTP / security checkpoint in the headed browser.

        Polls every 5 s; returns True if session becomes 'ready' within max_wait seconds.
        When headless=True this cannot be resolved interactively, so it returns False immediately.
        """
        if self.headless:
            self.logger.error(
                "Facebook checkpoint detected during %s but browser is headless — "
                "cannot complete OTP. Run --setup (headed) to re-authenticate.",
                source,
            )
            return False

        self.logger.warning(
            "\n"
            "  ┌─────────────────────────────────────────────────┐\n"
            "  │   Facebook One-Time Password / Checkpoint        │\n"
            "  ├─────────────────────────────────────────────────┤\n"
            "  │                                                  │\n"
            "  │  Facebook is asking for verification.            │\n"
            "  │  Please complete it in the browser window        │\n"
            "  │  that is currently open on your screen.          │\n"
            "  │                                                  │\n"
            "  │  The watcher will resume automatically once      │\n"
            "  │  you complete the check (up to %3ds).            │\n"
            "  │                                                  │\n"
            "  └─────────────────────────────────────────────────┘",
            max_wait,
        )

        elapsed = 0
        while elapsed < max_wait:
            await asyncio.sleep(5)
            elapsed += 5
            try:
                state = await self._check_session_state()
            except Exception:
                continue
            if state == "ready":
                self.logger.info(
                    "Facebook checkpoint resolved after %ds! Resuming %s...", elapsed, source
                )
                return True
            self.logger.debug(
                "Waiting for checkpoint resolution (%ds / %ds)...", elapsed, max_wait
            )

        self.logger.error(
            "Facebook checkpoint not resolved within %ds — skipping %s this cycle.",
            max_wait,
            source,
        )
        return False

    # ── Session State ───────────────────────────────────────────────

    async def _check_session_state(self) -> str:
        """Returns: 'ready', 'login_required', 'captcha', 'unknown'."""
        assert self._page is not None
        current_url = self._page.url
        self.logger.debug("Checking Facebook session state, URL: %s", current_url)

        # URL-based detection (most reliable)
        if "/checkpoint" in current_url or "captcha" in current_url.lower():
            return "captcha"
        if "/login" in current_url or "/recover" in current_url:
            return "login_required"

        # DOM-based login form check
        for sel in [
            'input[name="email"]',
            'input[name="pass"]',
            'form[action*="login"]',
            'button[name="login"]',
        ]:
            try:
                if await self._page.query_selector(sel):
                    return "login_required"
            except Exception:
                pass

        if await self._is_authenticated():
            return "ready"
        return "unknown"

    async def _is_authenticated(self) -> bool:
        """Check if user is logged into Facebook."""
        assert self._page is not None
        current_url = self._page.url

        is_fb_page = any(
            p in current_url
            for p in ["facebook.com/", "fb.com/"]
        )
        if not is_fb_page:
            return False

        # Try authenticated-only selectors
        auth_selectors = [
            '[aria-label="Facebook"]',             # nav logo (only logged in)
            'div[role="navigation"]',              # top nav
            '[aria-label*="profile" i]',           # profile link
            '[aria-label*="your profile" i]',
            'div[data-pagelet="LeftRail"]',        # left sidebar
            'div[data-pagelet="Stories"]',         # stories (logged-in feed)
        ]
        for sel in auth_selectors:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    self.logger.debug("Facebook auth via selector: %s", sel)
                    return True
            except Exception:
                continue

        # Broad check: many interactive elements = logged in
        try:
            buttons = await self._page.query_selector_all("button")
            links = await self._page.query_selector_all("a")
            total = len(buttons) + len(links)
            if total > 30:
                self.logger.debug("Facebook auth via element count (%d)", total)
                return True
        except Exception:
            pass

        return False

    async def setup_session(self) -> bool:
        """Interactive setup: open headed browser for manual Facebook + Instagram login."""
        self.logger.info("Starting Meta session setup (headed mode)...")

        original_headless = self.headless
        self.headless = False

        try:
            await self._launch_browser()
            await self._navigate_and_wait("https://www.facebook.com/", wait_seconds=5.0)

            state = await self._check_session_state()
            self.logger.info("Initial Facebook session state: %s", state)

            if state != "ready":
                self.logger.info(
                    "\n"
                    "  ┌─────────────────────────────────────────────────┐\n"
                    "  │         Meta (Facebook + Instagram) Setup        │\n"
                    "  ├─────────────────────────────────────────────────┤\n"
                    "  │                                                  │\n"
                    "  │  1. Log in with your Facebook credentials        │\n"
                    "  │  2. Complete any 2FA or CAPTCHA challenges       │\n"
                    "  │  3. (Optional) Navigate to instagram.com and     │\n"
                    "  │     log in to save both sessions at once         │\n"
                    "  │  4. Wait until you can see your Facebook feed    │\n"
                    "  │                                                  │\n"
                    "  │  >>> Press ENTER in this terminal when done <<<  │\n"
                    "  │                                                  │\n"
                    "  └─────────────────────────────────────────────────┘\n"
                )

                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, input)

                self.logger.info("User confirmed. Verifying session...")
                await asyncio.sleep(2)
                state = await self._check_session_state()
                self.logger.info("Post-login Facebook session state: %s", state)

                if state != "ready":
                    self.logger.error(
                        "Login verification failed. Current URL: %s", self._page.url
                    )
                    return False
            else:
                self.logger.info("Already logged in to Facebook!")

            # Always navigate to messages/ after login to surface any e2ee
            # encryption checkpoint before saving the session.
            self.logger.info(
                "Navigating to facebook.com/messages/ to check for verification prompts..."
            )
            await self._navigate_and_wait(
                "https://www.facebook.com/messages/", wait_seconds=5.0
            )
            messages_state = await self._check_session_state()
            messages_url = self._page.url  # type: ignore[union-attr]

            if messages_state == "captcha":
                self.logger.info(
                    "Facebook messages checkpoint detected (URL: %s)", messages_url
                )
                self.logger.info(
                    "\n"
                    "  ┌─────────────────────────────────────────────────┐\n"
                    "  │      Facebook Verification Required              │\n"
                    "  ├─────────────────────────────────────────────────┤\n"
                    "  │                                                  │\n"
                    "  │  Facebook is showing a verification screen      │\n"
                    "  │  (end-to-end encryption / security checkpoint). │\n"
                    "  │                                                  │\n"
                    "  │  Please complete the verification in the        │\n"
                    "  │  browser window, then press Enter here.         │\n"
                    "  │                                                  │\n"
                    "  │  >>> Press ENTER when verification is done <<<  │\n"
                    "  │                                                  │\n"
                    "  └─────────────────────────────────────────────────┘\n"
                )
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, input)
                self.logger.info("Verification confirmed. Continuing to save session...")
                await asyncio.sleep(2)

            self.logger.info(
                "Waiting 30s to persist session to %s ...", self.session_path
            )
            await asyncio.sleep(30)
            self.logger.info("Meta session saved successfully!")
            return True

        finally:
            self.headless = original_headless
            await self._close_browser()

    # ── Processed IDs ───────────────────────────────────────────────

    def _load_processed_ids(self) -> None:
        if not self.processed_ids_path.exists():
            self._processed_ids = {}
            self._last_cleanup = None
            return
        try:
            data = json.loads(self.processed_ids_path.read_text(encoding="utf-8"))
            self._processed_ids = data.get("processed_ids", {})
            self._last_cleanup = data.get("last_cleanup")
        except (json.JSONDecodeError, KeyError):
            self.logger.warning("Corrupted processed_facebook.json, starting fresh")
            self._processed_ids = {}
            self._last_cleanup = None

    def _save_processed_ids(self) -> None:
        self.processed_ids_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "processed_ids": self._processed_ids,
            "last_cleanup": self._last_cleanup or now_iso(),
        }
        self.processed_ids_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _cleanup_old_ids(self) -> None:
        now = now_iso()
        if self._last_cleanup and is_within_hours(self._last_cleanup, 24):
            return
        cutoff = []
        for key, processed_at in self._processed_ids.items():
            try:
                if not is_within_hours(processed_at, PROCESSED_IDS_RETENTION_DAYS * 24):
                    cutoff.append(key)
            except (ValueError, TypeError):
                cutoff.append(key)
        for key in cutoff:
            del self._processed_ids[key]
        self._last_cleanup = now
        if cutoff:
            self.logger.info("Cleaned up %d old Facebook processed IDs", len(cutoff))

    # ── Notification Scanning ───────────────────────────────────────

    async def _scan_notifications(self) -> list[dict[str, Any]]:
        """Navigate to Facebook notifications page and extract items."""
        assert self._page is not None

        self.logger.info("Scanning Facebook notifications...")
        await self._navigate_and_wait(
            "https://www.facebook.com/notifications/", wait_seconds=15.0
        )

        page_url = self._page.url
        page_title = await self._page.title()
        self.logger.info("Notifications page — title: %r  url: %s", page_title, page_url)

        state = await self._check_session_state()
        if state in ("login_required", "captcha"):
            await self._save_debug_screenshot("notifications_auth_fail")
            resolved = await self._wait_for_checkpoint(source="notifications")
            if not resolved:
                self._log_error("facebook", f"session_{state}")
                return []
            # Re-navigate now that checkpoint is resolved
            await self._navigate_and_wait(
                "https://www.facebook.com/notifications/", wait_seconds=8.0
            )

        # Broad selector cascade for notification items
        notification_selectors = [
            '[data-pagelet="NotificationsFeed"] > div',
            'div[aria-label*="Notification" i] > div',
            'div[role="feed"] > div',
            'div[data-pagelet*="Notification"] > div',
            '[role="main"] div > a[href*="notification"]',
            "main article",
            "main li",
            'div[role="article"]',
        ]

        cards: list = []
        used_selector = ""
        for sel in notification_selectors:
            try:
                cards = await self._page.query_selector_all(sel)
                self.logger.debug("FB notification probe '%s': %d matches", sel, len(cards))
                if 0 < len(cards) <= 100:
                    used_selector = sel
                    break
                cards = []
            except Exception:
                pass

        if not cards:
            self.logger.info("No Facebook notification elements found")
            await self._save_debug_screenshot("fb_notifications_empty")
            return []

        self.logger.info(
            "Found %d Facebook notification elements via '%s'", len(cards), used_selector
        )

        cards = cards[:MAX_NOTIFICATIONS]
        items: list[dict[str, Any]] = []

        for card in cards:
            try:
                text = (await card.inner_text()).strip()
                if not text or len(text) < 10:
                    continue

                time_el = await card.query_selector("time")
                time_str = ""
                if time_el:
                    time_str = (await time_el.inner_text()).strip()

                actor = ""
                for actor_sel in ["a strong", "strong", "a span", "a"]:
                    actor_el = await card.query_selector(actor_sel)
                    if actor_el:
                        actor = (await actor_el.inner_text()).strip()
                        if actor and len(actor) < 100:
                            break
                        actor = ""

                priority, matched_keyword = _classify_priority(text, self.keywords)
                if matched_keyword is None:
                    continue

                dedup_key = _make_dedup_key(actor or "facebook", text, time_str)
                if dedup_key in self._processed_ids:
                    continue

                self.logger.info(
                    "Matched FB notification: actor='%s', keyword='%s'",
                    actor, matched_keyword,
                )

                items.append({
                    "item_type": "notification",
                    "sender": actor or "Facebook",
                    "preview": text[:500],
                    "time": time_str,
                    "priority": priority,
                    "matched_keyword": matched_keyword,
                    "dedup_key": dedup_key,
                    "needs_reply": False,
                })
            except Exception:
                self.logger.debug("Failed to extract Facebook notification", exc_info=True)

        return items

    # ── Message Scanning ────────────────────────────────────────────

    async def _detect_and_wait_for_pin(self) -> bool:
        """Detect the E2EE PIN screen and wait for the user to complete it.

        Returns True if the PIN was entered and the page is ready, False if not detected.
        """
        assert self._page is not None
        pin_selectors = [
            'input[aria-label*="PIN" i]',
            'input[placeholder*="PIN" i]',
            'input[aria-label*="pin" i]',
            'input[type="password"][maxlength="6"]',
        ]
        pin_found = False
        for sel in pin_selectors:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    pin_found = True
                    break
            except Exception:
                pass

        # Also check page text for PIN prompt
        if not pin_found:
            try:
                content = await self._page.inner_text("body")
                if "enter your pin" in content.lower() or "restore your chat history" in content.lower():
                    pin_found = True
            except Exception:
                pass

        if not pin_found:
            return False

        if self.headless:
            self.logger.error(
                "Facebook E2EE PIN screen detected but browser is headless — "
                "cannot enter PIN. Run --setup (headed) to unlock encrypted chats."
            )
            return False

        self.logger.warning(
            "\n"
            "  ┌─────────────────────────────────────────────────┐\n"
            "  │   Facebook E2EE PIN Required                     │\n"
            "  ├─────────────────────────────────────────────────┤\n"
            "  │                                                  │\n"
            "  │  Facebook is asking for your chat history PIN.   │\n"
            "  │  Please enter it in the browser window or        │\n"
            "  │  click 'Skip' to continue without restoring      │\n"
            "  │  encrypted message history.                      │\n"
            "  │                                                  │\n"
            "  │  The watcher will resume automatically once      │\n"
            "  │  you complete the step (up to 180s).             │\n"
            "  │                                                  │\n"
            "  └─────────────────────────────────────────────────┘"
        )

        for _ in range(36):  # poll every 5s for up to 180s
            await asyncio.sleep(5)
            still_has_pin = False
            for sel in pin_selectors:
                try:
                    el = await self._page.query_selector(sel)
                    if el:
                        still_has_pin = True
                        break
                except Exception:
                    pass
            if not still_has_pin:
                self.logger.info("Facebook PIN screen dismissed — resuming message scan.")
                await asyncio.sleep(3)  # let page settle
                return True

        self.logger.error("Facebook PIN screen not dismissed within 180s — skipping this cycle.")
        return False

    async def _is_thread_unread(self, thread: Any, full_text: str = "") -> bool:
        """Return True if the thread row has an unread indicator.

        Checks (in order):
          1. Sidebar text contains 'Unread message:' (most reliable — Facebook renders this literally)
          2. Thread row aria-label mentions 'unread'
          3. Child DOM elements with unread selectors
        """
        # Primary: Facebook sidebar renders unread threads with literal text "Unread message:"
        if "unread message:" in full_text.lower():
            return True

        # Secondary: aria-label on the row (e.g. "Ramesha Javed, 1 unread message")
        try:
            label = await thread.get_attribute("aria-label") or ""
            if "unread" in label.lower():
                return True
        except Exception:
            pass

        # Tertiary: child elements that carry unread state
        for sel in ['[aria-label*="unread" i]', '[data-testid*="unread"]']:
            try:
                el = await thread.query_selector(sel)
                if el:
                    return True
            except Exception:
                pass

        return False

    @staticmethod
    def _is_recent_time(time_str: str) -> bool:
        """Return True if the Facebook relative time string represents within ~24 hours.

        Facebook formats: '5m', '2h', '1d', '2w', '3mon' etc.
        We only alert on messages from the last 24 h (minutes or hours only).
        """
        if not time_str:
            return False
        t = time_str.strip().lower()
        # Minutes or hours → recent
        if t.endswith("m") and t[:-1].isdigit():
            return True
        if t.endswith("h") and t[:-1].isdigit():
            return int(t[:-1]) <= 24
        # 1 day explicitly
        if t in ("1d", "today", "yesterday"):
            return True
        return False

    async def _scroll_sidebar_for_threads(self, max_scrolls: int = 8) -> None:
        """Scroll the Messenger sidebar to load all threads.

        First scrolls back to the TOP (so we always start from the most recent /
        unread messages), then scrolls down repeatedly until no new threads appear.
        """
        assert self._page is not None

        sidebar_selectors = [
            'div[aria-label*="Chats" i]',
            'div[aria-label*="Inbox" i]',
            '[role="navigation"]',
        ]
        sidebar_sel = None
        for sel in sidebar_selectors:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    sidebar_sel = sel
                    break
            except Exception:
                pass

        # ── Step 1: scroll back to top so we start from the most recent threads ──
        try:
            if sidebar_sel:
                await self._page.evaluate(
                    "(sel) => { const el = document.querySelector(sel); if (el) el.scrollTop = 0; }",
                    sidebar_sel,
                )
            else:
                await self._page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(1.5)
        except Exception:
            pass

        # ── Step 2: scroll down until thread count stabilises ──
        thread_row_sel = 'div[aria-label*="Chats" i] [role="row"]'
        prev_count = 0

        for i in range(max_scrolls):
            try:
                if sidebar_sel:
                    await self._page.evaluate(
                        "(sel) => { const el = document.querySelector(sel); if (el) el.scrollTop += 800; }",
                        sidebar_sel,
                    )
                else:
                    await self._page.evaluate("window.scrollBy(0, 800)")
            except Exception:
                pass

            await asyncio.sleep(1.5)

            try:
                current = await self._page.query_selector_all(thread_row_sel)
                count = len(current)
            except Exception:
                break

            self.logger.debug(
                "Sidebar scroll %d/%d — threads visible: %d", i + 1, max_scrolls, count
            )

            if count == prev_count:
                self.logger.debug("Sidebar fully loaded after %d scroll(s)", i + 1)
                break
            prev_count = count

    async def _scan_messages(self) -> list[dict[str, Any]]:
        """Navigate to Facebook Messenger and extract threads that are either
        unread or match a priority keyword."""
        assert self._page is not None

        self.logger.info("Scanning Facebook messages...")
        await self._navigate_and_wait(
            "https://www.facebook.com/messages/", wait_seconds=20.0
        )

        page_url = self._page.url
        page_title = await self._page.title()
        self.logger.info("Messages page — title: %r  url: %s", page_title, page_url)

        # Log unread badge count from title, e.g. "(3) Messenger | Facebook"
        import re as _re
        title_badge = _re.match(r"^\((\d+)\)", page_title or "")
        if title_badge:
            self.logger.info(
                "Page title reports %s unread message(s)", title_badge.group(1)
            )

        # Handle E2EE PIN screen (blocks access to encrypted chats)
        await self._detect_and_wait_for_pin()

        state = await self._check_session_state()
        if state in ("login_required", "captcha"):
            await self._save_debug_screenshot("fb_messages_auth_fail")
            resolved = await self._wait_for_checkpoint(source="messages")
            if not resolved:
                self._log_error("facebook", f"messages_session_{state}")
                return []
            # Re-navigate now that checkpoint is resolved
            await self._navigate_and_wait(
                "https://www.facebook.com/messages/", wait_seconds=20.0
            )

        # Scroll the sidebar once to surface threads below the fold
        await self._scroll_sidebar_for_threads()

        # Sidebar-specific selectors first, then broad fallbacks
        thread_selectors = [
            'div[aria-label*="Chats" i] [role="row"]',
            'div[aria-label*="Inbox" i] [role="row"]',
            '[role="main"] [role="row"]',
            '[role="main"] a[href*="/messages/"]',
            'div[aria-label*="chat" i]',
            '[role="navigation"] a[href*="/messages/"]',
            '[role="listbox"] > div',
            '[role="list"] li',
            "main li",
        ]

        threads: list = []
        used_selector = ""
        for sel in thread_selectors:
            try:
                threads = await self._page.query_selector_all(sel)
                self.logger.debug("FB message probe '%s': %d matches", sel, len(threads))
                if 0 < len(threads) <= 50:
                    used_selector = sel
                    break
                threads = []
            except Exception:
                pass

        if not threads:
            self.logger.info("No Facebook message threads found")
            return []

        self.logger.info(
            "Found %d Facebook message threads via '%s'", len(threads), used_selector
        )

        threads = threads[:MAX_MESSAGES]
        items: list[dict[str, Any]] = []

        for thread in threads:
            try:
                full_text = (await thread.inner_text()).strip()
                if not full_text or len(full_text) < 5:
                    continue

                lines = [line.strip() for line in full_text.split("\n") if line.strip()]

                sender = ""
                for sender_sel in ["h3", "h4", "strong", "a span", "a"]:
                    sender_el = await thread.query_selector(sender_sel)
                    if sender_el:
                        candidate = (await sender_el.inner_text()).strip()
                        if candidate and len(candidate) < 80:
                            sender = candidate
                            break
                # Fallback: use first non-empty line
                if not sender and lines:
                    sender = lines[0][:60]

                # "Active now" is an online-indicator, not the real sender name.
                # When present it appears as the first line; the real name is next.
                if sender.lower().startswith("active"):
                    for line in lines[1:]:
                        if line and not line.lower().startswith("active") and len(line) < 80:
                            sender = line
                            break

                preview = ""
                for prev_sel in ["p", '[class*="snippet"]', '[class*="preview"]']:
                    prev_el = await thread.query_selector(prev_sel)
                    if prev_el:
                        preview = (await prev_el.inner_text()).strip()
                        if preview:
                            break
                if not preview:
                    preview = " ".join(lines[1:]) if len(lines) > 1 else full_text

                # Try <time> element first; fall back to last short token in the raw text
                # (Facebook renders timestamps like "31m", "2h", "1d" as plain text).
                time_str = ""
                time_el = await thread.query_selector("time")
                if time_el:
                    time_str = (await time_el.inner_text()).strip()
                if not time_str and lines:
                    last_token = lines[-1]
                    if last_token and len(last_token) <= 8:
                        time_str = last_token

                search_text = f"{sender} {preview}"
                priority, matched_keyword = _classify_priority(search_text, self.keywords)

                is_unread = await self._is_thread_unread(thread, full_text=full_text)
                is_recent = self._is_recent_time(time_str)

                # Capture rules:
                # 1. Keyword match → always capture (read or unread)
                # 2. Unread AND recent (within ~24h) → capture (user hasn't seen it yet)
                # 3. Everything else → skip silently
                if matched_keyword is None:
                    if is_unread and is_recent:
                        priority = "high"
                        matched_keyword = "unread_message"
                    else:
                        self.logger.debug(
                            "Skipping thread: sender=%r  unread=%s  recent=%s  no keyword",
                            sender, is_unread, is_recent,
                        )
                        continue

                # For unread threads use a date-scoped dedup key so they re-surface
                # each day until the user reads them.
                from backend.utils.timestamps import now_iso as _now_iso
                today = _now_iso()[:10]  # YYYY-MM-DD
                if matched_keyword == "unread_message":
                    dedup_key = f"{sender}|unread|{today}"
                else:
                    dedup_key = _make_dedup_key(sender, preview, time_str)

                if dedup_key in self._processed_ids:
                    continue

                self.logger.info(
                    "Matched FB message: sender=%r  unread=%s  keyword=%r",
                    sender, is_unread, matched_keyword,
                )

                items.append({
                    "item_type": "message",
                    "sender": sender or "Unknown",
                    "preview": preview[:500],
                    "time": time_str,
                    "priority": priority,
                    "matched_keyword": matched_keyword,
                    "dedup_key": dedup_key,
                    "needs_reply": True,
                    "is_unread": is_unread,
                })
            except Exception:
                self.logger.debug("Failed to extract Facebook message thread", exc_info=True)

        return items

    # ── Core Watcher Logic ──────────────────────────────────────────

    async def check_for_updates(self) -> list[dict[str, Any]]:
        """Return new Facebook notifications and messages matching keywords.

        DEV_MODE: returns synthetic item without launching browser.
        Session missing: logs warning, returns [].
        Never raises.
        """
        # DEV_MODE short-circuit
        if self.dev_mode:
            self.logger.info("[DEV_MODE] FacebookWatcher: returning synthetic item")
            return [
                {
                    "item_type": "notification",
                    "sender": "[DEV_MODE]",
                    "preview": "[DEV_MODE] Synthetic Facebook notification for testing",
                    "time": "just now",
                    "priority": "low",
                    "matched_keyword": "dev",
                    "dedup_key": f"[DEV_MODE]|synthetic|{now_iso()}",
                    "needs_reply": False,
                }
            ]

        # Session guard
        if not self.session_path.exists():
            self.logger.warning(
                "Meta session not found at %s — run --setup to initialize",
                self.session_path,
            )
            return []

        self._load_processed_ids()
        self._cleanup_old_ids()

        try:
            await self._ensure_browser()
            messages = await self._scan_messages()
            items = messages
            self._consecutive_errors = 0
            self.logger.info(
                "Facebook: found %d messages matching keywords",
                len(messages),
            )
            return items
        except Exception:
            self._consecutive_errors += 1
            self.logger.exception(
                "Error scanning Facebook (consecutive errors: %d)",
                self._consecutive_errors,
            )
            await self._save_debug_screenshot("scan_error")
            self._log_error("facebook", "scan_failed")
            return []

    async def create_action_file(self, item: dict[str, Any]) -> Path | None:
        """Create vault/Needs_Action/FACEBOOK_*.md for a matched item."""
        sender_slug = _slugify(item["sender"])
        timestamp = format_filename_timestamp()
        filename = f"FACEBOOK_{sender_slug}_{timestamp}.md"
        file_path = self.needs_action / filename

        fb_id = f"FACEBOOK_{short_id()}_{timestamp}"

        frontmatter: dict[str, Any] = {
            "type": "facebook",
            "id": fb_id,
            "source": "facebook_watcher",
            "item_type": item["item_type"],
            "sender": item["sender"],
            "preview": item["preview"][:200],
            "received": now_iso(),
            "priority": item["priority"],
            "status": "pending",
        }
        if item.get("matched_keyword"):
            frontmatter["matched_keyword"] = item["matched_keyword"]
        if item.get("needs_reply"):
            frontmatter["needs_reply"] = True
        if item.get("is_unread"):
            frontmatter["is_unread"] = True

        body = f"""
## Facebook {item["item_type"].replace("_", " ").title()}

**From:** {item["sender"]}
**Type:** {item["item_type"]}
**Time:** {item.get("time", "unknown")}
**Priority:** {item["priority"]} (keyword: {item.get("matched_keyword", "unknown")})

## Content

{item["preview"]}

## Suggested Actions

- [ ] Review on Facebook
- [ ] Reply to sender
- [ ] Mark as processed
"""

        cid = correlation_id()

        if self.dry_run:
            self.logger.info(
                "[DRY RUN] Would create: %s (priority: %s, from: %s)",
                filename,
                item["priority"],
                item["sender"],
            )
            log_action(
                self.logs_path / "actions",
                {
                    "timestamp": now_iso(),
                    "correlation_id": cid,
                    "actor": "facebook_watcher",
                    "action_type": "facebook_detected",
                    "target": filename,
                    "result": "dry_run",
                    "parameters": {
                        "item_type": item["item_type"],
                        "sender": item["sender"],
                        "priority": item["priority"],
                        "dry_run": True,
                        "dev_mode": self.dev_mode,
                    },
                },
            )
            return None

        self.needs_action.mkdir(parents=True, exist_ok=True)
        create_file_with_frontmatter(file_path, frontmatter, body)

        self._processed_ids[item["dedup_key"]] = now_iso()
        self._save_processed_ids()

        log_action(
            self.logs_path / "actions",
            {
                "timestamp": now_iso(),
                "correlation_id": cid,
                "actor": "facebook_watcher",
                "action_type": "facebook_processed",
                "target": filename,
                "result": "success",
                "parameters": {
                    "item_type": item["item_type"],
                    "sender": item["sender"],
                    "priority": item["priority"],
                    "dev_mode": self.dev_mode,
                },
            },
        )

        self.logger.info("Created action file: %s (priority: %s)", filename, item["priority"])
        return file_path

    # ── Error Logging ───────────────────────────────────────────────

    def _log_error(self, target: str, error_msg: str) -> None:
        try:
            log_action(
                self.logs_path / "errors",
                {
                    "timestamp": now_iso(),
                    "correlation_id": correlation_id(),
                    "actor": "facebook_watcher",
                    "action_type": "error",
                    "target": target,
                    "error": error_msg,
                    "details": {
                        "consecutive_errors": self._consecutive_errors,
                        "dev_mode": self.dev_mode,
                    },
                    "result": "failure",
                },
            )
        except Exception:
            self.logger.exception("Failed to write Facebook error log")

    # ── Main Loop Override ──────────────────────────────────────────

    async def run(self) -> None:
        self.logger.info(
            "Starting FacebookWatcher (interval: %ds, dev_mode: %s)",
            self.check_interval,
            self.dev_mode,
        )
        try:
            if not self.dev_mode:
                await self._ensure_browser()
            while True:
                try:
                    items = await self.check_for_updates()
                    for item in items:
                        await self.create_action_file(item)
                except Exception:
                    self.logger.exception("Error in FacebookWatcher polling cycle")
                finally:
                    # Close browser after each cycle so the profile lock is released
                    # during the sleep window — prevents conflicts with action posters.
                    await self._close_browser()
                await asyncio.sleep(self.check_interval)
        finally:
            await self._close_browser()


# ── CLI Entry Point ──────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Facebook Watcher - AI Employee Perception Layer"
    )
    parser.add_argument("--once", action="store_true", help="Single check and exit")
    parser.add_argument("--setup", action="store_true", help="First-time Meta session setup")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    env_path = Path(__file__).resolve().parents[2] / "config" / ".env"
    load_dotenv(env_path)
    args = _parse_args(argv)

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    vault_path = os.getenv("VAULT_PATH", "./vault")
    session_path = os.getenv("FACEBOOK_SESSION_PATH", "config/meta_session")
    check_interval = int(os.getenv("FACEBOOK_CHECK_INTERVAL", "120"))
    headless = os.getenv("FACEBOOK_HEADLESS", "false").lower() == "true"
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
    dev_mode = os.getenv("DEV_MODE", "true").lower() == "true"

    keywords_env = os.getenv("FACEBOOK_KEYWORDS", "")
    keywords = [k.strip() for k in keywords_env.split(",") if k.strip()] or None

    watcher = FacebookWatcher(
        vault_path=vault_path,
        session_path=session_path,
        check_interval=check_interval,
        keywords=keywords,
        headless=headless,
        dry_run=dry_run,
        dev_mode=dev_mode,
    )

    if args.setup:
        logger.info("Starting Meta session setup...")
        success = asyncio.run(watcher.setup_session())
        if success:
            logger.info("Setup complete! Session saved to %s", session_path)
        else:
            logger.error("Setup failed.")
        return

    if args.once:
        logger.info("Running single Facebook check...")

        async def single_check() -> None:
            try:
                items = await watcher.check_for_updates()
                for item in items:
                    await watcher.create_action_file(item)
                logger.info("Check complete. Found %d matching items.", len(items))
            finally:
                await watcher._close_browser()

        asyncio.run(single_check())
        return

    logger.info(
        "Starting Facebook watcher (interval: %ds, headless: %s, dev_mode: %s)",
        check_interval,
        headless,
        dev_mode,
    )
    asyncio.run(watcher.run())


if __name__ == "__main__":
    main()
