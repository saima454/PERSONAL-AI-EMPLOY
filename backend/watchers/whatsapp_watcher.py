"""WhatsApp watcher - monitors WhatsApp Web for important messages via Playwright.

This is a PERCEPTION layer component. It observes WhatsApp Web and writes action
files to the vault. It never sends, modifies, or deletes messages.

Privacy: All messages are processed locally. No data is sent externally.

Usage:
    # First-time setup (headed browser for QR code scan)
    uv run python backend/watchers/whatsapp_watcher.py --setup

    # Continuous polling
    uv run python backend/watchers/whatsapp_watcher.py

    # Single check
    uv run python backend/watchers/whatsapp_watcher.py --once
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

# Default keywords that trigger action file creation
DEFAULT_KEYWORDS = [
    "urgent",
    "asap",
    "help",
    "deadline",
    "invoice",
    "payment",
    "meeting",
    "important",
]

HIGH_PRIORITY_KEYWORDS = {"urgent", "asap", "critical", "payment", "invoice"}
MEDIUM_PRIORITY_KEYWORDS = {"important", "meeting", "deadline", "help"}

# How many recent messages to include for context
CONTEXT_MESSAGE_COUNT = 3

# Processed IDs retention in days
PROCESSED_IDS_RETENTION_DAYS = 7

MAX_RETRIES = 3
MAX_BACKOFF_SECONDS = 60.0

# Selectors for WhatsApp Web DOM
SELECTORS = {
    "qr_code": 'canvas[aria-label*="Scan this QR code"]',
    "qr_code_fallback": 'div[data-testid="qrcode"]',
    "phone_disconnected": 'div[data-testid="alert-phone"]',
    "chat_list": 'div[data-testid="chat-list"]',
    "chat_list_aria": 'div[aria-label="Chat list"]',
    "chat_list_pane": "#pane-side",
    "chat_list_item": 'div[role="listitem"]',
    "loading": 'div[data-testid="startup"]',
    "chat_row": 'div[data-testid="cell-frame-container"]',
    "unread_badge": 'span[data-testid="icon-unread-count"]',
    "chat_row_with_unread": (
        'div[data-testid="cell-frame-container"]'
        ':has(span[data-testid="icon-unread-count"])'
    ),
    "conversation_header": 'div[data-testid="conversation-header"] span[dir="auto"]',
    "msg_container": 'div[data-testid="msg-container"]',
    "msg_text": 'span[data-testid="msg-text"] span',
    "msg_meta": 'div[data-testid="msg-meta"] span',
    "msg_author": 'span[data-testid="msg-author"]',
    "back_button": 'button[data-testid="back"]',
}


# Combined selector: any of these means chats are loaded / login succeeded
# div[role="row"] is confirmed present (66 elements) in WhatsApp Business Web
CHAT_LOADED_SELECTOR = ", ".join([
    'div[data-testid="chat-list"]',
    'div[aria-label="Chat list"]',
    "#pane-side",
    'div[role="listitem"]',
    'div[role="row"]',
    'div[data-testid="chat-list-search"]',
])


def _slugify(text: str, max_length: int = 40) -> str:
    """Convert text to a filename-safe slug."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:max_length].rstrip("-")


def _classify_priority(text: str, keywords: list[str]) -> tuple[str, str | None]:
    """Classify message priority based on keyword presence.

    Returns:
        Tuple of (priority_level, matched_keyword).
    """
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


def _make_dedup_key(sender: str, message_text: str, timestamp: str) -> str:
    """Create a deduplication key from message components."""
    return f"{sender}|{message_text[:100]}|{timestamp}"


