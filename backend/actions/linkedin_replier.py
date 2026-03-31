"""LinkedIn replier — sends approved replies to LinkedIn messages via Playwright.

This is an ACTION layer component. It reads approved linkedin_reply files from
vault/Approved/, finds the conversation by sender name on the LinkedIn messaging
page, and sends the reply body.

Privacy: Reply content is drafted and approved locally. Only the final approved
text is sent to LinkedIn.

Usage (standalone):
    uv run python backend/actions/linkedin_replier.py --file vault/Approved/linkedin-reply-*.md
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from backend.utils.frontmatter import extract_frontmatter, update_frontmatter
from backend.utils.logging_utils import log_action
from backend.utils.timestamps import now_iso
from backend.utils.uuid_utils import correlation_id

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parents[2]
load_dotenv(dotenv_path=_PROJECT_ROOT / "config" / ".env", override=True)

# Selectors for the LinkedIn messaging page
AUTHENTICATED_SELECTORS = [
    'img.global-nav__me-photo',
    'img.feed-identity-module__member-photo',
    'button[aria-label*="me" i]',
    'div.feed-identity-module',
    'div[data-control-name="identity_welcome_message"]',
    'span.feed-identity-module__actor-name',
    'a[href*="/in/"][data-control-name="identity_profile_photo"]',
    'div.share-box-feed-entry__trigger',
]

# Selectors for finding conversations in the thread list
THREAD_SELECTORS = [
    "div.msg-conversation-card--unread",
    "div.msg-conversation-card",
    '[class*="conversation-card"]',
    '[class*="msg-conversation"]',
    '[class*="conversation-list"] li',
    'main li',
    'aside li',
    '[role="list"] li',
    'ul li',
]

# Selectors for the message input in an open conversation
MESSAGE_INPUT_SELECTORS = [
    'div.msg-form__contenteditable[contenteditable="true"]',
    'div[role="textbox"][contenteditable="true"]',
    'div[contenteditable="true"][aria-label*="message" i]',
    'div[contenteditable="true"][aria-label*="write" i]',
    'div[contenteditable="true"]',
]

# Selectors for the send button
SEND_BUTTON_SELECTORS = [
    'button.msg-form__send-button',
    'button[aria-label="Send"]',
    'button[aria-label="send"]',
    'button[type="submit"][class*="send"]',
    '[data-control-name="send"]',
]


class LinkedInReplier:
    """Sends approved LinkedIn message replies from the vault."""

    def __init__(
        self,
        vault_path: str,
        session_path: str = "config/linkedin_session",
        headless: bool = True,
        dry_run: bool = True,
        dev_mode: bool = True,
    ):
        self.vault_path = Path(vault_path)
        self.approved_path = self.vault_path / "Approved"
        self.done_path = self.vault_path / "Done"
        self.logs_path = self.vault_path / "Logs"
        self.session_path = Path(session_path)
        self.headless = headless
        self.dry_run = dry_run
        self.dev_mode = dev_mode
        self.logger = logging.getLogger(self.__class__.__name__)
        self._playwright = None
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
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _ensure_browser(self) -> None:
        if self._page is None or self._context is None:
            await self._launch_browser()

    # ── Navigation ──────────────────────────────────────────────────

    async def _navigate_and_wait(self, url: str, wait_seconds: float = 10.0) -> None:
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
            screenshot_path = self.logs_path / f"debug_{label}.png"
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            await self._page.screenshot(path=str(screenshot_path), full_page=False)
            self.logger.info("Debug screenshot saved to %s", screenshot_path)
        except Exception:
            self.logger.debug("Could not save debug screenshot", exc_info=True)

    # ── Session State ───────────────────────────────────────────────

    async def _check_session_state(self) -> str:
        assert self._page is not None
        current_url = self._page.url

        if "/checkpoint/challenge" in current_url:
            return "captcha"
        if "/login" in current_url or "/authwall" in current_url:
            return "login_required"

        try:
            if await self._page.query_selector("#captcha-internal"):
                return "captcha"
        except Exception:
            pass

        for sel in ["form.login__form", "#username", 'input[name="session_key"]']:
            try:
                if await self._page.query_selector(sel):
                    return "login_required"
            except Exception:
                pass

        if await self._is_authenticated():
            return "ready"

        return "unknown"

    async def _is_authenticated(self) -> bool:
        assert self._page is not None
        current_url = self._page.url

        is_linkedin_page = any(
            p in current_url
            for p in ["/feed", "/messaging", "/notifications", "/mynetwork", "/in/"]
        )
        if not is_linkedin_page:
            return False

        for sel in AUTHENTICATED_SELECTORS:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    return True
            except Exception:
                continue

        try:
            buttons = await self._page.query_selector_all("button")
            links = await self._page.query_selector_all("a")
            imgs = await self._page.query_selector_all("img")
            if len(buttons) + len(links) + len(imgs) > 40:
                return True
        except Exception:
            pass

        return False

    # ── Reply Logic ─────────────────────────────────────────────────

    async def _find_conversation_by_sender(self, sender: str) -> bool:
        """Find and click the conversation matching sender name.

        Scans the thread list for a card whose text contains the sender name.
        Returns True if found and clicked.
        """
        assert self._page is not None

        self.logger.info("Looking for conversation with: %s", sender)
        sender_lower = sender.lower()

        threads: list = []
        used_selector = ""
        for sel in THREAD_SELECTORS:
            try:
                threads = await self._page.query_selector_all(sel)
                if 0 < len(threads) <= 50:
                    used_selector = sel
                    break
                if len(threads) > 50:
                    threads = []
            except Exception:
                pass

        if not threads:
            self.logger.warning("No conversation threads found on page")
            await self._save_debug_screenshot("replier_no_threads")
            return False

        self.logger.info("Scanning %d threads via '%s'", len(threads), used_selector)

        for thread in threads:
            try:
                full_text = (await thread.inner_text()).strip().lower()
                if sender_lower in full_text:
                    self.logger.info("Found conversation matching '%s' — clicking", sender)
                    await thread.click()
                    await asyncio.sleep(3)
                    return True
            except Exception:
                self.logger.debug("Error checking thread", exc_info=True)

        self.logger.warning("Could not find conversation for sender: %s", sender)
        await self._save_debug_screenshot("replier_sender_not_found")
        return False

    async def _type_reply(self, text: str) -> bool:
        """Find the message input field and type the reply."""
        assert self._page is not None
        self.logger.info("Typing reply (%d chars)...", len(text))

        for sel in MESSAGE_INPUT_SELECTORS:
            try:
                el = await self._page.query_selector(sel)
                if el and await el.is_visible():
                    self.logger.info("Found message input via: %s", sel)
                    await el.click()
                    await asyncio.sleep(0.5)
                    await self._page.keyboard.type(text, delay=20)
                    self.logger.info("Typed %d chars into message input", len(text))
                    return True
            except Exception as exc:
                self.logger.debug("Input selector '%s' error: %s", sel, exc)

        self.logger.error("Could not find message input field")
        await self._save_debug_screenshot("replier_input_not_found")
        return False

    async def _click_send(self) -> bool:
        """Find and click the Send button."""
        assert self._page is not None
        self.logger.info("Clicking Send button...")

        for sel in SEND_BUTTON_SELECTORS:
            try:
                el = await self._page.query_selector(sel)
                if el and await el.is_visible():
                    self.logger.info("Found send button via: %s", sel)
                    await el.click()
                    await asyncio.sleep(2)
                    return True
            except Exception as exc:
                self.logger.debug("Send button selector '%s' error: %s", sel, exc)

        # Keyboard fallback: Enter sends in LinkedIn messaging
        self.logger.info("Send button not found — trying Enter key")
        try:
            await self._page.keyboard.press("Enter")
            await asyncio.sleep(2)
            self.logger.info("Sent via Enter key")
            return True
        except Exception as exc:
            self.logger.debug("Enter key fallback error: %s", exc)

        self.logger.error("Could not click Send button")
        await self._save_debug_screenshot("replier_send_failed")
        return False

    async def send_reply(self, sender: str, reply_text: str) -> bool:
        """Send a reply to a LinkedIn message conversation.

        Full flow:
        1. Navigate to messaging
        2. Find conversation by sender name
        3. Type reply
        4. Click Send

        Returns True on success.
        """
        assert self._page is not None

        if self.dev_mode:
            self.logger.info(
                "[DEV_MODE] Would reply to '%s' (%d chars): %s",
                sender, len(reply_text), reply_text[:100],
            )
            return True

        if self.dry_run:
            self.logger.info(
                "[DRY RUN] Would reply to '%s' (%d chars)", sender, len(reply_text)
            )
            return True

        self.logger.info("=" * 60)
        self.logger.info("SENDING LINKEDIN REPLY to '%s' (%d chars)", sender, len(reply_text))
        self.logger.info("=" * 60)

        await self._navigate_and_wait(
            "https://www.linkedin.com/messaging/", wait_seconds=8.0
        )

        state = await self._check_session_state()
        if state != "ready":
            self.logger.error(
                "Not logged in to LinkedIn (state=%s). Cannot send reply.", state
            )
            await self._save_debug_screenshot("replier_not_logged_in")
            return False

        if not await self._find_conversation_by_sender(sender):
            return False

        if not await self._type_reply(reply_text):
            return False

        await asyncio.sleep(1)

        if not await self._click_send():
            return False

        self.logger.info("=" * 60)
        self.logger.info("REPLY SENT to '%s'", sender)
        self.logger.info("=" * 60)
        return True

    # ── File Lifecycle ──────────────────────────────────────────────

    @staticmethod
    def _extract_reply_body(body_text: str) -> str:
        """Extract content from the '## Reply Body' section, stripping HTML comments."""
        import re

        lines = body_text.strip().splitlines()
        in_content = False
        content_lines: list[str] = []

        for line in lines:
            if line.strip().lower().startswith("## reply body"):
                in_content = True
                continue
            if in_content and line.strip().startswith("## "):
                break
            if in_content:
                content_lines.append(line)

        if content_lines:
            raw = "\n".join(content_lines)
            cleaned = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL).strip()
            if cleaned:
                return cleaned

        return body_text.strip()

    def _move_to_done(self, file_path: Path, result: str) -> None:
        self.done_path.mkdir(parents=True, exist_ok=True)
        dest = self.done_path / file_path.name
        try:
            update_frontmatter(file_path, {
                "status": "done",
                "completed_at": now_iso(),
                "result": result,
            })
        except Exception:
            self.logger.warning("Could not update frontmatter on %s", file_path.name)
        shutil.move(str(file_path), str(dest))
        self.logger.info("Moved %s to Done/ (result: %s)", file_path.name, result)

    # ── Main Entry Point ────────────────────────────────────────────

    async def process_reply_file(self, file_path: Path) -> bool:
        """Process a single approved linkedin_reply file.

        Returns True on success (reply sent or dry_run/dev_mode).
        """
        content = file_path.read_text(encoding="utf-8")
        fm, body_text = extract_frontmatter(content)

        sender = fm.get("sender", "")
        if not sender:
            self.logger.error("No sender in %s — cannot reply", file_path.name)
            return False

        reply_text = self._extract_reply_body(body_text)
        if not reply_text:
            self.logger.error("Empty reply body in %s — skipping", file_path.name)
            return False

        cid = correlation_id()
        self.logger.info(
            "Sending LinkedIn reply to '%s' from %s (%d chars)",
            sender, file_path.name, len(reply_text),
        )

        await self._ensure_browser()

        success = await self.send_reply(sender, reply_text)

        log_action(
            self.logs_path / "actions",
            {
                "timestamp": now_iso(),
                "correlation_id": cid,
                "actor": "linkedin_replier",
                "action_type": "linkedin_reply",
                "target": file_path.name,
                "result": "success" if success else "failure",
                "parameters": {
                    "sender": sender,
                    "reply_length": len(reply_text),
                    "dry_run": self.dry_run,
                    "dev_mode": self.dev_mode,
                },
            },
        )

        if success:
            self._move_to_done(file_path, "success")
        else:
            self.logger.error("Failed to send reply for %s", file_path.name)

        return success
