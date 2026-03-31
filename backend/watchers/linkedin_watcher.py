"""LinkedIn watcher - monitors LinkedIn notifications and messages via Playwright.

This is a PERCEPTION layer component. It observes LinkedIn and writes action
files to the vault. It never interacts with notifications or sends messages.

Privacy: All data is processed locally. No data is sent externally.

Usage:
    # First-time setup (headed browser for manual login)
    uv run python backend/watchers/linkedin_watcher.py --setup

    # Continuous polling
    uv run python backend/watchers/linkedin_watcher.py

    # Single check
    uv run python backend/watchers/linkedin_watcher.py --once
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
    "opportunity",
    "invoice",
    "project",
    "meeting",
    "urgent",
    "proposal",
    "partnership",
    "job",
]

HIGH_PRIORITY_KEYWORDS = {"urgent", "invoice", "proposal"}
MEDIUM_PRIORITY_KEYWORDS = {"opportunity", "project", "meeting", "job", "partnership"}

PROCESSED_IDS_RETENTION_DAYS = 7

# LinkedIn selectors — grouped by page/feature
SELECTORS = {
    # Session state
    "login_form": "form.login__form, #username",
    "feed": "div.feed-shared-update-v2, main[role='main']",
    "nav": 'nav[aria-label="Primary"]',
    "captcha": "#captcha-internal",
    # Navigation
    "notifications_link": 'a[href*="/notifications/"]',
    "messaging_link": 'a[href*="/messaging/"]',
    # Notifications
    "notification_list": "div.nt-card-list",
    "notification_card": "div.nt-card",
    "notification_unread": "div.nt-card--unread",
    "notification_text": "div.nt-card__text",
    "notification_time": "time.nt-card__time-ago",
    "notification_actor": "span.nt-card__actor",
    # Messages
    "msg_container": "div.msg-conversations-container",
    "msg_thread": "div.msg-conversation-card",
    "msg_unread": "div.msg-conversation-card--unread",
    "msg_sender": "h3.msg-conversation-card__participant-names",
    "msg_preview": "p.msg-conversation-card__message-snippet",
    "msg_time": "time.msg-conversation-card__time-stamp",
}

# Combined selector for "logged in" state (loose — used for navigation waits)
LOGGED_IN_SELECTOR = ", ".join([
    'nav[aria-label="Primary"]',
    "main[role='main']",
    "div.feed-shared-update-v2",
])

# Stricter selectors that ONLY appear when truly authenticated
# These require the user to actually be logged in, not just on a public page
AUTHENTICATED_SELECTORS = [
    'img.global-nav__me-photo',                      # Profile photo in nav
    'img.feed-identity-module__member-photo',         # Profile photo in sidebar
    'button[aria-label*="me" i]',                     # "Me" dropdown menu
    'div.feed-identity-module',                       # Left sidebar identity card
    'div[data-control-name="identity_welcome_message"]',  # Welcome message
    'span.feed-identity-module__actor-name',          # Your name in sidebar
    'a[href*="/in/"][data-control-name="identity_profile_photo"]',  # Profile link
    'div.share-box-feed-entry__trigger',              # "Start a post" (only when logged in)
]


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


class LinkedInWatcher(BaseWatcher):
    """Watches LinkedIn notifications and messages, creates vault action files."""

    def __init__(
        self,
        vault_path: str,
        session_path: str = "config/linkedin_session",
        check_interval: int = 300,
        keywords: list[str] | None = None,
        headless: bool = True,
        dry_run: bool = True,
        dev_mode: bool = True,
    ):
        super().__init__(vault_path, check_interval)
        self.session_path = Path(session_path)
        self.keywords = keywords or DEFAULT_KEYWORDS[:]
        self.headless = headless
        self.dry_run = dry_run
        self.dev_mode = dev_mode
        self.processed_ids_path = self.logs_path / "processed_linkedin.json"
        self._processed_ids: dict[str, str] = {}
        self._last_cleanup: str | None = None
        self._consecutive_errors = 0
        self._backoff_delay = 1.0
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

    # ── Navigation ──────────────────────────────────────────────────

    async def _navigate_and_wait(self, url: str, wait_seconds: float = 10.0) -> None:
        """Navigate to a URL and wait for the page to fully render.

        Instead of waiting for specific CSS selectors (which LinkedIn changes
        frequently), this uses a simple strategy:
        1. Navigate with domcontentloaded
        2. Try to reach networkidle (with timeout)
        3. Wait a fixed delay for JavaScript rendering
        """
        assert self._page is not None
        self.logger.debug("Navigating to %s ...", url)

        await self._page.goto(url, wait_until="domcontentloaded", timeout=90000)

        # Try to wait for network to settle — but don't fail if it doesn't
        try:
            await self._page.wait_for_load_state("networkidle", timeout=15000)
            self.logger.debug("Network idle reached")
        except Exception:
            self.logger.debug("Network idle not reached within 15s, continuing")

        # Fixed wait for JS rendering (LinkedIn is heavy SPA)
        self.logger.debug("Waiting %.0fs for JS rendering...", wait_seconds)
        await asyncio.sleep(wait_seconds)

    async def _save_debug_screenshot(self, label: str = "debug") -> None:
        """Save a screenshot for debugging when something fails."""
        if self._page is None:
            return
        try:
            screenshot_path = self.logs_path / f"debug_screenshot_{label}.png"
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            await self._page.screenshot(path=str(screenshot_path), full_page=False)
            self.logger.info("Debug screenshot saved to %s", screenshot_path)
        except Exception:
            self.logger.debug("Could not save debug screenshot", exc_info=True)

    async def _debug_dump_page(self, label: str = "") -> None:
        """Log diagnostic info about the current page state."""
        if self._page is None:
            return
        try:
            url = self._page.url
            title = await self._page.title()
            self.logger.info("[DEBUG %s] URL: %s | Title: %s", label, url, title)

            # Count elements with various broad selectors
            probe_selectors = [
                "a", "button", "input", "img", "nav", "main", "header",
                "li", "article", "section", "h1", "h2", "h3",
                "time", "form",
                # Messaging-specific broad probes
                'a[href*="/messaging"]',
                '[class*="msg"]',
                '[class*="conversation"]',
                '[class*="thread"]',
                '[class*="unread"]',
                '[class*="notification"]',
                '[aria-label*="message" i]',
                '[aria-label*="conversation" i]',
            ]
            for sel in probe_selectors:
                try:
                    els = await self._page.query_selector_all(sel)
                    if els:
                        self.logger.info(
                            "[DEBUG %s] '%s': %d elements", label, sel, len(els)
                        )
                except Exception:
                    pass
        except Exception:
            self.logger.debug("Debug dump failed", exc_info=True)

    # ── Session State ───────────────────────────────────────────────

    async def _check_session_state(self) -> str:
        """Returns: 'ready', 'login_required', 'captcha', 'unknown'.

        Uses URL-based detection first (most reliable), then falls back
        to DOM selectors.
        """
        assert self._page is not None
        current_url = self._page.url
        self.logger.debug("Checking session state, URL: %s", current_url)

        # URL-based detection (most reliable — LinkedIn always redirects)
        if "/checkpoint/challenge" in current_url:
            return "captcha"
        if "/login" in current_url or "/authwall" in current_url:
            return "login_required"

        # DOM-based captcha check — use ONLY the specific LinkedIn CAPTCHA ID
        # Do NOT use broad wildcards like [class*="captcha"] as they can
        # match unrelated elements (e.g. reCAPTCHA scripts, ad iframes)
        try:
            if await self._page.query_selector("#captcha-internal"):
                return "captcha"
        except Exception:
            pass

        # DOM-based login form check
        for sel in [
            "form.login__form", "#username", 'input[name="session_key"]',
            'form[action*="login"]',
        ]:
            try:
                if await self._page.query_selector(sel):
                    return "login_required"
            except Exception:
                pass

        # If we're on a LinkedIn page (not login/authwall), check for auth
        if await self._is_authenticated():
            return "ready"

        return "unknown"

    async def _is_authenticated(self) -> bool:
        """Check if the user is truly logged in.

        Uses a combination of URL checks and broad DOM probes.
        """
        assert self._page is not None
        current_url = self._page.url

        # If URL is on a logged-in page, check for any user-specific content
        is_linkedin_page = any(
            p in current_url
            for p in ["/feed", "/messaging", "/notifications", "/mynetwork", "/in/"]
        )
        if not is_linkedin_page:
            return False

        # Try strict selectors first
        for sel in AUTHENTICATED_SELECTORS:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    self.logger.debug("Authenticated via selector: %s", sel)
                    return True
            except Exception:
                continue

        # Broad check: if we have many interactive elements on a LinkedIn
        # page, we're probably logged in (public pages are stripped down)
        try:
            buttons = await self._page.query_selector_all("button")
            links = await self._page.query_selector_all("a")
            imgs = await self._page.query_selector_all("img")
            total = len(buttons) + len(links) + len(imgs)
            self.logger.debug(
                "Page element count: %d buttons, %d links, %d imgs (total %d)",
                len(buttons), len(links), len(imgs), total,
            )
            # A logged-in LinkedIn page typically has 50+ interactive elements
            if total > 40:
                self.logger.debug("Authenticated via element count heuristic (%d)", total)
                return True
        except Exception:
            pass

        return False

    async def setup_session(self) -> bool:
        """Interactive setup: open headed browser for manual LinkedIn login.

        This method uses a manual confirmation flow — the browser stays open
        until the user presses Enter in the terminal, giving them full control
        over when the session is saved.
        """
        self.logger.info("Starting LinkedIn session setup (headed mode)...")

        original_headless = self.headless
        self.headless = False

        try:
            await self._launch_browser()
            await self._navigate_and_wait(
                "https://www.linkedin.com/feed/", wait_seconds=5.0
            )

            state = await self._check_session_state()
            self.logger.info("Initial session state: %s", state)

            if state == "ready":
                self.logger.info(
                    "Already logged in! Session is valid.\n"
                    "  Waiting 10 seconds to ensure session is saved..."
                )
                await asyncio.sleep(10)
                return True

            # Not logged in — prompt user to log in manually
            self.logger.info(
                "\n"
                "  ┌─────────────────────────────────────────────────┐\n"
                "  │         LinkedIn Manual Login Required           │\n"
                "  ├─────────────────────────────────────────────────┤\n"
                "  │                                                  │\n"
                "  │  1. Log in with your LinkedIn credentials        │\n"
                "  │  2. Complete any 2FA or CAPTCHA challenges       │\n"
                "  │  3. Wait until you can see your LinkedIn feed    │\n"
                "  │  4. Make sure you see your profile photo in      │\n"
                "  │     the top navigation bar                       │\n"
                "  │                                                  │\n"
                "  │  >>> Press ENTER in this terminal when done <<<  │\n"
                "  │                                                  │\n"
                "  └─────────────────────────────────────────────────┘\n"
            )

            # Wait for user to press Enter (run in executor to not block asyncio)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, input)

            self.logger.info("User confirmed login. Verifying session...")

            # Re-check after user confirmation
            await asyncio.sleep(2)
            state = await self._check_session_state()
            self.logger.info("Post-login session state: %s", state)

            if state == "ready":
                self.logger.info(
                    "Login confirmed! Waiting 30 seconds to ensure session "
                    "data is fully saved to %s ...",
                    self.session_path,
                )
                await asyncio.sleep(30)
                self.logger.info("Session saved successfully!")
                return True

            # Not authenticated even after user said they logged in
            # Run a diagnostic to help debug
            self.logger.warning(
                "Could not verify login. Running diagnostics..."
            )
            current_url = self._page.url
            self.logger.info("  Current URL: %s", current_url)

            for sel in AUTHENTICATED_SELECTORS:
                try:
                    el = await self._page.query_selector(sel)
                    self.logger.info(
                        "  Selector '%s': %s", sel, "FOUND" if el else "not found"
                    )
                except Exception:
                    self.logger.info("  Selector '%s': error", sel)

            self.logger.error(
                "Login verification failed. Please try again.\n"
                "  If LinkedIn loaded but verification failed, the selectors\n"
                "  may need updating. Check the diagnostics above."
            )
            return False

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
            self.logger.warning("Corrupted processed_linkedin.json, starting fresh")
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
            self.logger.info("Cleaned up %d old processed IDs", len(cutoff))

    # ── Notification Scanning ───────────────────────────────────────

    async def _scan_notifications(self) -> list[dict[str, Any]]:
        """Navigate to notifications page and extract items.

        Uses broad, resilient selectors instead of LinkedIn-specific class names.
        """
        assert self._page is not None

        self.logger.info("Scanning notifications...")
        await self._navigate_and_wait(
            "https://www.linkedin.com/notifications/", wait_seconds=10.0,
        )

        state = await self._check_session_state()
        self.logger.debug("Session state on notifications page: %s", state)

        if state in ("login_required", "captcha"):
            self.logger.error(
                "Session expired or CAPTCHA. Run --setup to re-login. (state=%s)", state
            )
            await self._save_debug_screenshot("notifications_auth_fail")
            self._log_error("linkedin", f"session_{state}")
            return []

        # Debug dump on first run to discover selectors
        await self._debug_dump_page("notifications")

        # ── Strategy: find notification items using broad selectors ──
        # LinkedIn notification items are typically in a list. Try multiple
        # container/item patterns from most specific to most broad.
        notification_item_selectors = [
            # Specific LinkedIn notification selectors (may break)
            "div.nt-card--unread",
            "div.nt-card",
            # Broader: artdeco card pattern
            "div.artdeco-card",
            # Broader: list items inside the main content area
            "main li",
            "main article",
            # Broadest: sections with text content
            "main section",
        ]

        cards: list = []
        used_selector = ""
        for sel in notification_item_selectors:
            try:
                cards = await self._page.query_selector_all(sel)
                self.logger.debug("Notification probe '%s': %d matches", sel, len(cards))
                if len(cards) > 0:
                    used_selector = sel
                    break
            except Exception:
                pass

        if not cards:
            self.logger.info("No notification elements found on page")
            await self._save_debug_screenshot("notifications_empty")
            return []

        self.logger.info(
            "Found %d notification elements via '%s'", len(cards), used_selector
        )

        cards = cards[:20]
        items: list[dict[str, Any]] = []

        for card in cards:
            try:
                # Get the full text of the card — works regardless of internal structure
                text = (await card.inner_text()).strip()
                if not text or len(text) < 10:
                    continue

                # Extract time from any <time> element
                time_el = await card.query_selector("time")
                time_str = ""
                if time_el:
                    time_str = (await time_el.inner_text()).strip()

                # Try to get actor from links or bold text
                actor = ""
                for actor_sel in ["a strong", "strong", "a span", "a"]:
                    actor_el = await card.query_selector(actor_sel)
                    if actor_el:
                        actor = (await actor_el.inner_text()).strip()
                        if actor and len(actor) < 100:
                            break
                        actor = ""

                # Check keyword match
                priority, matched_keyword = _classify_priority(text, self.keywords)
                if matched_keyword is None:
                    continue

                dedup_key = _make_dedup_key(actor or "linkedin", text, time_str)
                if dedup_key in self._processed_ids:
                    continue

                self.logger.info(
                    "Matched notification: actor='%s', keyword='%s', text='%s'",
                    actor, matched_keyword, text[:80],
                )

                items.append({
                    "item_type": "notification",
                    "sender": actor or "LinkedIn",
                    "preview": text[:500],
                    "time": time_str,
                    "priority": priority,
                    "matched_keyword": matched_keyword,
                    "dedup_key": dedup_key,
                })
            except Exception:
                self.logger.debug("Failed to extract notification", exc_info=True)

        return items

    # ── Message Scanning ────────────────────────────────────────────

    async def _scan_messages(self) -> list[dict[str, Any]]:
        """Navigate to messaging page and extract conversation threads.

        Uses broad, resilient selectors instead of LinkedIn-specific class names.
        """
        assert self._page is not None

        self.logger.info("Scanning messages...")
        await self._navigate_and_wait(
            "https://www.linkedin.com/messaging/", wait_seconds=10.0,
        )

        state = await self._check_session_state()
        self.logger.debug("Session state on messaging page: %s", state)

        if state in ("login_required", "captcha"):
            self.logger.error(
                "Session expired or CAPTCHA on messaging page. (state=%s)", state
            )
            await self._save_debug_screenshot("messaging_auth_fail")
            self._log_error("linkedin", f"session_{state}")
            return []

        # Debug dump to discover selectors
        await self._debug_dump_page("messaging")

        # ── Strategy: find conversation list items ──
        # LinkedIn messaging conversations are list items. Try multiple
        # selectors from most specific to most broad.
        thread_selectors = [
            # Specific LinkedIn selectors (may break)
            "div.msg-conversation-card--unread",
            "div.msg-conversation-card",
            # Class-contains patterns
            '[class*="conversation-list"] li',
            '[class*="msg-conversation"]',
            '[class*="conversation-card"]',
            # Broader: list items with unread styling
            'li[class*="unread"]',
            # Broad: list items in the main messaging area
            'main li',
            'aside li',
            '[role="list"] li',
            '[role="listbox"] li',
            # Broadest: any list items on page
            'ul li',
        ]

        threads: list = []
        used_selector = ""
        for sel in thread_selectors:
            try:
                threads = await self._page.query_selector_all(sel)
                self.logger.debug("Message probe '%s': %d matches", sel, len(threads))
                # Skip if too many (probably navigation li's)
                if 0 < len(threads) <= 50:
                    used_selector = sel
                    break
                if len(threads) > 50:
                    self.logger.debug(
                        "Skipping '%s' — too many matches (%d), likely nav", sel, len(threads)
                    )
                    threads = []
            except Exception:
                pass

        if not threads:
            self.logger.info("No message thread elements found on page")
            await self._save_debug_screenshot("messaging_empty")
            return []

        self.logger.info(
            "Found %d message threads via '%s'", len(threads), used_selector
        )

        threads = threads[:15]
        items: list[dict[str, Any]] = []

        for thread in threads:
            try:
                # Get the full text of the thread card
                full_text = (await thread.inner_text()).strip()
                if not full_text or len(full_text) < 5:
                    continue

                # Split into lines — typically: sender name, preview, time
                lines = [l.strip() for l in full_text.split("\n") if l.strip()]

                # Try to extract sender from first line or link/heading
                sender = ""
                for sender_sel in ["h3", "h4", "strong", "a span", "a"]:
                    sender_el = await thread.query_selector(sender_sel)
                    if sender_el:
                        sender = (await sender_el.inner_text()).strip()
                        if sender and len(sender) < 80:
                            break
                        sender = ""
                if not sender and lines:
                    sender = lines[0][:60]

                # Try to get preview text — usually the last substantive line
                preview = ""
                for prev_sel in [
                    "p", '[class*="snippet"]', '[class*="preview"]',
                    '[class*="message-snippet"]',
                ]:
                    prev_el = await thread.query_selector(prev_sel)
                    if prev_el:
                        preview = (await prev_el.inner_text()).strip()
                        if preview:
                            break
                if not preview:
                    # Use full text minus sender as preview
                    preview = " ".join(lines[1:]) if len(lines) > 1 else full_text

                # Extract time
                time_str = ""
                time_el = await thread.query_selector("time")
                if time_el:
                    time_str = (await time_el.inner_text()).strip()
                if not time_str:
                    # Look for time-like text in the lines
                    for line in reversed(lines):
                        if any(t in line.lower() for t in ["am", "pm", "ago", "min", "hr", "day"]):
                            time_str = line
                            break

                # Check keyword match against BOTH sender and preview
                search_text = f"{sender} {preview}"
                priority, matched_keyword = _classify_priority(search_text, self.keywords)
                if matched_keyword is None:
                    continue

                dedup_key = _make_dedup_key(sender, preview, time_str)
                if dedup_key in self._processed_ids:
                    continue

                self.logger.info(
                    "Matched message: sender='%s', keyword='%s', preview='%s'",
                    sender, matched_keyword, preview[:80],
                )

                items.append({
                    "item_type": "message",
                    "sender": sender or "Unknown",
                    "preview": preview[:500],
                    "time": time_str,
                    "priority": priority,
                    "matched_keyword": matched_keyword,
                    "dedup_key": dedup_key,
                })
            except Exception:
                self.logger.debug("Failed to extract message thread", exc_info=True)

        return items

    # ── Core Watcher Logic ──────────────────────────────────────────

    async def check_for_updates(self) -> list[dict[str, Any]]:
        self._load_processed_ids()
        self._cleanup_old_ids()

        try:
            await self._ensure_browser()
            messages = await self._scan_messages()
            items = messages
            self._consecutive_errors = 0
            self._backoff_delay = 1.0
            self.logger.info(
                "Found %d messages matching keywords",
                len(messages),
            )
            return items
        except Exception:
            self._consecutive_errors += 1
            self.logger.exception(
                "Error scanning LinkedIn (consecutive errors: %d)",
                self._consecutive_errors,
            )
            await self._save_debug_screenshot("scan_error")
            self._log_error("linkedin", "scan_failed")
            return []

    async def create_action_file(self, item: dict[str, Any]) -> Path | None:
        sender_slug = _slugify(item["sender"])
        timestamp = format_filename_timestamp()
        filename = f"LINKEDIN_{sender_slug}_{timestamp}.md"
        file_path = self.needs_action / filename

        li_id = f"LINKEDIN_{short_id()}_{timestamp}"

        frontmatter: dict[str, Any] = {
            "type": "linkedin",
            "id": li_id,
            "source": "linkedin_watcher",
            "item_type": item["item_type"],
            "sender": item["sender"],
            "preview": item["preview"][:200],
            "received": now_iso(),
            "priority": item["priority"],
            "status": "pending",
        }

        body = f"""