class WhatsAppWatcher(BaseWatcher):
    """Watches WhatsApp Web for important messages and creates vault action files."""

    def __init__(
        self,
        vault_path: str,
        session_path: str = "config/whatsapp_session",
        check_interval: int = 30,
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
        self.processed_ids_path = self.logs_path / "processed_whatsapp.json"
        self._processed_ids: dict[str, str] = {}
        self._last_cleanup: str | None = None
        self._consecutive_errors = 0
        self._backoff_delay = 1.0
        self._browser = None
        self._context = None
        self._page = None

    # ── Session / Browser Management ────────────────────────────────

    async def _launch_browser(self) -> None:
        """Launch Playwright browser with persistent context for session."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self.session_path.mkdir(parents=True, exist_ok=True)

        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.session_path),
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

    async def _close_browser(self) -> None:
        """Close browser and cleanup.

        Suppresses TargetClosedError which occurs when the browser is
        already closing (e.g. during orchestrator shutdown).
        """
        try:
            if self._context:
                await self._context.close()
        except Exception as exc:
            if "Target closed" in str(exc) or "TargetClosedError" in type(exc).__name__:
                self.logger.debug("Browser already closed during shutdown")
            else:
                self.logger.warning("Error closing browser context: %s", exc)
        finally:
            self._context = None
            self._page = None
        try:
            if hasattr(self, "_playwright") and self._playwright:
                await self._playwright.stop()
        except Exception:
            self.logger.debug("Playwright already stopped during shutdown")
        finally:
            self._playwright = None

    async def _ensure_browser(self) -> None:
        """Ensure browser is running and page is available."""
        if self._page is None or self._context is None:
            await self._launch_browser()

    async def _navigate_to_whatsapp(self) -> None:
        """Navigate to WhatsApp Web and wait for it to fully load."""
        assert self._page is not None
        self.logger.debug("Navigating to web.whatsapp.com...")
        await self._page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")
        # Wait for either chat list (logged in) or QR code (need login)
        self.logger.debug("Waiting for initial page elements...")
        await self._page.wait_for_selector(
            f'{CHAT_LOADED_SELECTOR}, {SELECTORS["qr_code"]}, {SELECTORS["qr_code_fallback"]}',
            timeout=60000,
        )
        self.logger.debug("Initial page element found, waiting for full render...")

    async def _wait_for_chats_to_render(self, timeout: float = 15.0) -> None:
        """Wait for WhatsApp Web to fully render chat rows after initial load.

        WhatsApp Web loads in stages: shell -> contacts -> messages.
        The chat list container appears first, but individual chat rows
        take additional time to populate.
        """
        assert self._page is not None
        self.logger.debug("Waiting up to %.0fs for chat rows to render...", timeout)

        # First wait a fixed minimum for JS to hydrate
        await asyncio.sleep(3)

        # Then poll for actual chat row elements
        elapsed = 3.0
        poll_interval = 1.0
        while elapsed < timeout:
            # Try multiple selectors for chat rows
            for selector_name, selector in [
                ("cell-frame-container", 'div[data-testid="cell-frame-container"]'),
                ("listitem role", 'div[role="listitem"]'),
                ("row role", 'div[role="row"]'),
                ("chat aria-label", 'div[aria-label][data-testid="cell-frame-container"]'),
                ("span with title in pane-side", '#pane-side span[title]'),
            ]:
                elements = await self._page.query_selector_all(selector)
                if elements:
                    self.logger.debug(
                        "Chat rows found via '%s': %d elements (after %.1fs)",
                        selector_name, len(elements), elapsed,
                    )
                    # Give a bit more time for unread badges to render
                    await asyncio.sleep(2)
                    return

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        self.logger.warning(
            "Chat rows did not appear within %.0fs. "
            "Page may still be loading or selectors may be outdated.",
            timeout,
        )

    async def _is_chat_loaded(self) -> bool:
        """Check if any chat-list selector is present on the page."""
        assert self._page is not None
        result = await self._page.query_selector(CHAT_LOADED_SELECTOR)
        return result is not None

    async def _check_session_state(self) -> str:
        """Check current WhatsApp Web session state.

        Returns:
            One of: "ready", "qr_code", "phone_disconnected", "loading", "unknown"
        """
        assert self._page is not None

        if await self._is_chat_loaded():
            # Check for phone disconnected overlay
            if await self._page.query_selector(SELECTORS["phone_disconnected"]):
                return "phone_disconnected"
            return "ready"

        if await self._page.query_selector(SELECTORS["qr_code"]):
            return "qr_code"
        if await self._page.query_selector(SELECTORS["qr_code_fallback"]):
            return "qr_code"
        if await self._page.query_selector(SELECTORS["loading"]):
            return "loading"

        return "unknown"

    async def setup_session(self) -> bool:
        """Interactive setup: open headed browser for QR code scanning.

        Returns:
            True if session was established successfully.
        """
        self.logger.info("Starting WhatsApp Web session setup (headed mode)...")

        # Force headed mode for setup
        original_headless = self.headless
        self.headless = False

        try:
            await self._launch_browser()
            await self._navigate_to_whatsapp()

            state = await self._check_session_state()
            if state == "ready":
                self.logger.info("Already logged in! Session is valid.")
                return True

            if state == "qr_code":
                self.logger.info(
                    "QR code displayed. Scan with your phone:\n"
                    "  1. Open WhatsApp on your phone\n"
                    "  2. Go to Settings > Linked Devices > Link a Device\n"
                    "  3. Scan the QR code in the browser window\n"
                    "  Waiting up to 5 minutes..."
                )
                # Wait for any chat-loaded selector (user scanned QR)
                try:
                    await self._page.wait_for_selector(
                        CHAT_LOADED_SELECTOR,
                        timeout=300000,  # 5 minutes to scan
                    )
                    self.logger.info(
                        "Login detected! Chats are visible. "
                        "Session saved to %s",
                        self.session_path,
                    )
                    return True
                except Exception:
                    self.logger.error("QR code scan timed out after 5 minutes.")
                    return False

            self.logger.warning("Unexpected state during setup: %s", state)
            return False

        finally:
            self.headless = original_headless
            await self._close_browser()

    # ── Processed IDs ───────────────────────────────────────────────

    def _load_processed_ids(self) -> None:
        """Load processed message IDs from disk."""
        if not self.processed_ids_path.exists():
            self._processed_ids = {}
            self._last_cleanup = None
            return

        try:
            data = json.loads(self.processed_ids_path.read_text(encoding="utf-8"))
            self._processed_ids = data.get("processed_ids", {})
            self._last_cleanup = data.get("last_cleanup")
        except (json.JSONDecodeError, KeyError):
            self.logger.warning("Corrupted processed_whatsapp.json, starting fresh")
            self._processed_ids = {}
            self._last_cleanup = None

    def _save_processed_ids(self) -> None:
        """Save processed message IDs to disk."""
        self.processed_ids_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "processed_ids": self._processed_ids,
            "last_cleanup": self._last_cleanup or now_iso(),
        }
        self.processed_ids_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _cleanup_old_ids(self) -> None:
        """Remove processed IDs older than retention period."""
        now = now_iso()

        if self._last_cleanup and is_within_hours(self._last_cleanup, 24):
            return

        cutoff_ids = []
        for msg_key, processed_at in self._processed_ids.items():
            try:
                if not is_within_hours(processed_at, PROCESSED_IDS_RETENTION_DAYS * 24):
                    cutoff_ids.append(msg_key)
            except (ValueError, TypeError):
                cutoff_ids.append(msg_key)

        for msg_key in cutoff_ids:
            del self._processed_ids[msg_key]

        self._last_cleanup = now
        if cutoff_ids:
            self.logger.info("Cleaned up %d old processed message IDs", len(cutoff_ids))

    # ── Message Extraction ──────────────────────────────────────────

    async def _get_unread_chats(self) -> list[dict[str, Any]]:
        """Find all chats with unread message indicators.

        Tries multiple selector strategies since WhatsApp Web DOM changes frequently.

        Returns:
            List of dicts with chat element references and sender names.
        """
        assert self._page is not None

        # ── Strategy 1: compound :has() selector ──
        unread_strategies = [
            (
                "row + aria unread",
                'div[role="row"]:has(span[aria-label*="unread"])',
            ),
            (
                "row + icon-unread-count",
                'div[role="row"]:has(span[data-testid="icon-unread-count"])',
            ),
            (
                "cell-frame + aria unread",
                'div[data-testid="cell-frame-container"]:has(span[aria-label*="unread"])',
            ),
            (
                "cell-frame + icon-unread-count",
                'div[data-testid="cell-frame-container"]:has(span[data-testid="icon-unread-count"])',
            ),
            (
                "listitem + aria unread",
                'div[role="listitem"]:has(span[aria-label*="unread"])',
            ),
        ]

        chat_rows = []
        matched_strategy = None

        for strategy_name, selector in unread_strategies:
            try:
                rows = await self._page.query_selector_all(selector)
                self.logger.debug(
                    "Unread strategy '%s': %d matches", strategy_name, len(rows)
                )
                if rows:
                    chat_rows = rows
                    matched_strategy = strategy_name
                    break
            except Exception:
                self.logger.debug(
                    "Unread strategy '%s' failed", strategy_name, exc_info=True
                )

        if not chat_rows:
            # ── Debug: dump what IS on the page ──
            await self._debug_dump_chat_state()
            return []

        self.logger.debug(
            "Using unread strategy '%s', found %d unread rows",
            matched_strategy, len(chat_rows),
        )

        # ── Extract chat names from matched rows ──
        unread_chats = []
        for row in chat_rows:
            chat_name = await self._extract_chat_name_from_row(row)
            if chat_name:
                self.logger.debug("Unread chat detected: '%s'", chat_name)
                unread_chats.append({
                    "element": row,
                    "chat_name": chat_name,
                })
            else:
                self.logger.debug("Found unread row but could not extract chat name")

        return unread_chats

    async def _extract_chat_name_from_row(self, row: Any) -> str:
        """Try multiple approaches to extract the chat name from a row element."""
        name_selectors = [
            'span[dir="auto"][title]',
            'span[title]',
            'span[dir="auto"]',
        ]
        for sel in name_selectors:
            try:
                el = await row.query_selector(sel)
                if el:
                    title = await el.get_attribute("title")
                    if title and title.strip():
                        return title.strip()
                    text = await el.inner_text()
                    if text and text.strip() and len(text.strip()) < 100:
                        return text.strip()
            except Exception:
                continue
        return ""

    async def _debug_dump_chat_state(self) -> None:
        """Log diagnostic info about the current page state."""
        assert self._page is not None

        # Count total chat rows with various selectors
        diagnostics = [
            ("div[data-testid='cell-frame-container']", 'div[data-testid="cell-frame-container"]'),
            ("div[role='listitem']", 'div[role="listitem"]'),
            ("div[role='row']", 'div[role="row"]'),
            ("#pane-side span[title]", '#pane-side span[title]'),
            ("span[data-testid='icon-unread-count']", 'span[data-testid="icon-unread-count"]'),
            ("span[aria-label*='unread']", 'span[aria-label*="unread"]'),
        ]

        self.logger.debug("── Chat page diagnostic dump ──")
        for label, sel in diagnostics:
            try:
                els = await self._page.query_selector_all(sel)
                count = len(els)
                detail = ""
                if count > 0 and count <= 5:
                    # Show text content of first few matches
                    texts = []
                    for el in els[:3]:
                        try:
                            t = await el.inner_text()
                            texts.append(repr(t[:80]))
                        except Exception:
                            texts.append("(error reading text)")
                    detail = f" -> {', '.join(texts)}"
                self.logger.debug("  %-45s : %d%s", label, count, detail)
            except Exception:
                self.logger.debug("  %-45s : selector error", label)

        # Also try to grab any visible chat names via #pane-side
        try:
            titles = await self._page.query_selector_all('#pane-side span[title]')
            if titles:
                names = []
                for t in titles[:10]:
                    name = await t.get_attribute("title")
                    if name:
                        names.append(name)
                self.logger.debug("  Visible chat names: %s", names)
            else:
                self.logger.debug("  No span[title] elements found in #pane-side")
        except Exception:
            self.logger.debug("  Could not read chat names from #pane-side")

        self.logger.debug("── End diagnostic dump ──")

    async def _extract_messages_from_chat(self, chat_name: str) -> list[dict[str, str]]:
        """Extract recent messages from the currently open chat.

        Returns:
            List of dicts with sender, text, and time fields.
        """
        assert self._page is not None

        # Wait for messages to render after opening chat
        await asyncio.sleep(2)

        messages = []

        # Try multiple selectors for message containers
        msg_containers = []
        msg_selectors = [
            ('msg-container', 'div[data-testid="msg-container"]'),
            ('message-in', 'div.message-in'),
            ('focusable message', 'div[data-testid="conv-msg-true"], div[data-testid="conv-msg-false"]'),
            ('role row in conversation', 'div[role="row"] div[data-pre-plain-text]'),
        ]
        for sel_name, sel in msg_selectors:
            msg_containers = await self._page.query_selector_all(sel)
            if msg_containers:
                self.logger.debug(
                    "Chat '%s': found %d message containers via '%s'",
                    chat_name, len(msg_containers), sel_name,
                )
                break

        if not msg_containers:
            # Fallback: try to get any text from the conversation panel
            self.logger.debug(
                "Chat '%s': no message containers found with any selector. "
                "Trying fallback text extraction...",
                chat_name,
            )
            return await self._extract_messages_fallback(chat_name)

        # Get last N messages for context
        recent = msg_containers[-CONTEXT_MESSAGE_COUNT:] if msg_containers else []

        # Try multiple text selectors per message
        text_selectors = [
            'span[data-testid="msg-text"] span',
            'span.selectable-text span',
            'span[dir="ltr"]',
            'span.selectable-text',
        ]
        meta_selectors = [
            'div[data-testid="msg-meta"] span',
            'span[data-testid="msg-time"]',
            'div.copyable-text span[dir="auto"]',
        ]

        for container in recent:
            try:
                # Try text selectors in order
                text = ""
                for tsel in text_selectors:
                    text_el = await container.query_selector(tsel)
                    if text_el:
                        text = (await text_el.inner_text()).strip()
                        if text:
                            break

                # Try time selectors
                time_str = ""
                for msel in meta_selectors:
                    time_el = await container.query_selector(msel)
                    if time_el:
                        time_str = (await time_el.inner_text()).strip()
                        if time_str:
                            break

                author_el = await container.query_selector(SELECTORS["msg_author"])
                author = await author_el.inner_text() if author_el else chat_name

                if text:
                    messages.append({
                        "sender": author.strip(),
                        "text": text,
                        "time": time_str,
                    })
                    self.logger.debug(
                        "  Message: [%s] %s: %s",
                        time_str, author.strip(), text[:80],
                    )
            except Exception:
                self.logger.debug("Failed to extract message from container", exc_info=True)
                continue

        self.logger.debug(
            "Chat '%s': extracted %d messages", chat_name, len(messages)
        )
        return messages

    async def _extract_messages_fallback(self, chat_name: str) -> list[dict[str, str]]:
        """Last-resort message extraction using data-pre-plain-text attribute."""
        assert self._page is not None
        messages = []
        try:
            # WhatsApp stores message metadata in data-pre-plain-text
            elements = await self._page.query_selector_all('div[data-pre-plain-text]')
            recent = elements[-CONTEXT_MESSAGE_COUNT:] if elements else []
            for el in recent:
                pre_text = await el.get_attribute("data-pre-plain-text") or ""
                inner = await el.inner_text()
                if inner:
                    messages.append({
                        "sender": chat_name,
                        "text": inner.strip(),
                        "time": pre_text.strip("[] "),
                    })
                    self.logger.debug(
                        "  Fallback message: %s: %s", pre_text, inner.strip()[:80]
                    )
        except Exception:
            self.logger.debug("Fallback extraction failed", exc_info=True)
        self.logger.debug(
            "Chat '%s': fallback extracted %d messages", chat_name, len(messages)
        )
        return messages

    async def _open_chat(self, chat_element: Any, chat_name: str = "") -> bool:
        """Click on a chat element to open it.

        Returns:
            True if the chat opened successfully.
        """
        assert self._page is not None
        try:
            self.logger.debug("Opening chat '%s'...", chat_name)
            await chat_element.click()
            # Wait for conversation panel to appear
            header_selectors = [
                SELECTORS["conversation_header"],
                'header span[dir="auto"]',
                'div[data-testid="conversation-panel-wrapper"]',
            ]
            for sel in header_selectors:
                try:
                    await self._page.wait_for_selector(sel, timeout=5000)
                    self.logger.debug("Chat '%s' opened (matched: %s)", chat_name, sel)
                    return True
                except Exception:
                    continue
            # If none matched, still return True if the page changed
            self.logger.debug("Chat '%s': no header selector matched, but click succeeded", chat_name)
            await asyncio.sleep(1)
            return True
        except Exception:
            self.logger.debug("Failed to open chat '%s'", chat_name, exc_info=True)
            return False

    async def _go_back_to_chat_list(self) -> None:
        """Navigate back from an open chat to the chat list."""
        assert self._page is not None
        back_btn = await self._page.query_selector(SELECTORS["back_button"])
        if back_btn:
            await back_btn.click()
            await asyncio.sleep(0.5)

    # ── Core Watcher Logic ──────────────────────────────────────────

    async def check_for_updates(self) -> list[dict[str, Any]]:
        """Poll WhatsApp Web for new unread messages matching keywords.

        Returns:
            List of message dicts that need action files created.
        """
        self._load_processed_ids()
        self._cleanup_old_ids()

        try:
            items = await self._scan_unread_messages()
            self._consecutive_errors = 0
            self._backoff_delay = 1.0
            return items
        except Exception:
            self._consecutive_errors += 1
            self.logger.exception(
                "Error scanning WhatsApp messages (consecutive errors: %d)",
                self._consecutive_errors,
            )
            self._log_error("whatsapp_web", "scan_failed")
            return []

    async def _scan_unread_messages(self) -> list[dict[str, Any]]:
        """Scan WhatsApp Web for unread messages and filter by keywords.

        Returns:
            List of parsed message dicts ready for action file creation.
        """
        await self._ensure_browser()
        assert self._page is not None

        # Check if we need to navigate to WhatsApp Web
        current_url = self._page.url
        if "web.whatsapp.com" not in current_url:
            await self._navigate_to_whatsapp()

        # Check session state
        state = await self._check_session_state()
        self.logger.debug("Session state: %s", state)

        if state == "qr_code":
            self.logger.error(
                "WhatsApp session expired. Run with --setup to re-authenticate."
            )
            self._log_error("whatsapp_web", "session_expired")
            return []

        if state == "phone_disconnected":
            self.logger.warning("Phone not connected. Will retry next cycle.")
            self._log_error("whatsapp_web", "phone_disconnected")
            return []

        if state != "ready":
            self.logger.warning("WhatsApp Web not ready (state: %s)", state)
            return []

        # Wait for chats to fully render (badges, names, etc.)
        await self._wait_for_chats_to_render(timeout=15.0)

        # Find unread chats
        unread_chats = await self._get_unread_chats()
        if not unread_chats:
            self.logger.info("No unread chats found (or no unread selectors matched)")
            return []

        self.logger.info("Found %d unread chats", len(unread_chats))
        parsed_items: list[dict[str, Any]] = []

        for chat_info in unread_chats:
            try:
                chat_name = chat_info["chat_name"]
                if not await self._open_chat(chat_info["element"], chat_name):
                    continue
                messages = await self._extract_messages_from_chat(chat_name)

                if not messages:
                    await self._go_back_to_chat_list()
                    continue

                # Check the latest message for keyword match
                latest_msg = messages[-1]
                all_text = " ".join(m["text"] for m in messages)
                priority, matched_keyword = _classify_priority(all_text, self.keywords)

                if matched_keyword is None:
                    # No keyword match, skip this chat
                    await self._go_back_to_chat_list()
                    continue

                # Build dedup key from latest message
                dedup_key = _make_dedup_key(
                    chat_name,
                    latest_msg["text"],
                    latest_msg.get("time", ""),
                )

                if dedup_key in self._processed_ids:
                    await self._go_back_to_chat_list()
                    continue

                parsed_items.append({
                    "chat_name": chat_name,
                    "sender": latest_msg["sender"],
                    "message_text": latest_msg["text"],
                    "message_time": latest_msg.get("time", ""),
                    "priority": priority,
                    "matched_keyword": matched_keyword,
                    "context_messages": messages,
                    "dedup_key": dedup_key,
                })

                await self._go_back_to_chat_list()

            except Exception:
                self.logger.debug("Error processing chat %s", chat_info.get("chat_name", "?"), exc_info=True)
                try:
                    await self._go_back_to_chat_list()
                except Exception:
                    pass

        return parsed_items

    # ── Action File Creation ────────────────────────────────────────

    async def create_action_file(self, item: dict[str, Any]) -> Path | None:
        """Create a markdown action file in Needs_Action for a WhatsApp message.

        Args:
            item: Parsed message dict from check_for_updates.

        Returns:
            Path to created file, or None if dry_run.
        """
        sender_slug = _slugify(item["chat_name"])
        timestamp = format_filename_timestamp()
        filename = f"WHATSAPP_{sender_slug}_{timestamp}.md"
        file_path = self.needs_action / filename

        wa_id = f"WHATSAPP_{short_id()}_{timestamp}"

        frontmatter: dict[str, Any] = {
            "type": "whatsapp",
            "id": wa_id,
            "source": "whatsapp_watcher",
            "sender": item["chat_name"],
            "message_preview": item["message_text"][:200],
            "received": now_iso(),
            "priority": item["priority"],
            "status": "pending",
            "chat_name": item["chat_name"],
        }

        # Build context messages section
        context_lines = []
        for msg in item.get("context_messages", []):
            time_str = msg.get("time", "??:??")
            context_lines.append(f"- [{time_str}] {msg['sender']}: {msg['text']}")
        context_section = "\n".join(context_lines) if context_lines else "(no context available)"

        body = f"""
## WhatsApp Message

**From:** {item["chat_name"]}
**Chat:** {item["chat_name"]}
**Time:** {item.get("message_time", "unknown")}
**Priority:** {item["priority"]} (keyword: {item.get("matched_keyword", "unknown")})

## Recent Messages (Context)

{context_section}

## Suggested Actions

- [ ] Reply to sender
- [ ] Forward info to relevant party
- [ ] Mark as processed
"""

        cid = correlation_id()

        if self.dry_run:
            self.logger.info(
                "[DRY RUN] Would create action file: %s (priority: %s, from: %s)",
                filename,
                item["priority"],
                item["chat_name"],
            )
            log_action(
                self.logs_path / "actions",
                {
                    "timestamp": now_iso(),
                    "correlation_id": cid,
                    "actor": "whatsapp_watcher",
                    "action_type": "whatsapp_detected",
                    "target": filename,
                    "result": "dry_run",
                    "parameters": {
                        "chat_name": item["chat_name"],
                        "message_preview": item["message_text"][:100],
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

        # Track as processed
        self._processed_ids[item["dedup_key"]] = now_iso()
        self._save_processed_ids()

        log_action(
            self.logs_path / "actions",
            {
                "timestamp": now_iso(),
                "correlation_id": cid,
                "actor": "whatsapp_watcher",
                "action_type": "whatsapp_processed",
                "target": filename,
                "result": "success",
                "parameters": {
                    "chat_name": item["chat_name"],
                    "message_preview": item["message_text"][:100],
                    "priority": item["priority"],
                    "matched_keyword": item.get("matched_keyword"),
                    "dry_run": False,
                    "dev_mode": self.dev_mode,
                },
            },
        )

        self.logger.info(
            "Created action file: %s (priority: %s)", filename, item["priority"]
        )
        return file_path

    # ── Error Logging ───────────────────────────────────────────────

    def _log_error(self, target: str, error_msg: str) -> None:
        """Log an error to the vault error logs."""
        try:
            log_action(
                self.logs_path / "errors",
                {
                    "timestamp": now_iso(),
                    "correlation_id": correlation_id(),
                    "actor": "whatsapp_watcher",
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
        """Main polling loop with browser lifecycle management."""
        self.logger.info("Starting %s (interval: %ds)", self.__class__.__name__, self.check_interval)
        try:
            await self._ensure_browser()
            assert self._page is not None
            await self._navigate_to_whatsapp()

            # Verify session
            state = await self._check_session_state()
            if state == "qr_code":
                self.logger.warning(
                    "WhatsApp not logged in — QR code is displayed in the browser.\n"
                    "  1. Open WhatsApp on your phone\n"
                    "  2. Go to Settings > Linked Devices > Link a Device\n"
                    "  3. Scan the QR code in the browser window\n"
                    "  Waiting until you scan (Ctrl+C to cancel)..."
                )
                # Poll indefinitely — no timeout. A normal return or a timeout
                # exception would cause the watchdog to restart immediately.
                # Only CancelledError (Ctrl+C / orchestrator shutdown) or a
                # successful scan should exit this block.
                while True:
                    await asyncio.sleep(5)
                    state = await self._check_session_state()
                    if state == "ready":
                        self.logger.info("QR code scanned — logged in successfully. Starting watcher.")
                        break
                    if state == "qr_code":
                        continue  # still waiting
                    # Any other state (unknown, loading) — keep waiting
                    self.logger.debug("WhatsApp state while waiting for QR scan: %s", state)
            if state != "ready":
                self.logger.warning("WhatsApp Web state: %s. Attempting to proceed...", state)

            while True:
                try:
                    items = await self.check_for_updates()
                    for item in items:
                        await self.create_action_file(item)
                except Exception:
                    self.logger.exception("Error in %s polling cycle", self.__class__.__name__)
                finally:
                    # Close browser after every scan so the profile lock is released
                    # during the sleep window. The replier (or any other action) can
                    # then freely open the same session without conflict.
                    await self._close_browser()
                await asyncio.sleep(self.check_interval)
        finally:
            await self._close_browser()


# ── CLI Entry Point ─────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WhatsApp Watcher - AI Employee Perception Layer"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single check and exit",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="First-time setup: open headed browser for QR code scan",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for the WhatsApp watcher."""
    # Load .env from config/ directory (project convention)
    env_path = Path(__file__).resolve().parents[2] / "config" / ".env"
    load_dotenv(env_path)
    args = _parse_args(argv)

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    vault_path = os.getenv("VAULT_PATH", "./vault")
    session_path = os.getenv("WHATSAPP_SESSION_PATH", "config/whatsapp_session")
    check_interval = int(os.getenv("WHATSAPP_CHECK_INTERVAL", "30"))
    headless = os.getenv("WHATSAPP_HEADLESS", "false").lower() == "true"
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
    dev_mode = os.getenv("DEV_MODE", "true").lower() == "true"

    # Parse keywords from env
    keywords_env = os.getenv("WHATSAPP_KEYWORDS")
    keywords = None
    if keywords_env:
        keywords = [k.strip() for k in keywords_env.split(",") if k.strip()]

    watcher = WhatsAppWatcher(
        vault_path=vault_path,
        session_path=session_path,
        check_interval=check_interval,
        keywords=keywords,
        headless=headless,
        dry_run=dry_run,
        dev_mode=dev_mode,
    )

    if args.setup:
        logger.info("Starting WhatsApp Web setup...")
        success = asyncio.run(watcher.setup_session())
        if success:
            logger.info("Setup complete! You can now run the watcher normally.")
        else:
            logger.error("Setup failed. Please try again.")
        return

    if args.once:
        logger.info("Running single WhatsApp check...")

        async def single_check() -> None:
            try:
                await watcher._ensure_browser()
                assert watcher._page is not None
                await watcher._navigate_to_whatsapp()
                # Wait for full render before scanning
                await watcher._wait_for_chats_to_render(timeout=15.0)
                items = await watcher.check_for_updates()
                for item in items:
                    await watcher.create_action_file(item)
                logger.info("Check complete. Found %d matching messages.", len(items))
            finally:
                await watcher._close_browser()

        asyncio.run(single_check())
        return

    logger.info(
        "Starting WhatsApp watcher (interval: %ds, headless: %s, dry_run: %s)",
        check_interval,
        headless,
        dry_run,
    )
    asyncio.run(watcher.run())


if __name__ == "__main__":
    main()