## LinkedIn {item["item_type"].title()}

**From:** {item["sender"]}
**Type:** {item["item_type"]}
**Time:** {item.get("time", "unknown")}
**Priority:** {item["priority"]} (keyword: {item.get("matched_keyword", "unknown")})

## Content

{item["preview"]}

## Suggested Actions

- [ ] Reply to sender
- [ ] Review on LinkedIn
- [ ] Mark as processed
"""

        cid = correlation_id()

        if self.dry_run:
            self.logger.info(
                "[DRY RUN] Would create: %s (priority: %s, from: %s)",
                filename, item["priority"], item["sender"],
            )
            log_action(
                self.logs_path / "actions",
                {
                    "timestamp": now_iso(),
                    "correlation_id": cid,
                    "actor": "linkedin_watcher",
                    "action_type": "linkedin_detected",
                    "target": filename,
                    "result": "dry_run",
                    "parameters": {
                        "item_type": item["item_type"],
                        "sender": item["sender"],
                        "priority": item["priority"],
                        "matched_keyword": item.get("matched_keyword"),
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
                "actor": "linkedin_watcher",
                "action_type": "linkedin_processed",
                "target": filename,
                "result": "success",
                "parameters": {
                    "item_type": item["item_type"],
                    "sender": item["sender"],
                    "priority": item["priority"],
                    "matched_keyword": item.get("matched_keyword"),
                    "dry_run": False,
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
                    "actor": "linkedin_watcher",
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
            self.logger.exception("Failed to write error log")

    # ── Main Loop Override ──────────────────────────────────────────

    async def run(self) -> None:
        self.logger.info("Starting %s (interval: %ds)", self.__class__.__name__, self.check_interval)
        try:
            await self._ensure_browser()

            # Check login state before entering the polling loop.
            # If not logged in, keep the browser open so the user can log in
            # interactively — do not close and restart.
            await self._navigate_and_wait("https://www.linkedin.com/feed/", wait_seconds=5.0)
            state = await self._check_session_state()

            if state == "login_required":
                self.logger.warning(
                    "LinkedIn not logged in — browser is open.\n"
                    "  Please log in to LinkedIn in the browser window.\n"
                    "  Waiting until you log in (Ctrl+C to cancel)..."
                )
                # Poll indefinitely — no timeout. A normal return would cause the
                # watchdog to restart immediately. Only CancelledError (Ctrl+C /
                # orchestrator shutdown) or a successful login should exit this block.
                while True:
                    await asyncio.sleep(5)
                    state = await self._check_session_state()
                    if state == "ready":
                        self.logger.info(
                            "Login detected! Session saved to %s. Starting watcher.",
                            self.session_path,
                        )
                        await asyncio.sleep(5)  # let session data flush to disk
                        break

            while True:
                try:
                    items = await self.check_for_updates()
                    for item in items:
                        await self.create_action_file(item)
                except Exception:
                    self.logger.exception("Error in %s polling cycle", self.__class__.__name__)
                finally:
                    # Close browser after each cycle so the profile lock is released
                    # during the sleep window — allows LinkedInReplier to use the
                    # same session path without a "browser already closed" conflict.
                    await self._close_browser()
                await asyncio.sleep(self.check_interval)
        finally:
            await self._close_browser()


# ── CLI Entry Point ─────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LinkedIn Watcher - AI Employee Perception Layer"
    )
    parser.add_argument("--once", action="store_true", help="Single check and exit")
    parser.add_argument("--setup", action="store_true", help="First-time login setup")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    env_path = Path(__file__).resolve().parents[2] / "config" / ".env"
    load_dotenv(env_path)
    args = _parse_args(argv)

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    vault_path = os.getenv("VAULT_PATH", "./vault")
    session_path = os.getenv("LINKEDIN_SESSION_PATH", "config/linkedin_session")
    check_interval = int(os.getenv("LINKEDIN_CHECK_INTERVAL", "300"))
    headless = os.getenv("LINKEDIN_HEADLESS", "false").lower() == "true"
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
    dev_mode = os.getenv("DEV_MODE", "true").lower() == "true"

    keywords_env = os.getenv("LINKEDIN_KEYWORDS")
    keywords = None
    if keywords_env:
        keywords = [k.strip() for k in keywords_env.split(",") if k.strip()]

    watcher = LinkedInWatcher(
        vault_path=vault_path,
        session_path=session_path,
        check_interval=check_interval,
        keywords=keywords,
        headless=headless,
        dry_run=dry_run,
        dev_mode=dev_mode,
    )

    if args.setup:
        logger.info("Starting LinkedIn setup...")
        success = asyncio.run(watcher.setup_session())
        if success:
            logger.info("Setup complete!")
        else:
            logger.error("Setup failed.")
        return

    if args.once:
        logger.info("Running single LinkedIn check...")

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
        "Starting LinkedIn watcher (interval: %ds, headless: %s, dry_run: %s)",
        check_interval, headless, dry_run,
    )
    asyncio.run(watcher.run())


if __name__ == "__main__":
    main()
